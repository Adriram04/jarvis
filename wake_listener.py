#!/usr/bin/env python3
"""
Lightweight wake listener for Jarvis.

Behavior:
1) Continuously monitors microphone input.
2) Detects a "double clap" pattern.
3) Launches Jarvis when the pattern is detected.

This listener is intentionally independent from the main app so it can run
even when Electron/FastAPI are not active.
"""

from __future__ import annotations

import argparse
import collections
import math
import os
import signal
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Deque, Optional, Tuple

try:
    import pyaudio
except ImportError as exc:  # pragma: no cover
    print(
        "PyAudio is required for wake listening. Install dependencies first:\n"
        "pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise


FORMAT = pyaudio.paInt16
CHANNELS = 1
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHUNK = 1024

if os.name == "nt":
    import ctypes


def rms_int16(buffer_bytes: bytes) -> float:
    """Compute RMS for 16-bit PCM audio data."""
    sample_count = len(buffer_bytes) // 2
    if sample_count <= 0:
        return 0.0

    samples = struct.unpack(f"<{sample_count}h", buffer_bytes)
    sum_squares = 0
    for sample in samples:
        sum_squares += sample * sample
    return math.sqrt(sum_squares / sample_count)


class DoubleClapDetector:
    """
    Adaptive double-clap detector.

    A clap is considered a short high-energy peak. Two claps within the
    configured gap window trigger the wake event.
    """

    def __init__(
        self,
        base_threshold_rms: float,
        min_gap_sec: float,
        max_gap_sec: float,
        peak_debounce_sec: float,
        noise_multiplier: float = 3.0,
    ) -> None:
        self.base_threshold_rms = base_threshold_rms
        self.min_gap_sec = min_gap_sec
        self.max_gap_sec = max_gap_sec
        self.peak_debounce_sec = peak_debounce_sec
        self.noise_multiplier = noise_multiplier

        self._noise_floor = 150.0
        self._last_peak_time = 0.0
        self._peaks: Deque[float] = collections.deque(maxlen=6)

    def _dynamic_threshold(self) -> float:
        return max(self.base_threshold_rms, self._noise_floor * self.noise_multiplier)

    def process(self, rms_value: float, now: float) -> Tuple[bool, Optional[float], float]:
        """
        Process one RMS sample.

        Returns:
            (triggered, gap, threshold)
        """
        threshold = self._dynamic_threshold()

        # Update noise floor slowly when signal is low.
        if rms_value < threshold * 0.5:
            self._noise_floor = 0.995 * self._noise_floor + 0.005 * rms_value

        # Peak gate.
        if rms_value < threshold:
            return False, None, threshold

        # Debounce so one physical clap does not register multiple peaks.
        if now - self._last_peak_time < self.peak_debounce_sec:
            return False, None, threshold

        self._last_peak_time = now
        self._peaks.append(now)

        if len(self._peaks) < 2:
            return False, None, threshold

        gap = self._peaks[-1] - self._peaks[-2]
        if self.min_gap_sec <= gap <= self.max_gap_sec:
            self._peaks.clear()
            return True, gap, threshold

        return False, gap, threshold


class JarvisLauncher:
    """Launches the main app command with cooldown and duplicate guard."""

    def __init__(
        self,
        project_root: Path,
        mode: str,
        launch_cmd: Optional[str],
        launch_cooldown_sec: float,
        startup_grace_sec: float,
        launch_visible: bool,
        backend_port: int,
        frontend_port: int,
        startup_min_hold_sec: float,
        keep_console_open: bool,
    ) -> None:
        self.project_root = project_root
        self.mode = mode
        self.launch_cmd = launch_cmd
        self.launch_cooldown_sec = launch_cooldown_sec
        self.startup_grace_sec = startup_grace_sec
        self.launch_visible = launch_visible
        self.backend_port = backend_port
        self.frontend_port = frontend_port
        self.startup_min_hold_sec = startup_min_hold_sec
        self.keep_console_open = keep_console_open

        self._last_launch = 0.0
        self._startup_lock_until = 0.0
        self._child_process: Optional[subprocess.Popen] = None

    def _build_command(self) -> str:
        if self.launch_cmd:
            return self.launch_cmd
        if self.mode == "electron":
            return "npm start"
        return "npm run dev"

    @staticmethod
    def _is_port_open(port: int) -> bool:
        # Try IPv4 and IPv6 localhost to avoid false negatives on Vite/Electron.
        targets = [
            (socket.AF_INET, "127.0.0.1"),
            (socket.AF_INET6, "::1"),
        ]
        for family, host in targets:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(0.25)
            try:
                if sock.connect_ex((host, port)) == 0:
                    return True
            except Exception:
                pass
            finally:
                sock.close()
        return False

    def _jarvis_is_running(self) -> bool:
        # Backend and/or frontend already active -> do not relaunch.
        return self._is_port_open(self.backend_port) or self._is_port_open(self.frontend_port)

    def launch(self) -> Tuple[bool, str]:
        now = time.monotonic()
        early_unlock = False

        # If lock is active but app is clearly not running anymore, release lock early.
        if now < self._startup_lock_until:
            since_launch = now - self._last_launch
            if since_launch >= self.startup_min_hold_sec and not self._jarvis_is_running():
                self._startup_lock_until = 0.0
                early_unlock = True

        if now < self._startup_lock_until:
            return (
                False,
                f"Startup lock active ({self._startup_lock_until - now:.1f}s remaining).",
            )

        if self._jarvis_is_running():
            return False, "Jarvis already appears to be running (ports active)."

        elapsed = now - self._last_launch
        if elapsed < self.launch_cooldown_sec:
            return (
                False,
                f"Launch cooldown active ({self.launch_cooldown_sec - elapsed:.1f}s remaining).",
            )

        if self._child_process and self._child_process.poll() is None:
            return False, "Jarvis launch command is already running from this listener."

        command = self._build_command()

        creationflags = 0
        popen_kwargs = {}
        if os.name == "nt" and not self.launch_visible:
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        try:
            if os.name == "nt" and self.launch_visible:
                # Keep an interactive console open to inspect Jarvis startup/errors.
                # By default uses /c so the console closes when app exits.
                cmd_switch = "/k" if self.keep_console_open else "/c"
                visible_cmd = (
                    f'start "Jarvis Console" cmd {cmd_switch} '
                    f'"cd /d "{self.project_root}" && {command}"'
                )
                self._child_process = subprocess.Popen(
                    visible_cmd,
                    cwd=str(self.project_root),
                    shell=True,
                )
            else:
                self._child_process = subprocess.Popen(
                    command,
                    cwd=str(self.project_root),
                    shell=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                    **popen_kwargs,
                )
            self._last_launch = now
            self._startup_lock_until = now + self.startup_grace_sec
            if early_unlock:
                return True, (
                    "Startup lock released early (app was closed). "
                    f"Launched Jarvis with command: {command}"
                )
            return True, f"Launched Jarvis with command: {command}"
        except Exception as exc:
            return False, f"Failed to launch Jarvis: {exc}"


class WakeLogger:
    """Simple logger that writes to stdout and optional file."""

    def __init__(self, log_file: Optional[Path]) -> None:
        self.log_file = log_file
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, message: str) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {message}"
        print(line)
        if self.log_file:
            try:
                with self.log_file.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass


