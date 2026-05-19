"""
MCP Server for ARIA Robot Intelligence Architecture

This server bridges the LangGraph agent to the Webots simulator.
It exposes robot control and state reading as callable tools via the Model Context Protocol.

Tools exposed:
- get_state: Retrieve current robot sensor readings
- execute_action: Execute a robot action (move, turn, stop, grab)
- get_objects: Get list of objects in the world
- validate_action: Validate an action before execution
"""

import socket
import json
import logging
import threading
from typing import Dict, Any, Optional
from dataclasses import asdict

from src.common.config import WEBOTS_HOST, WEBOTS_PORT, WEBOTS_TIMEOUT
from src.common.types import RobotState, Action, ActionType

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[MCP] %(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WebotsBridge:
    """Manages TCP connection to Webots simulator controller."""

    def __init__(self, host: str = WEBOTS_HOST, port: int = WEBOTS_PORT, timeout: float = WEBOTS_TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.socket: Optional[socket.socket] = None
        self._connected = False
        self._connection_failures = 0
        self._last_error: Optional[str] = None
        self._lock = threading.Lock()

    def connect(self) -> bool:
        """Establish connection to Webots TCP server."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            self.socket.connect((self.host, self.port))
            self._connected = True
            self._connection_failures = 0
            self._last_error = None
            logger.info(f"Connected to Webots at {self.host}:{self.port}")
            return True
        except socket.timeout:
            msg = f"Connection timeout after {self.timeout}s - Webots may be paused or not responding"
            self._last_error = msg
            logger.error(f"Failed to connect to Webots: {msg}")
            self._connected = False
            self._connection_failures += 1
            return False
        except ConnectionRefusedError:
            msg = f"Connection refused on {self.host}:{self.port} - Is Webots running?"
            self._last_error = msg
            logger.error(f"Failed to connect to Webots: {msg}")
            self._connected = False
            self._connection_failures += 1
            return False
        except OSError as e:
            msg = f"OS error connecting to {self.host}:{self.port}: {e}"
            self._last_error = msg
            logger.error(f"Failed to connect to Webots: {msg}")
            self._connected = False
            self._connection_failures += 1
            return False

    def disconnect(self) -> None:
        """Close connection to Webots."""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
            self._connected = False

    def _recv_json_line(self) -> Dict[str, Any]:
        """Receive one newline-terminated JSON response from Webots.
        
        Note: Responses can be large (327KB+) due to base64-encoded camera images.
        We need to read until we have a complete, valid JSON object.
        """
        if self.socket is None:
            raise ConnectionError("Socket is not connected")

        chunks = []
        timeout_msg = f"No response from Webots after {self.timeout}s - simulator may be paused"
        
        try:
            while True:
                chunk = self.socket.recv(65536)  # Increased from 4096 to handle large responses
                if not chunk:
                    raise ConnectionError("Webots closed the TCP connection")
                chunks.append(chunk)
                
                # Try to decode and parse what we have so far
                try:
                    data = b"".join(chunks).decode("utf-8")
                    if "\n" in data:
                        line = data.split("\n", 1)[0].strip()
                        if not line:
                            raise ConnectionError("Webots returned an empty response")
                        # Try to parse - this will only succeed if JSON is complete
                        response = json.loads(line)
                        return response
                except json.JSONDecodeError:
                    # JSON not complete yet, keep reading
                    pass
                except UnicodeDecodeError:
                    # Partial UTF-8 sequence, keep reading
                    pass
                    
        except socket.timeout:
            raise ConnectionError(timeout_msg)

    def send_command(self, cmd: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send a command to Webots and receive response."""
        with self._lock:
            last_error: Optional[Exception] = None

            for attempt in range(2):
                if not self._connected:
                    logger.warning(f"Not connected to Webots. Attempting reconnect (attempt {attempt + 1}/2)...")
                    if not self.connect():
                        if self._last_error:
                            return {"status": "error", "message": self._last_error}
                        return {"status": "error", "message": "Failed to connect to Webots"}

                try:
                    cmd_json = json.dumps(cmd) + "\n"
                    assert self.socket is not None
                    self.socket.sendall(cmd_json.encode("utf-8"))
                    response = self._recv_json_line()
                    logger.debug(f"Webots response: {response}")
                    return response

                except (socket.timeout, ConnectionError, OSError, json.JSONDecodeError) as e:
                    last_error = e
                    logger.warning(f"Command failed on attempt {attempt + 1}/2: {e}")
                    self.disconnect()

            message = str(last_error) if last_error else "Unknown TCP error"
            logger.error(f"Command failed after retry: {message}")
            return {"status": "error", "message": message}

    def get_state(self, include_camera: bool = False) -> Optional[Dict[str, Any]]:
        """Fetch current robot state from Webots.
        
        Args:
            include_camera: Whether to include base64-encoded camera image.
                           Default False to keep response small (~2KB vs 327KB).
                           Set True only when camera feed is specifically needed.
        """
        return self.send_command({"cmd": "get_state", "include_camera": include_camera})

    def execute_action(self, action: Action) -> Optional[Dict[str, Any]]:
        """Execute an action on the robot."""
        action_dict = {
            "type": action.type.value if isinstance(action.type, ActionType) else action.type,
            "params": action.params
        }
        return self.send_command({"cmd": "execute", "action": action_dict})

    def stop_robot(self) -> Optional[Dict[str, Any]]:
        """Emergency stop."""
        return self.send_command({"cmd": "stop"})

    def get_objects(self) -> Optional[Dict[str, Any]]:
        """Get list of objects in the world."""
        # TODO: Implement object detection from Webots world
        return {"objects": [], "note": "Object detection not yet implemented"}


# Global bridge instance
_bridge: Optional[WebotsBridge] = None


def get_bridge() -> WebotsBridge:
    """Get or create the Webots bridge singleton."""
    global _bridge
    if _bridge is None:
        _bridge = WebotsBridge()
        _bridge.connect()
    return _bridge


# ============================================================================
# Tool Functions - These are called by the agent via MCP
# ============================================================================

def tool_get_state(include_camera: bool = True) -> Dict[str, Any]:
    """
    MCP Tool: Get current robot state.

    Args:
        include_camera: Whether to include camera image (default True for UI/perception)

    Returns:
        Robot state including position, orientation, and sensor readings.
    """
    bridge = get_bridge()
    state = bridge.get_state(include_camera=include_camera)

    if state and state.get("status") != "error":
        return {
            "success": True,
            "state": state,
            "message": "Robot state retrieved successfully"
        }
    else:
        return {
            "success": False,
            "state": None,
            "message": state.get("message", "Failed to get robot state") if state else "Connection error"
        }


def tool_execute_action(action_type: str, velocity: Optional[float] = None,
                        angular_velocity: Optional[float] = None,
                        duration: Optional[float] = None) -> Dict[str, Any]:
    """
    MCP Tool: Execute an action on the robot.

    Args:
        action_type: Type of action ('move', 'turn', 'stop', 'grab')
        velocity: Linear velocity (m/s) for move actions
        angular_velocity: Rotational velocity (rad/s) for turn actions
        duration: Duration of action (not yet used)

    Returns:
        Execution result with status and feedback.
    """
    bridge = get_bridge()

    # Build action
    params = {}
    if velocity is not None:
        params["velocity"] = velocity
    if angular_velocity is not None:
        params["angular_velocity"] = angular_velocity
    if duration is not None:
        params["duration"] = duration

    try:
        action = Action(
            type=ActionType(action_type) if isinstance(action_type, str) else action_type,
            params=params,
            reasoning="Executed via agent"
        )
    except ValueError as e:
        return {
            "success": False,
            "message": f"Invalid action type: {action_type}"
        }

    # Execute action
    result = bridge.execute_action(action)

    if result and result.get("status") == "ok":
        return {
            "success": True,
            "action": action_type,
            "message": "Action executed successfully",
            "feedback": result
        }
    else:
        return {
            "success": False,
            "action": action_type,
            "message": result.get("message", "Action execution failed") if result else "Connection error"
        }


def tool_stop() -> Dict[str, Any]:
    """
    MCP Tool: Emergency stop - stop all motors.

    Returns:
        Stop result.
    """
    bridge = get_bridge()
    result = bridge.stop_robot()

    if result and result.get("status") == "ok":
        return {
            "success": True,
            "message": "Robot stopped successfully"
        }
    else:
        return {
            "success": False,
            "message": result.get("message", "Stop failed") if result else "Connection error"
        }


def tool_get_objects() -> Dict[str, Any]:
    """
    MCP Tool: Get list of objects in the world.

    Returns:
        List of objects with positions.
    """
    bridge = get_bridge()
    result = bridge.get_objects()

    return {
        "success": True,
        "objects": result.get("objects", []),
        "message": result.get("note", "")
    }


def tool_validate_action(action_type: str, **params) -> Dict[str, Any]:
    """
    MCP Tool: Validate an action without executing it.

    Args:
        action_type: Type of action to validate
        **params: Action parameters

    Returns:
        Validation result.
    """
    valid_actions = ["move", "turn", "stop", "grab"]

    if action_type not in valid_actions:
        return {
            "valid": False,
            "message": f"Invalid action type. Must be one of: {', '.join(valid_actions)}"
        }

    # Validate parameters based on action type
    if action_type == "move":
        if "velocity" in params and (not isinstance(params["velocity"], (int, float))):
            return {"valid": False, "message": "velocity must be a number"}

    elif action_type == "turn":
        if "angular_velocity" in params and (not isinstance(params["angular_velocity"], (int, float))):
            return {"valid": False, "message": "angular_velocity must be a number"}

    return {
        "valid": True,
        "message": f"Action '{action_type}' is valid"
    }


# ============================================================================
# MCP Tool Registry
# ============================================================================

MCP_TOOLS = {
    "get_state": {
        "function": tool_get_state,
        "description": "Get current robot state: position, orientation, sensor readings, optionally camera",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_camera": {
                    "type": "boolean",
                    "description": "Include camera image in response (default True)",
                    "default": True
                }
            },
            "required": []
        }
    },
    "execute_action": {
        "function": tool_execute_action,
        "description": "Execute a robot action: move, turn, stop, or grab",
        "input_schema": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": ["move", "turn", "stop", "grab"],
                    "description": "Type of action to execute"
                },
                "velocity": {
                    "type": "number",
                    "description": "Linear velocity in m/s (for move)"
                },
                "angular_velocity": {
                    "type": "number",
                    "description": "Rotational velocity in rad/s (for turn)"
                },
                "duration": {
                    "type": "number",
                    "description": "Duration of action in seconds"
                }
            },
            "required": ["action_type"]
        }
    },
    "stop": {
        "function": tool_stop,
        "description": "Emergency stop - stop all robot motors immediately",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    "get_objects": {
        "function": tool_get_objects,
        "description": "Get list of objects in the world and their positions",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    "validate_action": {
        "function": tool_validate_action,
        "description": "Validate an action without executing it",
        "input_schema": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "description": "Action type to validate"
                }
            },
            "required": ["action_type"]
        }
    }
}


