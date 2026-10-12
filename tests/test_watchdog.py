"""Tests for the auto-off :class:`Watchdog`.

A fake timer factory records its constructor args and lets the test fire or
cancel on demand, so there are no real wall-clock sleeps.
"""

from __future__ import annotations

from farm_agent.safety import Watchdog


class FakeTimer:
    """Records (delay, callback); fires/cancels only when the test says so."""

    def __init__(self, delay: float, callback) -> None:
        self.delay = delay
        self.callback = callback
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        self.callback()


def _factory():
    """Return a timer_factory plus the list of timers it creates."""
    created: list[FakeTimer] = []

    def factory(delay, callback):
        timer = FakeTimer(delay, callback)
        created.append(timer)
        return timer

    return factory, created


def test_schedule_starts_timer_with_right_delay_and_callback_fires() -> None:
    factory, created = _factory()
    wd = Watchdog(timer_factory=factory)

    fired: list[str] = []
    wd.schedule("pump_1", 300, lambda: fired.append("off"))

    assert len(created) == 1
    assert created[0].delay == 300
    assert created[0].started is True

    created[0].fire()
    assert fired == ["off"]


def test_immediate_firing_factory() -> None:
    # A factory whose .start() fires the callback immediately.
    fired: list[str] = []

    class ImmediateTimer(FakeTimer):
        def start(self) -> None:
            super().start()
            self.callback()

    wd = Watchdog(timer_factory=ImmediateTimer)
    wd.schedule("pump_1", 5, lambda: fired.append("off"))
    assert fired == ["off"]


def test_scheduling_same_key_twice_cancels_first() -> None:
    factory, created = _factory()
    wd = Watchdog(timer_factory=factory)

    wd.schedule("pump_1", 100, lambda: None)
    wd.schedule("pump_1", 200, lambda: None)

    assert len(created) == 2
    assert created[0].cancelled is True
    assert created[1].cancelled is False
    assert created[1].delay == 200


def test_cancel_stops_pending_timer() -> None:
    factory, created = _factory()
    wd = Watchdog(timer_factory=factory)

    wd.schedule("pump_1", 100, lambda: None)
    wd.cancel("pump_1")
    assert created[0].cancelled is True

    # Cancelling an unknown key is a no-op.
    wd.cancel("nope")


def test_cancel_all_stops_every_timer() -> None:
    factory, created = _factory()
    wd = Watchdog(timer_factory=factory)

    wd.schedule("pump_1", 100, lambda: None)
    wd.schedule("valve_1", 200, lambda: None)
    wd.cancel_all()

    assert all(t.cancelled for t in created)
    # After cancel_all, keys are forgotten: rescheduling creates a fresh timer.
    wd.schedule("pump_1", 50, lambda: None)
    assert len(created) == 3


def test_default_timer_factory_is_threading_timer() -> None:
    import threading

    wd = Watchdog()
    assert wd._timer_factory is threading.Timer
