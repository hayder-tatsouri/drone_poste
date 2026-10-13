"""DronePi web interface: video page + map/control page, served from the Pi."""
import asyncio
import io
import json
import logging
import math
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from mavsdk import System
from mavsdk.action import ActionError
from pydantic import BaseModel, Field

CONN = os.environ.get("MAV_CONN", "serial:///dev/serial0:57600")
MAX_ALT = float(os.environ.get("MAX_ALT", "20"))
BASE = Path(__file__).parent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dronepi")

drone = None
tasks = []

state = {
    "connected": False,
    "armed": False,
    "in_air": False,
    "mode": None,
    "lat": None,
    "lon": None,
    "rel_alt": None,
    "abs_alt": None,
    "roll": 0.0,
    "pitch": 0.0,
    "yaw": 0.0,
    "speed": None,
    "battery_v": None,
    "sats": None,
    "fix": None,
    "global_ok": False,
    "home_ok": False,
    "home": None,
}


# ---------------------------------------------------------------- camera
class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.cond = threading.Condition()

    def write(self, buf):
        with self.cond:
            self.frame = bytes(buf)
            self.cond.notify_all()
        return len(buf)


class Camera:
    def __init__(self):
        self.ok = False
        self.output = StreamingOutput()
        self.cam = None

    def start(self):
        try:
            from picamera2 import Picamera2
            from picamera2.encoders import MJPEGEncoder
            from picamera2.outputs import FileOutput

            self.cam = Picamera2()
            cfg = self.cam.create_video_configuration(
                main={"size": (640, 480)}, controls={"FrameRate": 15}
            )
            self.cam.configure(cfg)
            try:
                self.cam.set_controls({"AfMode": 2})  # continuous autofocus (Camera Module 3)
            except Exception:
                pass
            self.cam.start_recording(MJPEGEncoder(), FileOutput(self.output))
            self.ok = True
            log.info("Camera started")
        except Exception as e:
            log.warning("Camera unavailable: %s", e)

    def stop(self):
        if self.cam is not None:
            try:
                self.cam.stop_recording()
                self.cam.close()
            except Exception:
                pass

    def frames(self):
        last = None
        while True:
            with self.output.cond:
                self.output.cond.wait(timeout=2)
                frame = self.output.frame
            if frame is None or frame is last:
                continue
            last = frame
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                + str(len(frame)).encode()
                + b"\r\n\r\n"
                + frame
                + b"\r\n"
            )


camera = Camera()


# ---------------------------------------------------------------- telemetry
def name_of(enum_value):
    return str(enum_value).split(".")[-1]


async def pump(name, factory, handler):
    """Keep one telemetry stream alive, restart it if it errors."""
    while True:
        try:
            async for item in factory():
                handler(item)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("%s stream error: %s", name, e)
        await asyncio.sleep(1)


def on_position(p):
    state["lat"] = p.latitude_deg
    state["lon"] = p.longitude_deg
    state["rel_alt"] = p.relative_altitude_m
    state["abs_alt"] = p.absolute_altitude_m


def on_attitude(a):
    state["roll"] = a.roll_deg
    state["pitch"] = a.pitch_deg
    state["yaw"] = a.yaw_deg


def on_battery(b):
    v = b.voltage_v
    state["battery_v"] = None if (v is None or math.isnan(v)) else v


def on_gps(g):
    state["sats"] = g.num_satellites
    state["fix"] = name_of(g.fix_type)


def on_health(h):
    state["global_ok"] = bool(h.is_global_position_ok)
    state["home_ok"] = bool(h.is_home_position_ok)


def on_home(h):
    state["home"] = {"lat": h.latitude_deg, "lon": h.longitude_deg}


def on_velocity(v):
    state["speed"] = math.hypot(v.north_m_s, v.east_m_s)


async def bring_up():
    global drone
    drone = System()
    log.info("Connecting to %s", CONN)
    await drone.connect(system_address=CONN)

    tasks.append(asyncio.create_task(pump(
        "link", lambda: drone.core.connection_state(),
        lambda s: state.update(connected=s.is_connected))))
    while not state["connected"]:
        await asyncio.sleep(0.2)
    log.info("Flight controller connected")

    for setter, hz in (
        (drone.telemetry.set_rate_position, 5),
        (drone.telemetry.set_rate_attitude_euler, 5),
        (drone.telemetry.set_rate_battery, 1),
        (drone.telemetry.set_rate_gps_info, 1),
        (drone.telemetry.set_rate_home, 1),
        (drone.telemetry.set_rate_velocity_ned, 2),
    ):
        try:
            await setter(hz)
        except Exception as e:
            log.info("Could not set telemetry rate: %s", e)

    t = drone.telemetry
    streams = (
        ("position", t.position, on_position),
        ("attitude", t.attitude_euler, on_attitude),
        ("battery", t.battery, on_battery),
        ("gps", t.gps_info, on_gps),
        ("health", t.health, on_health),
        ("home", t.home, on_home),
        ("velocity", t.velocity_ned, on_velocity),
        ("armed", t.armed, lambda v: state.update(armed=bool(v))),
        ("in_air", t.in_air, lambda v: state.update(in_air=bool(v))),
        ("mode", t.flight_mode, lambda m: state.update(mode=name_of(m))),
    )
    for name, factory, handler in streams:
        tasks.append(asyncio.create_task(pump(name, factory, handler)))


@asynccontextmanager
async def lifespan(app):
    camera.start()
    main_task = asyncio.create_task(bring_up())
    yield
    main_task.cancel()
    for t in tasks:
        t.cancel()
    camera.stop()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
async def page_video():
    return FileResponse(BASE / "static" / "video.html")


@app.get("/map")
async def page_map():
    return FileResponse(BASE / "static" / "map.html")


@app.get("/video")
def video():
    if not camera.ok:
        raise HTTPException(503, "Camera unavailable")
    return StreamingResponse(
        camera.frames(), media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            payload = {**state, "camera": camera.ok, "max_alt": MAX_ALT}
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(0.2)
    except Exception:
        pass


# ---------------------------------------------------------------- commands
class TakeoffReq(BaseModel):
    altitude: float = Field(ge=1, le=MAX_ALT)


async def act(fn):
    if drone is None or not state["connected"]:
        raise HTTPException(503, "Flight controller not connected")
    try:
        await fn()
    except ActionError as e:
        raise HTTPException(409, str(e))


@app.post("/api/takeoff")
async def takeoff(req: TakeoffReq):
    if not state["global_ok"]:
        raise HTTPException(409, "No valid GPS position yet")
    if state["in_air"]:
        raise HTTPException(409, "The drone is already in the air")

    async def seq():
        await drone.action.set_takeoff_altitude(req.altitude)
        await drone.action.arm()
        await drone.action.takeoff()

    await act(seq)
    return {"ok": True, "message": f"Taking off to {req.altitude:g} m"}


@app.post("/api/rtl")
async def rtl():
    await act(lambda: drone.action.return_to_launch())
    return {"ok": True, "message": "Returning home"}


@app.post("/api/land")
async def land():
    await act(lambda: drone.action.land())
    return {"ok": True, "message": "Landing"}


@app.post("/api/disarm")
async def disarm():
    if state["in_air"]:
        raise HTTPException(409, "Refused: the drone is in the air")
    await act(lambda: drone.action.disarm())
    return {"ok": True, "message": "Disarmed"}
