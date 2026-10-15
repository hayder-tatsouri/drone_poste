#!/usr/bin/env bash
# One-command setup for the DronePi web interface. Needs internet on the Pi.
# Usage: unzip dronepi-web.zip -d ~/poste-app/web && bash ~/poste-app/web/setup.sh
set -e
cd "$(dirname "$0")"

# serial port for the flight controller (UART on /dev/serial0)
grep -q '^enable_uart=1' /boot/firmware/config.txt || echo 'enable_uart=1' | sudo tee -a /boot/firmware/config.txt
grep -q '^dtoverlay=disable-bt' /boot/firmware/config.txt || echo 'dtoverlay=disable-bt' | sudo tee -a /boot/firmware/config.txt
sudo systemctl enable ssh

sudo apt update
sudo apt install -y python3-picamera2 unzip curl
python3 -m venv --system-site-packages ../venv
../venv/bin/pip install -r requirements.txt

# map libraries, stored locally so the page works without internet
mkdir -p static/leaflet/images static/maps
cd static/leaflet
B=https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4
curl -fsSLO $B/leaflet.js
curl -fsSLO $B/leaflet.css
curl -fsSL $B/images/layers.png -o images/layers.png
curl -fsSL $B/images/layers-2x.png -o images/layers-2x.png
curl -fsSL https://unpkg.com/protomaps-leaflet@5.0.0/dist/protomaps-leaflet.js -o protomaps-leaflet.js
cd ../..

sudo cp dronepi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dronepi

echo
echo "Done. Next:"
echo "1. Copy tunisia.pmtiles to ~/poste-app/web/static/maps/"
echo "2. sudo reboot"
