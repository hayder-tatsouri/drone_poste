# DronePi web interface

Two pages served by the Pi:
- `/` live video (Pi Camera v3) with an attitude indicator
- `/map` live position on a map, plus Take off, Return home, Land, Disarm

## Install on the Pi (needs internet Wi-Fi for this step)

    sudo apt update && sudo apt install -y python3-picamera2 unzip
    cd ~/poste-app && unzip dronepi-web.zip -d web
    python3 -m venv --system-site-packages ~/poste-app/venv
    ~/poste-app/venv/bin/pip install -r ~/poste-app/web/requirements.txt
    rpicam-hello --list-cameras        # the camera must be listed

## Run by hand first

Close any other script using /dev/serial0 (only one program can hold the port).

    cd ~/poste-app/web
    ~/poste-app/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000

Open http://<pi-address>:8000 from a phone or laptop on the same network
(hotspot: http://10.42.0.1:8000).

## Start on boot

    sudo cp ~/poste-app/web/dronepi.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now dronepi
    journalctl -u dronepi -f           # logs

## Settings (in dronepi.service)

- MAV_CONN: connection string, default serial:///dev/serial0:57600
- MAX_ALT: maximum takeoff altitude in meters, default 20 (enforced by the server)
- Map start position: DEFAULT_CENTER in static/map.html

## Notes

- The map loads Leaflet and tiles from the internet, in the browser of the device you
  view it from. On the offline hotspot the map stays empty; video and controls still work.
- Take off needs a valid GPS position and the flight controller in GUIDED mode.
  Set GUIDED from the transmitter or Mission Planner first. The page shows the current
  mode in the top strip.
- Test with propellers removed first.
# drone_poste
