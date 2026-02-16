"""Error recovery strategies for self-healing automation.

When an action fails, the recovery system attempts alternative approaches:
1. Retry with same parameters (transient failures)
2. Re-locate element with vision and retry (UI shifted)
3. Try alternative actions (scroll into view, wait for load, dismiss dialogs)
4. Escalate to LLM for creative recovery
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RecoveryStrategy(str, Enum):
    """Available recovery strategies."""

    RETRY = "retry"
    RELOCATE = "relocate"
    SCROLL_AND_RETRY = "scroll_and_retry"
    WAIT_AND_RETRY = "wait_and_retry"
    DISMISS_DIALOG = "dismiss_dialog"
    LLM_RECOVERY = "llm_recovery"
    SKIP = "skip"
    ABORT = "abort"


@dataclass
class RecoveryAttempt:
    """Record of a recovery attempt."""

    strategy: RecoveryStrategy
    success: bool
    duration: float = 0.0
    details: str = ""


@dataclass
class RecoveryConfig:
    """Configuration for recovery behavior."""

    max_retries: int = 3
    retry_delay: float = 0.5
    wait_timeout: float = 10.0
    scroll_attempts: int = 3
    enable_llm_recovery: bool = True
    strategies: list[RecoveryStrategy] = field(
        default_factory=lambda: [
            RecoveryStrategy.RETRY,
            RecoveryStrategy.WAIT_AND_RETRY,
            RecoveryStrategy.RELOCATE,
            RecoveryStrategy.SCROLL_AND_RETRY,
            RecoveryStrategy.DISMISS_DIALOG,
            RecoveryStrategy.LLM_RECOVERY,
        ]
    )


@dataclass
class FailureContext:
    """Context about a failed action for recovery analysis."""

    action_type: str
    target: str | None
    error: str
    screenshot_before: Any = None
    screenshot_after: Any = None
    attempt_number: int = 0
    history: list[dict] = field(default_factory=list)


class RecoveryManager:
    """Manages error recovery with escalating strategies.

    Cycles through recovery strategies from least to most expensive:
    simple retry → wait → relocate → scroll → dismiss → LLM recovery
    """

    def __init__(self, config: RecoveryConfig | None = None):
        self.config = config or RecoveryConfig()
        self._attempts: list[RecoveryAttempt] = []
        self._failure_patterns: dict[str, int] = {}

    def suggest_recovery(self, context: FailureContext) -> RecoveryStrategy:
        """Suggest the best recovery strategy based on failure context."""
        error = context.error.lower()
        attempt = context.attempt_number

        # Track failure patterns
        pattern_key = f"{context.action_type}:{context.target or 'none'}"
        self._failure_patterns[pattern_key] = self._failure_patterns.get(pattern_key, 0) + 1
        pattern_count = self._failure_patterns[pattern_key]

        # Too many failures on the same action → abort
        if pattern_count > self.config.max_retries * 2:
            return RecoveryStrategy.ABORT

        # Error-specific recovery
        if "not found" in error or "element" in error:
            if attempt == 0:
                return RecoveryStrategy.WAIT_AND_RETRY
            if attempt == 1:
                return RecoveryStrategy.RELOCATE
            if attempt == 2:
                return RecoveryStrategy.SCROLL_AND_RETRY
            return RecoveryStrategy.LLM_RECOVERY

        if "timeout" in error:
            if attempt < 2:
                return RecoveryStrategy.WAIT_AND_RETRY
            return RecoveryStrategy.LLM_RECOVERY

        if "dialog" in error or "popup" in error or "modal" in error:
            return RecoveryStrategy.DISMISS_DIALOG

        if "coordinate" in error or "click" in error:
            if attempt == 0:
                return RecoveryStrategy.RELOCATE
            return RecoveryStrategy.SCROLL_AND_RETRY

        # Default escalation: retry → wait → relocate → LLM
        strategies = self.config.strategies
        idx = min(attempt, len(strategies) - 1)
        return strategies[idx]

    def get_retry_actions(self, strategy: RecoveryStrategy, context: FailureContext) -> list[dict]:
        """Generate recovery action sequence for a strategy."""
        actions = []

        if strategy == RecoveryStrategy.RETRY:
            actions.append({"type": "wait", "duration": self.config.retry_delay})
            actions.append({"type": "retry_original"})

        elif strategy == RecoveryStrategy.WAIT_AND_RETRY:
            actions.append({"type": "wait", "duration": self.config.wait_timeout / 3})
            actions.append({"type": "retry_original"})

        elif strategy == RecoveryStrategy.RELOCATE:
            actions.append({"type": "screenshot"})
            actions.append({"type": "find_element", "target": context.target})
            actions.append({"type": "retry_with_new_coords"})

        elif strategy == RecoveryStrategy.SCROLL_AND_RETRY:
            for direction in ["down", "up"]:
                actions.append({"type": "scroll", "direction": direction, "amount": 3})
                actions.append({"type": "wait", "duration": 0.5})
                actions.append({"type": "screenshot"})
                actions.append({"type": "find_element", "target": context.target})
                actions.append({"type": "retry_if_found"})

        elif strategy == RecoveryStrategy.DISMISS_DIALOG:
            actions.append({"type": "key", "keys": "escape"})
            actions.append({"type": "wait", "duration": 0.5})
            actions.append({"type": "retry_original"})

        elif strategy == RecoveryStrategy.LLM_RECOVERY:
            actions.append({"type": "screenshot"})
            actions.append({"type": "llm_analyze_failure", "context": context})

        return actions

    def record_attempt(
        self, strategy: RecoveryStrategy, success: bool, duration: float = 0.0, details: str = ""
    ) -> None:
        """Record a recovery attempt for analytics."""
        self._attempts.append(
            RecoveryAttempt(
                strategy=strategy,
                success=success,
                duration=duration,
                details=details,
            )
        )

    def clear_pattern(self, action_type: str, target: str | None = None) -> None:
        """Clear failure pattern tracking (e.g., after successful action)."""
        pattern_key = f"{action_type}:{target or 'none'}"
        self._failure_patterns.pop(pattern_key, None)

    @property
    def attempts(self) -> list[RecoveryAttempt]:
        return list(self._attempts)

    @property
    def success_rate(self) -> float:
        """Recovery success rate."""
        if not self._attempts:
            return 0.0
        successful = sum(1 for a in self._attempts if a.success)
        return successful / len(self._attempts)

    @property
    def stats(self) -> dict[str, Any]:
        """Get recovery statistics."""
        by_strategy: dict[str, dict] = {}
        for attempt in self._attempts:
            name = attempt.strategy.value
            if name not in by_strategy:
                by_strategy[name] = {"total": 0, "success": 0}
            by_strategy[name]["total"] += 1
            if attempt.success:
                by_strategy[name]["success"] += 1

        return {
            "total_attempts": len(self._attempts),
            "success_rate": self.success_rate,
            "by_strategy": by_strategy,
            "failure_patterns": dict(self._failure_patterns),
        }
