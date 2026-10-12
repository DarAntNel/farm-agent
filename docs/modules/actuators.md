# Actuators — acting on the environment

The actuator framework: one uniform interface for devices that *do* things
(pumps, relays), deliberately "dumb" — all safety policy lives elsewhere.

## What it does

An **`Actuator`** is the mirror image of a sensor: it acts on the environment
instead of observing it. Every actuator takes a `Command` and returns an
`ActuatorResult`. The framework has one base class and three concrete devices.

### `Actuator` (abstract base — `actuators/base.py`)

The uniform interface. Every actuator has:

- `id`, `name`, `kind`, `is_on` properties, and `state()` — a dict of
  `id`/`name`/`kind`/`is_on`/`since` (when it last changed).
- **`_perform(command)`** — the *raw* hardware action, implemented by each
  subclass. May raise on hardware failure.
- **`apply(command) -> ActuatorResult`** — the template method. It calls
  `_perform`, and on success updates tracked state (`is_on`, `since`) and returns
  `ActuatorResult.ok(...)`; if `_perform` raises, it catches the exception and
  returns `ActuatorResult.rejected(...)` with a `"hardware error: ..."` reason.
- **`safe_off()`** — force the actuator to its safe (off) state by applying an
  `"off"` command from source `"system"`.
- `from_config(cfg, *, transport=None)` — classmethod the factory calls.

**`_perform` vs `apply`:** subclasses implement only `_perform` (the device-
specific "flip the pin" / "write the line"). Everything common — exception
handling, state tracking, building the result — lives once in `apply`. You call
`apply` (or, in practice, let the controller call it); you never call `_perform`
directly.

### The concrete actuators

- **`RelayActuator`** (`actuators/relay.py`) — type key `"relay"`. Drives a
  single GPIO pin high (on) or low (off); a water pump is a relay actuator.
  Config declares the `pin`. The `RPi.GPIO` import is **lazy**, and the backend
  that toggles the pin is **injectable** (`backend(pin, value)`), so it imports
  and tests without any hardware. `_perform` drives the pin high for any action
  except `"off"`.
- **`SerialActuator`** (`actuators/serial_actuator.py`) — type key
  `"serial_actuator"`. For actuators wired to the Arduino: `_perform` writes one
  command line through a `LineSink` (the shared transport), e.g. `pump on 180` or
  `pump off`. Config: `command` (the Arduino-side device name, defaults to the
  id). Requires a `transport`.
- **`FakeActuator`** (`actuators/fake.py`) — type key `"fake"`. Performs no real
  action; it **records every `Command`** in a `performed` list. It is the default
  actuator in `SIMULATE=true` mode and a handy spy in tests.

### These are "dumb" — safety lives elsewhere

This is the single most important thing to understand about actuators: **the base
class and the concrete devices enforce no policy.** `apply` assumes the command
has *already* been validated. There is no runtime cap, no cooldown, no mutual
exclusion here.

That is on purpose. In normal operation **nothing outside the package calls
`apply` directly** — every command flows through the `ActuatorController`
(`control/controller.py`), which first runs the `SafetyGuard` (clamp duration,
reject on cooldown / daily cap / mutual exclusion) and then schedules the auto-off
watchdog. The actuator just does the raw action. Keeping safety out of the device
classes means the rules live in *one* auditable place and cannot be partially
re-implemented (or forgotten) per device. See the safety-model and controller
docs for the chokepoint.

## How to use it

In normal operation you build actuators from config and drive them through the
controller, never directly. The direct steps (used in tests) are:

1. **Build an actuator** via `from_config` (or construct directly in tests).
2. **Apply a command** — `apply(Command(...))`.
3. **Inspect state** — `state()` or `is_on`.
4. **Force off** when needed — `safe_off()`.

```python
from farm_agent.actuators.relay import RelayActuator
from farm_agent.models import Command

# Inject a backend so no GPIO is needed (records pin writes).
log = []
pump = RelayActuator("pump_1", "Water pump", pin=17, backend=lambda pin, v: log.append((pin, v)))

result = pump.apply(Command(actuator_id="pump_1", action="on", duration_s=180))
print(result.accepted)     # True
print(pump.state())        # {... 'is_on': True, 'since': '...'}

pump.safe_off()
print(pump.is_on)          # False
```

To add a brand-new actuator type, see
[adding-an-actuator.md](../guides/adding-an-actuator.md) — one class plus one
config line via the [registry](registry.md).

## What it depends on

- **`farm_agent.models`** — consumes `Command`, produces `ActuatorResult`; uses
  `utc_now_iso` for the `since` timestamp.
- **`farm_agent.registry`** — each concrete actuator decorates itself with
  `@actuator_registry.register(...)`.
- **`farm_agent.transport`** — `SerialActuator` depends on the `LineSink`
  protocol.
- **`RPi.GPIO`** — only imported lazily inside `RelayActuator`, at first real use.
  Never required to import the package; `FakeActuator` needs nothing at all.

It does **not** depend on the safety or control layers — the dependency runs the
other way (the controller depends on actuators).

## Example

Using `FakeActuator` as a spy to assert exactly what was commanded (the
simulation/test pattern):

```python
from farm_agent.actuators.fake import FakeActuator
from farm_agent.models import Command

pump = FakeActuator.from_config({"id": "pump_1", "name": "Water pump"})

pump.apply(Command(actuator_id="pump_1", action="on", duration_s=120, source="local_rules"))
pump.safe_off()

# Every command it was asked to perform is recorded, in order:
for cmd in pump.performed:
    print(cmd.action, cmd.duration_s, cmd.source)
# on 120 local_rules
# off None system
```

## Where it lives

- `farm_agent/actuators/base.py` — `Actuator` (`_perform`, `apply`, `state`,
  `safe_off`)
- `farm_agent/actuators/relay.py` — `RelayActuator`
- `farm_agent/actuators/serial_actuator.py` — `SerialActuator`
- `farm_agent/actuators/fake.py` — `FakeActuator`

Related docs: [models.md](models.md), [transport.md](transport.md),
[registry.md](registry.md), [sensors.md](sensors.md), and the safety-model /
controller docs for where policy actually lives.
