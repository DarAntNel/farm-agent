# Design Decisions (the "why")

[overview.md](overview.md) explains *what* the framework is and *how* it fits
together. This document explains the **deliberate choices** behind it: why the
parts are shaped the way they are, and where each idea lives in the code. If you
ever wonder "why didn't they just do X?", look here.

Terminology and class names match the code so you can grep for them.

---

## 1. One `Sensor` interface over two very different hardware paths

**The decision:** there is a single `Sensor` abstract base class with one method,
`read() -> Reading`. Two abstract subclasses capture the two completely different
ways a value is obtained:

- **`SerialSensor`** — the value arrives as a field inside the Arduino's JSON
  frame, pulled from the shared `SerialTransport`.
- **`DirectSensor`** — the value is read directly from Raspberry Pi hardware
  (I2C, 1-Wire, GPIO).

**Why it matters:** these two paths have nothing in common at the hardware level
(a serial port versus an I2C bus), yet the rest of the system should not care.
Because both end up as a `Sensor` that returns a `Reading`, the `SensorHub`, the
control cycle, and the web layer treat a soil probe wired to an Arduino and a
temperature probe wired straight to the Pi as **interchangeable**. You can move a
sensor from one wiring scheme to the other without touching any code above the
sensor class.

A nice consequence: a *failed* read is still a `Reading` (with `ok=False` and an
`error` message), so one broken sensor never crashes a batch read. Serial sensors
even share a single `extract()` + validation + calibration path, so a concrete
sensor usually only declares its JSON field name, unit, and valid range.

> In code: `farm_agent/sensors/base.py`.

---

## 2. "Add a device = one class + one config line" (registry + config)

**The decision:** a single tiny generic `Registry` class maps a string type-key
to a class, and it is reused for **both** sensors and actuators
(`sensor_registry`, `actuator_registry`). A concrete class registers itself with
a decorator; a config-driven factory looks the key up to build the object.

Adding a new device type is therefore:

1. Write the class.
2. Decorate it: `@sensor_registry.register("my_type")`.
3. Add one line to the wiring config naming that type and its port.

No other code changes — not the hub, not the controller, not the web layer.

**Why it matters:** this is the system's main extensibility mechanism, and using
the *same* pattern for sensors and actuators keeps it DRY. The registry also
raises **clear, actionable errors**: a duplicate registration names the class it
clashes with, and an unknown-type lookup lists the available types, so a typo in
config produces a helpful message instead of a mysterious `KeyError`.

> In code: `farm_agent/registry.py`.

---

## 3. "The decision layer proposes; the safety guard disposes"

**The decision:** the thing that *chooses* actions (the `DecisionStrategy`) has
**no authority to act**. It only returns a list of `Command` objects, which are
merely *requests*. Every command must pass the deterministic `SafetyGuard` before
it can reach hardware, where it may be clamped (duration capped) or rejected
(cooldown, daily cap, mutual exclusion).

**Why it matters:** the plan is for an LLM/agent to make decisions eventually. An
LLM can be creative, wrong, or manipulated. By forcing *every* proposal — whether
from today's deterministic rules or tomorrow's LLM — through the same
deterministic chokepoint, the behaviour that actually drives hardware stays
predictable and bounded. The guard is pure and deterministic (all time comes from
an injected clock, no I/O), so it is easy to test exhaustively, and "when in
doubt, reject" plus "off is always allowed" makes the fail-safe behaviour the
*default*, not an afterthought.

This is covered in depth in [safety-model.md](safety-model.md).

> In code: `farm_agent/control/strategy.py` (proposes),
> `farm_agent/safety/guard.py` (disposes),
> `farm_agent/control/controller.py` (enforces the route).

---

## 4. Wiring config vs policy config: two separate concerns

**The decision:** configuration is split into two files/loaders:

- **Wiring config** — *what hardware exists and where it is plugged in*: which
  sensors and actuators exist, the serial port, I2C channel/address, GPIO pin,
  1-Wire id, and calibration offsets.
- **Policy config** — *how the farm should behave*: target range per sensor, the
  decision rules, the safety limits per actuator, which strategy to use, and
  event-store settings.

**Why it matters:** these two concerns change for different reasons and by
different people. Rewiring a sensor onto a different pin is a *hardware* change;
deciding that soil should stay between two moisture values is an *agronomy /
policy* change. Keeping them apart means you can re-tune the farm's behaviour
without risking the hardware map, and vice versa. It also makes the "it just runs
in simulation out of the box" promise easy: both loaders have sane defaults and
validate on load with specific errors.

