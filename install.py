"""Install, inspect, or remove VoiceType for the current macOS user."""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid


APP_ID = "local.voicetype"
PREVIOUS_APP_ID = "local.dameum"
MODEL = "mlx-community/whisper-large-v3-turbo"
BEGIN = "-- BEGIN VOICETYPE MANAGED INTEGRATION"
END = "-- END VOICETYPE MANAGED INTEGRATION"
ROOT = Path(__file__).resolve().parent
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def find_tool(name):
    found = shutil.which(name)
    if found:
        return found
    candidate = Path("/opt/homebrew/bin") / name
    return str(candidate) if candidate.is_file() else None


def find_hammerspoon():
    for folder in (Path("/Applications"), Path.home() / "Applications"):
        app = folder / "Hammerspoon.app"
        if app.is_dir():
            return app
    return None


def check_environment():
    problems = []
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        problems.append("VoiceType supports Apple Silicon Macs only.")
    elif int(platform.mac_ver()[0].split(".")[0]) < 15:
        problems.append("macOS 15 or later is required.")
    for tool in ("uv", "sox"):
        if not find_tool(tool):
            problems.append(f"Missing {tool}. Install dependencies with: brew install uv sox speexdsp")
    if not find_hammerspoon():
        problems.append("Missing Hammerspoon. Install it with: brew install --cask hammerspoon")
    library = os.environ.get("VOICETYPE_SPEEXDSP_LIBRARY")
    candidates = [Path(library).expanduser()] if library else [
        Path("/opt/homebrew/opt/speexdsp/lib/libspeexdsp.dylib"),
        Path("/usr/local/opt/speexdsp/lib/libspeexdsp.dylib"),
    ]
    if not any(p.is_file() for p in candidates):
        problems.append("Missing speexdsp. Install it with: brew install speexdsp")
    if not (ROOT / "payload/VoiceType Audio.app").is_dir():
        result = subprocess.run(["/usr/bin/xcrun", "--find", "swiftc"], capture_output=True)
        if result.returncode:
            problems.append("Source installation needs Apple's command line developer tools: xcode-select --install")
    return problems


def edit_integration(original, enabled, legacy=None):
    if original.count(BEGIN) != original.count(END) or original.count(BEGIN) > 1:
        raise RuntimeError("VoiceType found an invalid VoiceType integration block from the previous installation; no changes made")
    if BEGIN in original:
        start = original.index(BEGIN)
        finish = original.index(END, start) + len(END)
        original = original[:start] + original[finish:].lstrip("\n")
    if legacy is not None:
        previous_path = f"/Library/Application Support/{legacy.name}/integration/"
        blocks = re.compile(
            r"^-- BEGIN (?P<label>[A-Z0-9_ ]+) MANAGED INTEGRATION\n"
            r"(?P<body>.*?)^-- END (?P=label) MANAGED INTEGRATION(?:\n|$)",
            re.MULTILINE | re.DOTALL,
        )
        original = blocks.sub(lambda match: "" if previous_path in match["body"] else match[0], original)
        if previous_path in original:
            raise RuntimeError("The previous installation has an invalid managed integration block")
    if not enabled:
        return original
    block = '\n'.join([
        BEGIN,
        'require("hs.ipc")',
        'dofile(os.getenv("HOME") .. "/Library/Application Support/local.voicetype/integration/voicetype.lua")',
        END,
        '',
    ])
    return original.rstrip("\n") + ("\n\n" if original.strip() else "") + block


def write_file(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(text)
    temporary.chmod(0o700 if executable else 0o600)
    temporary.replace(path)


def launch_agent(home, data, logs):
    if not data.is_relative_to(home) or not logs.is_relative_to(home):
        raise RuntimeError("VoiceType must be installed within the current user's home directory")
    return {
        "Label": APP_ID,
        "ProgramArguments": [str(data / "bin/voicetype"), "serve", "--open-ui"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "ExitTimeOut": 30,
        "WorkingDirectory": str(data),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
        "StandardOutPath": str(logs / "launchd.log"),
        "StandardErrorPath": str(logs / "launchd.log"),
    }


def run_client(binary, *arguments, timeout=5):
    result = subprocess.run([str(binary), *arguments], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stdout.strip() or result.stderr.strip())
    return json.loads(result.stdout)


def running(label):
    return subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def stop_agent(label, binary=None):
    if not running(label):
        return False
    if binary is not None:
        state = run_client(binary, "status")
        if state.get("status") == "recording":
            raise RuntimeError("Finish the active recording before installing or removing VoiceType")
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], check=True)
    deadline = time.monotonic() + 45
    while running(label):
        if time.monotonic() >= deadline:
            raise RuntimeError(f"The previous service is still shutting down: {label}")
        time.sleep(0.1)
    return True


