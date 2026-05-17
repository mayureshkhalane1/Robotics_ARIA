"""Tests for the baseline ARIA agent policy."""

from src.agent.graph import run_reactive_agent
from src.agent.nodes import choose_reactive_action, robot_state_from_response
from src.common.types import ActionType, RobotState


def make_state(front_value: float) -> RobotState:
    return RobotState(
        position=(0.0, 0.0, 0.0),
        orientation=(0.0, 0.0, 0.0),
        proximity_sensors={
            "distance_0": front_value,
            "distance_1": front_value,
            "distance_2": front_value,
        },
        wheel_velocities=(0.0, 0.0),
    )


def test_reactive_policy_moves_when_clear():
    action = choose_reactive_action(make_state(10.0), obstacle_threshold=800.0)
    assert action.type == ActionType.MOVE
    assert action.params["velocity"] > 0


def test_reactive_policy_turns_when_obstacle_close():
    action = choose_reactive_action(make_state(1000.0), obstacle_threshold=800.0)
    assert action.type == ActionType.TURN
    assert action.params["angular_velocity"] > 0


def test_robot_state_from_webots_response():
    state = robot_state_from_response(
        {
            "timestamp": 1.5,
            "position": [1.0, 2.0, 3.0],
            "orientation": [0.0, 1.0, 0.0],
            "proximity": {"distance_0": "12.5"},
            "wheel_velocities": [0.2, 0.3],
        }
    )
    assert state.position == (1.0, 2.0, 3.0)
    assert state.proximity_sensors["distance_0"] == 12.5
    assert state.wheel_velocities == (0.2, 0.3)


def test_reactive_agent_loop_with_fake_tools():
    actions = []

    def fake_get_state():
        return {
            "success": True,
            "state": {
                "timestamp": 1.0,
                "position": [0.0, 0.0, 0.0],
                "orientation": [0.0, 0.0, 0.0],
                "proximity": {"distance_0": 1.0, "distance_1": 1.0, "distance_2": 1.0},
                "wheel_velocities": [0.0, 0.0],
            },
        }

    def fake_execute_action(**kwargs):
        actions.append(kwargs)
        return {"success": True}

    final_state = run_reactive_agent(
        goal="test",
        max_steps=3,
        sleep_seconds=0,
        get_state=fake_get_state,
        execute_action=fake_execute_action,
    )

    assert final_state.success is True
    assert final_state.step_count == 3
    assert len(actions) == 3
    assert all(action["action_type"] == "move" for action in actions)
