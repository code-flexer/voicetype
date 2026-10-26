"""Local dictation with ordered audio delivery and a continuous recording context."""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import wave


from voicetype_paths import MODEL_REPO, data_dir, log_dir, prepare_runtime, runtime_dir


STATE = data_dir()
LOG_DIR = log_dir()
SOCKET = runtime_dir() / "control.sock"
RATE = 16000
FRAME_SAMPLES = 480
FRAME_BYTES = FRAME_SAMPLES * 2
LOG = logging.getLogger("voicetype")


@dataclass(frozen=True)
class Chunk:
    pcm: bytes
    start_sample: int
    emit_from: int
    emit_until: int


class Chunker:
    """Split on pauses, retaining timed overlap at forced boundaries."""

    def __init__(self, minimum_seconds=6.0, maximum_seconds=10.0):
        if not 0 < minimum_seconds <= maximum_seconds:
            raise ValueError("Invalid chunk durations")
        self.minimum = round(minimum_seconds * RATE)
        self.maximum = round(maximum_seconds * RATE)
        self.frames = deque()
        self.cursor = 0
        self.emit_from = 0
        self.trailing = 0
        self.active = False

    def feed(self, pcm: bytes, speech: bool) -> list[Chunk]:
        if len(pcm) != FRAME_BYTES:
            raise ValueError("Expected a complete 30 ms PCM frame")
        self.frames.append((self.cursor, pcm, speech))
        self.cursor += FRAME_SAMPLES
        if speech:
            self.active = True
            self.trailing = 0
        else:
            self.trailing += 1
        if not self.active:
            while len(self.frames) > 10:
                self.frames.popleft()
            return []
        size = len(self.frames) * FRAME_SAMPLES
        if size >= self.minimum and self.trailing >= 6:
            return self._emit(forced=False)
        if size >= self.maximum:
            return self._emit(forced=True)
        return []

    def _emit(self, forced: bool) -> list[Chunk]:
        if not self.frames:
            return []
        frames = list(self.frames)
        voiced = sum(int(frame[2]) for frame in frames)
        overlap = 17 if forced else 0
        end = frames[-1][0] + FRAME_SAMPLES
        until = end - (overlap // 2) * FRAME_SAMPLES
        result = []
        if voiced >= 3:
            result.append(Chunk(b"".join(f[1] for f in frames), frames[0][0],
                                self.emit_from, until))
        self.emit_from = until
        self.frames = deque(frames[-overlap:] if overlap else [])
        self.active = any(f[2] for f in self.frames)
        self.trailing = 0
        return result

    def finish(self) -> list[Chunk]:
        return self._emit(forced=False)


def committed_text(result: dict, chunk: Chunk) -> str:
    words = [word for segment in result.get("segments", [])
             for word in segment.get("words", [])]
    if result.get("text", "").strip() and not words:
        raise RuntimeError("The decoder returned text without required word timestamps")
    kept = []
    for word in words:
        midpoint = chunk.start_sample + (word["start"] + word["end"]) * RATE / 2
        if chunk.emit_from <= midpoint < chunk.emit_until:
            kept.append(word["word"])
    return "".join(kept).strip()


class Engine:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="decoder")
        self.pool.submit(self._warm).result()

    def _warm(self):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        from huggingface_hub import snapshot_download
        import mlx_whisper
        import numpy as np

        self.model = snapshot_download(MODEL_REPO, local_files_only=True)
        self.decode = mlx_whisper.transcribe
        self.np = np
        self.decode(np.zeros(RATE, dtype=np.float32), path_or_hf_repo=self.model,
                    language="ko", temperature=0.0, condition_on_previous_text=False)

    def submit(self, chunk: Chunk):
        queued = time.monotonic()
        return self.pool.submit(self._transcribe, chunk, queued)

    def _transcribe(self, chunk: Chunk, queued: float) -> dict:
        started = time.monotonic()
        audio = self.np.frombuffer(chunk.pcm, dtype=self.np.int16).astype(self.np.float32) / 32768
        rms = float(self.np.sqrt(self.np.mean(audio ** 2))) if audio.size else 0.0
        peak = float(self.np.max(self.np.abs(audio))) if audio.size else 0.0
        if rms < 0.01 and peak < 0.05:
            return {"text": "", "metrics": {"audio_seconds": round(len(audio) / RATE, 3),
                    "queue_seconds": round(started - queued, 3), "decode_seconds": 0.0,
                    "skipped_silence": True}}
        timed_boundary = (chunk.start_sample < chunk.emit_from or
                          chunk.emit_until < chunk.start_sample + len(audio))
        result = self.decode(
            audio, path_or_hf_repo=self.model, language="ko",
            temperature=(0.0, 0.2, 0.4), condition_on_previous_text=False,
            word_timestamps=timed_boundary,
            hallucination_silence_threshold=1.0 if timed_boundary else None,
        )
        text = committed_text(result, chunk) if timed_boundary else result["text"].strip()
        metrics = {"audio_seconds": round(len(audio) / RATE, 3),
                   "queue_seconds": round(started - queued, 3),
                   "decode_seconds": round(time.monotonic() - started, 3)}
        LOG.info("chunk %s", json.dumps(metrics))
        return {"text": text, "metrics": metrics}

    def close(self):
        self.pool.shutdown(wait=True)


