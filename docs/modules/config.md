# Configuration

Two separate kinds of config — **wiring** (what hardware exists) and **policy** (what the farm should do) — each with loaders, env overrides, and validation.

## What it does

The framework splits configuration into two deliberately independent concerns. Keeping them apart means you can change farming behaviour without touching hardware topology, and vice versa.

### WIRING vs POLICY — the split

| | **Wiring** (`wiring.py`) | **Policy** (`policy.py`) |
|---|---|---|
| Answers | *Which devices exist and where are they wired?* | *What should the farm do?* |
| Contents | The serial link; a list of sensors and actuators, each with a registered `type`, an `id`, and its port (serial field, I2C channel/address, GPIO pin, 1-Wire id) + calibration offsets. | Target ranges per sensor, the deviation→command rules, per-actuator safety limits, the chosen decision strategy, event-store settings. |
| Env override | `WIRING_CONFIG` → path to a JSON file | `POLICY_CONFIG` → path to a JSON file |
| Fallback | `DEFAULT_WIRING` (in `defaults.py`) | `DEFAULT_POLICY` (in `defaults.py`) |

Both loaders follow the same pattern: use the explicit `path` argument if given, else the env var, else the built-in defaults. The defaults let the app boot and do something useful **in simulation with no external files**.

### Loading

- **`load_wiring(path=None) -> dict`** — loads the raw wiring dict. If a path (argument or `$WIRING_CONFIG`) is given, it reads and `json.load`s the file, then validates it; otherwise it returns `DEFAULT_WIRING` as-is.
- **`load_policy(path=None) -> FarmPolicy`** — same pattern, returning a `FarmPolicy` wrapper. Without a path it returns `FarmPolicy(DEFAULT_POLICY)`.

### Building devices (the factory)

- **`build_sensors(wiring, *, transport, buses=None) -> list`** and **`build_actuators(wiring, *, transport=None) -> list`** turn a wiring dict into live objects. They first import the concrete device modules so the classes self-register, then for each entry look the `type` up in the registry (`sensor_registry` / `actuator_registry`) and call the class's `from_config(cfg, ...)`. This is the "add a device = one class + one config line" pattern.

### `FarmPolicy` helpers

`FarmPolicy` is a frozen dataclass wrapping the raw policy dict, with typed lookup helpers used by the assess and safety layers:

- `strategy` (property) — the selected strategy name, default `"local_rules"`.
- `target_for(sensor_id)` — `(low, high)` tuple for a sensor, or `None` if no target is configured.
- `rule_for(sensor_id, direction)` — the rule dict for a deviation (`"low"`/`"high"`), or `None`.
- `limits_for(actuator_id)` — a `SafetyLimits` for the actuator (falls back to `DEFAULT_LIMITS` if none configured). Imported lazily to avoid a circular import with the safety layer.

### Validation

Both configs are validated on load with clear, specific errors:

- **Wiring:** the top level must be a JSON object; `sensors`/`actuators` must be lists; each entry must have both `type` and `id`.
- **Policy:** the top level must be a JSON object; every target must have `low` and `high`, and `low` must not exceed `high`.

(Note: validation runs on files loaded from a path. The built-in defaults are trusted and returned directly.)

## How to use it

1. Decide whether to rely on defaults (simulation) or point the env vars at JSON files.
2. Load both configs.
3. Build sensors/actuators from the wiring, and pass the `FarmPolicy` to the assess, strategy, and safety layers.

```python
from farm_agent.config.wiring import load_wiring, build_sensors, build_actuators
from farm_agent.config.policy import load_policy

wiring = load_wiring()        # $WIRING_CONFIG, else DEFAULT_WIRING
policy = load_policy()        # $POLICY_CONFIG, else DEFAULT_POLICY

sensors   = build_sensors(wiring, transport=transport, buses=buses)
actuators = build_actuators(wiring, transport=transport)

print(policy.strategy)                 # "local_rules"
print(policy.target_for("soil_1"))     # (400.0, 800.0)
print(policy.rule_for("soil_1", "low"))# {"actuator_id": "pump_1", "action": "on", "duration_s": 180}
print(policy.limits_for("pump_1"))     # SafetyLimits(max_runtime_s=300.0, cooldown_s=600.0, ...)
```

To override via environment (pointing at your own JSON files):

```bash
export WIRING_CONFIG=/etc/farm/wiring.json
export POLICY_CONFIG=/etc/farm/policy.json
```

## What it depends on

- `farm_agent.config.defaults` — `DEFAULT_WIRING` and `DEFAULT_POLICY`.
- `farm_agent.registry` — `sensor_registry` / `actuator_registry`, used by the build factories.
- `farm_agent.sensors` / `farm_agent.actuators` — imported so device classes self-register before building.
- `farm_agent.safety.limits` — `SafetyLimits` / `DEFAULT_LIMITS`, used (lazily) by `limits_for`. See [safety-guard.md](safety-guard.md).
- Standard library `json` and `os` for file loading and env lookups.

## Example

Loading a custom policy file and using the helpers the rest of the system relies on:

```python
# /etc/farm/policy.json
# {
#   "strategy": "local_rules",
#   "targets": {"soil_1": {"low": 400, "high": 800}},
#   "rules":   {"soil_1": {"low": {"actuator_id": "pump_1", "action": "on", "duration_s": 120}}},
#   "safety":  {"pump_1": {"max_runtime_s": 300, "cooldown_s": 600, "max_activations_per_day": 24}}
# }

from farm_agent.config.policy import load_policy

policy = load_policy("/etc/farm/policy.json")   # validated on load
assert policy.target_for("soil_1") == (400.0, 800.0)
assert policy.limits_for("pump_1").cooldown_s == 600.0

# A bad target is rejected with a clear error:
# load_policy of {"targets": {"soil_1": {"low": 900, "high": 100}}}
#   -> ValueError: Target for 'soil_1' has low > high.
```

## Where it lives

- `farm_agent/config/wiring.py` — `load_wiring`, `build_sensors`, `build_actuators`, wiring validation.
- `farm_agent/config/policy.py` — `FarmPolicy`, `load_policy`, policy validation.
- `farm_agent/config/defaults.py` — `DEFAULT_WIRING`, `DEFAULT_POLICY`.
