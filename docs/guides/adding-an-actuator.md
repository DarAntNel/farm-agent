# Adding an Actuator

This tutorial adds a new actuator (a device that *acts on* the farm) to the
framework. As with sensors, the rule is **one class + one config line**. By the end
you will drive a new "grow light" relay through the safety-guarded command endpoint,
all in simulation.

An actuator is the mirror image of a sensor. The important safety rule: **nothing
calls an actuator directly.** Every command flows through the `ActuatorController`,
which runs the safety guard, the auto-off watchdog, dry-run handling, and the event
log. Your actuator class only models the raw device.

The model class to copy is `RelayActuator` (`farm_agent/actuators/relay.py`).

---

## What an actuator must provide

Subclass `Actuator` and supply:

- a `kind` class attribute (a short category string),
- `_perform(self, command)` — do the raw hardware action for a `Command`. It may
  raise on hardware failure; the base class turns that into a rejected result.
- a `from_config(cls, cfg, *, transport=None)` classmethod — build an instance from
  one wiring entry,
- the `@actuator_registry.register("my_type")` decorator.

The base class already tracks on/off state, timestamps, `safe_off()`, and `state()`,
and wraps `_perform` in `apply()` which converts exceptions into an
`ActuatorResult.rejected(...)`. You do not write any of that.

For reference, the whole relay class is small:

```python
@actuator_registry.register("relay")
class RelayActuator(Actuator):
    kind = "relay"

    def __init__(self, actuator_id, name, pin, *, backend=None):
        super().__init__(actuator_id, name)
        self._pin = pin
        self._backend = backend          # injectable for tests

    def _resolve_backend(self):
        if self._backend is None:
            self._backend = _make_gpio_backend()   # lazy hardware import
        return self._backend

    def _perform(self, command):
        value = command.action != "off"  # "off" -> low, else high
        self._resolve_backend()(self._pin, value)

    @classmethod
    def from_config(cls, cfg, *, transport=None):
        return cls(cfg["id"], cfg.get("name", cfg["id"]), cfg["pin"])
```

Two patterns to copy from it:

1. **Lazy hardware import** — the GPIO library is imported inside
   `_make_gpio_backend()`, only when a command is actually performed, so the module
   imports fine on any machine.
2. **Injectable backend** — tests pass a fake backend; real hardware builds one
   lazily.

---

## Worked example: a "grow light" relay

A grow light is just another relay on a GPIO pin. Rather than reuse the generic
`relay` type, we will register a dedicated `grow_light` type so it reads clearly in
config and can grow its own behaviour later.

### Step 1 — Write the actuator class

Create `farm_agent/actuators/grow_light.py`:

```python
"""A grow-light relay on the Raspberry Pi.

A grow light is driven exactly like the water pump: a single GPIO pin is set high
to switch the light on and low to switch it off. The GPIO library is imported
lazily and the toggle backend is injectable, so this module imports on any machine
and is testable with no hardware. No safety policy lives here — the controller and
guard handle that.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from farm_agent.actuators.base import Actuator
from farm_agent.models import Command
from farm_agent.registry import actuator_registry

Backend = Callable[[int, bool], None]


def _make_gpio_backend() -> Backend:
    try:
        import RPi.GPIO as GPIO  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "RPi.GPIO is not available; inject a backend or run in simulation."
        ) from exc

    GPIO.setmode(GPIO.BCM)

    def _backend(pin: int, value: bool) -> None:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.HIGH if value else GPIO.LOW)

    return _backend


@actuator_registry.register("grow_light")
class GrowLightActuator(Actuator):
    """Drives a single GPIO relay pin on (light) / off (dark)."""

    kind = "grow_light"

    def __init__(
        self,
        actuator_id: str,
        name: str,
        pin: int,
        *,
        backend: Optional[Backend] = None,
    ) -> None:
        super().__init__(actuator_id, name)
        self._pin = pin
        self._backend = backend

    def _resolve_backend(self) -> Backend:
        if self._backend is None:
            self._backend = _make_gpio_backend()
        return self._backend

    def _perform(self, command: Command) -> None:
        value = command.action != "off"
        self._resolve_backend()(self._pin, value)

    @classmethod
    def from_config(cls, cfg: dict[str, Any], *, transport: Any = None) -> "GrowLightActuator":
        return cls(cfg["id"], cfg.get("name", cfg["id"]), cfg["pin"])
```

> If your actuator is wired to the **Arduino** rather than the Pi's GPIO, copy
> `SerialActuator` (`farm_agent/actuators/serial_actuator.py`) instead: its
> `_perform` writes a command line over the shared serial transport, and its
> `from_config` takes the injected `transport`.

### Step 2 — Make the module import on package load

The register decorator runs only when the module is imported. Add yours to
`farm_agent/actuators/__init__.py`:

```python
from farm_agent.actuators import relay, serial_actuator, fake, grow_light  # noqa: F401
```

