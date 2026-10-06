from __future__ import annotations

import subprocess
import threading
from typing import Callable

from .devices import detect_display
from .model import AppConfig, VideoSource
from .pipeline import _layout_boxes, _transform_chain

PREVIEW_W = 640
PREVIEW_H = 360
PREVIEW_FPS = 2


def _preview_input_args(src: VideoSource) -> list[str]:
    """Capture preview sources at preview rate instead of their program rate.

    Keep known-good camera resolution/pixel format intact so USB cameras are not
    forced into an unsupported mode, but only request the two frames per second
    that the preview can actually display.
    """
    fps = PREVIEW_FPS
    if not src.enabled or src.kind == 'blank':
        return ['-f', 'lavfi', '-r', str(fps), '-i', 'color=c=black:s=640x360']
    if src.kind == 'test':
        return ['-f', 'lavfi', '-r', str(fps), '-i', f'testsrc2=size=640x360:rate={fps}']
    if src.kind == 'screen':
        return [
            '-f', 'x11grab', '-framerate', str(fps),
            '-video_size', f'{src.width}x{src.height}',
            '-i', f'{detect_display()}+{src.x},{src.y}',
        ]
    if src.kind == 'area':
        return [
            '-f', 'x11grab', '-framerate', str(fps),
            '-video_size', f'{src.area_width}x{src.area_height}',
            '-i', f'{detect_display()}+{src.x},{src.y}',
        ]
    if src.kind == 'v4l2':
        args = ['-thread_queue_size', '2', '-f', 'v4l2', '-framerate', str(fps)]
        if src.width and src.height:
            args += ['-video_size', f'{src.width}x{src.height}']
        if src.pixel_format:
            args += ['-input_format', src.pixel_format]
        return args + ['-i', src.device]
    raise ValueError(f'Preview unsupported for source kind: {src.kind}')


def build_program_preview_command(config: AppConfig) -> list[str]:
    """Build one deliberately low-load FFmpeg process for PROGRAM preview.

    Preview capture is throttled at the input boundary. RECORD/LIVE continues to
    use the normal pipeline and is intentionally unaffected by this module.
    """
    cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
        '-filter_complex_threads', '1',
    ]

    for panel in config.panels[:4]:
        cmd += _preview_input_args(panel.source)

    active = [
        i for i, panel in enumerate(config.panels[:4])
        if panel.source.enabled and panel.source.kind != 'blank'
    ]

    if len(active) == 1:
        only = active[0]
        boxes = [(0, 0, 1, 1) for _ in range(4)]
        boxes[only] = (0, 0, PREVIEW_W, PREVIEW_H)
    else:
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
        '-vcodec', 'ppm',
        '-'
    ]
    return cmd


def _read_token(stream) -> bytes:
    token = bytearray()
    while True:
        b = stream.read(1)
        if not b:
            return bytes(token)
        if b == b'#':
            while b not in (b'\n', b''):
                b = stream.read(1)
            continue
        if b.isspace():
            if token:
                return bytes(token)
            continue
        token.extend(b)


def _read_exact(stream, size: int) -> bytes | None:
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)


def _read_ppm(stream) -> bytes | None:
    if _read_token(stream) != b'P6':
        return None
    try:
        width = int(_read_token(stream))
        height = int(_read_token(stream))
        maxval = int(_read_token(stream))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0 or maxval != 255:
        return None
    payload = _read_exact(stream, width * height * 3)
    if payload is None:
        return None
    header = f'P6\n{width} {height}\n255\n'.encode('ascii')
    return header + payload


class ProgramPreviewWorker:
    """Exactly one preview FFmpeg process for the complete program feed."""

    def __init__(
        self,
        config: AppConfig,
        on_frame: Callable[[bytes], None],
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
                frame = _read_ppm(p.stdout)
                if frame is None:
                    break
                self.on_frame(frame)
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
                p.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                p.kill()
        self.thread = None
