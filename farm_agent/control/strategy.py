"""Decision strategies: how deviations become proposed commands.

A :class:`DecisionStrategy` proposes commands; it has NO authority to act — the
safety guard still vets everything. This is the seam where the LLM agent plugs
in later: swap ``LocalRulesStrategy`` for ``LlmStrategy`` via policy config
(Open/Closed — no other code changes).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from farm_agent.config.policy import FarmPolicy
from farm_agent.models import Command, Deviation, Event, Reading


class DecisionStrategy(ABC):
    """Proposes actuator commands from the current situation."""

    name: str = "strategy"

    @abstractmethod
    def decide(
        self,
        readings: list[Reading],
        deviations: list[Deviation],
        history: list[Event],
    ) -> list[Command]:
        raise NotImplementedError


class LocalRulesStrategy(DecisionStrategy):
    """Deterministic threshold rules from policy config.

    This is the always-available, offline fallback: for each deviation it looks
    up ``policy.rule_for(sensor_id, direction)`` and emits the command it names.
    """

    name = "local_rules"

    def __init__(self, policy: FarmPolicy) -> None:
        self._policy = policy

    def decide(
        self,
        readings: list[Reading],
        deviations: list[Deviation],
        history: list[Event],
    ) -> list[Command]:
        commands: list[Command] = []
        for dev in deviations:
            rule = self._policy.rule_for(dev.sensor_id, dev.direction)
            if not rule:
                continue
            commands.append(
                Command(
                    actuator_id=rule["actuator_id"],
                    action=rule.get("action", "on"),
                    duration_s=rule.get("duration_s"),
                    params=rule.get("params", {}),
                    source="local_rules",
                )
            )
        return commands


class LlmStrategy(DecisionStrategy):
    """Placeholder for the future LLM/agent decision maker.

    Implements the interface so the rest of the system can already depend on it,
    but does not yet call any model — it proposes no commands. The real version
    (a later sub-project) will assemble ``readings + policy + recent history``
    into a prompt, call the Claude API, and return schema-validated commands,
    all still subject to the safety guard.
    """

    name = "llm"

    #: Set True once the real integration lands.
    wired = False

    def __init__(self, policy: FarmPolicy) -> None:
        self._policy = policy

    def decide(
        self,
        readings: list[Reading],
        deviations: list[Deviation],
        history: list[Event],
    ) -> list[Command]:
        # Not yet wired: propose nothing. The control cycle records a note.
        return []


_STRATEGIES: dict[str, type[DecisionStrategy]] = {
    LocalRulesStrategy.name: LocalRulesStrategy,
    LlmStrategy.name: LlmStrategy,
}


def build_strategy(policy: FarmPolicy) -> DecisionStrategy:
    """Instantiate the strategy named by ``policy.strategy``."""
    key = policy.strategy
    try:
        cls = _STRATEGIES[key]
    except KeyError:
        available = ", ".join(sorted(_STRATEGIES))
        raise ValueError(
            f"Unknown decision strategy {key!r}. Available: {available}."
        ) from None
    return cls(policy)
