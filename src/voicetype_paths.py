"""Resolve stable user-owned paths across application display-name changes."""

import os
from pathlib import Path
import tempfile


APP_ID = "local.voicetype"
MODEL_REPO = "mlx-community/whisper-large-v3-turbo"


def data_dir():
    override = os.environ.get("VOICETYPE_DATA_DIR")
    return Path(override).expanduser() if override else Path.home() / "Library/Application Support" / APP_ID


def log_dir():
    override = os.environ.get("VOICETYPE_LOG_DIR")
    return Path(override).expanduser() if override else Path.home() / "Library/Logs" / APP_ID


def runtime_dir():
    override = os.environ.get("VOICETYPE_RUNTIME_DIR")
    return Path(override).expanduser() if override else Path(tempfile.gettempdir()) / f"voicetype-{os.getuid()}"


def prepare_runtime():
    path = runtime_dir()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise RuntimeError("VoiceType runtime directory must be owned by the current user")
    path.chmod(0o700)
    if len(os.fsencode(path / "control.sock")) >= 104:
        raise RuntimeError("VoiceType runtime directory is too long for a macOS control socket")
    return path
