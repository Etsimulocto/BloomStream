from __future__ import annotations

import base64
import struct
import subprocess
import threading
from typing import Callable

from .model import AppConfig
from .pipeline import _layout_boxes, _transform_chain, _video_input_args

PREVIEW_W = 640
PREVIEW_H = 360
PREVIEW_FPS = 2
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def build_program_preview_command(config: AppConfig) -> list[str]:
    """Build one low-rate FFmpeg process for the composed PROGRAM preview."""
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin']

    for panel in config.panels[:4]:
        cmd += _video_input_args(panel.source, config.output.fps)

    boxes = _layout_boxes(config.layout, PREVIEW_W, PREVIEW_H)
    filters: list[str] = []
    visible: list[tuple[int, int, int]] = []

    for i, (x, y, w, h) in enumerate(boxes):
        if w <= 1 or h <= 1:
            continue
        filters.append(f'[{i}:v]{_transform_chain(config.panels[i].source, w, h)}[v{i}]')
        visible.append((i, x, y))

    filters.append(f'color=c=black:s={PREVIEW_W}x{PREVIEW_H}:r={PREVIEW_FPS}[base]')
    last = 'base'
    for mix_index, (i, x, y) in enumerate(visible):
        nxt = f'pmix{mix_index}'
        filters.append(f'[{last}][v{i}]overlay={x}:{y}:shortest=1[{nxt}]')
        last = nxt

    filters.append(f'[{last}]fps={PREVIEW_FPS},format=rgb24[preview]')
    cmd += [
        '-filter_complex', ';'.join(filters),
        '-map', '[preview]',
        '-an',
        '-f', 'image2pipe',
        '-vcodec', 'png',
        '-compression_level', '3',
        '-'
    ]
    return cmd


def _read_exact(stream, size: int) -> bytes | None:
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)


def _read_png(stream) -> bytes | None:
    signature = _read_exact(stream, len(PNG_SIGNATURE))
    if signature != PNG_SIGNATURE:
        return None

    out = bytearray(signature)
    while True:
        header = _read_exact(stream, 8)
        if header is None:
            return None
        length = struct.unpack('>I', header[:4])[0]
        chunk_type = header[4:8]
        payload_and_crc = _read_exact(stream, length + 4)
        if payload_and_crc is None:
            return None
        out.extend(header)
        out.extend(payload_and_crc)
        if chunk_type == b'IEND':
            return bytes(out)


class ProgramPreviewWorker:
    """Exactly one preview FFmpeg process for the complete program feed."""

    def __init__(
        self,
        config: AppConfig,
        on_frame: Callable[[str], None],
        on_error: Callable[[str], None],
        on_exit: Callable[[], None],
    ):
        self.config = config
        self.on_frame = on_frame
        self.on_error = on_error
        self.on_exit = on_exit
        self.process: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return
        self._stop.clear()
        try:
            cmd = build_program_preview_command(self.config)
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
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
        try:
            while not self._stop.is_set():
                frame = _read_png(p.stdout)
                if frame is None:
                    break
                self.on_frame(base64.b64encode(frame).decode('ascii'))
        finally:
            if not self._stop.is_set() and p.poll() not in (0, None):
                msg = ''
                if p.stderr:
                    try:
                        msg = p.stderr.read().decode('utf-8', 'replace').strip()
                    except Exception:
                        pass
                self.on_error(msg or 'program preview stopped')
            self.on_exit()

    def stop(self) -> None:
        self._stop.set()
        p = self.process
        self.process = None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=0.75)
            except subprocess.TimeoutExpired:
                p.kill()
        self.thread = None
