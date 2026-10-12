# Watchdog

A guaranteed auto-off timer that makes sure an actuator can never be left running indefinitely.

## What it does

When an actuator turns **on with a duration**, something must guarantee it turns **off** later — even if the decision layer crashes, the process is busy, or the next control cycle never comes. The `Watchdog` is that safety net. It schedules a one-shot timer that fires an `off` callback after the duration elapses.

Key behaviours:

- **One timer per actuator, keyed by id.** Scheduling a new timer for a key that already has one cancels the old timer first (`schedule` calls `cancel(key)` internally), so there is only ever one pending auto-off per actuator.
- **`schedule(key, delay_s, callback)`** — start a timer for `key` that calls `callback` after `delay_s` seconds.
- **`cancel(key)`** — cancel and forget the pending timer for `key` (a no-op if there is none).
- **`cancel_all()`** — cancel every pending timer; used on shutdown and during `safe_init`.
- **Daemon timers.** When the timer is a real `threading.Timer` (a `threading.Thread`), the watchdog sets `timer.daemon = True` so a pending auto-off never keeps the interpreter alive — a script, a test, or a shutting-down server can exit cleanly. Injected fake timers in tests are left untouched.
- **Injectable timer factory.** The constructor takes `timer_factory(delay_s, callback)`, defaulting to `threading.Timer`. Tests pass a fake factory so they can fire timers synchronously instead of waiting on real wall-clock time.

The watchdog does not know anything about actuators or safety limits — it only starts and cancels timers. The `ActuatorController` wires it to the actual `safe_off` action (see [controller.md](controller.md)). This separation keeps the watchdog tiny and fully testable.

## How to use it

You normally let the `ActuatorController` drive the watchdog. The steps below show what it does.

1. Construct a `Watchdog` (optionally with a `timer_factory` for tests).
2. When an actuator goes on with a duration, call `schedule(actuator_id, duration_s, off_callback)`.
3. If the actuator is turned off early, call `cancel(actuator_id)` so the stale timer does not fire later.
4. On shutdown, call `cancel_all()`.

```python
from farm_agent.safety.watchdog import Watchdog

watchdog = Watchdog()   # uses threading.Timer by default

def turn_pump_off():
    print("auto-off: pump_1")

# Pump just turned on for 180s; guarantee it stops.
watchdog.schedule("pump_1", 180.0, turn_pump_off)

# If the pump is turned off manually before 180s elapses:
watchdog.cancel("pump_1")

# On shutdown:
watchdog.cancel_all()
```

## What it depends on

- `threading` (standard library) — `threading.Timer` is the default timer factory, and the daemon check uses `threading.Thread`.
- An injected `timer_factory: Callable[[float, Callable[[], None]], Any]` returning an object with `.start()` and `.cancel()`. Default is `threading.Timer`; tests supply a fake.
- Nothing else — no models, no actuators, no config. The callback supplied by the caller does the real work.

## Example

A test-style example using a fake timer that records scheduling and can be fired on demand — no real waiting:

```python
from farm_agent.safety.watchdog import Watchdog

class FakeTimer:
    def __init__(self, delay, callback):
        self.delay, self.callback, self.started, self.cancelled = delay, callback, False, False
    def start(self):  self.started = True
    def cancel(self): self.cancelled = True
    def fire(self):   self.callback()   # test triggers the auto-off manually

created = []
def factory(delay, callback):
    t = FakeTimer(delay, callback)
    created.append(t)
    return t

watchdog = Watchdog(timer_factory=factory)

fired = []
watchdog.schedule("pump_1", 180.0, lambda: fired.append("off"))
assert created[-1].started            # timer was started

# Rescheduling cancels the previous timer for the same key:
watchdog.schedule("pump_1", 60.0, lambda: fired.append("off2"))
assert created[0].cancelled

# Simulate the duration elapsing:
created[-1].fire()
assert fired == ["off2"]
```

## Where it lives

- `farm_agent/safety/watchdog.py` — the `Watchdog` class (`schedule`, `cancel`, `cancel_all`).
