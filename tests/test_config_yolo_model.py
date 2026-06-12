from src.common.config import _normalize_yolo_model_name


def test_yolo_model_default_uses_yolo11m() -> None:
    assert _normalize_yolo_model_name("") == "yolo11m"


def test_yolo_model_keeps_explicit_choice() -> None:
    assert _normalize_yolo_model_name("yolo11m") == "yolo11m"
