"""Tests for conservative VLM target acceptance."""

from types import SimpleNamespace

from src.agent.aria_agent import (
    _accept_vlm_target_claim,
    _build_yolo_vlm_prompt,
    _high_confidence_target_pursuit_response,
    _should_query_vlm_after_yolo,
    _should_retry_yolo_for_target,
    _target_close_enough,
    _target_reached_by_yolo,
    _yolo_low_confidence_pursuit_response,
    _vlm_text_only_hint_is_actionable,
    _should_sample_vlm,
    _vlm_hint_action,
    _vlm_text_mentions_target,
)


def test_vlm_claim_without_bbox_is_rejected():
    """A bare VLM sighting claim must not end the search."""
    assert not _accept_vlm_target_claim(
        target_found=True,
        target_visible_confidence=0.65,
        target_direction="center",
        target_bbox=None,
        frame_shape=(240, 320, 3),
    )


def test_vlm_text_mention_without_claim_is_rejected():
    """Scene text saying the target name is not enough for success."""
    assert not _accept_vlm_target_claim(
        target_found=False,
        target_visible_confidence=0.95,
        target_direction="center",
        target_bbox=[20, 30, 80, 120],
        frame_shape=(240, 320, 3),
    )


def test_vlm_claim_with_bbox_and_high_confidence_is_accepted():
    """A strong VLM claim with a valid box can confirm the target."""
    assert _accept_vlm_target_claim(
        target_found=True,
        target_visible_confidence=0.93,
        target_direction="left",
        target_bbox=[20, 30, 80, 120],
        frame_shape=(240, 320, 3),
    )


def test_vlm_normalized_bbox_is_rejected():
    """The VLM often returns 0..1 boxes; those are not actionable pixels."""
    assert not _accept_vlm_target_claim(
        target_found=True,
        target_visible_confidence=0.93,
        target_direction="right",
        target_bbox=[0.61, 0.54, 0.92, 0.73],
        frame_shape=(240, 320, 3),
    )


def test_vlm_qwen_1000_bbox_is_accepted_for_approach():
    """Qwen-style 0..1000 boxes should convert to image pixels."""
    assert _accept_vlm_target_claim(
        target_found=True,
        target_visible_confidence=0.58,
        target_direction="right",
        target_bbox=[469, 371, 521, 419],
        frame_shape=(240, 320, 3),
        min_confidence=0.50,
    )


def test_vlm_qwen_1000_bbox_is_accepted_for_find():
    """A grounded VLM box with moderate confidence should still stop on sight."""
    assert _accept_vlm_target_claim(
        target_found=True,
        target_visible_confidence=0.58,
        target_direction="center",
        target_bbox=[469, 371, 521, 419],
        frame_shape=(240, 320, 3),
    )


def test_vlm_mixed_coordinate_bbox_is_rejected():
    """Mixed x=1000-scale/y=0..1-scale boxes are not trustworthy."""
    assert not _accept_vlm_target_claim(
        target_found=True,
        target_visible_confidence=0.58,
        target_direction="right",
        target_bbox=[491, 0.62, 537, 0.67],
        frame_shape=(240, 320, 3),
        min_confidence=0.50,
    )


def test_approach_done_depends_on_visual_target_size_only():
    """A tiny or missing target box must not be treated as reached."""
    assert not _target_close_enough(0.0)
    assert not _target_close_enough(0.05)
    assert _target_close_enough(0.18)


def test_high_confidence_centered_yolo_target_stops_on_close_proximity():
    """A close centered YOLO target should stop before safety recovery turns away."""
    assert _target_reached_by_yolo(
        target_bbox_frac=0.08,
        target_err=0.10,
        confidence=0.80,
        scan_result={"front": 820.0},
    )


def test_side_yolo_target_does_not_stop_from_front_proximity():
    """Side boxes should still be centered before front proximity counts as reached."""
    assert not _target_reached_by_yolo(
        target_bbox_frac=0.08,
        target_err=0.62,
        confidence=0.80,
        scan_result={"front": 820.0},
    )


def test_low_confidence_yolo_target_does_not_stop_from_front_proximity():
    """The 1m stop rule still requires a trusted YOLO target."""
    assert not _target_reached_by_yolo(
        target_bbox_frac=0.08,
        target_err=0.10,
        confidence=0.42,
        scan_result={"front": 820.0},
    )


