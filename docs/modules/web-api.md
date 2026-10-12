# Web API

A thin Flask layer that shapes JSON and maps outcomes to HTTP status codes, delegating all real work to injected collaborators — with a token-protected seam on every route that can move hardware.

## What it does

The HTTP layer is deliberately **thin**: it does no sensing, deciding, or acting itself. It is a Flask **application factory**, `create_app`, that receives its collaborators by injection (dependency inversion) and simply translates between JSON requests/responses and the domain objects. All the behaviour lives in the hub, controller, and cycle it is handed.

### `create_app(hub, controller, cycle, event_store, *, api_token=None) -> Flask`

Builds and returns the Flask app. If `api_token` is provided it is stored in `app.config["API_TOKEN"]`. The factory wires up every route below.

### Authentication (`auth.py`)

`require_token` is a decorator applied to routes that can move hardware. It is a **starter seam, not a hardened auth system**:

- It reads the configured token from `app.config["API_TOKEN"]` or the `API_TOKEN` env var.
- **Fail-closed:** if no token is configured, the guarded route is refused with **403** outright (rather than left open).
- If a token is configured but the request's token does not match, it returns **403**.
- The token is read from an `Authorization: Bearer <token>` header, or failing that an `X-API-Token` header.

### Routes

| Route | Auth | Behaviour & status codes |
|-------|------|--------------------------|
| `GET /` | no | Service info JSON. 200. |
| `GET /health` | no | `{"status": "healthy"}`. 200. |
| `GET /sensor` | no | **Back-compat** endpoint (see below). 200, or **503** if the Arduino sensors can't be read. |
| `GET /sensors` | no | All sensors + readings (`hub.read_all()`). 200 even if some readings have `ok=false`. |
| `GET /sensors/<id>` | no | One sensor's reading. 200, or **404** if the id is unknown. |
| `GET /actuators` | no | All actuators + current state (`controller.states()`). 200. |
| `GET /actuators/<id>` | no | One actuator's state. 200, or **404** if unknown. |
| `POST /actuators/<id>/command` | **yes** | Manual command through the guarded controller. 200 accepted, **422** rejected (with reason), **404** unknown id, **403** no/invalid token. |
| `POST /control/tick` | **yes** | Run one `cycle.run_once()`; returns the summary. 200 (**403** without token). |
| `GET /control/status` | no | Loop + actuator + strategy snapshot (`cycle.status()`). 200. |
| `GET /events?n=` | no | The `n` most recent events (default 50; a non-integer `n` falls back to 50). 200. |

**Status code summary:** `200` success · `403` missing/invalid token on a guarded route · `404` unknown sensor/actuator id · `422` command rejected by the safety guard (body carries the reason) · `503` the back-compat `/sensor` endpoint when the Arduino sensors are all unreadable.

### The `/sensor` back-compat endpoint

`GET /sensor` preserves the original app's contract: a single combined payload with `soil_raw` and `temperature_c` (plus a timestamp and a fixed `sensor` label). It reads all sensors and picks out `soil_1` and `temp_1`. If the soil reading failed **and** temperature is missing or also failed, it returns **503** with an error — matching the original "Arduino unreadable" behaviour. New code should prefer `GET /sensors`.

### The command route and the safety model

`POST /actuators/<id>/command` builds a `Command` (with `source="manual"`) from the JSON body (`action` defaulting to `"on"`, plus optional `duration_s` and `params`) and calls `controller.execute(...)`. This is important: even a manual web command goes through the **same guarded controller** as everything else — **decision proposes, guard disposes** applies to humans too. An unknown id surfaces as `KeyError` → 404; a guard rejection surfaces as `accepted=false` → 422 with the reason.

## How to use it

1. Build the collaborators (hub, controller, cycle, event store) — normally done by the thin `app.py` entrypoint.
2. Call `create_app(...)`, passing an `api_token` (or set `API_TOKEN` in the environment).
3. Run the returned Flask app.

```python
from farm_agent.web.app import create_app

app = create_app(hub, controller, cycle, event_store, api_token="s3cret")
app.run(host="0.0.0.0", port=5000)
```

Calling a guarded route (note the fail-closed behaviour if no token is configured):

```bash
# Read routes are open:
curl http://localhost:5000/sensors

# A manual command needs the token:
curl -X POST http://localhost:5000/actuators/pump_1/command \
     -H "Authorization: Bearer s3cret" \
     -H "Content-Type: application/json" \
     -d '{"action": "on", "duration_s": 120}'
```

## What it depends on

- `flask` — `Flask`, `jsonify`, `request` (and `current_app` in `auth.py`).
- `farm_agent.sensors.hub.SensorHub` — read routes.
- `farm_agent.control.controller.ActuatorController` — actuator state and the command chokepoint (see [controller.md](controller.md)).
- `farm_agent.control.cycle.ControlCycle` — `POST /control/tick` and `GET /control/status` (see [control-cycle.md](control-cycle.md)).
- `farm_agent.events.store.EventStore` — `GET /events`.
- `farm_agent.models.Command` — built from the command request body.
- `farm_agent.web.auth.require_token` + the `API_TOKEN` env var — the auth seam.

## Example

Exercising the auth and status codes with Flask's test client (the shape used in the test suite):

```python
from farm_agent.web.app import create_app

app = create_app(hub, controller, cycle, event_store, api_token="s3cret")
client = app.test_client()

# Open read route:
assert client.get("/sensors").status_code == 200

# Guarded route without a token -> 403:
assert client.post("/actuators/pump_1/command", json={"action": "on"}).status_code == 403

# Unknown actuator -> 404:
r = client.post("/actuators/ghost/command",
                json={"action": "on"},
                headers={"Authorization": "Bearer s3cret"})
assert r.status_code == 404

# Guard rejection (e.g. in cooldown) -> 422 with a reason:
r = client.post("/actuators/pump_1/command",
                json={"action": "on"},
                headers={"Authorization": "Bearer s3cret"})
if r.status_code == 422:
    print(r.get_json()["reason"])
```

## Where it lives

- `farm_agent/web/app.py` — `create_app` and all route handlers.
- `farm_agent/web/auth.py` — `require_token` and token extraction.