class CumulativeDecoder:
    """Adapt an ordered audio session to the existing whole-audio local decoder."""

    def __init__(self, engine, speculative=False):
        self.engine = engine
        self.speculative = speculative
        self.condition = threading.Condition()
        self.audio = bytearray()
        self.completed_size = 0
        self.latest = {"text": "", "metrics": {}}
        self.history = []
        self.closed = False
        self.error = None
        self.worker = threading.Thread(target=self._run, name="audio-session", daemon=True)
        self.worker.start()

    def append(self, pcm):
        if len(pcm) % 2:
            raise ValueError("PCM samples must contain complete 16-bit values")
        with self.condition:
            if self.closed:
                raise RuntimeError("The audio session has already ended")
            self.audio.extend(pcm)
            self.condition.notify()

    def _run(self):
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.closed or
                                            (self.speculative and len(self.audio) > self.completed_size))
                    if len(self.audio) == self.completed_size and self.closed:
                        return
                    snapshot = bytes(self.audio)
                chunk = Chunk(snapshot, 0, 0, len(snapshot) // 2)
                result = self.engine.submit(chunk).result()
                with self.condition:
                    self.completed_size = len(snapshot)
                    self.latest = result
                    self.history.append(result["metrics"])
        except Exception as error:
            self.error = error

    def finish(self):
        with self.condition:
            self.closed = True
            self.condition.notify()
        self.worker.join()
        if self.error:
            raise RuntimeError(str(self.error)) from self.error
        return self.latest, self.history


class OutputMute:
    """Mute only an unmuted output, then restore only changes owned by this session."""

    def __init__(self, get_muted=None, set_muted=None):
        self.get_muted = get_muted or self._get_muted
        self.set_muted = set_muted or self._set_muted
        self.lock = threading.Lock()
        self.owned = False
        self.active = True
        self.error = None
        self.timer = None

    @staticmethod
    def _get_muted():
        result = subprocess.run(["/usr/bin/osascript", "-e", "output muted of (get volume settings)"],
                                capture_output=True, text=True, check=True, timeout=3)
        value = result.stdout.strip()
        if value not in {"true", "false"}:
            raise RuntimeError("Unable to read the current output mute state")
        return value == "true"

    @staticmethod
    def _set_muted(value):
        subprocess.run(["/usr/bin/osascript", "-e",
                        "set volume output muted " + ("true" if value else "false")],
                       capture_output=True, check=True, timeout=3)

    def apply(self, ready=lambda: True):
        with self.lock:
            if not self.active or not ready():
                return
            try:
                if not self.get_muted():
                    self.set_muted(True)
                    self.owned = True
            except Exception as error:
                self.error = error

    def arm(self, ready):
        self.timer = threading.Timer(0.5, self.apply, args=(ready,))
        self.timer.daemon = True
        self.timer.start()

    def restore(self):
        if self.timer:
            self.timer.cancel()
        with self.lock:
            self.active = False
            if self.owned:
                try:
                    self.set_muted(False)
                    self.owned = False
                except Exception as error:
                    self.error = error
        if self.error:
            raise RuntimeError("Output mute control failed: " + str(self.error)) from self.error


class Session:
    def __init__(self, engine: Engine, source: Path | None = None, paced=False, mode="session", mute_output=False, audio_mode="mute"):
        if mode not in {"session", "preview", "split"}:
            raise ValueError("Expected session, preview, or split mode")
        self.engine = engine
        self.mode = mode
        if audio_mode not in {"mute", "music"}:
            raise ValueError("Expected mute or music audio mode")
        self.audio_mode = audio_mode
        if mode == "split":
            import webrtcvad
            self.vad = webrtcvad.Vad(2)
        self.cumulative = None
        self.output_mute = OutputMute() if mute_output and source is None and audio_mode == "mute" else None
        self.capture_ended = threading.Event()
        self.capture_ended_at = None
        self.echo_metrics = None
        self.packet = bytearray()
        self.chunker = Chunker()
        self.jobs = []
        self.error = None
        self.process = None
        self.started = time.monotonic()
        self.finish_requested = threading.Event()
        self.source = source
        self.paced = paced
        self.thread = threading.Thread(target=self._capture, name="audio-reader", daemon=True)

    def start(self):
        if self.source is None:
            if self.audio_mode == "music":
                from audio_modes import audio_permissions, helper
                executable = helper()
                permissions = audio_permissions()
                if not all(permissions.get(name) is True for name in ("microphone", "system_audio")):
                    missing = [label for name, label in (("microphone", "Microphone"), ("system_audio", "System audio"))
                               if not permissions[name]]
                    raise RuntimeError(" · ".join(missing) + " permission required.\nChoose VoiceType → Grant audio permissions…")
                command = [str(executable)]
            else:
                executable = shutil.which("sox")
                if not executable:
                    raise RuntimeError("sox is required for microphone recording")
                command = [executable, "-q", "-d", "-c", "1", "-r", str(RATE),
                           "-b", "16", "-e", "signed-integer", "-t", "raw", "-"]
            LOG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.stderr = (LOG_DIR / "recorder.log").open("wb")
            try:
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE, stderr=self.stderr,
                )
            except Exception:
                self.stderr.close()
                raise
        if self.mode != "split":
            self.cumulative = CumulativeDecoder(self.engine, speculative=self.mode == "preview")
        self.thread.start()
        if self.output_mute:
            self.output_mute.arm(lambda: self.chunker.cursor > 0 and not self.finish_requested.is_set())

    def _feed(self, pcm: bytes):
        if self.mode != "split":
            self.chunker.cursor += len(pcm) // 2
            self.packet.extend(pcm)
            packet_bytes = 3 * RATE * 2
            while len(self.packet) >= packet_bytes:
                self.cumulative.append(bytes(self.packet[:packet_bytes]))
                del self.packet[:packet_bytes]
            return
        if len(pcm) < FRAME_BYTES:
            pcm += b"\0" * (FRAME_BYTES - len(pcm))
        for chunk in self.chunker.feed(pcm, self.vad.is_speech(pcm, RATE)):
            self.jobs.append(self.engine.submit(chunk))

    def _capture(self):
        try:
            if self.source:
                with wave.open(str(self.source), "rb") as recording:
                    if (recording.getframerate(), recording.getnchannels(), recording.getsampwidth()) != (RATE, 1, 2):
                        raise ValueError("Expected a 16 kHz mono 16-bit PCM WAV")
                    while pcm := recording.readframes(FRAME_SAMPLES):
                        self._feed(pcm)
                        if self.paced:
                            deadline = self.started + self.chunker.cursor / RATE
                            time.sleep(max(0, deadline - time.monotonic()))
            else:
                if self.audio_mode == "music":
                    from audio_modes import align_packets, cancel_echo, read_packets
                    packets = []
                    first = None
                    for packet in read_packets(self.process.stdout):
                        if first is None:
                            first = packet[1]
                        if packet[1] - first > 600:
                            raise RuntimeError("Recording exceeded ten minutes; nothing was copied")
                        packets.append(packet)
                else:
                    while pcm := self.process.stdout.read(FRAME_BYTES):
                        self._feed(pcm)
                        if self.chunker.cursor / RATE > 600:
                            raise RuntimeError("Recording exceeded ten minutes; nothing was copied")
                code = self.process.wait(timeout=3)
                self.capture_ended_at = time.monotonic()
                self.capture_ended.set()
                if not self.finish_requested.is_set():
                    raise RuntimeError(f"Microphone recorder stopped unexpectedly ({code}); see Library/Logs/local.voicetype/recorder.log")
                if code not in {0, -signal.SIGINT}:
                    raise RuntimeError(f"Microphone capture failed ({code}); see Library/Logs/local.voicetype/recorder.log")
                if self.audio_mode == "music":
                    microphone, reference = align_packets(packets)
                    pcm, self.echo_metrics = cancel_echo(microphone, reference)
                    self._feed(pcm)
            if self.mode != "split":
                if self.packet:
                    self.cumulative.append(bytes(self.packet))
                    self.packet.clear()
            else:
                for chunk in self.chunker.finish():
                    self.jobs.append(self.engine.submit(chunk))
        except Exception as error:
            self.error = error
        finally:
            if self.capture_ended_at is None:
                self.capture_ended_at = time.monotonic()
            self.capture_ended.set()
            if self.process:
                if self.process.poll() is None:
                    self.process.kill()
                    self.process.wait()
                self.process.stdout.close()
                self.stderr.close()
            if self.output_mute:
                try:
                    self.output_mute.restore()
                except RuntimeError as error:
                    self.error = self.error or error

    def finish(self, copy: bool = True) -> dict:
        requested = time.monotonic()
        self.finish_requested.set()
        if self.process and self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
        if self.process and not self.capture_ended.wait(timeout=5):
            self.process.kill()
            self.thread.join(timeout=3)
            raise RuntimeError("Microphone capture did not stop; nothing was copied")
        self.thread.join(timeout=120 if self.process else None)
        if self.thread.is_alive():
            self.process.kill()
            self.thread.join(timeout=3)
            raise RuntimeError("Microphone recorder did not stop cleanly; nothing was copied")
        if self.error:
            if self.cumulative:
                self.cumulative.finish()
            for job in self.jobs:
                job.result()
            raise RuntimeError(str(self.error)) from self.error
        audio_ended = time.monotonic()
        if self.cumulative:
            latest, history = self.cumulative.finish()
            outputs = [latest]
        else:
            outputs = [job.result() for job in self.jobs]
            history = [out["metrics"] for out in outputs]
        text = " ".join(out["text"] for out in outputs if out["text"])
        decoded = time.monotonic()
        if copy and text:
            subprocess.run(["/usr/bin/pbcopy"], input=text.encode("utf-8"), check=True, timeout=5)
        completed = time.monotonic()
        metrics = {
            "audio_seconds": round(self.chunker.cursor / RATE, 3),
            "recording_stop_seconds": round(max(0, (self.capture_ended_at or audio_ended) - requested), 3),
            "audio_preprocess_seconds": round(max(0, audio_ended - max(requested, self.capture_ended_at or audio_ended)), 3),
            "remaining_decode_seconds": round(decoded - audio_ended, 3),
            "clipboard_seconds": round(completed - decoded, 3),
            "stop_to_result_seconds": round(completed - requested, 3),
            "chunks": history,
            "mode": self.mode,
            "audio_mode": self.audio_mode,
            "echo_cancellation": self.echo_metrics,
            "context": "complete audio from recording start" if self.cumulative else "independent split audio",
        }
        LOG.info("completed %s", json.dumps(metrics))
        return {"status": "completed", "text": text, "copied": bool(copy and text), "metrics": metrics}