Without this line the factory raises `Unknown actuator type 'grow_light'` when it
tries to build it.

### Step 3 — Add a wiring entry

Add the device to your wiring config (see
[adding-a-sensor.md](adding-a-sensor.md) Step 3 for the file layout). In the
`actuators` list:

```json
{
  "actuators": [
    {"type": "relay",      "id": "pump_1",  "name": "Water pump", "pin": 17},
    {"type": "grow_light", "id": "light_1", "name": "Grow light", "pin": 27}
  ]
}
```

An actuator entry needs `type` and `id`; the `relay`/`grow_light` types also need a
`pin`.

### Step 4 — Add safety limits in policy

Every actuator should have safety limits so the guard can protect it. In your policy
config, under `"safety"`:

```json
{
  "safety": {
    "pump_1":  {"max_runtime_s": 300, "cooldown_s": 600, "max_activations_per_day": 24, "mutually_exclusive_with": []},
    "light_1": {"max_runtime_s": 43200, "cooldown_s": 60, "max_activations_per_day": 48, "mutually_exclusive_with": []}
  }
}
```

What each limit does:

- `max_runtime_s` — an `on` command's `duration_s` is **clamped** to this.
- `cooldown_s` — minimum seconds between activations.
- `max_activations_per_day` — hard cap in a rolling 24h.
- `mutually_exclusive_with` — ids of actuators that must not be on at the same time.

If you omit a `safety` block for an actuator, conservative defaults apply
(`max_runtime_s=300`, no cooldown, effectively unlimited activations). See
[configuring-rules.md](configuring-rules.md) for the full picture, including how to
map a sensor deviation to an automatic command.

### Step 5 — Run in simulation and send a guarded command

In simulation, actuators are replaced by `FakeActuator` (it records commands instead
of touching a pin), so you can safely exercise the whole path. Guarded endpoints
need `API_TOKEN` set.

```bash
# Git Bash / macOS / Linux
SIMULATE=true API_TOKEN=dev-secret \
  WIRING_CONFIG=my-wiring.json \
  POLICY_CONFIG=my-policy.json \
  python app.py
```

```powershell
# Windows PowerShell
$env:SIMULATE = "true"; $env:API_TOKEN = "dev-secret"
$env:WIRING_CONFIG = "my-wiring.json"; $env:POLICY_CONFIG = "my-policy.json"
./.venv/Scripts/python.exe app.py
```

Check it is present:

```bash
curl http://localhost:8080/actuators
```

Expected (note `kind` shows `"fake"` in simulation — the fake stands in for the real
device):

```json
{"actuators": [
  {"id": "pump_1",  "name": "Water pump", "kind": "fake", "is_on": false, "since": null},
  {"id": "light_1", "name": "Grow light", "kind": "fake", "is_on": false, "since": null}
]}
```

Now send a command through the guarded endpoint:

```bash
curl -X POST http://localhost:8080/actuators/light_1/command \
  -H "Authorization: Bearer dev-secret" \
  -H "Content-Type: application/json" \
  -d '{"action": "on", "duration_s": 120}'
```

Expected (`accepted: true`; the guard may clamp `duration_s` to `max_runtime_s`):

```json
{"actuator_id": "light_1", "accepted": true, "applied": {"actuator_id": "light_1", "action": "on", "duration_s": 120, ...}, "reason": null, "timestamp": "..."}
```

Status codes you may see from this endpoint:

- `200` — accepted (possibly clamped).
- `422` — rejected by the guard; the body carries the `reason` (e.g. in cooldown,
  over daily cap, or a mutually-exclusive actuator is on).
- `403` — no/invalid token, or `API_TOKEN` not configured.
- `404` — unknown actuator id.

Turn it off again:

```bash
curl -X POST http://localhost:8080/actuators/light_1/command \
  -H "Authorization: Bearer dev-secret" \
  -H "Content-Type: application/json" \
  -d '{"action": "off"}'
```

---

## What NOT to touch

- Do **not** edit `Actuator` in `actuators/base.py`, the `ActuatorController`, the
  guard, or the web layer. New actuator types plug in through the registry alone.
- Do **not** call `actuator.apply(...)` from anywhere — always go through the
  controller so the guard, watchdog, dry-run, and event log run.
- Do **not** put safety logic in your actuator class; it belongs in policy config and
  the guard.

---

## Verify it worked

You have added an actuator successfully when:

1. The app starts with no import or config errors.
2. `curl http://localhost:8080/actuators` lists your new id.
3. `curl http://localhost:8080/actuators/<id>` returns its state (404 would mean it
   is not wired in).
4. A guarded `POST /actuators/<id>/command` with `{"action":"on"}` returns
   `accepted: true`, and a follow-up `GET /actuators/<id>` shows `is_on: true`.
5. `GET /events` shows an `actuation` event for the command.
