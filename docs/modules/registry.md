# Registry — the extensibility mechanism

A tiny generic type registry, reused for both sensors and actuators, that lets a
new device be added with one class and one line of config.

## What it does

`registry.py` defines one small generic class, `Registry`, and creates two shared
instances from it:

- **`sensor_registry`** — maps a string type-key (e.g. `"soil_moisture"`) to a
  sensor class.
- **`actuator_registry`** — maps a string type-key (e.g. `"relay"`) to an
  actuator class.

A `Registry` maps a string `type` key to a class. It offers:

- **`register(key)`** — a *decorator* that registers the decorated class under
  `key`. Raises a clear `ValueError` if that key is already taken by a different
  class (catching double-imports and copy-paste typos).
- **`get(key)`** — return the class registered under `key`, or raise a `KeyError`
  whose message **lists the available types** (so a typo in config produces an
  actionable error, not a mysterious `KeyError`).
- **`available()`** — the sorted list of registered keys.
- **`key in registry`** — membership test via `__contains__`.

### How it powers extensibility

This is the mechanism that makes the framework **open for extension without
modifying existing code** (the "O" in SOLID). A concrete device class registers
*itself* under a string key with the decorator, and the config-driven factory
(see [config](../modules/config.md) / `config/wiring.py`) looks that key up to
build the object. So adding a new device type is just:

1. **Write a class** (a `Sensor` or `Actuator` subclass).
2. **Decorate it** with `@sensor_registry.register("my_type")` (or
   `@actuator_registry.register(...)`).
3. **Add one line** to the wiring config naming that `type` and its port.

No factory code, no `if/elif` ladder, and no other module changes.

Registration happens as an **import side effect**: the decorator runs when the
module is imported. So the concrete device modules must actually be imported for
their types to appear in the registry. The package does this in
`farm_agent/config/wiring.py` (`_ensure_registered()` imports
`farm_agent.sensors` and `farm_agent.actuators`), whose package `__init__` files
import each concrete module.

## How to use it

**To register a new type**, decorate your class:

```python
from farm_agent.registry import sensor_registry
from farm_agent.sensors.base import SerialSensor

@sensor_registry.register("humidity")
class HumiditySensor(SerialSensor):
    kind = "humidity"
    FIELD = "humidity_pct"
    UNIT = "%"
    VALID_RANGE = (0, 100)
```

**To build an object from a type key** (what the factory does):

```python
from farm_agent.registry import sensor_registry

cls = sensor_registry.get("humidity")        # -> HumiditySensor
sensor = cls.from_config({"id": "hum_1", "type": "humidity"}, transport=transport)
```

**To discover or check types:**

```python
sensor_registry.available()      # ['ads1115_soil', 'ds18b20', 'soil_moisture', ...]
"relay" in actuator_registry     # True
```

## What it depends on

Nothing but the standard library (`typing`). Like `models`, the registry sits at
the bottom of the dependency graph: concrete sensor and actuator modules import
*it* to register themselves, and the config layer imports it to look types up.
It knows nothing about `Sensor`, `Actuator`, or hardware — it is a plain generic
map, which is exactly why the same class serves both device families (DRY).

## Example

Registering, then looking up, and the clear errors you get for mistakes:

```python
from farm_agent.registry import actuator_registry

# Looking up an unknown type lists what IS available:
try:
    actuator_registry.get("rely")   # typo
except KeyError as exc:
    print(exc)
    # "Unknown actuator type 'rely'. Available types: fake, relay, serial_actuator."

# Registering the same key to a different class is rejected:
@actuator_registry.register("relay")
class AnotherRelay:  # noqa
    ...
# ValueError: actuator type 'relay' is already registered to RelayActuator;
# cannot re-register to AnotherRelay.
```

## Where it lives

`farm_agent/registry.py`

Related docs: [sensors.md](sensors.md), [actuators.md](actuators.md), and the
end-to-end tutorials [adding-a-sensor.md](../guides/adding-a-sensor.md) and
[adding-an-actuator.md](../guides/adding-an-actuator.md).