def list_tools() -> list[Dict[str, Any]]:
    """Return list of available MCP tools."""
    return [
        {
            "name": name,
            "description": tool["description"],
            "input_schema": tool["input_schema"]
        }
        for name, tool in MCP_TOOLS.items()
    ]


def call_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Call an MCP tool by name with given arguments."""
    if name not in MCP_TOOLS:
        return {"error": f"Unknown tool: {name}"}

    tool_info = MCP_TOOLS[name]
    try:
        result = tool_info["function"](**arguments)
        return result
    except TypeError as e:
        return {"error": f"Invalid arguments for tool '{name}': {e}"}
    except Exception as e:
        logger.error(f"Tool error: {e}")
        return {"error": f"Tool execution failed: {e}"}


# ============================================================================
# CLI / Testing
# ============================================================================

def main():
    """Test the MCP server."""
    logger.info("Starting MCP Server tests...")

    # Test listing tools
    tools = list_tools()
    logger.info(f"Available tools: {[t['name'] for t in tools]}")

    # Test connecting to Webots
    bridge = get_bridge()
    if not bridge._connected:
        logger.error("Could not connect to Webots. Make sure the simulator is running.")
        return

    # Test get_state
    logger.info("\nTesting get_state...")
    result = call_tool("get_state", {})
    logger.info(f"get_state result: {result}")

    # Test execute_action
    logger.info("\nTesting execute_action...")
    result = call_tool("execute_action", {
        "action_type": "move",
        "velocity": 1.0
    })
    logger.info(f"execute_action result: {result}")

    # Test validate_action
    logger.info("\nTesting validate_action...")
    result = call_tool("validate_action", {
        "action_type": "move",
        "velocity": 1.0
    })
    logger.info(f"validate_action result: {result}")

    # Stop robot
    logger.info("\nStopping robot...")
    result = call_tool("stop", {})
    logger.info(f"stop result: {result}")


if __name__ == "__main__":
    main()
