# API Endpoints Reference

Every HTTP endpoint exposed by the farm-agent Flask app. The HTTP layer is a thin
JSON shell over the injected `SensorHub`, `ActuatorController`, `ControlCycle`
and `EventStore` (see [`farm_agent/web/app.py`](../../farm_agent/web/app.py)).

All responses are JSON. The base URL defaults to `http://localhost:8080`
(the port comes from the `PORT` env var; see
[config-schema.md](config-schema.md#environment-variables)).

## Authentication

Only routes that can **move hardware** require a token (see
[`farm_agent/web/auth.py`](../../farm_agent/web/auth.py) and the
[web-api module doc](../modules/web-api.md)). Auth is **fail-closed**:

- If **no** `API_TOKEN` is configured, every guarded route returns **403**
  (the endpoint is disabled, not left open).
- If a token **is** configured, the request must present it, either as
  `Authorization: Bearer <API_TOKEN>` (preferred) or the `X-API-Token: <API_TOKEN>`
  header. A missing or wrong token returns **403**.

Read routes are always open.

## Endpoint summary

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET  | `/`                         | no  | Service info |
| GET  | `/health`                   | no  | Liveness probe |
| GET  | `/sensor`                   | no  | Back-compat combined soil + temperature reading |
| GET  | `/sensors`                  | no  | All sensors, each read once |
| GET  | `/sensors/<id>`             | no  | One sensor by id |
| GET  | `/actuators`                | no  | All actuators and their current state |
| GET  | `/actuators/<id>`           | no  | One actuator by id |
| POST | `/actuators/<id>/command`   | **yes** | Manual command through the safety guard |
| POST | `/control/tick`             | **yes** | Run one sense → decide → act cycle |
| GET  | `/control/status`           | no  | Loop, strategy, sensor and actuator status |
| GET  | `/events?n=`                | no  | Recent audit events |

Status codes used across the API: **200** (OK), **403** (auth failure on a
guarded route), **404** (unknown sensor/actuator id), **422** (command accepted
by HTTP but rejected by the safety guard), **503** (serial transport fully down,
`/sensor` only).

---

## GET /

Service information. Always 200.

**Request**

```bash
curl http://localhost:8080/
```

**Response** `200 OK`

```json
{
  "application": "farm-agent",
  "status": "running",
  "message": "Smart-farm sensor + actuator API"
}
```

| Status | When |
|--------|------|
| 200 | Always |

---

## GET /health

Liveness probe. Always 200.

**Request**

```bash
curl http://localhost:8080/health
```

**Response** `200 OK`

```json
{"status": "healthy"}
```

| Status | When |
|--------|------|
| 200 | Always |

---

## GET /sensor

**Back-compatibility** endpoint that reproduces the original app's combined
output: the `soil_raw` and `temperature_c` values from the sensors with ids
`soil_1` and `temp_1`. Prefer [`/sensors`](#get-sensors) for new clients.

**Request**

```bash
curl http://localhost:8080/sensor
```

**Response** `200 OK`

```json
{
  "sensor": "capacitive-soil-moisture-and-DS18B20",
  "soil_raw": 512.0,
  "temperature_c": 21.5,
  "timestamp": "2026-10-11T12:00:00+00:00"
}
```

If either `soil_1` or `temp_1` is not configured, its value is `null`. The
endpoint returns **503** only when the soil sensor failed **and** the
temperature sensor is missing or also failed (i.e. the Arduino transport is
fully down):

**Response** `503 Service Unavailable`

```json
{
  "error": "Unable to read Arduino sensors",
  "details": "serial port /dev/arduino not available"
}
```

| Status | When |
|--------|------|
| 200 | At least one of the two sensors read successfully (or exists) |
| 503 | Soil read failed and temperature is missing/failed (transport down) |

---

## GET /sensors

Reads every configured sensor once and returns all readings. Returns **200**
even if some individual readings have `ok: false` — one broken sensor never
breaks the batch.

**Request**

```bash
curl http://localhost:8080/sensors
```

**Response** `200 OK`

```json
{
  "sensors": [
    {
      "sensor_id": "soil_1",
      "name": "Soil moisture",
      "value": 512.0,
      "unit": "raw",
      "timestamp": "2026-10-11T12:00:00+00:00",
      "ok": true,
      "error": null
    },
    {
      "sensor_id": "temp_1",
      "name": "Air/soil temperature",
      "value": null,
      "unit": "°C",
      "timestamp": "2026-10-11T12:00:00+00:00",
      "ok": false,
      "error": "field 'temperature_c' missing from frame"
    }
  ]
}
```

| Status | When |
|--------|------|
| 200 | Always (failed sensors appear with `ok: false`) |

---

## GET /sensors/\<id\>

Reads a single sensor by id.

**Request**

```bash
curl http://localhost:8080/sensors/soil_1
```

**Response** `200 OK`

```json
{
  "sensor_id": "soil_1",
  "name": "Soil moisture",
  "value": 512.0,
  "unit": "raw",
  "timestamp": "2026-10-11T12:00:00+00:00",
  "ok": true,
  "error": null
}
```

**Response** `404 Not Found`

```json
{"error": "Unknown sensor 'soil_99'"}
```

| Status | When |
|--------|------|
| 200 | Sensor exists (even if the read itself failed, with `ok: false`) |
| 404 | No sensor with that id |

---

## GET /actuators

Lists every actuator and its current state (no action is taken).

**Request**

```bash
curl http://localhost:8080/actuators
```

**Response** `200 OK`

```json
{
  "actuators": [
    {
      "id": "pump_1",
      "name": "Water pump",
      "kind": "relay",
      "is_on": false,
      "since": null
    }
  ]
}
```

| Status | When |
|--------|------|
| 200 | Always |

---

## GET /actuators/\<id\>

Returns one actuator's state.

**Request**

```bash
curl http://localhost:8080/actuators/pump_1
```

**Response** `200 OK`

```json
{
  "id": "pump_1",
  "name": "Water pump",
  "kind": "relay",
  "is_on": true,
  "since": "2026-10-11T12:00:00+00:00"
}
```

**Response** `404 Not Found`

```json
{"error": "Unknown actuator 'pump_99'"}
```

| Status | When |
|--------|------|
| 200 | Actuator exists |
| 404 | No actuator with that id |

---

## POST /actuators/\<id\>/command

**Guarded.** Submit a manual command for one actuator. The HTTP layer builds a
`Command` with `source: "manual"` and passes it to the
`ActuatorController`, which runs the [safety guard](../modules/safety-guard.md)
first. A command the guard rejects returns **422** with the reason; nothing
fires.

**Request body** (all fields optional):

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `action` | string | `"on"` | `"on"`, `"off"` or `"set"` |
| `duration_s` | number \| null | `null` | Auto-off after N seconds (clamped to `max_runtime_s`) |
| `params` | object | `{}` | Pass-through parameters for the actuator |

**Example request (guarded POST, with token)**

```bash
curl -X POST http://localhost:8080/actuators/pump_1/command \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "on", "duration_s": 120}'
```

**Response** `200 OK` (accepted; may be clamped)

```json
{
  "actuator_id": "pump_1",
  "accepted": true,
  "applied": {
    "actuator_id": "pump_1",
    "action": "on",
    "duration_s": 120,
    "params": {},
    "source": "manual",
    "timestamp": "2026-10-11T12:00:00+00:00"
  },
  "reason": null,
  "timestamp": "2026-10-11T12:00:00+00:00"
}
```

**Response** `422 Unprocessable Entity` (guard rejected it)

```json
{
  "actuator_id": "pump_1",
  "accepted": false,
  "applied": null,
  "reason": "pump_1 is in cooldown for another 480s",
  "timestamp": "2026-10-11T12:00:00+00:00"
}
```

**Response** `403 Forbidden` (no/invalid token)

```json
{"error": "Invalid or missing API token."}
```

(If no `API_TOKEN` is configured at all, the body is instead
`{"error": "This endpoint is disabled because no API_TOKEN is configured."}`.)

**Response** `404 Not Found`

```json
{"error": "Unknown actuator 'pump_99'"}
```

| Status | When |
|--------|------|
| 200 | Command accepted by the guard (possibly clamped) |
| 403 | No token configured, or token missing/invalid |
| 404 | No actuator with that id |
| 422 | Command rejected by the safety guard (see `reason`) |

---

## POST /control/tick

**Guarded.** Runs one `ControlCycle.run_once()`: read all sensors → find
deviations against policy targets → let the decision strategy propose commands →
execute each through the safety-guarded controller → record audit events. Returns
a summary of the whole cycle.

**Request**

```bash
curl -X POST http://localhost:8080/control/tick \
  -H "Authorization: Bearer $API_TOKEN"
```

**Response** `200 OK`

```json
{
  "strategy": "local_rules",
  "readings": [
    {"sensor_id": "soil_1", "name": "Soil moisture", "value": 350.0,
     "unit": "raw", "timestamp": "2026-10-11T12:00:00+00:00",
     "ok": true, "error": null}
  ],
  "deviations": [
    {"sensor_id": "soil_1", "metric": "soil_1", "value": 350.0,
     "target_low": 400.0, "target_high": 800.0, "direction": "low"}
  ],
  "commands": [
    {"actuator_id": "pump_1", "action": "on", "duration_s": 180,
     "params": {}, "source": "local_rules",
     "timestamp": "2026-10-11T12:00:00+00:00"}
  ],
  "results": [
    {"actuator_id": "pump_1", "accepted": true, "applied": { "...": "..." },
     "reason": null, "timestamp": "2026-10-11T12:00:00+00:00"}
  ],
  "note": null
}
```

| Status | When |
|--------|------|
| 200 | Cycle ran (individual commands may still have been rejected; see `results`) |
| 403 | No token configured, or token missing/invalid |

---

## GET /control/status

Returns the current control-loop configuration and live state. Open (no auth).

**Request**

```bash
curl http://localhost:8080/control/status
```

**Response** `200 OK`

```json
{
  "strategy": "local_rules",
  "dry_run": false,
  "sensors": [
    {"id": "soil_1", "name": "Soil moisture", "kind": "soil_moisture"},
    {"id": "temp_1", "name": "Air/soil temperature", "kind": "temperature"}
  ],
  "actuators": [
    {"id": "pump_1", "name": "Water pump", "kind": "relay",
     "is_on": false, "since": null}
  ]
}
```

| Status | When |
|--------|------|
| 200 | Always |

---

## GET /events?n=

Returns the most recent audit events (readings, deviations, decisions,
actuations), newest last. The `n` query parameter limits the count (default
**50**); a non-integer value falls back to 50.

**Request**

```bash
curl "http://localhost:8080/events?n=5"
```

**Response** `200 OK`

```json
{
  "events": [
    {
      "type": "reading",
      "payload": {"sensor_id": "soil_1", "value": 350.0, "ok": true, "...": "..."},
      "timestamp": "2026-10-11T12:00:00+00:00"
    },
    {
      "type": "actuation",
      "payload": {"requested": { "...": "..." }, "result": { "...": "..." }, "dry_run": false},
      "timestamp": "2026-10-11T12:00:01+00:00"
    }
  ]
}
```

| Status | When |
|--------|------|
| 200 | Always |

---

## Related

- [config-schema.md](config-schema.md) — env vars (`API_TOKEN`, `PORT`, …) and config files
- [sensor-types.md](sensor-types.md) — the sensor kinds returned by `/sensors`
- [actuator-types.md](actuator-types.md) — the actuator kinds driven by `/actuators/<id>/command`
- [web-api module doc](../modules/web-api.md) · [safety-guard module doc](../modules/safety-guard.md)
