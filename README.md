# BloomStream

BloomStream is a lightweight Raspberry Pi broadcast mixer for the Bloom ecosystem.

It is intentionally smaller and simpler than OBS: choose sources, assign them to panels, mix audio, and send one finished program feed to YouTube or another RTMP/RTMPS destination.

## Core idea

BloomStream treats cameras, screen regions, mini apps, overlays, and audio devices as independent sources feeding a small program mixer.

```text
USB CAM ---------+
CSI CAM ---------+
SCREEN ----------+--> VIDEO MIXER --+
SCREEN AREA -----+                   |
MINI APPS -------+                   +--> PROGRAM OUT --> H.264/AAC --> RTMPS
OVERLAYS --------+                   |
                                    |
MIC -------------+--> AUDIO MIXER --+
SYSTEM AUDIO ----+
APP AUDIO -------+
```

## v0.1 goals

- Raspberry Pi 5 / Debian 12 first
- 4 configurable visual panels
- Source selector for every panel
- Bottom-right panel blank by default for Bloom mini apps
- USB V4L2 camera input
- Raspberry Pi CSI/libcamera input
- Desktop capture
- Selectable screen-area capture
- Image/text/mini-app sources
- Per-input resolution and frame-rate settings
- Per-input crop, scale, fit/fill, rotation, and flip
- Simple panel arrangement presets
- Drag/reassign panel sources
- Mono and stereo audio inputs
- Per-source mute, gain, balance/pan, and level metering
- Program output settings separate from source settings
- Local recording
- RTMP/RTMPS streaming, including YouTube
- Diagnostic-first source status and camera ownership reporting

## Default four-panel workspace

```text
+----------------------+----------------------+
| PANEL 1              | PANEL 2              |
| Screen / Cam / Area  | Screen / Cam / Area  |
+----------------------+----------------------+
| PANEL 3              | PANEL 4              |
| Screen / Cam / Area  | Mini App / Blank     |
+----------------------+----------------------+
```

Panel 4 starts blank so Bloom mini apps can be shown without covering the main source.

## Layout presets

- 2 x 2
- 1 large + 3 small
- 2 vertical
- 2 horizontal
- Fullscreen + PiP
- Custom panel assignment

## Source settings

Each visual source keeps its own capture settings:

- width / height
- FPS
- pixel/input format where applicable
- crop / screen region
- fit / fill / stretch
- scale
- position
- rotation
- horizontal / vertical flip
- enabled / disabled

A 1080p camera can therefore feed a 720p program without changing the camera's native configuration.

## Audio

Each audio source can be configured independently:

- mono / stereo
- gain
- mute
- pan / balance
- duplicate mono to L+R
- collapse stereo to mono
- sample rate
- latency / buffering

The program mixer produces one final audio bus for the encoder.

## Appearance

BloomStream should keep appearance controls intentionally small:

- dark / light theme
- panel borders on/off
- corner radius
- panel labels on/off
- background
- panel spacing
- preferred mini-app panel

## Program output

Initial target:

```text
1280x720 @ 30 FPS
H.264 video
AAC audio
48 kHz audio
RTMP / RTMPS
```

Higher resolutions and frame rates can be added after the Pi 5 pipeline is proven stable.

## BloomCore rules

BloomStream follows the same serviceable design approach as the rest of the Bloom stack:

1. Inspect live devices before assuming names or numbers.
2. Detect capabilities, not just `/dev/videoN` paths.
3. Keep capture, mixing, encoding, and UI as separate layers.
4. Every source carries a diagnostic path.
5. Preserve known-good configurations.
6. Never make the stream key part of source code or Git history.

> The source is also the service manual.

## Planned architecture

```text
bloomstream/
  app.py              UI / controller
  sources/            camera, screen, area, image, mini-app adapters
  mixer/              panel compositor and audio mixer
  output/             FFmpeg/GStreamer encoder + RTMP(S)
  diagnostics/        device detection and health checks
  config/             layouts, sources, output profiles
```

The first implementation should use existing Linux media plumbing (FFmpeg/GStreamer/libcamera/V4L2/PipeWire where appropriate) rather than reimplementing codecs.

## Security

Stream keys and credentials belong in local user configuration only and must never be committed to the repository.
