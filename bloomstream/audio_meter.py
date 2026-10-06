from __future__ import annotations

from array import array
import math
import subprocess
import sys
import threading
from typing import Callable


METER_RATE = 8000
METER_CHANNELS = 2
METER_CHUNK_FRAMES = 800  # 100 ms at 8 kHz
METER_FLOOR_DB = -60.0


def _dbfs(rms: float) -> float:
    if rms <= 0.0:
        return METER_FLOOR_DB
    db = 20.0 * math.log10(rms / 32768.0)
    return max(METER_FLOOR_DB, min(0.0, db))


def _percent(db: float) -> float:
    return max(0.0, min(100.0, (db - METER_FLOOR_DB) / -METER_FLOOR_DB * 100.0))


class AudioMeterWorker:
    """Very small PulseAudio/PipeWire level reader for UI metering only.

    It deliberately uses a low sample rate and never touches BloomStream's
    FFmpeg record/stream pipeline. PulseAudio sources can have multiple clients,
    so this can watch the same source that FFmpeg later records/streams.
    """

    def __init__(
        self,
        device: str,
        on_level: Callable[[float, float, float, float], None],
        on_error: Callable[[str], None] | None = None,
    ):
        self.device = device
        self.on_level = on_level
        self.on_error = on_error or (lambda _text: None)
        self.process: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if not self.device or (self.process and self.process.poll() is None):
            return
        self._stop.clear()
        try:
            self.process = subprocess.Popen(
                [
                    'parec',
                    '--device', self.device,
                    '--format=s16le',
                    f'--rate={METER_RATE}',
                    f'--channels={METER_CHANNELS}',
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                bufsize=0,
            )
        except Exception as exc:
            self.on_error(str(exc))
            self.process = None
            return

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        p = self.process
        if not p or not p.stdout:
            return

        frame_bytes = METER_CHANNELS * 2
        chunk_bytes = METER_CHUNK_FRAMES * frame_bytes
        try:
            while not self._stop.is_set():
                data = p.stdout.read(chunk_bytes)
                if not data or len(data) < frame_bytes:
                    break

                samples = array('h')
                samples.frombytes(data[: len(data) - (len(data) % frame_bytes)])
                if sys.byteorder != 'little':
                    samples.byteswap()

                left_sq = 0.0
                right_sq = 0.0
                frames = len(samples) // 2
                if frames <= 0:
                    continue

                for i in range(0, frames * 2, 2):
                    left = samples[i]
                    right = samples[i + 1]
                    left_sq += left * left
                    right_sq += right * right

                left_rms = math.sqrt(left_sq / frames)
                right_rms = math.sqrt(right_sq / frames)
                left_db = _dbfs(left_rms)
                right_db = _dbfs(right_rms)
                self.on_level(_percent(left_db), _percent(right_db), left_db, right_db)
        finally:
            if not self._stop.is_set() and p.poll() not in (0, None):
                self.on_error('audio meter source stopped')

    def stop(self) -> None:
        self._stop.set()
        p = self.process
        self.process = None
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=0.25)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    p.kill()
                except OSError:
                    pass
        self.thread = None
