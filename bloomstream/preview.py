from __future__ import annotations

"""BloomStream preview safe mode.

The first live-preview implementation started one FFmpeg process per panel. On a
Raspberry Pi that can create too much concurrent capture/scale/decode work and
can also fight over V4L2 devices. Until BloomStream has a single shared preview
compositor, previews are intentionally disabled.

Recording and streaming use the normal main pipeline and are unaffected.
"""

from typing import Callable
from .model import VideoSource


class PreviewWorker:
    """No-process preview placeholder used in Pi safe mode."""

    def __init__(
        self,
        panel_index: int,
        source: VideoSource,
        on_frame: Callable[[int, bytes], None],
        on_error: Callable[[int, str], None],
    ):
        self.panel_index = panel_index
        self.source = source
        self.on_frame = on_frame
        self.on_error = on_error

    def start(self) -> None:
        label = self.source.name or self.source.kind or 'Blank'
        self.on_error(
            self.panel_index,
            f'{label}\nLive preview disabled in Pi safe mode.\nUse RECORD to test program output.',
        )

    def stop(self) -> None:
        return