def start_agent(plist):
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)], check=True)


def refresh_hammerspoon():
    app = find_hammerspoon()
    subprocess.run(["open", "-ga", str(app)], check=True)
    cli = app / "Contents/Frameworks/hs/hs"
    for _ in range(15):
        check = subprocess.run([str(cli), "-c", "return true"], capture_output=True)
        if check.returncode == 0:
            result = subprocess.run([str(cli), "-c", "hs.reload()"], capture_output=True, text=True)
            if result.returncode not in (0, 69):
                raise RuntimeError("Could not reload Hammerspoon: " + result.stderr)
            return
        time.sleep(0.2)
    subprocess.run(["/usr/bin/killall", "-TERM", "Hammerspoon"], capture_output=True)
    for _ in range(30):
        if subprocess.run(["/usr/bin/pgrep", "-x", "Hammerspoon"], capture_output=True).returncode:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("Hammerspoon did not close; reload its configuration manually")
    subprocess.run(["open", "-ga", str(app)], check=True)
    for _ in range(30):
        if subprocess.run([str(cli), "-c", "return true"], capture_output=True).returncode == 0:
            return
        time.sleep(0.2)
    raise RuntimeError("Hammerspoon did not expose its control connection after restarting")


def previous_installation(home, selected=None):
    support = home / "Library/Application Support"
    data = selected.expanduser() if selected else support / PREVIOUS_APP_ID
    if not (data / "installation.json").is_file():
        if selected:
            raise RuntimeError("The selected previous installation has no installation manifest")
        return None
    if data.is_symlink() or data.parent.resolve() != support.resolve() or data.name == APP_ID:
        raise RuntimeError("The previous installation must be a separate user-owned application directory")
    manifest = json.loads((data / "installation.json").read_text())
    label = manifest.get("app_id")
    release = Path(manifest.get("release", ""))
    if (label != data.name or not re.fullmatch(r"local\.[a-z0-9.-]+", label or "") or
            release.is_symlink() or release.resolve().parent != (data / "releases").resolve()):
        raise RuntimeError("The previous installation ownership could not be verified")
    agent = home / "Library/LaunchAgents" / (label + ".plist")
    if not agent.is_file() or agent.is_symlink():
        raise RuntimeError("The previous installation has no valid startup registration")
    with agent.open("rb") as stream:
        registration = plistlib.load(stream)
    arguments = registration.get("ProgramArguments", [])
    binary = Path(arguments[0]) if arguments else Path()
    if (registration.get("Label") != label or not binary.is_file() or
            binary.resolve().parent != (data / "bin").resolve()):
        raise RuntimeError("The previous startup registration does not belong to the selected installation")
    return {"data": data, "label": label, "agent": agent, "binary": binary, "version": manifest.get("version")}


def reset_previous_permissions(previous):
    for app in sorted(previous["data"].glob("*.app")):
        info = app / "Contents/Info.plist"
        if app.is_symlink() or not info.is_file():
            raise RuntimeError("The previous audio application is not a valid owned application")
        with info.open("rb") as stream:
            identifier = plistlib.load(stream).get("CFBundleIdentifier", "")
        if not identifier.startswith("local.") or identifier == "local.voicetype.audio":
            raise RuntimeError("The previous audio application identity could not be verified")
        subprocess.run(["/usr/bin/tccutil", "reset", "All", identifier], check=True)


def archive_previous_installation(previous, backup, home):
    previous["agent"].unlink()
    shutil.move(str(previous["data"]), str(backup / "previous-installation"))
    logs = home / "Library/Logs" / previous["label"]
    if logs.is_dir() and not logs.is_symlink():
        shutil.move(str(logs), str(backup / "previous-logs"))
    runtime = Path(tempfile.gettempdir()) / f"{previous['label'].split('.')[-1]}-{os.getuid()}"
    if runtime.is_dir() and not runtime.is_symlink() and runtime.stat().st_uid == os.getuid():
        shutil.rmtree(runtime)