def test_high_confidence_side_target_moves_forward_instead_of_recovering():
    """A visible trusted target should be approached immediately, not centered forever."""
    action, reason, pursuing, scanning, done = _high_confidence_target_pursuit_response(
        target_reached=False,
        target_visual_close=False,
        confidence=0.80,
        target_side="left",
        guided_action="turn_left_45",
    )

    assert action == "move_forward"
    assert pursuing is True
    assert scanning is False
    assert done is False
    assert "approaching visible target" in reason


def test_high_confidence_reached_target_stops():
    """A trusted target that is already close enough should stop."""
    action, reason, pursuing, scanning, done = _high_confidence_target_pursuit_response(
        target_reached=True,
        target_visual_close=False,
        confidence=0.80,
        target_side="center",
        guided_action="move_forward",
    )

    assert action == "stop"
    assert pursuing is True
    assert scanning is False
    assert done is True
    assert "reached" in reason


def test_yolo_low_confidence_keeps_approaching_longer():
    """A weak target hit should keep closing in for a few more cycles."""
    action, reason, pursuing, scanning, streak = _yolo_low_confidence_pursuit_response(
        target_close=False,
        low_conf_streak=0,
    )
    assert action == "move_forward"
    assert pursuing is True
    assert scanning is False
    assert streak == 0
    assert "raise confidence" in reason

    action, reason, pursuing, scanning, streak = _yolo_low_confidence_pursuit_response(
        target_close=True,
        low_conf_streak=4,
    )
    assert action == "move_forward"
    assert pursuing is True
    assert scanning is False
    assert streak == 5
    assert "raise confidence" in reason


def test_vlm_text_target_hint_detects_bare_alias():
    """Text mentioning the target should trigger grounding, not success."""
    assert _vlm_text_mentions_target(
        "A room with a wooden floor. A soccer ball is on the ground near a door.",
        ["ball", "soccer ball", "sports ball"],
    )


def test_vlm_text_target_hint_ignores_other_scene_text():
    """Unrelated scene text should not trigger the fallback."""
    assert not _vlm_text_mentions_target(
        "A wooden table with a white wall in the background.",
        ["ball", "soccer ball", "sports ball"],
    )


def test_vlm_text_target_hint_ignores_statue_or_picture_mentions():
    """A statue/photo of the target is not the actual target."""
    assert not _vlm_text_mentions_target(
        "On the countertop, there is a silver statue of a soccer ball.",
        ["ball", "soccer ball", "sports ball"],
    )


def test_vlm_text_only_hint_is_never_actionable_without_claim():
    """A text-only VLM mention must not become pursuit."""
    assert not _vlm_text_only_hint_is_actionable(True, False)
    assert _vlm_text_only_hint_is_actionable(True, True)


def test_vlm_first_mode_samples_every_cycle(monkeypatch):
    """VLM-first should not wait 10s before the first grounded answer."""
    # The function gates on the module-global USE_LLM (False when ARIA_USE_LLM=0,
    # which is the shipped .env.example default). Force it on so this test
    # actually exercises the perception-mode branch instead of the LLM-off guard.
    monkeypatch.setattr("src.agent.aria_agent.USE_LLM", True)
    assert _should_sample_vlm(
        perception_mode="vlm_first",
        frame_present=True,
        step=2,
        last_llm_ts=0.0,
        cycle_start=100.0,
        backoff_until_step=0,
    )


def test_sensor_only_mode_never_samples_vlm():
    """Sensor-only mode must not call the VLM."""
    assert not _should_sample_vlm(
        perception_mode="sensor_only",
        frame_present=True,
        step=2,
        last_llm_ts=0.0,
        cycle_start=100.0,
        backoff_until_step=0,
    )


def test_hybrid_mode_still_obeys_interval():
    """Non-vlm-first modes keep the cadence throttle."""
    assert not _should_sample_vlm(
        perception_mode="hybrid",
        frame_present=True,
        step=2,
        last_llm_ts=99.5,
        cycle_start=100.0,
        backoff_until_step=0,
    )


