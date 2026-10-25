# Getting Started

This guide gets the farm-agent running on your machine **with no hardware at all**,
using the built-in simulation mode. You will create a virtual environment, install
the dependencies, run the app, poke a few endpoints, run it in Docker, and finally
run the test suite.

You do **not** need an Arduino, a Raspberry Pi, or any sensors to follow this guide.

> **New to the project?** The one thing to remember: the app always boots with sane
> defaults, and `SIMULATE=true` replaces every piece of hardware with a fake. So you
> can run the whole sense -> decide -> act loop on a laptop.

---

## What you need

- Python 3.10 or newer (the project is developed against 3.12).
- `git` (you already have the repo).
- Optional, for the Docker section: Docker Desktop.

All commands below are shown twice where it matters:

- **Windows (project venv):** `./.venv/Scripts/python.exe ...`
- **Plain / cross-platform:** `python ...`

Run them from the repository root: `C:\Users\Daryl\Documents\BIZ\farm-agent`.

---

## Step 1 — Create the virtual environment

```powershell
# Windows (PowerShell), from the repo root
python -m venv .venv
```

```bash
# macOS / Linux
python3 -m venv .venv
```

This creates a `.venv/` folder. You do **not** have to "activate" it — you can call
the interpreter inside it directly, which is what the commands in these guides do:

```powershell
# Windows
./.venv/Scripts/python.exe --version
```

```bash
# macOS / Linux
./.venv/bin/python --version
```

If you prefer to activate it (so a plain `python` points at the venv):

```powershell
# Windows PowerShell
./.venv/Scripts/Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

---

## Step 2 — Install the requirements

```powershell
# Windows
./.venv/Scripts/python.exe -m pip install --upgrade pip
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

```bash
# macOS / Linux (or with the venv activated)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` includes Flask, pyserial, the Adafruit/Raspberry Pi hardware
libraries, and pytest. Do not worry about the hardware libraries — they are imported
**lazily** and are only touched when you actually drive real hardware, so everything
works on a laptop. (The `RPi.GPIO` line is pinned to ARM platforms, so pip simply
skips it on a normal PC.)

---

## Step 3 — Run the app in simulation mode

Simulation (`SIMULATE=true`) swaps the real serial link and hardware buses for
in-memory fakes and uses fake actuators, so nothing touches hardware.

```powershell
# Windows PowerShell
$env:SIMULATE = "true"
./.venv/Scripts/python.exe app.py
```

```bash
# macOS / Linux (or Git Bash on Windows)
SIMULATE=true python app.py
```

You should see Flask start up and listen on port **8080** (set `PORT` to change it).
Leave this terminal running and open a **second** terminal for the next step.

---

## Step 4 — Hit the endpoints

In your second terminal, call the read-only endpoints. These examples use `curl`
(available in Git Bash and modern Windows). PowerShell users can also use
`Invoke-RestMethod`.

### Health check

```bash
curl http://localhost:8080/health
```

Expected:

```json
{"status": "healthy"}
```

### All sensors + their current readings

```bash
curl http://localhost:8080/sensors
```

Expected (values come from the simulated Arduino frame — soil `300`, temp `22.0`):

```json
{
  "sensors": [
    {"sensor_id": "soil_1", "name": "Soil moisture", "value": 300.0, "unit": "raw",  "ok": true,  "error": null, "timestamp": "..."},
    {"sensor_id": "temp_1", "name": "Air/soil temperature", "value": 22.0, "unit": "\u00b0C", "ok": true, "error": null, "timestamp": "..."}
  ]
}
```

### Control-loop status

```bash
curl http://localhost:8080/control/status
```

Expected (shows the selected strategy, dry-run flag, and the wired devices):

```json
{
  "strategy": "local_rules",
  "dry_run": false,
  "sensors":  [ ... ],
  "actuators":[ {"id": "pump_1", "name": "Water pump", "kind": "fake", "is_on": false, "since": null} ]
}
```

> **Note on the actuator `kind`:** in simulation every actuator is a `FakeActuator`,
> so `kind` shows `"fake"` even though the wiring declares a `relay`. That is
> expected — the fake records commands instead of toggling a GPIO pin.

A couple more worth knowing:

