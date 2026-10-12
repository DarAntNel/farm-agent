# Control Cycle

One pass of the smart-farm loop: sense, assess, decide, act — recording an audit event at every step.

## What it does

`ControlCycle` is the minimal orchestration spine that ties the whole system together. One call to `run_once()` performs a single pass of the control loop and returns a summary. A background scheduler that calls `run_once` on a timer is a **later sub-project**; today the cycle is driven on demand (via `POST /control/tick`) and by tests.

### `run_once() -> dict`

1. **Sense.** `readings = hub.read_all()`; record a `reading` event per reading.
2. **Assess.** `deviations = find_deviations(readings, policy)`; record a `deviation` event per deviation (see [decision.md](decision.md)).
3. **Decide.** Fetch recent history (`event_store.recent(50)`), then `commands = strategy.decide(readings, deviations, history)`. The strategy only *proposes*. If the strategy reports `wired = False` (the `LlmStrategy` stub), a note is attached. A single `decision` event is recorded with the strategy name, the proposed commands, and the note.
4. **Act.** Each command is sent through `controller.execute(cmd)` — so the safety guard, watchdog, dry-run handling, and `actuation` events all apply (see [controller.md](controller.md)). Nothing bypasses the guard.
5. **Return a summary** dict: `strategy`, `readings`, `deviations`, `commands`, `results`, and `note`.

This ordering is the heart of **"decision proposes, guard disposes"**: the strategy's commands are never executed directly — every one of them goes through the guarded controller in step 4.

### `status() -> dict`

A read-only snapshot: the active strategy name, whether the controller is in `dry_run`, the list of sensors (`hub.list_sensors()`), and current actuator states (`controller.states()`). Exposed via `GET /control/status`.

## How to use it

1. Assemble the collaborators: a `SensorHub`, an `ActuatorController`, a `DecisionStrategy`, a `FarmPolicy`, and an `EventStore`.
2. Construct the `ControlCycle`.
3. Call `run_once()` whenever you want one pass of the loop; read `status()` for a snapshot.

```python
from farm_agent.control.cycle import ControlCycle
from farm_agent.control.strategy import build_strategy

cycle = ControlCycle(
    hub=hub,
    controller=controller,
    strategy=build_strategy(policy),
    policy=policy,
    event_store=event_store,
)

summary = cycle.run_once()
print(summary["strategy"], len(summary["commands"]), "commands proposed")

snapshot = cycle.status()
print(snapshot["dry_run"], snapshot["actuators"])
```

## What it depends on

- `farm_agent.sensors.hub.SensorHub` — step 1, reads all sensors.
- `farm_agent.control.assess.find_deviations` + `farm_agent.config.policy.FarmPolicy` — step 2, finds out-of-range readings.
- `farm_agent.control.strategy.DecisionStrategy` — step 3, proposes commands (see [decision.md](decision.md)).
- `farm_agent.control.controller.ActuatorController` — step 4, the guarded chokepoint (see [controller.md](controller.md)).
- `farm_agent.events.store.EventStore` — records `reading`, `deviation`, `decision` events (actuation events come from the controller) and supplies recent history.
- `farm_agent.models.Event`.

## Example

A single tick in simulation. Dry soil produces a deviation, the local-rules strategy proposes a pump-on, and the controller handles it — all captured in the returned summary and the event log:

```python
summary = cycle.run_once()

# The pipeline is visible in the summary:
print([r["sensor_id"] for r in summary["readings"]])    # e.g. ['soil_1', 'temp_1']
print([d["direction"] for d in summary["deviations"]])  # e.g. ['low'] if soil is dry
print(summary["commands"])                              # proposals from the strategy
print(summary["results"])                               # outcomes after the guard

# Events were recorded in order: reading(s) -> deviation(s) -> decision -> actuation(s)
recent = event_store.recent(10)
print([e.type for e in recent])
```

## Where it lives

- `farm_agent/control/cycle.py` — the `ControlCycle` class (`run_once`, `status`).
