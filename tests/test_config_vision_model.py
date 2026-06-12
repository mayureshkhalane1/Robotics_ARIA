from src.common.config import _normalize_vision_model_name


def test_vision_model_default_uses_fast_qwen3_vl_4b() -> None:
    assert _normalize_vision_model_name("") == "qwen3-vl:4b-instruct-q4_K_M"


def test_vision_model_aliases_map_to_fast_qwen3_vl_4b() -> None:
    assert _normalize_vision_model_name("qwen3vl:4b") == "qwen3-vl:4b-instruct-q4_K_M"
    assert _normalize_vision_model_name("qwen3-vl:4b") == "qwen3-vl:4b-instruct-q4_K_M"


def test_vision_model_keeps_explicit_llava_choice() -> None:
    assert _normalize_vision_model_name("llava-phi3:latest") == "llava-phi3:latest"
