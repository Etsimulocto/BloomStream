from __future__ import annotations
from pathlib import Path
import shlex
from typing import Iterable
from .devices import detect_display
from .model import AppConfig, AudioSource, VideoSource

class PipelineError(RuntimeError):
    pass

def _video_input_args(src: VideoSource, output_fps: int) -> list[str]:
    fps=max(1,int(src.fps or output_fps))
    if not src.enabled or src.kind=='blank': return ['-f','lavfi','-r',str(fps),'-i','color=c=black:s=640x360']
    if src.kind=='test': return ['-f','lavfi','-r',str(fps),'-i',f'testsrc2=size=640x360:rate={fps}']
    if src.kind=='screen': return ['-f','x11grab','-framerate',str(fps),'-video_size',f'{src.width}x{src.height}','-i',f'{detect_display()}+{src.x},{src.y}']
    if src.kind=='area': return ['-f','x11grab','-framerate',str(fps),'-video_size',f'{src.area_width}x{src.area_height}','-i',f'{detect_display()}+{src.x},{src.y}']
    if src.kind=='v4l2':
        args=['-f','v4l2','-framerate',str(fps)]
        if src.width and src.height: args += ['-video_size',f'{src.width}x{src.height}']
        if src.pixel_format: args += ['-input_format',src.pixel_format]
        return args+['-i',src.device]
    if src.kind=='csi': raise PipelineError('CSI camera detected but its capture adapter is not enabled yet. Use V4L2, screen, area, blank, or test for this first live build.')
    raise PipelineError(f'Unsupported source kind: {src.kind}')

def _audio_input_args(src: AudioSource) -> list[str]:
    if not src.device or src.mute: return []
    return ['-f','pulse','-sample_rate',str(src.sample_rate),'-i',src.device]

def _layout_boxes(layout: str, width: int, height: int) -> list[tuple[int,int,int,int]]:
    if layout=='2 horizontal': return [(0,0,width,height//2),(0,height//2,width,height-height//2),(0,0,1,1),(0,0,1,1)]
    if layout=='2 vertical': return [(0,0,width//2,height),(width//2,0,width-width//2,height),(0,0,1,1),(0,0,1,1)]
    if layout=='1 large + 3 small':
        big=int(width*.72); sw=width-big; h3=height//3
        return [(0,0,big,height),(big,0,sw,h3),(big,h3,sw,h3),(big,h3*2,sw,height-h3*2)]
    if layout=='fullscreen + PiP':
        pw=max(160,width//4); ph=max(90,height//4); m=18
        return [(0,0,width,height),(width-pw-m,height-ph-m,pw,ph),(0,0,1,1),(0,0,1,1)]
    w2,h2=width//2,height//2
    return [(0,0,w2,h2),(w2,0,width-w2,h2),(0,h2,w2,height-h2),(w2,h2,width-w2,height-h2)]

def _transform_chain(src: VideoSource, w:int, h:int)->str:
    fs=[]
    if src.hflip: fs.append('hflip')
    if src.vflip: fs.append('vflip')
    rot=src.rotation%360
    if rot==90: fs.append('transpose=clock')
    elif rot==180: fs += ['hflip','vflip']
    elif rot==270: fs.append('transpose=cclock')
    if src.fit=='stretch': fs.append(f'scale={w}:{h}')
    elif src.fit=='fill': fs += [f'scale={w}:{h}:force_original_aspect_ratio=increase',f'crop={w}:{h}']
    else: fs += [f'scale={w}:{h}:force_original_aspect_ratio=decrease',f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black']
    fs.append('setsar=1')
    return ','.join(fs)

def build_ffmpeg_command(config:AppConfig, mode:str='stream')->list[str]:
    if mode not in {'stream','record'}: raise PipelineError('mode must be stream or record')
    out=config.output
    if mode=='stream' and (not out.endpoint or not out.stream_key): raise PipelineError('Streaming endpoint and stream key are required.')

    cmd=['ffmpeg','-hide_banner','-loglevel','warning','-y']
    boxes=_layout_boxes(config.layout,out.width,out.height)

    # FFmpeg requires every input to be declared before output options such as
    # -filter_complex and -map. Keep all video/audio inputs together here.
    for panel in config.panels[:4]:
        cmd += _video_input_args(panel.source,out.fps)

    audio_inputs=[]
    for src in config.audio:
        args=_audio_input_args(src)
        if args:
            cmd += args
            audio_inputs.append(src)

    silent_audio_index=None
    if not audio_inputs:
        silent_audio_index=4
        cmd += ['-f','lavfi','-i',f'anullsrc=channel_layout=stereo:sample_rate={out.sample_rate}']

    filters=[]
    for i,(x,y,w,h) in enumerate(boxes):
        filters.append(f'[{i}:v]{_transform_chain(config.panels[i].source,max(1,w),max(1,h))}[v{i}]')
    filters.append(f'color=c=black:s={out.width}x{out.height}:r={out.fps}[base]')

    last='base'
    for i,(x,y,w,h) in enumerate(boxes):
        nxt=f'mix{i}'
        enable='0' if w<=1 or h<=1 else '1'
        filters.append(f"[{last}][v{i}]overlay={x}:{y}:enable='{enable}'[{nxt}]")
        last=nxt

    if audio_inputs:
        labels=[]
        for j,src in enumerate(audio_inputs):
            idx=4+j
            label=f'a{j}'
            af=[f'volume={float(src.gain_db)}dB']
            if src.mode=='mono':
                af.append('pan=stereo|c0=c0|c1=c0')
            elif abs(src.pan)>0.001:
                p=max(-1.0,min(1.0,float(src.pan)))
                left=1.0 if p<=0 else 1.0-p
                right=1.0 if p>=0 else 1.0+p
                af.append(f'pan=stereo|c0={left:.3f}*c0|c1={right:.3f}*c1')
            filters.append(f"[{idx}:a]{','.join(af)}[{label}]")
            labels.append(f'[{label}]')
        filters.append(''.join(labels)+f'amix=inputs={len(labels)}:normalize=0[aout]')

    cmd += ['-filter_complex',';'.join(filters),'-map',f'[{last}]']
    if audio_inputs:
        cmd += ['-map','[aout]']
    else:
        cmd += ['-map',f'{silent_audio_index}:a']

    cmd += [
        '-r',str(out.fps),
        '-c:v','libx264','-preset',out.preset,'-tune','zerolatency',
        '-pix_fmt','yuv420p',
        '-b:v',f'{out.video_bitrate_kbps}k',
        '-maxrate',f'{out.video_bitrate_kbps}k',
        '-bufsize',f'{out.video_bitrate_kbps*2}k',
        '-g',str(out.fps*2),
        '-c:a','aac','-b:a',f'{out.audio_bitrate_kbps}k',
        '-ar',str(out.sample_rate),'-ac','2'
    ]

    if mode=='stream':
        cmd += ['-f','flv',out.endpoint.rstrip('/')+'/'+out.stream_key.strip()]
    else:
        path=out.record_path or str(Path.home()/'Videos'/'BloomStream-%Y%m%d-%H%M%S.mkv')
        cmd += ['-strftime','1',path]
    return cmd

def shell_preview(command:Iterable[str], hide_secret:str='')->str:
    parts=[]
    for part in command:
        shown=part.replace(hide_secret,'••••••••') if hide_secret and hide_secret in part else part
        parts.append(shlex.quote(shown))
    return ' '.join(parts)
