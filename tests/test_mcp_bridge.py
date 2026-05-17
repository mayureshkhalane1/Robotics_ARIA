"""Tests for WebotsBridge TCP robustness."""

from src.mcp_server.server import WebotsBridge


class FakeSocket:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = []
        self.closed = False

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, _size):
        if self.chunks:
            return self.chunks.pop(0)
        return b""

    def close(self):
        self.closed = True


class RetryBridge(WebotsBridge):
    def __init__(self, sockets):
        super().__init__(host="localhost", port=19997, timeout=1)
        self.sockets = list(sockets)
        self.connect_count = 0

    def connect(self) -> bool:
        self.connect_count += 1
        if not self.sockets:
            self._connected = False
            return False
        self.socket = self.sockets.pop(0)
        self._connected = True
        return True


def test_recv_json_line_handles_partial_response():
    sock = FakeSocket([b'{"status":', b' "ok"}\n'])
    bridge = WebotsBridge()
    bridge.socket = sock
    bridge._connected = True

    assert bridge._recv_json_line() == {"status": "ok"}


def test_send_command_retries_after_empty_response():
    first = FakeSocket([b""])
    second = FakeSocket([b'{"status":"ok","timestamp":1}\n'])
    bridge = RetryBridge([first, second])

    result = bridge.send_command({"cmd": "get_state"})

    assert result == {"status": "ok", "timestamp": 1}
    assert first.closed is True
    assert bridge.connect_count == 2
    assert len(first.sent) == 1
    assert len(second.sent) == 1
