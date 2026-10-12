# Actuator Controller

The single chokepoint through which every command reaches hardware, so the safety guard, watchdog, event log, and dry-run always apply.

## What it does

`ActuatorController` is the one place in the system that is allowed to call `Actuator.apply`. Nothing else — not the web layer, not the decision layer — touches an actuator directly. Routing everything through here guarantees that the full safety pipeline runs for **every** command, no matter who proposed it. This is the concrete expression of **"decision proposes, guard disposes."**

### `execute(command) -> ActuatorResult`

The chokepoint, in order:

1. **Unknown id raises `KeyError`.** If `command.actuator_id` is not a known actuator, `execute` raises `KeyError` immediately. (The web layer maps this to a 404.)
2. **Guard review.** The command is passed to `SafetyGuard.review` (see [safety-guard.md](safety-guard.md)). If rejected, the controller records an `actuation` event and returns the rejection — nothing fires.
3. **Apply (unless dry-run).** The approved (possibly clamped) command is used:
   - In **dry-run** mode the controller does **not** fire the actuator; it returns an accepted result with reason `"dry-run: not applied"` and records the event. Safe to run on real hardware.
   - Otherwise it calls `actuator.apply(approved)`.
4. **On a successful `on`:** it calls `guard.record_activation(...)` (so cooldown and the daily cap are enforced next time) and, if the command has a `duration_s`, schedules a guaranteed auto-off via the watchdog (see [watchdog.md](watchdog.md)).
5. **On a successful `off`:** it cancels any pending watchdog timer for that actuator.
6. **Event log.** Every outcome — rejection, dry-run, or real apply — is recorded as an `actuation` event in the event store. The auto-off callback also records its own `actuation` event (`auto_off: true`).

### `safe_init()`

Called at startup: cancels all watchdog timers and forces **every** actuator to `safe_off()`. The system never boots into an unknown "on" state.

### Other members

- `get(actuator_id)` — return one actuator, raising `KeyError` if unknown (web → 404).
- `states()` — a list of each actuator's `state()` dict.
- `dry_run` (property) — whether the controller is in dry-run mode.
- `shutdown()` — cancel all watchdog timers.

## How to use it

1. Build the actuators, a `SafetyGuard`, a `Watchdog`, and an `EventStore`.
2. Construct the controller, passing `dry_run=True` if you want to simulate without firing hardware.
3. Call `safe_init()` once at startup.
4. Call `execute(command)` for every command — typically from the control cycle or a web command route.

```python
from farm_agent.control.controller import ActuatorController
from farm_agent.safety.guard import SafetyGuard
from farm_agent.safety.watchdog import Watchdog
from farm_agent.events.store import InMemoryEventStore
from farm_agent.models import Command

controller = ActuatorController(
    actuators=[pump],              # list of Actuator objects
    guard=SafetyGuard(policy),
    watchdog=Watchdog(),
    event_store=InMemoryEventStore(),
    dry_run=False,
)
controller.safe_init()            # force everything off at startup

result = controller.execute(
    Command(actuator_id="pump_1", action="on", duration_s=180, source="manual")
)
print(result.accepted, result.reason)
```

## What it depends on

- `farm_agent.actuators.base.Actuator` — the devices it drives (via `apply` / `safe_off` / `state`).
- `farm_agent.safety.guard.SafetyGuard` — vets and clamps every command; told of activations via `record_activation`. See [safety-guard.md](safety-guard.md).
- `farm_agent.safety.watchdog.Watchdog` — schedules/cancels guaranteed auto-off. See [watchdog.md](watchdog.md).
- `farm_agent.events.store.EventStore` — where every actuation outcome is recorded.
- `farm_agent.models` — `Command`, `ActuatorResult`, `Event`.

## Example

A dry-run controller logs the would-apply command but never fires the actuator; an unknown id raises `KeyError`:

```python
from farm_agent.control.controller import ActuatorController
from farm_agent.safety.guard import SafetyGuard
from farm_agent.safety.watchdog import Watchdog
from farm_agent.events.store import InMemoryEventStore
from farm_agent.models import Command

store = InMemoryEventStore()
controller = ActuatorController([pump], SafetyGuard(policy), Watchdog(), store, dry_run=True)

result = controller.execute(Command("pump_1", "on", duration_s=180, source="manual"))
assert result.accepted
assert result.reason == "dry-run: not applied"
assert pump.is_on is False                 # nothing actually fired
assert store.recent(1)[0].type == "actuation"   # but it was logged

# Unknown actuator -> KeyError (web layer turns this into a 404):
try:
    controller.execute(Command("ghost", "on"))
except KeyError as exc:
    print("unknown actuator:", exc)
```

## Where it lives

- `farm_agent/control/controller.py` — the `ActuatorController` class.
