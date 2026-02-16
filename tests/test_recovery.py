"""Tests for error recovery system."""

from screenpilot.recovery.strategy import (
    FailureContext,
    RecoveryConfig,
    RecoveryManager,
    RecoveryStrategy,
)


def test_suggest_retry_on_first_failure():
    manager = RecoveryManager()
    ctx = FailureContext(
        action_type="click",
        target="submit button",
        error="generic error",
        attempt_number=0,
    )
    strategy = manager.suggest_recovery(ctx)
    assert strategy == RecoveryStrategy.RETRY


def test_suggest_relocate_for_element_not_found():
    manager = RecoveryManager()
    ctx = FailureContext(
        action_type="click",
        target="submit button",
        error="element not found on screen",
        attempt_number=1,
    )
    strategy = manager.suggest_recovery(ctx)
    assert strategy == RecoveryStrategy.RELOCATE


def test_suggest_wait_for_timeout():
    manager = RecoveryManager()
    ctx = FailureContext(
        action_type="click",
        target="button",
        error="timeout waiting for element",
        attempt_number=0,
    )
    strategy = manager.suggest_recovery(ctx)
    assert strategy == RecoveryStrategy.WAIT_AND_RETRY


def test_suggest_dismiss_for_dialog():
    manager = RecoveryManager()
    ctx = FailureContext(
        action_type="click",
        target="submit",
        error="blocked by dialog popup",
        attempt_number=0,
    )
    strategy = manager.suggest_recovery(ctx)
    assert strategy == RecoveryStrategy.DISMISS_DIALOG


def test_abort_after_many_failures():
    manager = RecoveryManager(RecoveryConfig(max_retries=2))
    ctx = FailureContext(
        action_type="click",
        target="submit",
        error="element not found",
        attempt_number=0,
    )
    # Simulate many failures on same action
    for _ in range(10):
        manager.suggest_recovery(ctx)
    strategy = manager.suggest_recovery(ctx)
    assert strategy == RecoveryStrategy.ABORT


def test_get_retry_actions():
    manager = RecoveryManager()
    ctx = FailureContext(action_type="click", target="btn", error="fail")
    actions = manager.get_retry_actions(RecoveryStrategy.RETRY, ctx)
    assert len(actions) == 2
    assert actions[0]["type"] == "wait"
    assert actions[1]["type"] == "retry_original"


def test_get_scroll_retry_actions():
    manager = RecoveryManager()
    ctx = FailureContext(action_type="click", target="btn", error="fail")
    actions = manager.get_retry_actions(RecoveryStrategy.SCROLL_AND_RETRY, ctx)
    assert any(a["type"] == "scroll" for a in actions)


def test_get_dismiss_dialog_actions():
    manager = RecoveryManager()
    ctx = FailureContext(action_type="click", target="btn", error="fail")
    actions = manager.get_retry_actions(RecoveryStrategy.DISMISS_DIALOG, ctx)
    assert any(a["type"] == "key" for a in actions)


def test_record_and_stats():
    manager = RecoveryManager()
    manager.record_attempt(RecoveryStrategy.RETRY, success=True, duration=0.5)
    manager.record_attempt(RecoveryStrategy.RETRY, success=False, duration=0.3)
    manager.record_attempt(RecoveryStrategy.RELOCATE, success=True, duration=1.0)

    assert len(manager.attempts) == 3
    assert abs(manager.success_rate - 2 / 3) < 0.01

    stats = manager.stats
    assert stats["total_attempts"] == 3
    assert stats["by_strategy"]["retry"]["total"] == 2
    assert stats["by_strategy"]["retry"]["success"] == 1


def test_clear_pattern():
    manager = RecoveryManager()
    ctx = FailureContext(action_type="click", target="btn", error="fail", attempt_number=0)
    manager.suggest_recovery(ctx)
    assert manager._failure_patterns.get("click:btn", 0) > 0

    manager.clear_pattern("click", "btn")
    assert manager._failure_patterns.get("click:btn", 0) == 0


def test_escalation_order():
    """Test that recovery escalates through strategies."""
    manager = RecoveryManager()
    strategies = []
    for attempt in range(4):
        ctx = FailureContext(
            action_type="type",
            target="input",
            error="element not found",
            attempt_number=attempt,
        )
        strategies.append(manager.suggest_recovery(ctx))

    # Should escalate: wait → relocate → scroll → LLM
    assert strategies[0] == RecoveryStrategy.WAIT_AND_RETRY
    assert strategies[1] == RecoveryStrategy.RELOCATE
    assert strategies[2] == RecoveryStrategy.SCROLL_AND_RETRY
    assert strategies[3] == RecoveryStrategy.LLM_RECOVERY
