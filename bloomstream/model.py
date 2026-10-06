from __future__ import annotations
from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
from typing import Any

@dataclass
class VideoSource:
    kind: str = 'blank'
    name: str = 'Blank'
    device: str = ''
    width: int = 1280
    height: int = 720
    fps: int = 30
    pixel_format: str = 'mjpeg'
    x: int = 0
    y: int = 0
    area_width: int = 1280
    area_height: int = 720
    fit: str = 'fit'
    rotation: int = 0
    hflip: bool = False
    vflip: bool = False
    enabled: bool = True

@dataclass
class AudioSource:
    name: str = 'None'
    device: str = ''
    mode: str = 'stereo'
    gain_db: float = 0.0
    pan: float = 0.0
    mute: bool = False
    sample_rate: int = 48000

@dataclass
class Panel:
    source: VideoSource = field(default_factory=VideoSource)

@dataclass
class OutputProfile:
    width: int = 1280
    height: int = 720
    fps: int = 30
    video_bitrate_kbps: int = 4500
    audio_bitrate_kbps: int = 160
    sample_rate: int = 48000
    preset: str = 'veryfast'
    endpoint: str = 'rtmps://a.rtmps.youtube.com/live2'
    stream_key: str = ''
    record_path: str = ''

@dataclass
class AppConfig:
    panels: list[Panel] = field(default_factory=lambda: [Panel() for _ in range(4)])
    audio: list[AudioSource] = field(default_factory=list)
    output: OutputProfile = field(default_factory=OutputProfile)
    layout: str = '2x2'
    theme: str = 'dark'
    panel_labels: bool = True
    borders: bool = True
    mini_app_panel: int = 4

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'AppConfig':
        panels=[]
        for item in data.get('panels', []):
            src=item.get('source', item)
            panels.append(Panel(VideoSource(**{k:v for k,v in src.items() if k in VideoSource.__dataclass_fields__})))
        while len(panels)<4: panels.append(Panel())
        audio=[AudioSource(**{k:v for k,v in item.items() if k in AudioSource.__dataclass_fields__}) for item in data.get('audio', [])]
        output=OutputProfile(**{k:v for k,v in data.get('output',{}).items() if k in OutputProfile.__dataclass_fields__})
        return cls(panels=panels[:4], audio=audio, output=output, layout=data.get('layout','2x2'), theme=data.get('theme','dark'), panel_labels=bool(data.get('panel_labels',True)), borders=bool(data.get('borders',True)), mini_app_panel=int(data.get('mini_app_panel',4)))

    def to_dict(self) -> dict[str, Any]:
        data=asdict(self)
        data['output']['stream_key']=''
        return data

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2)+'\n', encoding='utf-8')

    @classmethod
    def load(cls, path: Path) -> 'AppConfig':
        if not path.exists(): return cls()
        return cls.from_dict(json.loads(path.read_text(encoding='utf-8')))
