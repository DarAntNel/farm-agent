"""Safety spine: the deterministic layer that guards hardware.

Re-exports the public safety surface so callers can simply do
``from farm_agent.safety import SafetyGuard, Watchdog, SafetyLimits``.
"""

from __future__ import annotations

from farm_agent.safety.guard import SafetyGuard
from farm_agent.safety.limits import DEFAULT_LIMITS, SafetyLimits
from farm_agent.safety.watchdog import Watchdog

__all__ = ["SafetyGuard", "Watchdog", "SafetyLimits", "DEFAULT_LIMITS"]
