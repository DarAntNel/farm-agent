"""Policy config: farming behaviour.

Policy is *what the farm should do*: the target range for each sensor, the rule
that maps a deviation to an actuator command, the per-actuator safety limits,
and which decision strategy to use. It is intentionally separate from wiring so
behaviour can change without touching hardware topology.

``FarmPolicy`` is a thin typed wrapper with lookup helpers used by the assess
and safety layers.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from farm_agent.config.defaults import DEFAULT_POLICY

# NOTE: ``safety.limits`` is imported lazily inside ``limits_for`` to avoid a
# circular import (the safety guard imports FarmPolicy from this module).


@dataclass(frozen=True)
class FarmPolicy:
    raw: dict[str, Any]

    @property
    def strategy(self) -> str:
        return self.raw.get("strategy", "local_rules")

    def target_for(self, sensor_id: str) -> Optional[tuple[float, float]]:
        t = self.raw.get("targets", {}).get(sensor_id)
        if not t:
            return None
        return float(t["low"]), float(t["high"])

    def rule_for(self, sensor_id: str, direction: str) -> Optional[dict[str, Any]]:
        return self.raw.get("rules", {}).get(sensor_id, {}).get(direction)

    def limits_for(self, actuator_id: str) -> "SafetyLimits":
        from farm_agent.safety.limits import DEFAULT_LIMITS, SafetyLimits

        data = self.raw.get("safety", {}).get(actuator_id)
        return SafetyLimits.from_dict(data) if data else DEFAULT_LIMITS


def load_policy(path: Optional[str] = None) -> FarmPolicy:
    """Load policy from ``path`` / ``$POLICY_CONFIG`` / defaults."""
    path = path or os.getenv("POLICY_CONFIG")
    if not path:
        return FarmPolicy(DEFAULT_POLICY)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    _validate_policy(data)
    return FarmPolicy(data)


def _validate_policy(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("Policy config must be a JSON object.")
    for sid, t in data.get("targets", {}).items():
        if "low" not in t or "high" not in t:
            raise ValueError(f"Target for {sid!r} needs 'low' and 'high'.")
        if float(t["low"]) > float(t["high"]):
            raise ValueError(f"Target for {sid!r} has low > high.")
