from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import glob, os, re, shutil, subprocess

@dataclass(frozen=True)
class DeviceChoice:
    label: str
    value: str
    kind: str

def _run(args: list[str], timeout: float = 3.0) -> str:
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=timeout,check=False)
        return (p.stdout or '')+(p.stderr or '')
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ''

def _is_capture_node(path: str) -> bool:
    text=_run(['v4l2-ctl','-d',path,'--all'])
    if not text: return False
    if 'Metadata Capture' in text and 'Video Capture' not in text: return False
    return 'Video Capture' in text

def detect_v4l2() -> list[DeviceChoice]:
    out=[]
    def key(p:str)->int:
        m=re.search(r'\d+$',p)
        return int(m.group()) if m else 9999
    for path in sorted(glob.glob('/dev/video*'),key=key):
        if not _is_capture_node(path): continue
        text=_run(['v4l2-ctl','-d',path,'--all'])
        m=re.search(r'Card type\s*:\s*(.+)',text)
        card=m.group(1).strip() if m else Path(path).name
        out.append(DeviceChoice(f'{card} ({path})',path,'v4l2'))
    return out

def detect_csi() -> list[DeviceChoice]:
    if not shutil.which('rpicam-hello'): return []
    text=_run(['rpicam-hello','--list-cameras'],5)
    if 'Available cameras' not in text: return []
    out=[]
    for line in text.splitlines():
        m=re.match(r'\s*(\d+)\s*:\s*([^\[]+)',line)
        if m:
            idx,name=m.groups()
            out.append(DeviceChoice(f'CSI {idx}: {name.strip()}',idx,'csi'))
    return out

def detect_audio() -> list[DeviceChoice]:
    out=[DeviceChoice('No audio','','audio')]
    if shutil.which('pactl'):
        for line in _run(['pactl','list','short','sources']).splitlines():
            cols=line.split('\t')
            if len(cols)>=2: out.append(DeviceChoice(cols[1],cols[1],'audio'))
    return out

def detect_display() -> str:
    return os.environ.get('DISPLAY',':0.0')

def diagnostics() -> str:
    chunks=['BloomStream diagnostics',f'DISPLAY={detect_display()}',f"ffmpeg={'yes' if shutil.which('ffmpeg') else 'NO'}",f"v4l2-ctl={'yes' if shutil.which('v4l2-ctl') else 'NO'}",f"rpicam-hello={'yes' if shutil.which('rpicam-hello') else 'no'}",f"pactl={'yes' if shutil.which('pactl') else 'no'}",'','V4L2 capture nodes:']
    cams=detect_v4l2(); chunks.extend([f'  {d.label}' for d in cams] or ['  none'])
    chunks += ['', 'CSI cameras:']; csi=detect_csi(); chunks.extend([f'  {d.label}' for d in csi] or ['  none'])
    chunks += ['', 'Audio sources:']; aud=detect_audio()[1:]; chunks.extend([f'  {d.label}' for d in aud] or ['  none'])
    return '\n'.join(chunks)
