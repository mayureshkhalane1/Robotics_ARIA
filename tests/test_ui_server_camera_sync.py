from src.ui.server import _camera_event_is_fresh


def test_camera_event_is_fresh_with_recent_agent_frame() -> None:
    event = {"type": "camera", "captured_at": 100.0}
    assert _camera_event_is_fresh(event, now=100.5)


def test_camera_event_is_stale_when_too_old() -> None:
    event = {"type": "camera", "captured_at": 100.0}
    assert not _camera_event_is_fresh(event, now=103.5)


def test_camera_event_without_timestamp_is_not_fresh() -> None:
    assert not _camera_event_is_fresh({"type": "camera"}, now=100.0)


def test_camera_event_uses_wall_clock_capture_time() -> None:
    event = {"type": "camera", "captured_at": 500.0, "robot_timestamp": 10.0}
    assert _camera_event_is_fresh(event, now=500.2)