class Controller:
    def __init__(self, engine):
        self.engine = engine
        self.session = None

    def handle(self, command, audio_mode=None):
        from audio_modes import audio_permissions, get_audio_mode, helper, set_audio_mode
        if command == "status":
            return {"status": "recording" if self.session else "ready", "offline": True, "model": MODEL_REPO,
                    "audio_mode": get_audio_mode()}
        if command in {"check-permissions", "audio-permissions"}:
            if self.session:
                raise RuntimeError("Finish the active recording before checking audio permissions")
            return {"status": "permissions", **audio_permissions(authorize=command == "audio-permissions")}
        if command == "set-audio-mode":
            if self.session:
                raise RuntimeError("Finish the active recording before changing audio mode")
            if audio_mode == "music":
                helper()
            set_audio_mode(audio_mode)
            return {"status": "ready", "audio_mode": audio_mode}
        if command not in {"start", "stop", "toggle", "shutdown"}:
            raise ValueError("Expected status, start, stop, toggle, or shutdown")
        if command == "shutdown":
            if self.session:
                raise RuntimeError("Stop the active recording before shutting down")
            return {"status": "shutdown"}
        if command == "start" or (command == "toggle" and self.session is None):
            if self.session:
                raise RuntimeError("A recording is already active")
            selected = get_audio_mode()
            session = Session(self.engine, mute_output=selected == "mute", audio_mode=selected)
            session.start()
            self.session = session
            return {"status": "recording"}
        if self.session is None:
            raise RuntimeError("No recording is active")
        session, self.session = self.session, None
        return session.finish()


