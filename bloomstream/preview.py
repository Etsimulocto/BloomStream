from __future__ import annotations

import base64
import subprocess
import threading
from typing import Callable

from .devices import detect_display
from .model import VideoSource

PREVIEW_W = 480
PREVIEW_H = 270
PREVIEW_FPS = 5


def _input_args(src: VideoSource) -> list[str]:
    fps = max(1, min(PREVIEW_FPS, int(src.fps or PREVIEW_FPS)))
    if not src.enabled or src.kind == 'blank':
        return ['-f', 'lavfi', '-i', f'color=c=black:s={PREVIEW_W}x{PREVIEW_H}:r={fps}']
    if src.kind == 'test':
        return ['-f', 'lavfi', '-i', f'testsrc2=size={PREVIEW_W}x{PREVIEW_H}:rate={fps}']
    if src.kind == 'screen':
        return ['-f', 'x11grab', '-framerate', str(fps), '-video_size', f'{src.width}x{src.height}', '-i', f'{detect_display()}+{src.x},{src.y}']
    if src.kind == 'area':
        return ['-f', 'x11grab', '-framerate', str(fps), '-video_size', f'{src.area_width}x{src.area_height}', '-i', f'{detect_display()}+{src.x},{src.y}']
    if src.kind == 'v4l2':
        args = ['-f', 'v4l2', '-framerate', str(fps)]
        if src.width and src.height:
            args += ['-video_size', f'{src.width}x{src.height}']
        if src.pixel_format:
            args += ['-input_format', src.pixel_format]
        return args + ['-i', src.device]
    raise ValueError(f'Preview unsupported for {src.kind}')


def _vf(src: VideoSource) -> str:
    fs: list[str] = []
    if src.hflip:
        fs.append('hflip')
    if src.vflip:
        fs.append('vflip')
    rot = src.rotation % 360
    if rot == 90:
        fs.append('transpose=clock')
    elif rot == 180:
        fs += ['hflip', 'vflip']
    elif rot == 270:
        fs.append('transpose=cclock')
    if src.fit == 'fill':
        fs += [f'scale={PREVIEW_W}:{PREVIEW_H}:force_original_aspect_ratio=increase', f'crop={PREVIEW_W}:{PREVIEW_H}']
    elif src.fit == 'stretch':
        fs.append(f'scale={PREVIEW_W}:{PREVIEW_H}')
    else:
        fs += [f'scale={PREVIEW_W}:{PREVIEW_H}:force_original_aspect_ratio=decrease', f'pad={PREVIEW_W}:{PREVIEW_H}:(ow-iw)/2:(oh-ih)/2:black']
    fs += [f'fps={PREVIEW_FPS}', 'format=rgb24']
    return ','.join(fs)


def _read_token(stream) -> bytes:
    token = bytearray()
    while True:
        b = stream.read(1)
        if not b:
            return bytes(token)
        if b == b'#':
            while b not in (b'\n', b''):
                b = stream.read(1)
            if token:
                return bytes(token)
            continue
        if b.isspace():
            if token:
                return bytes(token)
            continue
        token.extend(b)


def _read_ppm(stream) -> bytes | None:
    """Read one P6 frame and return base64 data safe for Tk PhotoImage.

    Passing raw P6 bytes through tkinter's Tcl argument bridge is unreliable
    because the pixel payload contains NUL bytes.  Tk accepts base64 image data,
    so encode each complete frame before handing it to the UI thread.
    """
    magic = _read_token(stream)
    if magic != b'P6':
        return None
    try:
        width = int(_read_token(stream))
        height = int(_read_token(stream))
        maxval = int(_read_token(stream))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0 or maxval != 255:
        return None
    payload = stream.read(width * height * 3)
    if len(payload) != width * height * 3:
        return None
    header = f'P6\n{width} {height}\n255\n'.encode('ascii')
    return base64.b64encode(header + payload)


class PreviewWorker:
    def __init__(self, panel_index: int, source: VideoSource, on_frame: Callable[[int, bytes], None], on_error: Callable[[int, str], None]):
        self.panel_index = panel_index
        self.source = source
        self.on_frame = on_frame
        self.on_error = on_error
        self.process: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self.stop()
        self._stop.clear()
        try:
            cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error'] + _input_args(self.source)
            cmd += ['-vf', _vf(self.source), '-an', '-f', 'image2pipe', '-vcodec', 'ppm', '-']
        except Exception as exc:
            self.on_error(self.panel_index, str(exc))
            return
        try:
            self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except Exception as exc:
            self.on_error(self.panel_index, str(exc))
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        p = self.process
        if not p or not p.stdout:
            return
        while not self._stop.is_set():
            frame = _read_ppm(p.stdout)
            if frame is None:
                break
            self.on_frame(self.panel_index, frame)
        if not self._stop.is_set() and p.poll() not in (0, None):
            msg = ''
            if p.stderr:
                try:
                    msg = p.stderr.read().decode('utf-8', 'replace').strip()
                except Exception:
                    pass
            self.on_error(self.panel_index, msg or 'preview stopped')

    def stop(self) -> None:
        """Stop a preview quickly; never hold the Tk close path for seconds."""
        self._stop.set()
        p = self.process
        self.process = None
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=0.15)
            except subprocess.TimeoutExpired:
                try:
                    p.kill()
                    p.wait(timeout=0.15)
                except (subprocess.TimeoutExpired, OSError):
                    pass
            except OSError:
                pass
        self.thread = None
