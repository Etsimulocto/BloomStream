#!/usr/bin/env bash
set -euo pipefail

echo '== BloomStream installer =='
sudo apt update
sudo apt install -y ffmpeg v4l-utils python3-tk pulseaudio-utils
mkdir -p "$HOME/.local/share/applications"
ROOT="$(cd "$(dirname "$0")" && pwd)"
cat > "$HOME/.local/share/applications/bloomstream.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=BloomStream
Comment=Lightweight 4-panel Pi broadcast mixer
Exec=sh -lc 'cd "$ROOT" && python3 main.py'
Terminal=false
Categories=AudioVideo;Recorder;
EOF
chmod +x "$ROOT/main.py"
echo 'Installed dependencies.'
echo "Run: cd \"$ROOT\" && python3 main.py"
