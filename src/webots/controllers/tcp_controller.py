"""
Webots Robot Controller - TCP Server Bridge

This script runs INSIDE Webots as a robot controller.
It listens on TCP port 19997 for commands from the agent and streams sensor data back.

To use:
1. In Webots, create a robot with wheels and sensors
2. Create a controller node and paste this script
3. Run simulation - server will listen on port 19997

Commands:
- {"cmd": "get_state"} -> returns current sensor readings
- {"cmd": "execute", "action": {...}} -> executes action and returns status
- {"cmd": "stop"} -> stops all motors
"""

import socket
import json
import base64
from typing import Dict, Any, Optional

try:
    from controller import Robot, Motor, DistanceSensor, GPS, Compass, Camera
except ImportError:
    print("[ERROR] Webots controller module not found. This script must run inside Webots.")
    exit(1)


class WebotsRobotServer:
    """Manages robot control and TCP communication."""

    def __init__(self, port: int = 19997):
        self.port = port
        self.robot = Robot()
        self.timestep = int(self.robot.getBasicTimeStep())

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
        self.server_socket.setblocking(False)

        self.client_socket: Optional[socket.socket] = None
        print(f"[Webots] Robot server initialized on port {self.port}")

    def _close_client(self) -> None:
        """Close the current client socket safely."""
        if self.client_socket:
            try:
                self.client_socket.close()
            except Exception:
                pass
        self.client_socket = None

    def _available_devices(self) -> Dict[str, Any]:
        """Return Webots devices by name without triggering missing-device warnings."""
        devices: Dict[str, Any] = {}
        try:
            for i in range(self.robot.getNumberOfDevices()):
                device = self.robot.getDeviceByIndex(i)
                devices[device.getName()] = device
        except Exception as e:
            print(f"[WARNING] Could not enumerate devices: {e}")
        return devices

    def _setup_motors(self) -> None:
        """Initialize wheel motors."""
        try:
            devices = self._available_devices()
            # Support both generic tutorial names and Webots Pioneer 3-DX names.
            # Pioneer3dx.proto uses "left wheel" and "right wheel".
            for name in ("left wheel motor", "left wheel"):
                self.left_motor = devices.get(name)
                if self.left_motor:
                    print(f"[Webots] Left motor: {name}")
                    break

            for name in ("right wheel motor", "right wheel"):
                self.right_motor = devices.get(name)
                if self.right_motor:
                    print(f"[Webots] Right motor: {name}")
                    break

            if self.left_motor and self.right_motor:
                # Set to velocity control mode
                self.left_motor.setPosition(float('inf'))
                self.right_motor.setPosition(float('inf'))
                self.left_motor.setVelocity(0.0)
                self.right_motor.setVelocity(0.0)
                print("[Webots] Motors initialized")
            else:
                print("[WARNING] Could not find wheel motors")
        except Exception as e:
            print(f"[WARNING] Motor setup failed: {e}")

    def _setup_sensors(self) -> None:
        """Initialize proximity, GPS, and compass sensors."""
        try:
            devices = self._available_devices()
            # Distance/Proximity sensors. Support generic names plus Pioneer 3-DX
            # sonar names so0..so15.
            for i in range(8):  # Up to 8 sensors
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

            # Compass
            self.compass = devices.get("compass")
            if self.compass:
                self.compass.enable(self.timestep)

            # Camera (optional)
            self.camera = devices.get("camera")
            if self.camera:
                self.camera.enable(self.timestep)

            sensor_count = len(self.proximity_sensors)
            print(f"[Webots] Sensors initialized: {sensor_count} proximity, GPS={'yes' if self.gps else 'no'}, Compass={'yes' if self.compass else 'no'}")
        except Exception as e:
            print(f"[WARNING] Sensor setup failed: {e}")

    def get_robot_state(self, include_camera: bool = True) -> Dict[str, Any]:
        """Return current sensor readings as a dict.
        
        Args:
            include_camera: If False, skip camera image to reduce response size (327KB -> 2KB)
        """
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
            gps_values = self.gps.getValues()
            if gps_values:
                state["position"] = list(gps_values)

        # Orientation from compass and simulation
        if self.compass:
            compass_values = self.compass.getValues()
            if compass_values:
                # Convert to angle in radians
                state["orientation"] = list(compass_values)

        # Proximity sensors
        for sensor_name, sensor in self.proximity_sensors.items():
            try:
                state["proximity"][sensor_name] = float(sensor.getValue())
            except:
                state["proximity"][sensor_name] = -1.0

        # Wheel velocities
        if self.left_motor and self.right_motor:
            state["wheel_velocities"] = [
                float(self.left_motor.getVelocity()),
                float(self.right_motor.getVelocity())
            ]

        # Camera (optional, can be expensive due to base64 encoding)
        if include_camera and self.camera:
            try:
                image = self.camera.getImage()
                if image:
                    state["camera"] = {
                        "encoding": "bgra8_base64",
                        "width": int(self.camera.getWidth()),
                        "height": int(self.camera.getHeight()),
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
                # Move forward/backward
                velocity = float(params.get("velocity", 4.0))
                self.left_motor.setVelocity(velocity)
                self.right_motor.setVelocity(velocity)
                result = {"status": "ok", "action": action_type, "velocity": velocity}

            elif action_type == "turn":
                # Rotate in place
                angular_velocity = float(params.get("angular_velocity", 0.5))
                self.left_motor.setVelocity(-angular_velocity)
                self.right_motor.setVelocity(angular_velocity)
                result = {"status": "ok", "action": action_type, "angular_velocity": angular_velocity}

            elif action_type == "stop":
                # Stop all motors
                self.left_motor.setVelocity(0.0)
                self.right_motor.setVelocity(0.0)
                result = {"status": "ok", "action": action_type}

            elif action_type == "grab":
                # Placeholder for gripper action
                result = {"status": "ok", "action": action_type, "note": "Gripper not implemented"}

            else:
                result = {"status": "error", "message": f"Unknown action type: {action_type}"}

        except Exception as e:
            result = {"status": "error", "message": str(e)}

        return result

    def handle_command(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a command from the client."""
        command = cmd.get("cmd", "")

        if command == "get_state":
            # Support optional include_camera flag to reduce response size
            include_camera = cmd.get("include_camera", True)
            return self.get_robot_state(include_camera=include_camera)
        elif command == "execute":
            action = cmd.get("action", {})
            return self.execute_action(action)
        elif command == "stop":
            self.left_motor.setVelocity(0.0)
            self.right_motor.setVelocity(0.0)
            return {"status": "ok", "action": "stop"}
        else:
            return {"status": "error", "message": f"Unknown command: {command}"}

    def run(self) -> None:
        """Main loop: accept connections and handle commands."""
        step_count = 0
        while self.robot.step(self.timestep) != -1:
            step_count += 1

            # Try to accept a new connection
            try:
                if self.client_socket is None:
                    self.client_socket, addr = self.server_socket.accept()
                    self.client_socket.setblocking(False)
                    print(f"[Webots] Client connected: {addr}")
            except BlockingIOError:
                pass
            except Exception as e:
                print(f"[Webots] Accept error: {e}")

            # Handle incoming commands
            if self.client_socket:
                try:
                    # Try to receive data
                    data = self.client_socket.recv(4096)
                    if data:
                        try:
                            lines = data.decode('utf-8').strip().split('\n')
                            for line in lines:
                                if not line:
                                    continue
                                cmd = json.loads(line)
                                response = self.handle_command(cmd)
                                self.client_socket.sendall((json.dumps(response) + "\n").encode('utf-8'))
                        except json.JSONDecodeError as e:
                            error_response = {"status": "error", "message": f"JSON decode error: {e}"}
                            self.client_socket.sendall((json.dumps(error_response) + "\n").encode('utf-8'))
                    else:
                        # Client disconnected
                        print("[Webots] Client disconnected")
                        self._close_client()

                except BlockingIOError:
                    pass  # No data available
                except Exception as e:
                    print(f"[Webots] Command error: {e}")
                    self._close_client()

            # Periodic status
            if step_count % 100 == 0:
                state = self.get_robot_state()
                if state.get("position"):
                    print(f"[Webots] Step {step_count}: pos={state['position'][:2]}, dist sensors={len(self.proximity_sensors)}")


def main():
    """Entry point."""
    server = WebotsRobotServer(port=19997)
    try:
        server.run()
    except KeyboardInterrupt:
        print("\n[Webots] Shutting down...")
    except Exception as e:
        print(f"[Webots] Fatal error: {e}")


if __name__ == "__main__":
    main()