def acquire_single_instance_mutex(name: str = "Local\\JarvisWakeListenerMutex") -> object:
    """
    Create a single-instance lock.
    On Windows uses named mutex.
    """
    if os.name != "nt":
        # No-op object for non-Windows.
        return object()

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = ctypes.c_uint32

    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise RuntimeError("Unable to create wake listener mutex.")

    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        raise RuntimeError("Wake listener is already running.")

    return handle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Double-clap wake listener for Jarvis.")
    parser.add_argument(
        "--mode",
        choices=["dev", "electron"],
        default="dev",
        help="'dev' runs npm run dev, 'electron' runs npm start.",
    )
    parser.add_argument(
        "--launch-cmd",
        default=None,
        help="Custom launch command. Overrides --mode.",
    )
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parent),
        help="Project root where npm commands will run.",
    )
    parser.add_argument(
        "--device-index",
        type=int,
        default=None,
        help="Optional microphone device index for PyAudio input.",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=DEFAULT_SAMPLE_RATE,
        help="Input sample rate.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK,
        help="PyAudio chunk size.",
    )
    parser.add_argument(
        "--base-threshold-rms",
        type=float,
        default=2300.0,
        help="Base RMS threshold for clap peak detection.",
    )
    parser.add_argument(
        "--clap-min-gap",
        type=float,
        default=0.12,
        help="Minimum seconds between first and second clap.",
    )
    parser.add_argument(
        "--clap-max-gap",
        type=float,
        default=0.80,
        help="Maximum seconds between first and second clap.",
    )
    parser.add_argument(
        "--peak-debounce",
        type=float,
        default=0.08,
        help="Debounce seconds so one clap is not counted repeatedly.",
    )
    parser.add_argument(
        "--launch-cooldown",
        type=float,
        default=25.0,
        help="Seconds to wait before allowing another launch.",
    )
    parser.add_argument(
        "--startup-grace",
        type=float,
        default=45.0,
        help="Ignore additional clap launches while Jarvis is starting.",
    )
    parser.add_argument(
        "--startup-min-hold",
        type=float,
        default=8.0,
        help="Minimum seconds to keep startup lock before early release checks.",
    )
    parser.add_argument(
        "--launch-visible",
        action="store_true",
        help="On Windows, open a visible cmd window for Jarvis logs.",
    )
    parser.add_argument(
        "--backend-port",
        type=int,
        default=8000,
        help="Backend status port used to detect existing Jarvis session.",
    )
    parser.add_argument(
        "--frontend-port",
        type=int,
        default=5173,
        help="Frontend Vite port used to detect existing Jarvis session.",
    )
    parser.add_argument(
        "--keep-console-open",
        action="store_true",
        help="Keep visible cmd window open after command exits (/k).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print extra debug output.",
    )
    parser.add_argument(
        "--log-file",
        default=str(Path(__file__).resolve().parent / "wake_listener.log"),
        help="Path to listener log file. Use '' to disable file logging.",
    )
    return parser.parse_args()


