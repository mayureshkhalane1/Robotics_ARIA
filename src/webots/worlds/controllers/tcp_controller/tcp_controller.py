"""
Webots Robot Controller - TCP Server Bridge (FIXED VERSION)

Debug version with extensive logging to diagnose issues.
"""

import socket
import json
import base64
import sys
from typing import Dict, Any, Optional

try:
    from controller import Robot, Motor, DistanceSensor, GPS, Compass, Camera
except ImportError:
    print("[ERROR] Webots controller module not found. This must run inside Webots.")
    sys.exit(1)


class WebotsRobotServer:
    """Manages robot control and TCP communication."""

    def __init__(self, port: int = 19997):
        self.port = port
        self.robot = Robot()
        self.timestep = int(self.robot.getBasicTimeStep())
        print(f"[INIT] Timestep: {self.timestep}ms")

        # Motor setup
        self.left_motor: Optional[Motor] = None
        self.right_motor: Optional[Motor] = None
        self._setup_motors()

        # Sensor setup
        self.proximity_sensors: Dict[str, DistanceSensor] = {}
        self.gps: Optional[GPS] = None
        self.compass: Optional[Compass] = None
        self.camera: Optional[Camera] = None
        self._setup_sensors()

        # TCP Server
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(("127.0.0.1", self.port))
        self.server_socket.listen(1)
        self.server_socket.setblocking(False)  # Non-blocking accept
        self.server_socket.settimeout(0.1)  # 100ms timeout for accept

        self.client_socket: Optional[socket.socket] = None
        print(f"[OK] TCP server listening on port {self.port}")

    def _close_client(self) -> None:
        """Close the current client socket safely."""
        if self.client_socket:
            try:
                self.client_socket.close()
            except Exception:
                pass
        self.client_socket = None

    def _available_devices(self) -> Dict[str, Any]:
        """Return Webots devices by name."""
        devices: Dict[str, Any] = {}
        try:
            for i in range(self.robot.getNumberOfDevices()):
                device = self.robot.getDeviceByIndex(i)
                devices[device.getName()] = device
        except Exception as e:
            print(f"[WARN] Device enumeration failed: {e}")
        return devices

    def _setup_motors(self) -> None:
        """Initialize wheel motors."""
        try:
            devices = self._available_devices()
            for name in ("left wheel motor", "left wheel"):
                self.left_motor = devices.get(name)
                if self.left_motor:
                    print(f"[MOTOR] Left: {name}")
                    break

            for name in ("right wheel motor", "right wheel"):
                self.right_motor = devices.get(name)
                if self.right_motor:
                    print(f"[MOTOR] Right: {name}")
                    break

            if self.left_motor and self.right_motor:
                self.left_motor.setPosition(float('inf'))
                self.right_motor.setPosition(float('inf'))
                self.left_motor.setVelocity(0.0)
                self.right_motor.setVelocity(0.0)
                print("[OK] Motors initialized")
            else:
                print("[WARN] Wheel motors not found - robot won't move")
        except Exception as e:
            print(f"[WARN] Motor setup failed: {e}")

    def _setup_sensors(self) -> None:
        """Initialize sensors."""
        try:
            devices = self._available_devices()
            
            # Distance sensors
            for i in range(8):
                sensor = devices.get(f"distance sensor {i}")
                if sensor:
                    sensor.enable(self.timestep)
                    self.proximity_sensors[f"distance_{i}"] = sensor

            for i in range(16):
                sensor = devices.get(f"so{i}")
                if sensor:
                    sensor.enable(self.timestep)
                    self.proximity_sensors[f"so{i}"] = sensor

            # GPS
            self.gps = devices.get("gps")
            if self.gps:
                self.gps.enable(self.timestep)
                print("[SENSOR] GPS enabled")

            # Compass
            self.compass = devices.get("compass")
            if self.compass:
                self.compass.enable(self.timestep)
                print("[SENSOR] Compass enabled")

            # Camera
            self.camera = devices.get("camera")
            if self.camera:
                self.camera.enable(self.timestep)
                print(f"[SENSOR] Camera enabled ({self.camera.getWidth()}x{self.camera.getHeight()})")

            print(f"[OK] Sensors: {len(self.proximity_sensors)} proximity, GPS={bool(self.gps)}, Compass={bool(self.compass)}")
        except Exception as e:
            print(f"[WARN] Sensor setup failed: {e}")

    def get_robot_state(self, include_camera: bool = False) -> Dict[str, Any]:
        """Return current sensor readings."""
        state = {
            "timestamp": self.robot.getTime(),
            "position": None,
            "orientation": None,
            "proximity": {},
            "wheel_velocities": [0, 0],
            "camera": None,
        }

        # Position from GPS
        if self.gps:
            try:
                gps_values = self.gps.getValues()
                if gps_values:
                    state["position"] = list(gps_values)
            except Exception:
                pass

        # Orientation from compass
        if self.compass:
            try:
                compass_values = self.compass.getValues()
                if compass_values:
                    state["orientation"] = list(compass_values)
            except Exception:
                pass

        # Proximity sensors
        for sensor_name, sensor in self.proximity_sensors.items():
            try:
                state["proximity"][sensor_name] = float(sensor.getValue())
            except:
                state["proximity"][sensor_name] = -1.0

        # Wheel velocities
        if self.left_motor and self.right_motor:
            try:
                state["wheel_velocities"] = [
                    float(self.left_motor.getVelocity()),
                    float(self.right_motor.getVelocity())
                ]
            except:
                pass

        # Camera (optional, expensive)
        if include_camera and self.camera:
            try:
                image = self.camera.getImage()
                if image:
                    width = int(self.camera.getWidth())
                    height = int(self.camera.getHeight())
                    # High-res camera frames can exceed 5 MB once base64
                    # encoded. Downsample raw BGRA to keep TCP responses small
                    # and avoid client timeouts/disconnects.
                    max_dim = 480
                    stride = max(1, (max(width, height) + max_dim - 1) // max_dim)
                    if stride > 1:
                        raw = bytes(image)
                        row_bytes = width * 4
                        small = bytearray()
                        for y in range(0, height, stride):
                            row_start = y * row_bytes
                            for x in range(0, width, stride):
                                i = row_start + x * 4
                                small.extend(raw[i:i + 4])
                        image = bytes(small)
                        width = (width + stride - 1) // stride
                        height = (height + stride - 1) // stride
                    state["camera"] = {
                        "encoding": "bgra8_base64",
                        "width": width,
                        "height": height,
                        "data": base64.b64encode(image).decode("ascii"),
                    }
            except Exception as e:
                state["camera"] = {"error": str(e)}

        return state

    def execute_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a robot action."""
        action_type = action.get("type", "stop")
        params = action.get("params", {})

        try:
            if action_type == "move":
                velocity = float(params.get("velocity", 4.0))
                if self.left_motor and self.right_motor:
                    self.left_motor.setVelocity(velocity)
                    self.right_motor.setVelocity(velocity)
                    return {"status": "ok", "action": action_type, "velocity": velocity}
                else:
                    return {"status": "error", "message": "Motors not initialized"}

            elif action_type == "turn":
                angular_velocity = float(params.get("angular_velocity", 0.5))
                if self.left_motor and self.right_motor:
                    self.left_motor.setVelocity(-angular_velocity)
                    self.right_motor.setVelocity(angular_velocity)
                    return {"status": "ok", "action": action_type, "angular_velocity": angular_velocity}
                else:
                    return {"status": "error", "message": "Motors not initialized"}

            elif action_type == "stop":
                if self.left_motor and self.right_motor:
                    self.left_motor.setVelocity(0.0)
                    self.right_motor.setVelocity(0.0)
                return {"status": "ok", "action": action_type}

            elif action_type == "grab":
                return {"status": "ok", "action": action_type, "note": "Not implemented"}

            else:
                return {"status": "error", "message": f"Unknown action: {action_type}"}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    def handle_command(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a command from the client."""
        command = cmd.get("cmd", "")

        if command == "get_state":
            include_camera = cmd.get("include_camera", False)
            return self.get_robot_state(include_camera=include_camera)
        elif command == "execute":
            action = cmd.get("action", {})
            return self.execute_action(action)
        elif command == "stop":
            if self.left_motor and self.right_motor:
                self.left_motor.setVelocity(0.0)
                self.right_motor.setVelocity(0.0)
            return {"status": "ok", "action": "stop"}
        else:
            return {"status": "error", "message": f"Unknown command: {command}"}

    def run(self) -> None:
        """Main control loop."""
        step_count = 0
        client_count = 0
        
        print("[RUN] Entering main loop...")
        
        while self.robot.step(self.timestep) != -1:
            step_count += 1

            # Accept new connection even if an old/stale client is still held.
            # The ARIA UI may reconnect while a previous camera request timed
            # out; replacing the stale socket prevents new requests from sitting
            # unhandled in the OS backlog.
            try:
                new_client, addr = self.server_socket.accept()
                new_client.setblocking(False)
                new_client.settimeout(0.5)
                if self.client_socket:
                    print("[CLIENT] Replacing previous client")
                    self._close_client()
                self.client_socket = new_client
                client_count += 1
                print(f"[CLIENT] Connected #{client_count}: {addr}")
            except (BlockingIOError, socket.timeout):
                pass
            except Exception as e:
                print(f"[ERROR] Accept failed: {e}")

            # Handle incoming data from connected client
            if self.client_socket:
                try:
                    data = self.client_socket.recv(4096)
                    if data:
                        try:
                            lines = data.decode('utf-8').strip().split('\n')
                            for line in lines:
                                if not line:
                                    continue
                                cmd = json.loads(line)
                                response = self.handle_command(cmd)
                                response_json = json.dumps(response) + "\n"
                                self.client_socket.sendall(response_json.encode('utf-8'))
                                print(f"[CMD] {cmd.get('cmd')} -> sent response")
                        except json.JSONDecodeError as e:
                            error_response = {"status": "error", "message": f"JSON error: {e}"}
                            self.client_socket.sendall((json.dumps(error_response) + "\n").encode('utf-8'))
                    else:
                        print("[CLIENT] Disconnected")
                        self._close_client()

                except (BlockingIOError, socket.timeout):
                    # No data available right now, that's fine
                    pass
                except Exception as e:
                    print(f"[ERROR] Command handler: {e}")
                    self._close_client()

            # Periodic heartbeat
            if step_count % 200 == 0:  # Every 200 steps (2 seconds at 100ms timestep)
                try:
                    state = self.get_robot_state(include_camera=False)
                    pos = state.get("position")
                    print(f"[BEAT] Step {step_count}: pos={pos[:2] if pos else '?'}, sensors={len(self.proximity_sensors)}")
                except:
                    pass


def main():
    """Entry point."""
    print("[START] Webots TCP Controller")
    server = WebotsRobotServer(port=19997)
    try:
        server.run()
    except KeyboardInterrupt:
        print("\n[STOP] Shutdown requested")
    except Exception as e:
        print(f"[FATAL] {e}")


if __name__ == "__main__":
    main()
