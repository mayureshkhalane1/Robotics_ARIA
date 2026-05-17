"""
Unit tests for Webots TCP connection.

These tests verify that the controller can:
1. Connect to the TCP server
2. Retrieve robot state
3. Execute actions
4. Handle errors gracefully

To run: python -m pytest tests/test_webots_connection.py -v
(Requires Webots simulator running with tcp_controller.py as active controller)
"""

import socket
import json
import time
import pytest


def get_webots_connection(host="localhost", port=19997, timeout=1.0):
    """Create a connection to Webots controller."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return s
    except (ConnectionRefusedError, socket.timeout) as e:
        pytest.skip(f"Webots not running on {host}:{port}")


def send_command(sock, cmd):
    """Send command and receive response."""
    sock.sendall((json.dumps(cmd) + "\n").encode('utf-8'))
    response = sock.recv(4096).decode('utf-8').strip()
    return json.loads(response)


def test_webots_tcp_connection():
    """Test basic TCP connection to Webots."""
    s = get_webots_connection()
    s.close()
    assert True  # Connection succeeded


def test_get_state():
    """Test retrieving robot state from Webots."""
    s = get_webots_connection()

    try:
        response = send_command(s, {"cmd": "get_state"})

        # Verify response structure
        assert "timestamp" in response
        assert "proximity" in response
        assert "wheel_velocities" in response

        # Verify proximity sensors are present
        assert isinstance(response["proximity"], dict)

        # Verify wheel velocities
        assert len(response["wheel_velocities"]) == 2

        print(f"Robot state: {response}")
    finally:
        s.close()


def test_execute_move():
    """Test executing a move action."""
    s = get_webots_connection()

    try:
        response = send_command(s, {
            "cmd": "execute",
            "action": {
                "type": "move",
                "params": {"velocity": 1.0}
            }
        })

        assert response["status"] == "ok"
        assert response["action"] == "move"

        # Verify state changed
        time.sleep(0.1)
        state = send_command(s, {"cmd": "get_state"})
        assert state["wheel_velocities"] == [1.0, 1.0]

    finally:
        s.close()


def test_execute_turn():
    """Test executing a turn action."""
    s = get_webots_connection()

    try:
        response = send_command(s, {
            "cmd": "execute",
            "action": {
                "type": "turn",
                "params": {"angular_velocity": 0.5}
            }
        })

        assert response["status"] == "ok"
        assert response["action"] == "turn"

    finally:
        s.close()


def test_execute_stop():
    """Test stopping the robot."""
    s = get_webots_connection()

    try:
        # First move
        send_command(s, {
            "cmd": "execute",
            "action": {"type": "move", "params": {"velocity": 1.0}}
        })

        # Then stop
        response = send_command(s, {"cmd": "stop"})
        assert response["status"] == "ok"

        # Verify motors stopped
        state = send_command(s, {"cmd": "get_state"})
        assert state["wheel_velocities"] == [0.0, 0.0]

    finally:
        s.close()


def test_invalid_action():
    """Test handling of invalid action type."""
    s = get_webots_connection()

    try:
        response = send_command(s, {
            "cmd": "execute",
            "action": {
                "type": "invalid_action",
                "params": {}
            }
        })

        assert response["status"] == "error"

    finally:
        s.close()


def test_invalid_command():
    """Test handling of invalid command."""
    s = get_webots_connection()

    try:
        response = send_command(s, {"cmd": "invalid_cmd"})
        assert response["status"] == "error"

    finally:
        s.close()


if __name__ == "__main__":
    print("Run with: python -m pytest tests/test_webots_connection.py -v")
    print("Note: Requires Webots simulator running with tcp_controller.py as controller")
