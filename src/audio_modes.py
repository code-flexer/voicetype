"""Local audio-mode settings, timestamped capture, and reference-based echo cancellation."""

import ctypes
import ctypes.util
import os
import shutil
import subprocess
import json
import math
from pathlib import Path
import struct
import time


from voicetype_paths import data_dir


SETTINGS = data_dir() / "settings.json"


def find_speex_library():
    override = os.environ.get("VOICETYPE_SPEEXDSP_LIBRARY")
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_file():
            raise RuntimeError("VOICETYPE_SPEEXDSP_LIBRARY does not point to a file")
        return candidate
    candidates = [Path("/opt/homebrew/opt/speexdsp/lib/libspeexdsp.dylib"),
                  Path("/usr/local/opt/speexdsp/lib/libspeexdsp.dylib")]
    brew = shutil.which("brew")
    if brew and not any(path.is_file() for path in candidates):
        result = subprocess.run([brew, "--prefix", "speexdsp"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            candidates.insert(0, Path(result.stdout.strip()) / "lib/libspeexdsp.dylib")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = ctypes.util.find_library("speexdsp")
    if found:
        return found
    raise RuntimeError("Music mode requires speexdsp. Install it with: brew install speexdsp")
HEADER = struct.Struct("<4sIIId")
RATE = 16000


def get_audio_mode(path=SETTINGS):
    if not path.exists():
        return "mute"
    mode = json.loads(path.read_text())["audio_mode"]
    if mode not in {"mute", "music"}:
        raise ValueError("Invalid saved audio mode")
    return mode


def set_audio_mode(mode, path=SETTINGS):
    if mode not in {"mute", "music"}:
        raise ValueError("Expected mute or music audio mode")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"audio_mode": mode}) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def helper():
    from build_audio_capture import build
    find_speex_library()
    return build()


def audio_permissions(authorize=False):
    operation = "--authorize" if authorize else "--check"
    result = subprocess.run([str(helper()), operation], capture_output=True, text=True,
                            check=True, timeout=180 if authorize else 10)
    permissions = json.loads(result.stdout)
    if not isinstance(permissions, dict) or any(
        not isinstance(permissions.get(name), bool) for name in ("microphone", "system_audio")
    ):
        raise RuntimeError("The audio helper did not return valid permission states")
    return permissions


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        part = stream.read(size - len(data))
        if not part:
            if data:
                raise ValueError("Truncated native audio packet")
            return None
        data.extend(part)
    return bytes(data)


def read_packets(stream):
    import numpy as np

    while header := read_exact(stream, HEADER.size):
        magic, kind, rate, frames, timestamp = HEADER.unpack(header)
        if magic != b"WKAE" or kind not in {1, 2} or rate != RATE:
            raise ValueError("Invalid native audio packet header")
        if not 0 < frames <= 2 * RATE or not math.isfinite(timestamp):
            raise ValueError("Invalid native audio packet size or timestamp")
        payload = read_exact(stream, frames * 4)
        if payload is None:
            raise ValueError("Missing native audio samples")
        samples = np.frombuffer(payload, dtype="<f4").copy()
        if not np.isfinite(samples).all():
            raise ValueError("Nonfinite captured audio")
        yield kind, timestamp, samples


def align_packets(packets):
    import numpy as np

    microphone = [packet for packet in packets if packet[0] == 2]
    if not microphone:
        raise RuntimeError("No microphone samples were captured")
    origin = min(packet[1] for packet in microphone)
    end = max(packet[1] + len(packet[2]) / RATE for packet in microphone)
    if not 0 < end - origin <= 601:
        raise ValueError("Captured microphone timeline is outside the ten-minute limit")
    length = round((end - origin) * RATE)
    mic = np.zeros(length, dtype=np.float32)
    reference = np.zeros(length, dtype=np.float32)
    for kind, timestamp, samples in packets:
        position = round((timestamp - origin) * RATE)
        source_start = max(0, -position)
        start = max(0, position)
        count = min(len(samples) - source_start, length - start)
        if count > 0:
            target = mic if kind == 2 else reference
            target[start : start + count] = samples[source_start : source_start + count]
    return mic, reference


