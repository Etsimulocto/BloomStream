#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/.local/share/applications"

if command -v xdg-user-dir >/dev/null 2>&1; then
    DESKTOP_DIR="$(xdg-user-dir DESKTOP)"
else
    DESKTOP_DIR="$HOME/Desktop"
fi

# Guard against an unset/broken XDG desktop path.
if [[ -z "$DESKTOP_DIR" || "$DESKTOP_DIR" == "$HOME" ]]; then
    DESKTOP_DIR="$HOME/Desktop"
fi

mkdir -p "$APP_DIR" "$DESKTOP_DIR"

LAUNCHER="$APP_DIR/bloomstream.desktop"
cat > "$LAUNCHER" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=BloomStream
Comment=Lightweight 4-panel Pi broadcast mixer
Exec=sh -lc 'cd "$ROOT" && python3 main.py'
Path=$ROOT
Icon=camera-video
Terminal=false
StartupNotify=true
Categories=AudioVideo;Recorder;
EOF

chmod +x "$LAUNCHER"
cp "$LAUNCHER" "$DESKTOP_DIR/BloomStream.desktop"
chmod +x "$DESKTOP_DIR/BloomStream.desktop"

# Some Linux desktop environments mark copied launchers as untrusted.
# This is harmless if the current file manager does not use the metadata key.
if command -v gio >/dev/null 2>&1; then
    gio set "$DESKTOP_DIR/BloomStream.desktop" metadata::trusted true >/dev/null 2>&1 || true
fi

echo "BloomStream desktop icon installed:"
echo "  $DESKTOP_DIR/BloomStream.desktop"