def serve(open_ui=False):
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE, 0o700)
    prepare_runtime()
    LOG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (runtime_dir() / "daemon.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("The VoiceType service is already running") from None
        handler = RotatingFileHandler(LOG_DIR / "metrics.log", maxBytes=2_000_000, backupCount=2)
        logging.basicConfig(level=logging.INFO, handlers=[handler])
        engine = Engine()
        controller = Controller(engine)

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    line = self.rfile.readline(1025)
                    if len(line) > 1024:
                        raise ValueError("Control request is too large")
                    request = json.loads(line)
                    result = controller.handle(request["command"], request.get("audio_mode"))
                except Exception as error:
                    result = {"status": "error", "error": str(error)}
                try:
                    self.wfile.write((json.dumps(result, ensure_ascii=False) + "\n").encode())
                except (BrokenPipeError, ConnectionResetError):
                    LOG.error("Control client disconnected before result delivery")
                if result["status"] == "shutdown":
                    threading.Thread(target=self.server.shutdown, daemon=True).start()

        if SOCKET.exists():
            SOCKET.unlink()
        try:
            with socketserver.UnixStreamServer(str(SOCKET), Handler) as server:
                os.chmod(SOCKET, 0o600)
                def terminate(signum, frame):
                    threading.Thread(target=server.shutdown, daemon=True).start()
                signal.signal(signal.SIGTERM, terminate)
                signal.signal(signal.SIGINT, terminate)
                if open_ui:
                    subprocess.run(["/usr/bin/open", "-ga", "Hammerspoon"], check=True)
                LOG.info("ready offline=true model=%s", MODEL_REPO)
                server.serve_forever(poll_interval=0.1)
        finally:
            SOCKET.unlink(missing_ok=True)
            if controller.session:
                controller.session.finish(copy=False)
            engine.close()


def request(command: str, timeout: float = 300, audio_mode=None) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(SOCKET))
        payload = {"command": command}
        if audio_mode is not None:
            payload["audio_mode"] = audio_mode
        connection.sendall((json.dumps(payload) + "\n").encode())
        with connection.makefile("rb") as stream:
            line = stream.readline(4 * 1024 * 1024)
        if not line.endswith(b"\n"):
            raise RuntimeError("Incomplete response from the VoiceType service")
        result = json.loads(line)
        if result["status"] == "error":
            raise RuntimeError(result["error"])
        return result