```bash
curl http://localhost:8080/sensors/soil_1     # one sensor (404 if unknown)
curl http://localhost:8080/actuators          # actuator states
curl "http://localhost:8080/events?n=20"      # recent audit events
```

When you are done, stop the app with `Ctrl+C` in the first terminal.

---

## Step 5 — Environment variables you can set

The app is configured entirely through environment variables. The important ones:

| Variable | What it does | Default |
|----------|--------------|---------|
| `SIMULATE` | `true` -> fake transport, fake buses, fake actuators. No hardware needed. | `false` |
| `DRY_RUN` | `true` -> real sensing, but actuator commands are **logged, not fired**. Safe on a real farm. | `false` |
| `API_TOKEN` | Bearer token required to call the mutating endpoints (`POST /actuators/<id>/command`, `POST /control/tick`). If unset, those endpoints are **disabled** (403). | unset |
| `WIRING_CONFIG` | Path to a JSON file describing which devices exist and their ports. If unset, built-in defaults are used. | unset (defaults) |
| `POLICY_CONFIG` | Path to a JSON file with target ranges, rules, safety limits, and strategy. If unset, built-in defaults are used. | unset (defaults) |
| `PORT` | Port Flask listens on. | `8080` |

See [simulation-and-dry-run.md](simulation-and-dry-run.md) for `SIMULATE` vs `DRY_RUN`,
and [configuring-rules.md](configuring-rules.md) for `POLICY_CONFIG`.

### Example: calling a guarded endpoint

Guarded endpoints need `API_TOKEN` set **and** the matching token in the request.
Restart the app with a token:

```bash
# terminal 1
SIMULATE=true API_TOKEN=dev-secret python app.py
```

```bash
# terminal 2 — run one full control cycle (sense -> decide -> act)
curl -X POST http://localhost:8080/control/tick \
  -H "Authorization: Bearer dev-secret"
```

Without the header you get `403`. The token can be sent as
`Authorization: Bearer <token>` or as the `X-API-Token: <token>` header.

---

## Step 6 — Run it in Docker

The `Dockerfile` builds a slim image and runs `python app.py`. Build and run it,
passing the same environment variables with `-e`:

```bash
# from the repo root
docker build -t farm-agent .

docker run --rm -p 8080:8080 -e SIMULATE=true farm-agent
```

Then, from another terminal, verify exactly as in Step 4:

```bash
curl http://localhost:8080/health
curl http://localhost:8080/sensors
```

To run with a token and dry-run instead of full simulation:

```bash
docker run --rm -p 8080:8080 \
  -e DRY_RUN=true -e API_TOKEN=dev-secret \
  farm-agent
```

Stop the container with `Ctrl+C`.

---

## Step 7 — Run the tests

The test suite uses `pytest` and runs entirely without hardware (it uses the same
fakes simulation does). `pyproject.toml` already points pytest at the `tests/`
directory, so you can run it from the repo root with no arguments:

```powershell
# Windows
./.venv/Scripts/python.exe -m pytest
```

```bash
# macOS / Linux (or venv activated)
python -m pytest
```

Useful variations:

```bash
python -m pytest -v                 # verbose, one line per test
python -m pytest tests/test_web.py  # just the web-layer tests
python -m pytest -k guard           # only tests whose name matches "guard"
```

---

## Verify it worked

You are set up correctly if **all** of these are true:

1. `./.venv/Scripts/python.exe -m pip install -r requirements.txt` finished without errors.
2. `SIMULATE=true python app.py` starts and `curl http://localhost:8080/health`
   returns `{"status": "healthy"}`.
3. `curl http://localhost:8080/sensors` returns two sensors (`soil_1`, `temp_1`)
   both with `"ok": true`.
4. `docker build -t farm-agent .` succeeds and the container answers `/health`.
5. `python -m pytest` reports all tests passing.

If `/sensors` shows `"ok": false`, you are probably **not** in simulation — make sure
`SIMULATE` is set to `true` in the terminal that runs `app.py`.

Next steps:
- Add your own sensor — [adding-a-sensor.md](adding-a-sensor.md).
- Write and run tests for it — [testing.md](testing.md).
- Deploy to real hardware — [running-on-raspberry-pi.md](running-on-raspberry-pi.md).
