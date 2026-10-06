# BloomStream

BloomStream is a lightweight Raspberry Pi broadcast mixer for the Bloom ecosystem.

It is intentionally smaller and simpler than OBS: choose sources, assign them to panels, mix audio, and send one finished program feed to YouTube or another RTMP/RTMPS destination.

## v0.1 is runnable

The first working slice is now in the repo.

Implemented:

- Raspberry Pi 5 / Debian 12 first
- 4 configurable visual panels
- Per-panel source selector
- Blank and test-pattern sources
- USB V4L2 camera discovery
- Metadata-only V4L2 nodes are rejected
- Full desktop capture through X11
- Screen-area capture
- CSI camera discovery through `rpicam-hello --list-cameras`
- Per-source width, height, FPS, input format, area, fit/fill/stretch, rotate and flip
- Layouts: 2x2, 1 large + 3 small, 2 vertical, 2 horizontal, fullscreen + PiP
- 3 audio buses discovered through Pulse/PipeWire compatibility (`pactl`)
- Mono/stereo choice, gain, pan and mute
- Separate program output settings
- 720p30 defaults
- H.264 + AAC FFmpeg output
- RTMP/RTMPS streaming
- Local recording
- Built-in diagnostics tab
- Stream key remains memory-only and is never saved to normal config
- Desktop launcher installer

Known first-build boundary:

- CSI cameras are detected and shown in the source list, but the live CSI capture adapter is intentionally gated until the actual ribbon camera is tested on the target Pi. This avoids hard-coding the wrong libcamera/rpicam path.
- Panel canvases are control placeholders in v0.1; the actual composite is produced by FFmpeg. Embedded live preview is a next layer.

## Install on the Pi

```bash
git clone https://github.com/Etsimulocto/BloomStream.git
cd BloomStream
chmod +x install.sh
./install.sh
python3 main.py
```

If the repo already exists locally:

```bash
cd ~/BloomStream
git pull
chmod +x install.sh
./install.sh
python3 main.py
```

## First safe test

Before using YouTube, prove the compositor locally:

1. Set Panel 1 to **Test Pattern**.
2. Leave the other panels **Blank**.
3. Choose a recording path under Output.
4. Click **RECORD**.
5. Let it run a few seconds, then click **STOP**.

After that, try **Full Screen** or the Arducam V4L2 capture device.

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

## Source settings

Each visual source keeps its own capture settings:

- width / height
- FPS
- pixel/input format where applicable
- crop / screen region
- fit / fill / stretch
- rotation
- horizontal / vertical flip
- enabled / disabled

## Audio

Each audio source can be configured independently:

- mono / stereo
- gain
- mute
- pan / balance
- sample rate

The program mixer produces one final stereo audio bus for the encoder.

## Program output

Default target:

```text
1280x720 @ 30 FPS
H.264 video
AAC audio
48 kHz audio
4500 kbps video
160 kbps audio
RTMP / RTMPS
```

## Architecture

```text
bloomstream/
  app.py          Tkinter UI / controller
  devices.py      V4L2, CSI and audio discovery
  model.py        persistent source/layout/output model
  pipeline.py     FFmpeg compositor, audio mixer and output builder
main.py           launcher
install.sh        Raspberry Pi dependencies + desktop launcher
```

## BloomCore rules

1. Inspect live devices before assuming names or numbers.
2. Detect capabilities, not just `/dev/videoN` paths.
3. Keep capture, mixing, encoding, and UI as separate layers.
4. Every source carries a diagnostic path.
5. Preserve known-good configurations.
6. Never make the stream key part of source code or Git history.

> The source is also the service manual.

## Security

Stream keys and credentials belong in memory/local user state only and must never be committed to the repository.
