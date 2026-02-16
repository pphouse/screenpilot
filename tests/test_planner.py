"""Tests for the planner module."""

from screenpilot.planner.planner import Action, ActionType, Plan


def test_action_types():
    assert ActionType.CLICK == "click"
    assert ActionType.TYPE == "type"
    assert ActionType.DONE == "done"
    assert ActionType.FIND_AND_CLICK == "find_and_click"


def test_action_to_dict():
    action = Action(
        action_type=ActionType.CLICK,
        x=100,
        y=200,
        reasoning="Click the button",
    )
    d = action.to_dict()
    assert d["action_type"] == ActionType.CLICK
    assert d["x"] == 100
    assert d["y"] == 200
    assert "target" not in d  # None values excluded


def test_plan_navigation():
    plan = Plan(
        goal="test",
        actions=[
            Action(action_type=ActionType.CLICK, x=10, y=20),
            Action(action_type=ActionType.TYPE, text="hello"),
            Action(action_type=ActionType.DONE),
        ],
    )

    assert not plan.is_complete
    assert plan.next_action.action_type == ActionType.CLICK

    plan.advance()
    assert plan.current_step == 1
    assert plan.next_action.action_type == ActionType.TYPE

    plan.advance()
    plan.advance()
    assert plan.is_complete
    assert plan.next_action is None


def test_action_with_metadata():
    action = Action(
        action_type=ActionType.DRAG,
        x=100,
        y=100,
        metadata={"end_x": 300, "end_y": 300},
    )
    assert action.metadata["end_x"] == 300
