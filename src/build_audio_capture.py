"""Build the local audio helper as a signed application for macOS permissions."""

import hashlib
from importlib.resources import files
from pathlib import Path
import plistlib
import subprocess


from voicetype_paths import data_dir


APP = data_dir() / "VoiceType Audio.app"
EXECUTABLE = APP / "Contents/MacOS/voicetype-audio"


def build():
    source = Path(str(files("voicetype_resources").joinpath("audio_capture.swift")))
    signature = hashlib.sha256(source.read_bytes()).hexdigest()
    marker = APP / "Contents/Resources/source.sha256"
    (APP / "Contents/source.sha256").unlink(missing_ok=True)
    if EXECUTABLE.is_file() and marker.is_file() and marker.read_text() == signature:
        verified = subprocess.run(["codesign", "--verify", "--deep", "--strict", str(APP)],
                                  capture_output=True)
        if verified.returncode == 0:
            return EXECUTABLE
    EXECUTABLE.parent.mkdir(parents=True, exist_ok=True)
    info = {
        "CFBundleIdentifier": "local.voicetype.audio",
        "CFBundleName": "VoiceType Audio",
        "CFBundleExecutable": "voicetype-audio",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1",
        "NSMicrophoneUsageDescription": "Record your voice locally for dictation.",
        "NSAudioCaptureUsageDescription": "Capture speaker playback locally as an echo-cancellation reference.",
        "NSScreenCaptureUsageDescription": "Capture system audio only. No screen images are recorded.",
        "LSUIElement": True,
    }
    with (APP / "Contents/Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)
    subprocess.run(["xcrun", "swiftc", "-O", "-parse-as-library",
                    "-target", "arm64-apple-macos15.0", str(source), "-o", str(EXECUTABLE),
                    "-framework", "ScreenCaptureKit", "-framework", "AVFoundation",
                    "-framework", "CoreMedia", "-framework", "CoreGraphics"], check=True)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(signature)
    subprocess.run(["codesign", "--force", "--sign", "-", "--identifier",
                    "local.voicetype.audio", str(APP)], check=True)
    return EXECUTABLE


if __name__ == "__main__":
    print(build())
