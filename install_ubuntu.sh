#!/usr/bin/env bash
set -euo pipefail
sudo apt update
sudo apt install -y python3-venv python3-pip python3-pyatspi python3-gi libportaudio2 portaudio19-dev at-spi2-core xclip
if [[ "${XDG_SESSION_TYPE:-}" == "x11" ]]; then
  sudo apt install -y xdotool
else
  sudo apt install -y ydotool
fi
rm -rf .venv
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
python -m pip install -r requirements.txt
echo "Installed. The venv uses system site packages so pyatspi is visible."