def estimate_delay(microphone, reference):
    import numpy as np

    count = min(len(microphone), len(reference), 8 * RATE)
    if count < RATE // 4:
        return 0, 0.0
    mic = microphone[:count].astype(np.float64)
    ref = reference[:count].astype(np.float64)
    mic -= mic.mean()
    ref -= ref.mean()
    scale = np.linalg.norm(mic) * np.linalg.norm(ref)
    if scale < 1e-12:
        return 0, 0.0
    size = 1 << (2 * count - 1).bit_length()
    correlation = np.fft.irfft(np.fft.rfft(mic, size) * np.conj(np.fft.rfft(ref, size)), size)
    limit = min(RATE // 2, count - 1)
    lags = np.arange(-limit, limit + 1)
    values = np.abs(correlation[lags % size])
    peak = int(np.argmax(values))
    return int(lags[peak]), float(values[peak] / scale)


def cancel_echo(microphone, reference):
    import numpy as np

    started = time.monotonic()
    if len(microphone) != len(reference) or not len(microphone):
        raise ValueError("Echo cancellation needs equal, nonempty audio channels")
    if not np.isfinite(microphone).all() or not np.isfinite(reference).all():
        raise ValueError("Echo cancellation received nonfinite samples")
    if np.max(np.abs(reference)) < 1e-6:
        pcm = np.round(np.clip(microphone, -1, 1) * 32767).astype(np.int16)
        return pcm.tobytes(), {"reference_active": False, "processing_seconds": 0.0}
    lag, confidence = estimate_delay(microphone, reference)
    shift = lag - 2 * 160 if confidence >= 0.12 else 0
    aligned = np.zeros_like(reference)
    if shift >= 0:
        if shift < len(reference):
            aligned[shift:] = reference[:len(reference) - shift]
    elif -shift < len(reference):
        aligned[:shift] = reference[-shift:]
    lib = ctypes.CDLL(str(find_speex_library()))
    pointer = ctypes.POINTER(ctypes.c_int16)
    lib.speex_echo_state_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.speex_echo_state_init.restype = ctypes.c_void_p
    lib.speex_echo_state_destroy.argtypes = [ctypes.c_void_p]
    lib.speex_echo_ctl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    lib.speex_echo_cancellation.argtypes = [ctypes.c_void_p, pointer, pointer, pointer]
    lib.speex_preprocess_state_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.speex_preprocess_state_init.restype = ctypes.c_void_p
    lib.speex_preprocess_state_destroy.argtypes = [ctypes.c_void_p]
    lib.speex_preprocess_ctl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    lib.speex_preprocess_run.argtypes = [ctypes.c_void_p, pointer]
    frame = 160
    echo = lib.speex_echo_state_init(frame, 4096)
    preprocess = lib.speex_preprocess_state_init(frame, RATE)
    if not echo or not preprocess:
        if echo: lib.speex_echo_state_destroy(echo)
        if preprocess: lib.speex_preprocess_state_destroy(preprocess)
        raise RuntimeError("Unable to initialize the local echo canceller")
    try:
        rate = ctypes.c_int(RATE)
        if lib.speex_echo_ctl(echo, 24, ctypes.byref(rate)) != 0:
            raise RuntimeError("Unable to configure the echo cancellation sample rate")
        if lib.speex_preprocess_ctl(preprocess, 24, echo) != 0:
            raise RuntimeError("Unable to attach the residual echo suppressor")
        for setting, value in ((0, 1), (2, 0), (18, -10), (20, -40), (22, -12)):
            control = ctypes.c_int(value)
            if lib.speex_preprocess_ctl(preprocess, setting, ctypes.byref(control)) != 0:
                raise RuntimeError("Unable to configure residual echo suppression")
        padded = ((len(microphone) + frame - 1) // frame) * frame
        mic = np.zeros(padded, dtype=np.int16)
        ref = np.zeros(padded, dtype=np.int16)
        mic[:len(microphone)] = np.round(np.clip(microphone, -1, 1) * 32767).astype(np.int16)
        ref[:len(aligned)] = np.round(np.clip(aligned, -1, 1) * 32767).astype(np.int16)
        output = np.empty(padded, dtype=np.int16)
        for index in range(0, padded, frame):
            captured = mic[index:index + frame].ctypes.data_as(pointer)
            played = ref[index:index + frame].ctypes.data_as(pointer)
            cleaned = output[index:index + frame].ctypes.data_as(pointer)
            lib.speex_echo_cancellation(echo, captured, played, cleaned)
            lib.speex_preprocess_run(preprocess, cleaned)
        metrics = {"reference_active": True, "estimated_delay_ms": round(lag * 1000 / RATE, 2),
                   "alignment_confidence": round(confidence, 4),
                   "processing_seconds": round(time.monotonic() - started, 4)}
        return output[:len(microphone)].tobytes(), metrics
    finally:
        lib.speex_preprocess_state_destroy(preprocess)
        lib.speex_echo_state_destroy(echo)
