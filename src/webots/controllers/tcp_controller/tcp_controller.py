"""
ARIA TCP Controller for Webots R2025a (Windows-safe version).

Runs inside Webots as the Pioneer 3-DX controller.
Opens a TCP server on port 19997 so the ARIA agent (running in WSL2)
can read sensors and send motor commands.
"""

import socket
import json
import base64
import sys
from typing import Dict, Any, Optional

try:
    from controller import Robot, Motor, DistanceSensor, GPS, Compass, Camera
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
        sys.stdout.flush()

        self.left_motor: Optional[Motor] = None
        self.right_motor: Optional[Motor] = None
        self.proximity_sensors: Dict[str, Any] = {}
        self.gps: Optional[GPS] = None
        self.compass: Optional[Compass] = None
        self.camera: Optional[Camera] = None

        self._setup_motors()
        self._setup_sensors()
        self._setup_tcp()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

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
            print(f"[OK] Sensors: {len(self.proximity_sensors)} proximity, "
                  f"GPS={self.gps is not None}, Camera={self.camera is not None}")
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
            "position": None,
            "orientation": None,
            "proximity": {},
            "wheel_velocities": [0.0, 0.0],
            "camera": None,
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
        except Exception as e:
            state["error"] = str(e)
        return state

    def execute_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        atype = action.get("type", "stop")
        params = action.get("params", {})
        try:
            if atype == "move":
                v = float(params.get("velocity", 4.0))
                if self.left_motor and self.right_motor:
                    self.left_motor.setVelocity(v)
                    self.right_motor.setVelocity(v)
                return {"status": "ok", "action": atype, "velocity": v}
            elif atype == "turn":
                av = float(params.get("angular_velocity", 0.5))
                if self.left_motor and self.right_motor:
                    self.left_motor.setVelocity(-av)
                    self.right_motor.setVelocity(av)
                return {"status": "ok", "action": atype, "angular_velocity": av}
            elif atype == "stop":
                if self.left_motor and self.right_motor:
                    self.left_motor.setVelocity(0.0)
                    self.right_motor.setVelocity(0.0)
                return {"status": "ok", "action": "stop"}
            else:
                return {"status": "error", "message": f"Unknown action: {atype}"}
        except Exception as e:
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

            # Accept new connection
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

            # Handle commands
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