def ensure_daemon():
    try:
        request("status", timeout=0.5)
        return
    except (OSError, RuntimeError):
        pass
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    prepare_runtime()
    LOG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (LOG_DIR / "startup.log").open("ab") as log:
        process = subprocess.Popen([sys.executable, "-m", "voicetype", "serve"],
                                   stdout=log, stderr=log, start_new_session=True)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            request("status", timeout=0.5)
            return
        except (OSError, RuntimeError):
            if process.poll() is not None:
                raise RuntimeError("VoiceType failed to start; see the user Library/Logs/local.voicetype/startup.log") from None
            time.sleep(0.2)
    raise RuntimeError(f"VoiceType startup timed out; see {LOG_DIR / 'startup.log'}")


def benchmark(engine: Engine, source: Path, mode="session") -> dict:
    with wave.open(str(source), "rb") as recording:
        if (recording.getframerate(), recording.getnchannels(), recording.getsampwidth()) != (RATE, 1, 2):
            raise ValueError("Expected a 16 kHz mono 16-bit PCM WAV")
        pcm = recording.readframes(recording.getnframes())

    def baseline():
        audio = engine.np.frombuffer(pcm, dtype=engine.np.int16).astype(engine.np.float32) / 32768
        started = time.monotonic()
        result = engine.decode(audio, path_or_hf_repo=engine.model, language="ko",
                               temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
                               condition_on_previous_text=False)
        return {"decode_seconds": round(time.monotonic() - started, 3),
                "text": result["text"].strip()}

    full_recording = engine.pool.submit(baseline).result()
    session = Session(engine, source=source, paced=True, mode=mode)
    session.start()
    session.thread.join()
    streamed = session.finish(copy=False)
    import hashlib

    return {"status": "benchmark-completed", "input_sha256": hashlib.sha256(pcm).hexdigest(),
            "input_hash_scope": "Decoded PCM frames, not the WAV container",
            "model": MODEL_REPO, "baseline": full_recording, "v2": streamed,
            "limits": ["Single warmed-model run with synthetic real-time file delivery",
                       "Baseline uses v1 decoder settings, not the running v1 application",
                       "No microphone, music, recorder, hotkey, or clipboard latency measured"]}


