# Decision Layer

Turns sensor readings into proposed actuator commands — first by detecting deviations, then by running a pluggable decision strategy.

## What it does

The decision layer answers two questions:

1. **"Is anything out of range?"** — `assess.find_deviations`
2. **"What, if anything, should we do about it?"** — a `DecisionStrategy`

Remember the project's rule: **the decision layer only proposes.** Nothing it returns reaches hardware until the safety guard has vetted it (see [safety-guard.md](safety-guard.md)) and the controller has applied it (see [controller.md](controller.md)).

### `find_deviations(readings, policy) -> list[Deviation]`

A pure function (no side effects). For each `Reading` it looks up the sensor's target range via `policy.target_for(sensor_id)` and emits a `Deviation` when the value falls outside `[low, high]`:

- Readings that failed (`ok=False`), have no `value`, or have no configured target are **skipped**.
- `value < low` → `direction="low"`; `value > high` → `direction="high"`; in range → no deviation.

### `DecisionStrategy` (ABC)

The interface: `decide(readings, deviations, history) -> list[Command]`. Every strategy exposes a `name`. Two implementations exist:

- **`LocalRulesStrategy`** (`name="local_rules"`, implemented and always available). Deterministic threshold rules. For each deviation it looks up `policy.rule_for(sensor_id, direction)` and, if a rule exists, emits a `Command` built from it (`actuator_id`, `action` defaulting to `"on"`, `duration_s`, `params`), tagged `source="local_rules"`. This is the offline fallback that works without any network or model.

- **`LlmStrategy`** (`name="llm"`, a documented stub). It implements the interface so the rest of the system can already depend on it, but it is **not yet wired** (`wired = False`) and proposes **no commands**. It is the seam for a future sub-project: the real version will assemble `readings + policy + recent history` into a prompt, call the Claude API, and return schema-validated commands — all still passing through the safety guard. When a strategy has `wired = False`, the control cycle records a `decision` event noting that the strategy "not yet wired" (see [control-cycle.md](control-cycle.md)).

### `build_strategy(policy) -> DecisionStrategy`

Selects and instantiates the strategy named by `policy.strategy` (default `"local_rules"`). Unknown names raise a `ValueError` listing the available strategies. Because selection is by config, swapping in the LLM later is a **config change, not a code change** (Open/Closed Principle).

## How to use it

1. Read sensors into `list[Reading]` (via the `SensorHub`).
2. Call `find_deviations(readings, policy)` to find what is out of range.
3. Build a strategy with `build_strategy(policy)` (or construct one directly).
4. Call `strategy.decide(readings, deviations, history)` to get proposed commands.
5. Hand each command to the `ActuatorController` — do **not** act on them directly.

```python
from farm_agent.config.policy import FarmPolicy
from farm_agent.config.defaults import DEFAULT_POLICY
from farm_agent.control.assess import find_deviations
from farm_agent.control.strategy import build_strategy

policy = FarmPolicy(DEFAULT_POLICY)
readings = hub.read_all()                       # from the SensorHub

deviations = find_deviations(readings, policy)
strategy = build_strategy(policy)               # -> LocalRulesStrategy (per default policy)
commands = strategy.decide(readings, deviations, history=[])
# commands are PROPOSALS; feed them to the controller, which runs the guard first.
```

## What it depends on

- `farm_agent.models` — `Reading`, `Deviation`, `Command`, `Event`.
- `farm_agent.config.policy.FarmPolicy` — supplies target ranges (`target_for`), rules (`rule_for`), and the selected strategy name (`strategy`). See [config.md](config.md).
- No hardware, no network. `LocalRulesStrategy` is fully deterministic; `LlmStrategy` is an inert stub today.

## Example

Using the default policy, a dry soil reading (below its `low` of 400) produces a pump-on command; an in-range reading produces nothing:

```python
from farm_agent.config.policy import FarmPolicy
from farm_agent.config.defaults import DEFAULT_POLICY
from farm_agent.control.assess import find_deviations
from farm_agent.control.strategy import LocalRulesStrategy
from farm_agent.models import Reading

policy = FarmPolicy(DEFAULT_POLICY)
readings = [Reading(sensor_id="soil_1", name="Soil moisture", value=320, unit="raw")]

deviations = find_deviations(readings, policy)
print(deviations[0].direction)        # "low"  (320 < target low of 400)

commands = LocalRulesStrategy(policy).decide(readings, deviations, history=[])
print(commands[0].actuator_id, commands[0].action, commands[0].duration_s)
# pump_1 on 180

# In-range reading -> no deviation -> no command:
assert find_deviations(
    [Reading("soil_1", "Soil moisture", 600, "raw")], policy
) == []
```

## Where it lives

- `farm_agent/control/assess.py` — `find_deviations`.
- `farm_agent/control/strategy.py` — `DecisionStrategy`, `LocalRulesStrategy`, `LlmStrategy`, `build_strategy`.