> In code: `farm_agent/config/` (`wiring.py`, `policy.py`, `defaults.py`).

---

## 5. Dependency injection everywhere, with one composition root

**The decision:** no module reaches for a global. Every collaborator is passed in
through a constructor (or a factory function's arguments). The only place that
decides *which* concrete objects to build is `bootstrap.build_system`.

Examples you can see directly in the code:

- `ActuatorController(actuators, guard, watchdog, event_store, dry_run=...)` is
  handed all of its collaborators.
- `ControlCycle(hub, controller, strategy, policy, event_store)` is handed all of
  its collaborators.
- `SafetyGuard(policy, clock=time.monotonic)` takes an injected **clock**, so
  tests can control time for cooldown and daily-cap checks.
- `Watchdog(timer_factory=threading.Timer)` takes an injected **timer factory**,
  so tests fire the auto-off deterministically instead of waiting on the wall
  clock.
- `create_app(hub, controller, cycle, event_store, api_token=...)` is a Flask
  **app factory** that receives its dependencies rather than constructing them.

**Why it matters:** injection is what makes "runs without hardware" and
"exhaustively testable" true rather than aspirational. Swapping the real
transport for a simulated one, or a real relay for a `FakeActuator`, is a
one-line change *in the composition root* and invisible to everything else.

> In code: `farm_agent/bootstrap.py` (the composition root); every class
> constructor shows the injected collaborators.

---

## 6. SOLID, mapped to concrete places in the code

The guiding principles are SOLID + dependency injection. Here is where each
principle actually shows up, so the ideas are not abstract:

### S — Single Responsibility
Each file has one job. `transport.py` only owns the serial connection;
`guard.py` only validates commands; `controller.py` only routes commands to
hardware; `cycle.py` only orchestrates one pass; `web/app.py` only shapes JSON
and status codes. The web layer "is deliberately thin... delegating all real
work" (its module docstring).

### O — Open/Closed
Add a sensor or actuator by registering a new class — the registry and factory
are open to extension, closed to modification (§2). Likewise, swapping the
decision maker from `LocalRulesStrategy` to `LlmStrategy` is a **policy-config
change**, not a code change: `build_strategy(policy)` instantiates the strategy
named by `policy.strategy`.

> In code: `registry.py`, `control/strategy.py` (`build_strategy`).

### L — Liskov Substitution
Any `Sensor` is usable wherever a `Sensor` is expected — a `SerialSensor` and a
`DirectSensor` are interchangeable because both honour `read() -> Reading`
(stated verbatim in `sensors/base.py`). The same holds for `Actuator`: a
`RelayActuator`, a `SerialActuator`, and a `FakeActuator` are swapped freely
(simulation swaps in fakes with no other change).

### I — Interface Segregation
The interfaces are deliberately minimal. `Sensor` exposes essentially
`read()`; `Actuator` exposes `apply()`, `state()`, `safe_off()`;
`DecisionStrategy` exposes a single `decide(...)`; `EventStore` exposes
`record()` + `recent()`. No implementation is forced to depend on methods it does
not use.

> In code: `sensors/base.py`, `actuators/base.py`, `control/strategy.py`,
> `events/store.py`.

### D — Dependency Inversion
High-level code depends on **abstractions**, not concretions. `ControlCycle`
depends on the `DecisionStrategy` ABC and the `EventStore` ABC, not on
`LocalRulesStrategy` or `InMemoryEventStore`. The web factory depends on the
`SensorHub` / `ActuatorController` / `ControlCycle` it is *given*. The concrete
choices are injected by the composition root (§5).

> In code: `control/cycle.py`, `web/app.py`, wired in `bootstrap.py`.

---

## 7. A few smaller choices worth knowing

- **Immutable value objects.** `Reading`, `Command`, `ActuatorResult`,
  `Deviation`, and `Event` are frozen dataclasses. They are the *contracts* every
  layer speaks in; making them immutable means a command cannot be quietly
  mutated after the guard has vetted it (the guard produces a *clamped copy* via
  `Command.replace`).
- **Everything is auditable.** Every reading, deviation, decision, and actuation
  becomes an `Event`. The same history that answers "why did the pump run?" is
  exactly what a future LLM strategy will receive as "recent history".
- **Offline-first.** No cloud dependency is required to operate. The deterministic
  `LocalRulesStrategy` is the always-available fallback if/when the LLM path is
  unavailable.

---

## 8. Where to go next

- **What the system is and how it flows** -> [overview.md](overview.md)
- **The safety guarantees in detail** -> [safety-model.md](safety-model.md)
- **Map of all documentation** -> [../README.md](../README.md)
