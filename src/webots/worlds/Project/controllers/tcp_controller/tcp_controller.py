"""
ARIA TCP Controller for Webots R2025a (Windows-safe version).

Runs inside Webots as the Pioneer 3-DX controller.
Opens a TCP server on port 19997 so the ARIA agent (running in WSL2)
can read sensors and send motor commands.
"""

import socket
import json
import base64
import os
import sys
from typing import Dict, Any, Optional

try:
    from controller import Robot, Motor, DistanceSensor, GPS, Compass, Camera, Lidar
except ImportError:
    print("[FATAL] Webots controller module not found. Must run inside Webots.")
    sys.exit(1)


class WebotsRobotServer:

    def __init__(self, port: int = 19997):
        self.port = port
        self.tcp_ok = False

        self.robot = Robot()
        self.timestep = int(self.robot.getBasicTimeStep())
        print(f"[INIT] Robot ready. Timestep={self.timestep}ms")

        # Detect which world is actually loaded so the agent never has to guess
        # (and never chases a stale coordinate from a different world).
        self.world_name, self._world_sources = self._detect_world_name()
        print(f"[INIT] World detected: {self.world_name!r}")
        if self._world_sources:
            print(f"[INIT] World name sources seen: {self._world_sources}")
        else:
            print("[INIT] No world-name source found -- dumping WEBOTS_* env for diagnosis:")
            for k, v in sorted(os.environ.items()):
                if k.startswith("WEBOTS") or "WORLD" in k.upper():
                    print(f"        {k}={v}")
        sys.stdout.flush()

        self.left_motor: Optional[Motor] = None
        self.right_motor: Optional[Motor] = None
        self.proximity_sensors: Dict[str, Any] = {}
        self.gps: Optional[GPS] = None
        self.compass: Optional[Compass] = None
        self.camera: Optional[Camera] = None
        self.lidar: Optional[Lidar] = None

        self._setup_motors()
        self._setup_sensors()
        self._setup_tcp()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _detect_world_name(self):
        """Best-effort detection of the loaded world's file stem (e.g.
        "break_room").  The plain Robot API has no "get world path" call, so we
        try several sources and report which ones we found.

        Order of preference:
          1. self.robot.getWorldPath()  — exists on some Webots builds/Supervisor
          2. environment variables Webots sets for the controller process
          3. any WEBOTS_* env value that ends in .wbt

        Returns (stem_or_None, sources_dict).  sources_dict is surfaced to the
        agent so the run log shows exactly what was available on this machine.
        """
        sources: Dict[str, str] = {}

        # 1. API method, if this build exposes it (harmless if absent).
        try:
            getter = getattr(self.robot, "getWorldPath", None)
            if callable(getter):
                wp = getter()
                if wp:
                    sources["getWorldPath"] = str(wp)
        except Exception:
            pass

        # 2. Known candidate environment variables (vary by version/platform).
        for var in ("WEBOTS_WORLD", "WEBOTS_WORLD_PATH", "WEBOTS_CURRENT_WORLD",
                    "WEBOTS_WORLD_FILE", "WORLD_NAME"):
            v = os.environ.get(var)
            if v:
                sources[var] = v

        # 3. Catch-all: any WEBOTS_* env value pointing at a .wbt file.
        for k, v in os.environ.items():
            if k.startswith("WEBOTS") and v and v.lower().endswith(".wbt"):
                sources.setdefault(k, v)

        # Pick the first usable value → file stem (drop dir + .wbt extension).
        priority = ["getWorldPath", "WEBOTS_WORLD", "WEBOTS_WORLD_PATH",
                    "WEBOTS_CURRENT_WORLD", "WEBOTS_WORLD_FILE", "WORLD_NAME"]
        for key in priority:
            if key in sources:
                stem = os.path.splitext(os.path.basename(sources[key]))[0]
                if stem:
                    return stem, sources
        for v in sources.values():
            if str(v).lower().endswith(".wbt"):
                return os.path.splitext(os.path.basename(v))[0], sources
        return None, sources

    def _setup_motors(self) -> None:
        try:
            devices = self._devices()
            for name in ("left wheel motor", "left wheel"):
                if devices.get(name):
                    self.left_motor = devices[name]
                    break
            for name in ("right wheel motor", "right wheel"):
                if devices.get(name):
                    self.right_motor = devices[name]
                    break
            if self.left_motor and self.right_motor:
                # Set to velocity mode with infinite rotation
                self.left_motor.setPosition(float("inf"))
                self.right_motor.setPosition(float("inf"))
                # CRITICAL: Initialize to zero velocity (robot must be stopped initially)
                self.left_motor.setVelocity(0.0)
                self.right_motor.setVelocity(0.0)
                # Give motors time to settle
                for _ in range(5):
                    self.robot.step(self.timestep)
                print("[OK] Motors ready (velocity initialized to 0.0)")
            else:
                print("[WARN] Wheel motors not found")
            sys.stdout.flush()
        except Exception as e:
            print(f"[WARN] Motor setup failed: {e}")
            sys.stdout.flush()

    def _setup_sensors(self) -> None:
        try:
            devices = self._devices()
            for i in range(16):
                for pattern in (f"so{i}", f"distance sensor {i}"):
                    s = devices.get(pattern)
                    if s:
                        s.enable(self.timestep)
                        self.proximity_sensors[pattern] = s
                        break
            self.gps = devices.get("gps")
            if self.gps:
                self.gps.enable(self.timestep)
            self.compass = devices.get("compass")
            if self.compass:
                self.compass.enable(self.timestep)
            self.camera = devices.get("camera")
            if self.camera:
                self.camera.enable(self.timestep)
            self.lidar = devices.get("lidar")
            if self.lidar:
                self.lidar.enable(self.timestep)
                # point cloud not needed — we only read the range image
            print(f"[OK] Sensors: {len(self.proximity_sensors)} proximity, "
                  f"GPS={self.gps is not None}, Camera={self.camera is not None}, "
                  f"Lidar={self.lidar is not None}")
            sys.stdout.flush()
        except Exception as e:
            print(f"[WARN] Sensor setup failed: {e}")
            sys.stdout.flush()

    def _setup_tcp(self) -> None:
        """Open TCP server. On Windows, bind to 0.0.0.0 so WSL2 can reach it."""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(("0.0.0.0", self.port))
            self.server_socket.listen(1)
            self.server_socket.settimeout(0.1)
            self.client_socket: Optional[socket.socket] = None
            self.tcp_ok = True
            print(f"[OK] TCP server listening on 0.0.0.0:{self.port}")
            sys.stdout.flush()
        except OSError as e:
            print(f"[WARN] TCP bind failed (port {self.port} may be in use): {e}")
            print("[WARN] Robot will move but ARIA agent cannot connect.")
            sys.stdout.flush()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _devices(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        try:
            for i in range(self.robot.getNumberOfDevices()):
                d = self.robot.getDeviceByIndex(i)
                out[d.getName()] = d
        except Exception:
            pass
        return out

    def _gps_xy(self):
        """Return (x, y) ground-plane position, or None."""
        try:
            if self.gps:
                v = self.gps.getValues()
                if v:
                    return (v[0], v[1])
        except Exception:
            pass
        return None

    def _compass_xy(self):
        """Return the horizontal (x, y) components of the compass north vector.

        The world is Z-up (ENU), so the z component carries no heading
        information — only x and y do.  Returned as a tuple, or None.
        """
        try:
            if self.compass:
                v = self.compass.getValues()
                if v:
                    return (v[0], v[1])
        except Exception:
            pass
        return None

    def _close_client(self) -> None:
        if hasattr(self, "client_socket") and self.client_socket:
            try:
                self.client_socket.close()
            except Exception:
                pass
            self.client_socket = None

    # ------------------------------------------------------------------
    # State / actions
    # ------------------------------------------------------------------

    def get_state(self, include_camera: bool = True) -> Dict[str, Any]:
        state: Dict[str, Any] = {
            "timestamp": self.robot.getTime(),
            "world": self.world_name,            # loaded world's file stem, or None
            "world_sources": self._world_sources,  # what the controller could see
            "position": None,
            "orientation": None,
            "proximity": {},
            "wheel_velocities": [0.0, 0.0],
            "camera": None,
            "lidar": None,
        }
        try:
            if self.gps:
                v = self.gps.getValues()
                if v:
                    state["position"] = list(v)
            if self.compass:
                v = self.compass.getValues()
                if v:
                    state["orientation"] = list(v)
            for name, sensor in self.proximity_sensors.items():
                try:
                    state["proximity"][name] = float(sensor.getValue())
                except Exception:
                    state["proximity"][name] = -1.0
            if self.left_motor and self.right_motor:
                state["wheel_velocities"] = [
                    float(self.left_motor.getVelocity()),
                    float(self.right_motor.getVelocity()),
                ]
            if include_camera and self.camera:
                img = self.camera.getImage()
                if img:
                    state["camera"] = {
                        "encoding": "bgra8_base64",
                        "width": int(self.camera.getWidth()),
                        "height": int(self.camera.getHeight()),
                        "data": base64.b64encode(img).decode("ascii"),
                    }
            if self.lidar:
                ranges = self.lidar.getRangeImage()
                if ranges:
                    # inf/NaN -> -1.0 (no return); keep it JSON-safe and compact
                    clean = [
                        (round(float(r), 3) if (r == r and r != float("inf")) else -1.0)
                        for r in ranges
                    ]
                    state["lidar"] = {
                        "ranges": clean,
                        "fov": float(self.lidar.getFov()),
                        "resolution": int(self.lidar.getHorizontalResolution()),
                        "max_range": float(self.lidar.getMaxRange()),
                    }
        except Exception as e:
            state["error"] = str(e)
        return state

    def execute_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a robot action as a CLOSED-LOOP, self-terminating motion.

        The motion stops when the sensor goal is reached, then the motors are
        ALWAYS set back to zero before returning.  This makes every motion
        deterministic and independent of the Webots speed slider, and removes
        the old failure mode where the wheels kept spinning between the time
        this call returned and the agent's separate "stop" command arrived.

        Recognised params:
          velocity         wheel velocity (rad/s) for "move"
          angular_velocity differential wheel velocity (rad/s) for "turn"
          target_distance  metres to travel before stopping (closed-loop, GPS)
          target_angle     degrees to rotate before stopping (closed-loop, compass)
          steps            hard safety cap on simulation steps (anti-runaway)

        If target_distance / target_angle are omitted it falls back to running
        the step cap (legacy open-loop behaviour) but still stops the motors.
        """
        import math

        atype = action.get("type", "stop")
        params = action.get("params", {})

        # Hard safety cap so a missing/!noisy sensor can never spin forever.
        DEFAULT_STEP_CAP = {"move": 120, "turn": 160, "stop": 0}
        max_steps = int(params.get("steps", DEFAULT_STEP_CAP.get(atype, 10)))
        target_distance = params.get("target_distance")
        target_angle = params.get("target_angle")
        target_rad = math.radians(float(target_angle)) if target_angle is not None else None

        try:
            motor_left_vel = 0.0
            motor_right_vel = 0.0

            if atype == "move":
                v = float(params.get("velocity", 4.0))
                motor_left_vel = motor_right_vel = v
            elif atype == "turn":
                av = float(params.get("angular_velocity", 0.5))
                motor_left_vel, motor_right_vel = -av, av
            elif atype == "stop":
                motor_left_vel = motor_right_vel = 0.0
            else:
                return {"status": "error", "message": f"Unknown action: {atype}"}

            if not (self.left_motor and self.right_motor):
                return {"status": "error", "message": "Motors not initialized"}

            start_pos = self._gps_xy()
            start_heading = list(self.compass.getValues()) if self.compass else None
            prev_xy = self._compass_xy()
            accum_angle = 0.0
            reached = False

            self.left_motor.setVelocity(motor_left_vel)
            self.right_motor.setVelocity(motor_right_vel)

            step_count = 0
            while step_count < max_steps:
                if self.robot.step(self.timestep) == -1:
                    break
                step_count += 1

                if atype == "move" and target_distance is not None and start_pos:
                    cur = self._gps_xy()
                    if cur:
                        d = math.hypot(cur[0] - start_pos[0], cur[1] - start_pos[1])
                        if d >= float(target_distance):
                            reached = True
                            break

                elif atype == "turn" and target_rad is not None and prev_xy:
                    cur = self._compass_xy()
                    if cur:
                        # Signed incremental rotation between consecutive samples,
                        # accumulated so it stays correct through 180°/360°.
                        dot = prev_xy[0] * cur[0] + prev_xy[1] * cur[1]
                        crs = prev_xy[0] * cur[1] - prev_xy[1] * cur[0]
                        accum_angle += math.atan2(crs, dot)
                        prev_xy = cur
                        if abs(accum_angle) >= target_rad:
                            reached = True
                            break

            # ALWAYS stop the wheels once the motion is complete.
            self.left_motor.setVelocity(0.0)
            self.right_motor.setVelocity(0.0)

            end_pos = self._gps_xy()
            end_heading = list(self.compass.getValues()) if self.compass else None

            response = {
                "status": "ok",
                "action": atype,
                "duration_steps": step_count,
                "reached_target": reached,
            }
            if start_pos and end_pos:
                response["start_position"] = list(start_pos)
                response["end_position"] = list(end_pos)
                response["distance_traveled"] = math.hypot(
                    end_pos[0] - start_pos[0], end_pos[1] - start_pos[1]
                )
            if start_heading and end_heading:
                response["start_heading"] = start_heading
                response["end_heading"] = end_heading
            if atype == "turn":
                response["degrees_turned"] = math.degrees(accum_angle)
                response["angular_velocity"] = motor_left_vel
            elif atype == "move":
                response["velocity"] = motor_left_vel

            return response

        except Exception as e:
            import traceback
            traceback.print_exc()
            # Best-effort safety stop even on error.
            try:
                if self.left_motor and self.right_motor:
                    self.left_motor.setVelocity(0.0)
                    self.right_motor.setVelocity(0.0)
            except Exception:
                pass
            return {"status": "error", "message": str(e)}

    def handle_command(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        command = cmd.get("cmd", "")
        if command == "get_state":
            return self.get_state(include_camera=cmd.get("include_camera", True))
        elif command == "execute":
            return self.execute_action(cmd.get("action", {}))
        elif command == "stop":
            if self.left_motor and self.right_motor:
                self.left_motor.setVelocity(0.0)
                self.right_motor.setVelocity(0.0)
            return {"status": "ok", "action": "stop"}
        return {"status": "error", "message": f"Unknown command: {command}"}

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        print("[RUN] Entering main loop...")
        sys.stdout.flush()
        step = 0
        while self.robot.step(self.timestep) != -1:
            step += 1
            if not self.tcp_ok:
                continue

            if not self.client_socket:
                try:
                    self.client_socket, addr = self.server_socket.accept()
                    self.client_socket.settimeout(0.5)
                    print(f"[TCP] Client connected: {addr}")
                    sys.stdout.flush()
                except (socket.timeout, BlockingIOError):
                    pass
                except Exception as e:
                    print(f"[WARN] Accept error: {e}")
                    sys.stdout.flush()

            if self.client_socket:
                try:
                    data = self.client_socket.recv(4096)
                    if data:
                        for line in data.decode("utf-8").strip().split("\n"):
                            if not line:
                                continue
                            try:
                                cmd = json.loads(line)
                                resp = self.handle_command(cmd)
                                self.client_socket.sendall(
                                    (json.dumps(resp) + "\n").encode("utf-8")
                                )
                            except json.JSONDecodeError as e:
                                err = json.dumps({"status": "error", "message": str(e)})
                                self.client_socket.sendall((err + "\n").encode("utf-8"))
                    else:
                        print("[TCP] Client disconnected")
                        sys.stdout.flush()
                        self._close_client()
                except (socket.timeout, BlockingIOError):
                    pass
                except Exception as e:
                    print(f"[WARN] Client error: {e}")
                    sys.stdout.flush()
                    self._close_client()

            if step % 500 == 0:
                pos = None
                try:
                    if self.gps:
                        pos = [round(x, 2) for x in self.gps.getValues()[:2]]
                except Exception:
                    pass
                print(f"[BEAT] step={step} pos={pos}")
                sys.stdout.flush()


def main() -> None:
    print("[START] ARIA TCP Controller")
    sys.stdout.flush()
    try:
        server = WebotsRobotServer(port=19997)
        server.run()
    except KeyboardInterrupt:
        print("[STOP] Keyboard interrupt")
    except Exception as e:
        print(f"[FATAL] Unhandled exception: {e}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()


if __name__ == "__main__":
    main()
