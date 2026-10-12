# Removing a Device

This guide removes a sensor or an actuator cleanly. Because the framework is
config-driven, removal is mostly the reverse of adding: **delete one wiring line**,
and the device is gone. Deleting the Python module is optional cleanup.

The golden rule: a device exists at runtime **only if it has a wiring-config entry**.
The registry can know about a type without any device of that type being built.

---

## Step 1 — Decide how far you want to go

There are three levels of removal, from least to most thorough:

1. **Disable it** (reversible, recommended first) — remove its entry from the
   `sensors` or `actuators` list in your wiring config. The device is no longer built
   and no longer appears at `/sensors` or `/actuators`. The code stays in the repo.
2. **Remove the module too** — also delete the `.py` file and its import line. Do
   this when the device type will never be used again.
3. Nothing else. There is no database or cache to clean up.

Start with level 1; it is enough to make the device disappear.

---

## Step 2 — Delete the wiring-config line

Open your wiring config (the file `WIRING_CONFIG` points at, or
`farm_agent/config/defaults.py` if you are using the built-in defaults) and remove
the entry.

### Removing a sensor

Before:

```json
"sensors": [
  {"type": "soil_moisture", "id": "soil_1", "name": "Soil moisture", "field": "soil_raw"},
  {"type": "temperature",   "id": "temp_1", "name": "Air/soil temperature", "field": "temperature_c"},
  {"type": "humidity",      "id": "hum_1",  "name": "Relative humidity"}
]
```

After (humidity removed):

```json
"sensors": [
  {"type": "soil_moisture", "id": "soil_1", "name": "Soil moisture", "field": "soil_raw"},
  {"type": "temperature",   "id": "temp_1", "name": "Air/soil temperature", "field": "temperature_c"}
]
```

### Removing an actuator

Delete its object from the `actuators` list the same way, e.g. remove the
`{"type": "grow_light", "id": "light_1", "pin": 27}` entry.

> Mind the JSON commas: after deleting the last item in a list, make sure the new
> last item has **no** trailing comma, or the file will fail to parse.

---

## Step 3 — Clean up policy references (important)

Policy config can reference a device id. These references do no harm if left
(targets and safety blocks for a missing device are simply never consulted), but it
is tidy to remove them, and it avoids confusion:

- **For a removed sensor:** delete its entry under `"targets"`, and any rule under
  `"rules"` keyed by that sensor id.
- **For a removed actuator:** delete its entry under `"safety"`, and check that no
  rule's `"actuator_id"` still points at it. A rule that targets a deleted actuator
  would, if its sensor deviates, produce a command for an id the controller does not
  have — the controller raises `KeyError` and the web layer returns `404` for a
  manual call; in a control tick it would error on that command. So remove dangling
  rules.

Example — removing the soil sensor means also removing its target **and** the pump
rule that depended on it:

```json
"targets": {
  "temp_1": {"low": 5, "high": 35}
},
"rules": {}
```

---

## Step 4 (optional) — Delete the module and its import

If you are retiring the device type entirely:

1. Delete the module file, e.g. `farm_agent/sensors/humidity.py` or
   `farm_agent/actuators/grow_light.py`.
2. Remove its name from the package `__init__.py` import list:
   - sensors: edit the import block in `farm_agent/sensors/__init__.py`.
   - actuators: edit the import line in `farm_agent/actuators/__init__.py`.

If you delete the module but forget to remove the import line, the package will fail
to import with a `ModuleNotFoundError` at startup. If you remove the import line but
leave the module file, the module just never loads and its type never registers —
harmless, but dead code.

---

## What NOT to touch

- **Do not edit** `registry.py`, `sensors/base.py`, `actuators/base.py`, the hub, the
  controller, or the web layer. None of them hard-code device ids.
- **Do not** remove a built-in type's import if another wiring entry still uses that
  `type`. Removing one *instance* (a wiring line) is independent of removing the
  *type* (the class + import).
- **Do not** leave a rule whose `actuator_id` points at a deleted actuator (see
  Step 3).

---

## Step 5 — Restart and verify it is gone

Restart the app with your config:

```bash
# Git Bash / macOS / Linux
SIMULATE=true WIRING_CONFIG=my-wiring.json POLICY_CONFIG=my-policy.json python app.py
```

```powershell
# Windows PowerShell
$env:SIMULATE = "true"; $env:WIRING_CONFIG = "my-wiring.json"; $env:POLICY_CONFIG = "my-policy.json"
./.venv/Scripts/python.exe app.py
```

### Verify a removed sensor

```bash
curl http://localhost:8080/sensors            # the id should NOT be listed
curl -i http://localhost:8080/sensors/hum_1   # should return HTTP 404
```

A `404` from `/sensors/<id>` and the id's absence from `/sensors` confirms the sensor
is gone.

### Verify a removed actuator

```bash
curl http://localhost:8080/actuators            # the id should NOT be listed
curl -i http://localhost:8080/actuators/light_1 # should return HTTP 404
```

---

## Verify it worked

Removal is complete when:

1. The app starts with no import or config errors.
2. The device id no longer appears in `/sensors` (or `/actuators`).
3. Requesting it by id returns `404`.
4. If you deleted the module, `python -m pytest` still passes (nothing imported the
   deleted module).
