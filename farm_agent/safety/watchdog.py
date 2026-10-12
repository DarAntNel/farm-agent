"""Guaranteed auto-off watchdog.

When an actuator turns on with a duration, the controller schedules a guaranteed
``off`` here so the system can never be left running indefinitely — even if the
decision layer crashes or a later cycle never comes. Each timer is keyed (one per
actuator), so rescheduling cancels the previous timer first. The timer
constructor is injected (``timer_factory``) so tests drive it deterministically
instead of waiting on real wall-clock time.
"""

from __future__ import annotations

import threading
from typing import Any, Callable


class Watchdog:
    """Schedule, reschedule, and cancel one-shot auto-off callbacks per key.

    ``timer_factory(delay_s, callback)`` must return a timer-like object exposing
    ``.start()`` and ``.cancel()`` — :class:`threading.Timer` by default.
    """

    def __init__(self, *, timer_factory: Callable[[float, Callable[[], None]], Any] = threading.Timer) -> None:
        self._timer_factory = timer_factory
        # key -> live timer-like object.
        self._timers: dict[str, Any] = {}

    def schedule(self, key: str, delay_s: float, callback: Callable[[], None]) -> None:
        """Start a timer for ``key`` that fires ``callback`` after ``delay_s``.

        Any existing timer for ``key`` is cancelled first so there is only ever
        one pending auto-off per actuator.
        """
        self.cancel(key)
        timer = self._timer_factory(delay_s, callback)
        # Real Timer threads must be daemons so a pending auto-off never keeps
        # the interpreter (a script, a test, or a shutting-down server) alive.
        # Injected fake timers in tests are left untouched.
        if isinstance(timer, threading.Thread):
            timer.daemon = True
        self._timers[key] = timer
        timer.start()

    def cancel(self, key: str) -> None:
        """Cancel and forget the pending timer for ``key`` (no-op if none)."""
        timer = self._timers.pop(key, None)
        if timer is not None:
            timer.cancel()

    def cancel_all(self) -> None:
        """Cancel every pending timer (e.g. on shutdown)."""
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()