def install(args):
    verify_distribution()
    problems = check_environment()
    if problems:
        raise RuntimeError("\n".join(problems))
    home = Path.home()
    data = home / "Library/Application Support" / APP_ID
    logs = home / "Library/Logs" / APP_ID
    releases = data / "releases"
    release = releases / VERSION
    if release.exists():
        raise RuntimeError(f"Version {VERSION} is already installed. Remove it before reinstalling the same version.")
    previous = previous_installation(home, args.migrate_from)
    hammerspoon = home / ".hammerspoon/init.lua"
    original_init = hammerspoon.read_text() if hammerspoon.exists() else ""
    updated_init = edit_integration(original_init, True, previous["data"] if previous else None)
    marker = data / "installation.json"
    previous_manifest = json.loads(marker.read_text()) if marker.exists() else None
    public_launcher = data / "bin/voicetype"
    if public_launcher.is_symlink() or (public_launcher.exists() and previous_manifest is None):
        raise RuntimeError("The VoiceType launcher path is already occupied by an unmanaged file")
    print(f"Installing VoiceType {VERSION} for {home.name}", flush=True)
    print("Audio stays local. Installation may download Python, dependencies, and the Whisper model.", flush=True)
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    data.chmod(0o700)
    logs.mkdir(mode=0o700, parents=True, exist_ok=True)
    releases.mkdir(parents=True, exist_ok=True)
    stage = releases / (".install-" + uuid.uuid4().hex)
    stage.mkdir()
    try:
        for name in ("LICENSE", "THIRD_PARTY.md", "RELEASE_PLAN.md", "README.md", "CHANGELOG.md", "pyproject.toml", "uv.lock", "install.py", "Install.command", "Uninstall.command"):
            shutil.copy2(ROOT / name, stage / name)
        shutil.copytree(ROOT / "src", stage / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        stage.rename(release)
        subprocess.run([find_tool("uv"), "sync", "--locked", "--no-editable", "--no-dev", "--python", "3.13",
                        "--project", str(release)], check=True,
                       env={key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"})
        python = release / ".venv/bin/python"
        download = (
            "from huggingface_hub import snapshot_download; "
            f"print(snapshot_download({MODEL!r}, local_files_only={args.offline!r}))"
        )
        subprocess.run([str(python), "-c", download], check=True)
        payload = ROOT / "payload/VoiceType Audio.app"
        helper_app = data / "VoiceType Audio.app"
        if not helper_app.exists():
            if payload.is_dir():
                subprocess.run(["codesign", "--verify", "--deep", "--strict", str(payload)], check=True)
                shutil.copytree(payload, helper_app)
        subprocess.run([str(python), "-c", "from build_audio_capture import build; print(build())"], check=True)
        subprocess.run([str(helper_app / "Contents/MacOS/voicetype-audio"), "--self-test"],
                       stdout=subprocess.DEVNULL, check=True)
    except BaseException:
        if stage.exists():
            shutil.rmtree(stage)
        if release.exists():
            shutil.rmtree(release)
        raise

    backup = data / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True)
    if hammerspoon.exists():
        shutil.copy2(hammerspoon, backup / "hammerspoon-init.lua")
    agent = home / "Library/LaunchAgents" / (APP_ID + ".plist")
    original_agent = agent.read_bytes() if agent.exists() else None
    if original_agent:
        (backup / agent.name).write_bytes(original_agent)
    if previous:
        shutil.copy2(previous["agent"], backup / previous["agent"].name)
    settings = data / "settings.json"
    managed_paths = [public_launcher, data / "integration/voicetype.lua", marker, settings]
    previous_files = {path: path.read_bytes() if path.exists() else None for path in managed_paths}
    old_stopped = current_stopped = activated = False
    try:
        if previous:
            old_stopped = stop_agent(previous["label"], previous["binary"])
        current_stopped = stop_agent(APP_ID, data / "bin/voicetype")
        if previous and not settings.exists() and (previous["data"] / "settings.json").is_file():
            shutil.copy2(previous["data"] / "settings.json", settings)
        launcher = '#!/bin/sh\nset -eu\nexec ' + shlex.quote(str(release / ".venv/bin/voicetype")) + ' "$@"\n'
        write_file(data / "bin/voicetype", launcher, executable=True)
        integration = subprocess.check_output([
            str(release / ".venv/bin/python"), "-c",
            "from importlib.resources import files; print(files('voicetype_resources').joinpath('voicetype.lua').read_text(), end='')",
        ], text=True)
        write_file(data / "integration/voicetype.lua", integration)
        write_file(hammerspoon, updated_init)
        agent.parent.mkdir(parents=True, exist_ok=True)
        agent.write_bytes(plistlib.dumps(launch_agent(home, data, logs)))
        manifest = {"app_id": APP_ID, "name": "VoiceType", "version": VERSION, "release": str(release),
                    "installed_at": datetime.now().astimezone().isoformat(),
                    "previous_version": previous_manifest.get("version") if previous_manifest else
                    (previous["version"] if previous else None)}
        write_file(marker, json.dumps(manifest, indent=2) + "\n")
        start_agent(agent)
        activated = True
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                state = run_client(data / "bin/voicetype", "status")
                break
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                time.sleep(0.5)
        else:
            raise RuntimeError(f"VoiceType did not become ready. Inspect {logs / 'launchd.log'}")
        refresh_hammerspoon()
        if previous:
            reset_previous_permissions(previous)
    except BaseException:
        if activated:
            stop_agent(APP_ID)
        write_file(hammerspoon, original_init)
        for path, content in previous_files.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
                if path.name == "voicetype":
                    path.chmod(0o700)
        if original_agent is not None:
            agent.write_bytes(original_agent)
        else:
            agent.unlink(missing_ok=True)
        if current_stopped and original_agent:
            start_agent(agent)
        if old_stopped:
            start_agent(previous["agent"])
        refresh_hammerspoon()
        shutil.rmtree(release)
        raise
    if previous:
        archive_previous_installation(previous, backup, home)
    print(json.dumps({"installed": manifest, "state": state, "backup": str(backup)}, indent=2))


def uninstall():
    home = Path.home()
    data = home / "Library/Application Support" / APP_ID
    marker = data / "installation.json"
    if not marker.is_file():
        raise RuntimeError("No managed VoiceType installation was found")
    manifest = json.loads(marker.read_text())
    releases = data / "releases"
    release = Path(manifest["release"])
    if manifest.get("app_id") != APP_ID or release.parent != releases or release.is_symlink():
        raise RuntimeError("VoiceType installation ownership could not be verified")
    hammerspoon = home / ".hammerspoon/init.lua"
    original = hammerspoon.read_text() if hammerspoon.exists() else ""
    updated = edit_integration(original, False)
    stop_agent(APP_ID, data / "bin/voicetype")
    write_file(hammerspoon, updated)
    (home / "Library/LaunchAgents" / (APP_ID + ".plist")).unlink(missing_ok=True)
    for path in (data / "bin/voicetype", data / "integration/voicetype.lua", marker):
        path.unlink(missing_ok=True)
    if release.is_dir():
        shutil.rmtree(release)
    helper = data / "VoiceType Audio.app"
    if helper.is_dir() and not helper.is_symlink():
        shutil.rmtree(helper)
    refresh_hammerspoon()
    print("VoiceType removed from automatic startup and Hammerspoon.")
    print(f"Personal settings and backups remain at {data}; shared models are preserved.")


def verify_distribution():
    root = ROOT.resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text())
    for relative, digest in manifest["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise RuntimeError("The installer contains a missing or invalid file: " + relative)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError("The installer contains a modified file: " + relative)
    if manifest.get("name") != "VoiceType" or manifest.get("version") != VERSION:
        raise RuntimeError("The installer manifest does not match this VoiceType version")


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        "Requires Apple Silicon, macOS 15+, uv, sox, speexdsp and Hammerspoon. "
        "Run Install.command to install missing prerequisites, including Homebrew, automatically. "
        "Internet access is required for initial setup. Homebrew may request an administrator password. "
        "First use needs macOS audio/accessibility permission. "
        "Recording: Cmd+Option+D. Audio mode: Cmd+Option+Shift+M. "
        "Uninstall preserves personal settings and shared models."
    ))
    parser.add_argument("command", choices=("check", "install", "uninstall"))
    parser.add_argument("--offline", action="store_true", help="Require the Whisper model to be cached already")
    parser.add_argument("--migrate-from", type=Path, help="Import settings and replace a managed installation in the current user's Application Support directory")
    args = parser.parse_args()
    try:
        if args.command == "check":
            problems = check_environment()
            print(json.dumps({"ready_to_install": not problems, "problems": problems}, indent=2))
            return int(bool(problems))
        if args.command == "install":
            install(args)
        else:
            uninstall()
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print("VoiceType: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