def main():
    parser = argparse.ArgumentParser(prog="voicetype", description=__doc__)
    parser.add_argument("command", choices=["serve", "status", "start", "stop", "toggle", "shutdown", "transcribe-file", "benchmark-file", "set-audio-mode", "audio-permissions", "check-permissions"])
    parser.add_argument("file", nargs="?", type=Path)
    parser.add_argument("--copy", action="store_true")
    parser.add_argument("--plain", action="store_true")
    parser.add_argument("--open-ui", action="store_true", help="Open Hammerspoon after the service is ready")
    parser.add_argument("--audio-mode", choices=["mute", "music"])
    parser.add_argument("--mode", choices=["session", "preview", "split"], default="session",
                        help="File verification only; preview and split reproduce performance experiments")
    args = parser.parse_args()
    try:
        if args.command == "serve":
            serve(open_ui=args.open_ui)
            return 0
        if args.command in {"transcribe-file", "benchmark-file"}:
            if not args.file or not args.file.is_file():
                parser.error("The file command requires an existing WAV file")
            STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
            engine = Engine()
            try:
                if args.command == "benchmark-file":
                    result = benchmark(engine, args.file, mode=args.mode)
                else:
                    session = Session(engine, source=args.file, mode=args.mode)
                    session.start()
                    session.thread.join()
                    result = session.finish(copy=args.copy)
            finally:
                engine.close()
        else:
            if args.command == "set-audio-mode" and args.audio_mode is None:
                parser.error("set-audio-mode requires --audio-mode mute or music")
            if args.command in {"start", "toggle", "set-audio-mode", "audio-permissions", "check-permissions"}:
                ensure_daemon()
            result = request(args.command, audio_mode=args.audio_mode)
        if args.plain:
            if result["status"] == "recording":
                print("STARTED")
            elif result["status"] == "completed":
                print("RESULT:" + result["text"])
            else:
                print(result["status"].upper())
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        if args.plain:
            print("ERROR:" + str(error))
        else:
            print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
