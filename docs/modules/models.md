# Models — the shared value objects

The small, immutable records that every other module in the framework speaks in.

## What it does

`models.py` defines the **contracts** that flow between sensors, actuators, the
safety layer, the decision layer, and the web layer. Instead of passing loose
dictionaries around, each stage produces and consumes one of these typed records.
There are five, grouped by the stage of the control loop they belong to:

- **`Reading`** (sensing) — one measurement from a sensor: `sensor_id`, `name`,
  `value` (a `float`, or `None` on failure), `unit`, `timestamp`, `ok`, `error`.
  A *failed* read is still a `Reading` (with `ok=False` and an `error` message),
  so one broken sensor never crashes a batch read.
- **`Command`** (actuation) — a *requested* actuator action: `actuator_id`,
  `action` (`"on"`, `"off"`, or `"set"`), `duration_s`, `params`, `source`
  (who asked: `"local_rules"`, `"llm"`, `"manual"`, `"watchdog"`, `"system"`),
  `timestamp`. A command is only ever a request — it must pass the safety guard
  before it can reach hardware.
- **`ActuatorResult`** (actuation) — the outcome of trying to apply a `Command`:
  `actuator_id`, `accepted` (bool), `applied` (the `Command` that actually ran,
  possibly clamped, or `None`), `reason` (why it was rejected or clamped),
  `timestamp`.
- **`Deviation`** (decision) — a reading that has drifted outside its configured
  target range: `sensor_id`, `metric`, `value`, `target_low`, `target_high`,
  `direction` (`"low"` or `"high"`).
- **`Event`** (audit) — an append-only record of anything the system observes or
  does: `type` (`"reading"`, `"deviation"`, `"decision"`, `"actuation"`),
  `payload` (a dict), `timestamp`.

It also exports a single timestamp helper, `utc_now_iso()`, so every timestamp
in the system is produced the same way (and tests can monkeypatch one function
for deterministic time).

### Why they are immutable

Every class is a `@dataclass(frozen=True)`. Once created, a record cannot be
changed. This matters because these objects travel through many layers:

- A `Reading` logged to the event store is guaranteed to be the same reading the
  decision layer saw — nothing can quietly mutate it afterwards.
- The safety guard cannot accidentally alter a `Command` in place; to "clamp" a
  command it must create a *new* one (see `Command.replace()` below), which keeps
  the original request intact for the audit trail.
- Frozen records are safe to share across threads (the transport, watchdog, and
  web layer all run concurrently) without locking.

Because you cannot edit a frozen record, the "change" helpers all return a
**copy**.

### Constructor helpers

These classmethods and methods make the common cases readable and consistent:

- `Reading.failure(sensor_id, name, unit, error)` — build a failed reading
  (`value=None`, `ok=False`). Sensors return this instead of raising.
- `ActuatorResult.ok(actuator_id, applied, reason=None)` — an accepted result.
- `ActuatorResult.rejected(actuator_id, reason)` — a rejected result
  (`accepted=False`, `applied=None`).
- `Command.replace(**changes)` — return a *copy* of a command with some fields
  changed. The safety guard uses this to clamp a duration without mutating the
  original.
- `.to_dict()` — on every record, for serialising to JSON (events, the web API).
  `ActuatorResult.to_dict()` also expands its nested `applied` command.

## How to use it

1. **Import the record you need** from `farm_agent.models`.
2. **Create one** either directly or via a helper. Timestamps default to "now",
   so you usually omit them.
3. **Never try to assign to a field** after construction — it will raise a
   `FrozenInstanceError`. Use `.replace(...)` to make a modified copy.
4. **Serialise with `.to_dict()`** when writing to the event store or an HTTP
   response.

```python
from farm_agent.models import Reading, Command, ActuatorResult

# A good reading and a failed one
good = Reading(sensor_id="soil_1", name="Soil moisture", value=512.0, unit="raw")
bad = Reading.failure("soil_1", "Soil moisture", "raw", "No Arduino data received")

# A request to run the pump for 3 minutes
cmd = Command(actuator_id="pump_1", action="on", duration_s=180, source="local_rules")

# The guard clamps the duration (returns a NEW command, original untouched)
clamped = cmd.replace(duration_s=120)

# Outcomes
ok = ActuatorResult.ok("pump_1", applied=clamped, reason="duration clamped to max")
no = ActuatorResult.rejected("pump_1", reason="still in cooldown")
```

## What it depends on

Nothing. `models.py` imports only the Python standard library (`dataclasses`,
`datetime`, `typing`). This is deliberate: it sits at the bottom of the
dependency graph so every other module can import it freely without creating
cycles. Everything else depends on it, not the other way round.

## Example

A sensor turning a raw frame value into a `Reading`, and the decision layer
turning that into a `Deviation`:

```python
from farm_agent.models import Reading, Deviation

# Sensor side: produce a reading
reading = Reading(sensor_id="soil_1", name="Soil moisture", value=320.0, unit="raw")

# Decision side: it is below the target range of 400..800, so it is a deviation
if reading.ok and reading.value < 400:
    dev = Deviation(
        sensor_id=reading.sensor_id,
        metric="soil_moisture",
        value=reading.value,
        target_low=400,
        target_high=800,
        direction="low",
    )
    print(dev.to_dict())
    # {'sensor_id': 'soil_1', 'metric': 'soil_moisture', 'value': 320.0,
    #  'target_low': 400, 'target_high': 800, 'direction': 'low'}
```

## Where it lives

`farm_agent/models.py`

Related docs: [transport.md](transport.md), [sensors.md](sensors.md),
[actuators.md](actuators.md), [events.md](events.md).