def test_yolo_vlm_mode_samples_every_cycle(monkeypatch):
    """YOLO+VLM mode should ask for one grounded answer every cycle."""
    monkeypatch.setattr("src.agent.aria_agent.USE_LLM", True)
    assert _should_sample_vlm(
        perception_mode="yolo_vlm",
        frame_present=True,
        step=2,
        last_llm_ts=99.5,
        cycle_start=100.0,
        backoff_until_step=0,
    )
    assert _should_sample_vlm(
        perception_mode="yolo_vlm",
        frame_present=True,
        step=1,
        last_llm_ts=0.0,
        cycle_start=100.0,
        backoff_until_step=0,
    )


def test_yolo_vlm_waits_for_yolo_classes_before_vlm():
    """YOLO+VLM should skip the VLM when YOLO produced no classes for the frame."""
    assert not _should_query_vlm_after_yolo("yolo_vlm", [])
    assert _should_query_vlm_after_yolo(
        "yolo_vlm",
        [SimpleNamespace(class_name="umbrella", confidence=0.37)],
    )
    assert _should_query_vlm_after_yolo("vlm_first", [])


def test_yolo_target_retry_runs_when_target_alias_missing():
    """A target-aware second pass should be allowed when the first pass missed the target."""
    assert _should_retry_yolo_for_target([], {"plant", "potted plant"})
    assert _should_retry_yolo_for_target(
        [SimpleNamespace(class_name="umbrella", confidence=0.37)],
        {"plant", "potted plant"},
    )
    assert not _should_retry_yolo_for_target(
        [SimpleNamespace(class_name="plant", confidence=0.28)],
        {"plant", "potted plant"},
    )


def test_repeated_vlm_hint_turns_into_forward_probe():
    """Repeated ungrounded hints must not spin forever."""
    action, reason = _vlm_hint_action("right", repeat_count=0)
    assert action == "turn_right_45"
    assert "reorienting" in reason

    action, reason = _vlm_hint_action("right", repeat_count=1)
    assert action == "move_forward"
    assert "probing forward" in reason


def test_low_confidence_target_keeps_moving_until_close():
    """Weak YOLO hits should still drive forward when the target is far."""
    action, reason, pursuing, scanning, streak = _yolo_low_confidence_pursuit_response(
        target_close=False,
        low_conf_streak=0,
    )

    assert action == "move_forward"
    assert pursuing is True
    assert scanning is False
    assert streak == 0
    assert "closing in" in reason


def test_low_confidence_target_rescans_after_repeated_close_hits():
    """Weak YOLO hits near the target should rescan after repeated attempts."""
    action, reason, pursuing, scanning, streak = _yolo_low_confidence_pursuit_response(
        target_close=True,
        low_conf_streak=5,
    )

    assert action == "turn_around"
    assert pursuing is False
    assert scanning is True
    assert streak == 0
    assert "re-scan" in reason


def test_yolo_vlm_prompt_carries_yolo_ground_truth():
    """The VLM prompt should carry the short instruction and YOLO truth."""
    det = SimpleNamespace(
        class_name="sports ball",
        confidence=0.42,
        bbox=(40, 50, 120, 180),
        center=(80, 115),
    )

    system_prompt, user_prompt = _build_yolo_vlm_prompt(
        instruction="find the soccer ball",
        target="sports ball",
        target_det=det,
        frame_shape=(240, 320, 3),
        scan_result={"front": 46.0, "left": 836.0, "right": 842.0},
        approach_mode=True,
    )

    assert "YOLO confidence is ground truth" in system_prompt
    assert "Answer only whether the target is visible" in system_prompt
    assert "find the soccer ball" in user_prompt
    assert "sports ball" in user_prompt
    assert "0.42" in user_prompt
    assert "[40, 50, 120, 180]" in user_prompt
    assert "left" in user_prompt


def test_yolo_vlm_prompt_without_detection_stays_neutral():
    """A missed YOLO frame should not bias the VLM into parroting 'no target'."""
    system_prompt, user_prompt = _build_yolo_vlm_prompt(
        instruction="find the plant",
        target="plant",
        target_det=None,
        frame_shape=(240, 320, 3),
        scan_result={"front": 513.0, "left": 519.0, "right": 536.0},
        approach_mode=False,
    )

    assert "If YOLO has no candidate in this frame" in system_prompt
    assert "Do not say 'YOLO found no target'" in system_prompt
    assert "YOLO candidate in this frame: none" in user_prompt
    assert "YOLO bbox: null" in user_prompt
    assert "YOLO confidence: 0.00" in user_prompt