def run() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    log_file = Path(args.log_file).resolve() if args.log_file else None
    logger = WakeLogger(log_file=log_file)

    if not project_root.exists():
        logger.log(f"[WakeListener] Project root does not exist: {project_root}")
        return 2

    try:
        _mutex_handle = acquire_single_instance_mutex()
    except Exception as exc:
        logger.log(f"[WakeListener] {exc}")
        return 0

    detector = DoubleClapDetector(
        base_threshold_rms=args.base_threshold_rms,
        min_gap_sec=args.clap_min_gap,
        max_gap_sec=args.clap_max_gap,
        peak_debounce_sec=args.peak_debounce,
    )
    launcher = JarvisLauncher(
        project_root=project_root,
        mode=args.mode,
        launch_cmd=args.launch_cmd,
        launch_cooldown_sec=args.launch_cooldown,
        startup_grace_sec=args.startup_grace,
        launch_visible=args.launch_visible,
        backend_port=args.backend_port,
        frontend_port=args.frontend_port,
        startup_min_hold_sec=args.startup_min_hold,
        keep_console_open=args.keep_console_open,
    )

    pa = pyaudio.PyAudio()

    logger.log("[WakeListener] Running.")
    logger.log(f"[WakeListener] Project root: {project_root}")
    logger.log(f"[WakeListener] Mode: {args.mode}")
    if args.launch_cmd:
        logger.log(f"[WakeListener] Custom launch command: {args.launch_cmd}")
    logger.log(
        "[WakeListener] Double-clap window:"
        f" {args.clap_min_gap:.2f}s - {args.clap_max_gap:.2f}s"
    )
    logger.log(f"[WakeListener] Base RMS threshold: {args.base_threshold_rms}")
    logger.log(f"[WakeListener] Launch visible console: {args.launch_visible}")
    logger.log(
        "[WakeListener] Startup lock window: "
        f"{args.startup_grace:.1f}s | min hold: {args.startup_min_hold:.1f}s | "
        f"cooldown: {args.launch_cooldown:.1f}s"
    )
    logger.log(f"[WakeListener] Keep console open after exit: {args.keep_console_open}")
    logger.log("[WakeListener] Press Ctrl+C to stop.")

    # Preflight checks (without launching Jarvis).
    if not args.launch_cmd:
        npm_probe_cmd = "where npm" if os.name == "nt" else "which npm"
        try:
            npm_probe = subprocess.run(
                npm_probe_cmd,
                cwd=str(project_root),
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if npm_probe.returncode == 0:
                logger.log("[WakeListener] npm found in PATH.")
            else:
                logger.log(
                    "[WakeListener] npm not found in PATH. Listener can detect claps, "
                    "but launch will fail."
                )
        except Exception as exc:
            logger.log(f"[WakeListener] npm preflight check failed: {exc}")

    should_stop = False

    def stop_handler(signum, frame):  # noqa: ANN001
        nonlocal should_stop
        should_stop = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    stream = None
    try:
        stream = pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=args.sample_rate,
            input=True,
            frames_per_buffer=args.chunk_size,
            input_device_index=args.device_index,
        )
    except Exception as exc:
        logger.log(f"[WakeListener] Failed to open microphone stream: {exc}")
        pa.terminate()
        return 3

    try:
        while not should_stop:
            try:
                audio_chunk = stream.read(args.chunk_size, exception_on_overflow=False)
            except Exception as exc:
                logger.log(f"[WakeListener] Audio read error: {exc}")
                time.sleep(0.1)
                continue

            now = time.monotonic()
            rms_value = rms_int16(audio_chunk)
            triggered, gap, threshold = detector.process(rms_value, now)

            if args.verbose and rms_value > threshold * 0.7:
                logger.log(
                    f"[WakeListener] Peak candidate - RMS={rms_value:.0f}, "
                    f"threshold={threshold:.0f}, gap={gap}"
                )

            if triggered:
                logger.log(
                    f"[WakeListener] Double clap detected (gap={gap:.3f}s). "
                    "Attempting launch..."
                )
                launched, message = launcher.launch()
                if launched:
                    logger.log(f"[WakeListener] {message}")
                else:
                    logger.log(f"[WakeListener] Launch skipped: {message}")

    finally:
        if stream is not None:
            stream.stop_stream()
            stream.close()
        pa.terminate()
        logger.log("[WakeListener] Stopped.")

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
