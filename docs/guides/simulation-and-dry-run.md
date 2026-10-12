# Simulation and Dry-Run

The framework has two safety modes that let you exercise the whole system **without
risking a real farm**. They are different, they solve different problems, and you can
use them in sequence as you move from laptop to field. This guide explains both and
shows how to test the full control loop safely.

| Mode | Sensors | Actuators | Needs hardware? | Use it to... |
|------|---------|-----------|-----------------|--------------|
| `SIMULATE=true` | **Fake** transport + buses (invented readings) | **Fake** (record commands, touch nothing) | No | Develop and test logic on any machine / CI. |
| `DRY_RUN=true`  | **Real** sensing | Real actuators, but commands are **logged, not fired** | Yes (for real sensing) | Validate decisions against real readings before anything moves. |
| (neither)       | Real | Real, **fired** | Yes | Actually run the farm. |

The two flags are independent. You can even set both (real-ish? no — simulate wins
for transport/actuators; dry-run then just suppresses the fake "apply" too). In
practice you use **one at a time**.

---

## SIMULATE — no hardware at all

`SIMULATE=true` tells the composition root (`farm_agent/bootstrap.py`) to wire in:

- `SimulatedTransport` instead of the real serial link — it returns a fixed, sane
  Arduino frame (`soil_raw = 300`, `temperature_c = 22.0`) and records any command
  lines written to it.
- `SimBuses` instead of real I2C/1-Wire buses — it hands each direct sensor
  (ADS1115, DS18B20) a simulated device, so direct sensors return live simulated
  values too, with no hardware or vendor libraries.
- `FakeActuator` for **every** actuator — it records each `Command` instead of
  toggling a GPIO pin.

Because nothing touches hardware, this is the default for development and CI, and it
is what the test suite uses. The readings are deterministic (no randomness), so
behaviour is reproducible.

### When to use SIMULATE

- Writing or changing a sensor/actuator class.
- Testing policy: targets, rules, safety limits (see
  [configuring-rules.md](configuring-rules.md)).
- Running the full `sense -> decide -> act` loop on your laptop.
- CI / `pytest`.

### Run it

```bash
# Git Bash / macOS / Linux
SIMULATE=true API_TOKEN=dev-secret python app.py
```

```powershell
# Windows PowerShell
$env:SIMULATE = "true"; $env:API_TOKEN = "dev-secret"
./.venv/Scripts/python.exe app.py
```

The default simulated soil value (`300`) is below the default target (`400`), so a
control tick will *decide* to run the pump — and because the pump is a `FakeActuator`,
it records the command instead of running a motor:

```bash
curl -X POST http://localhost:8080/control/tick -H "Authorization: Bearer dev-secret"
```

You will see a deviation, a pump command, and `accepted: true` — with zero hardware.

---

## DRY_RUN — real sensing, no firing

`DRY_RUN=true` runs **everything for real except the final actuation**. Sensors read
real hardware, the assess/decide/guard pipeline runs normally, every event is
logged — but the `ActuatorController` **does not call the actuator**. Instead it
returns a successful result annotated `"dry-run: not applied"` and logs the command
it *would* have sent.

This is the mode to trust **on a real farm before you let it move anything**. You get
real readings and real decisions, and you can read the event log to confirm the
system would do the right thing — without a single relay clicking.

Key detail from the controller: in dry-run the command still passes the safety guard
first (so a command the guard would reject is still rejected), and only the physical
apply + watchdog scheduling are skipped.

### When to use DRY_RUN

- First boot on real hardware, to confirm sensors read sane values.
- Validating that your rules fire (or correctly do not fire) against live conditions.
- Any time you want to observe the decision loop on the real farm without actuation.

### Run it

```bash
# On the Raspberry Pi, with real sensors attached
DRY_RUN=true API_TOKEN=dev-secret python app.py
```

```bash
# or in Docker
docker run --rm -p 8080:8080 -e DRY_RUN=true -e API_TOKEN=dev-secret farm-agent
```

Then run a cycle and read the log:

```bash
curl -X POST http://localhost:8080/control/tick -H "Authorization: Bearer dev-secret"
curl "http://localhost:8080/events?n=20"
```

You can confirm you are in dry-run at any time:

```bash
curl http://localhost:8080/control/status
# -> {"strategy": "local_rules", "dry_run": true, ...}
```

---

## What the event log shows

Every mode records the same four event types, so the audit trail reads the same way —
only the actuation outcome differs. One control tick produces, in order:

1. `reading` events — one per sensor.
2. `deviation` events — one per out-of-range reading.
3. a `decision` event — the strategy name and the commands it proposed (plus a `note`
   if the strategy is the un-wired LLM stub).
4. `actuation` events — one per command, carrying the `requested` command, the
   `result`, and a `dry_run` flag.

The difference between the modes shows up in the `actuation` event's `result`:

- **SIMULATE:** `accepted: true`, applied to a `FakeActuator` — the command was
  "performed" but on a fake, so nothing physical happened. `dry_run: false`.
- **DRY_RUN:** `accepted: true` with `reason: "dry-run: not applied"` and
  `dry_run: true` — the controller deliberately did **not** fire the device, and no
  auto-off watchdog was scheduled.
- **Real mode:** `accepted: true`, applied to the real actuator, and a watchdog
  auto-off is scheduled for any timed `on` command (you will later see a second
  `actuation` event with `auto_off: true` when it fires).

Fetch them with:

```bash
curl "http://localhost:8080/events?n=50"
```

---

## A safe path from laptop to farm

Recommended sequence before you let the system control a real farm:

1. **SIMULATE on your laptop.** Write/adjust sensors, actuators, and policy. Run
   `python -m pytest`. Tick the loop and read `/events` until the decisions look
   right. (See [getting-started.md](getting-started.md) and
   [configuring-rules.md](configuring-rules.md).)
2. **DRY_RUN on the real hardware.** Deploy to the Pi with real sensors. Confirm
   `/sensors` shows believable values and `/control/tick` proposes the commands you
   expect — with nothing firing. Watch it across real conditions (e.g. let the soil
   actually dry out) and confirm the log says it *would* run the pump.
3. **Real mode.** Only once dry-run has convinced you, drop both flags and run for
   real. The safety guard and watchdog are now your backstop: durations are clamped,
   cooldowns and daily caps enforced, and every timed `on` gets a guaranteed auto-off.

---

## Verify it worked

### SIMULATE

```bash
SIMULATE=true API_TOKEN=dev-secret python app.py
curl http://localhost:8080/control/status   # "dry_run": false, actuators kind "fake"
curl -X POST http://localhost:8080/control/tick -H "Authorization: Bearer dev-secret"
```

You are in simulation if `/sensors` returns values with `ok: true` on a machine with
no hardware, and actuators report `kind: "fake"`.

### DRY_RUN

```bash
DRY_RUN=true API_TOKEN=dev-secret python app.py
curl http://localhost:8080/control/status   # "dry_run": true
curl -X POST http://localhost:8080/control/tick -H "Authorization: Bearer dev-secret"
curl "http://localhost:8080/events?n=10"
```

You are in dry-run if `/control/status` shows `"dry_run": true` and the `actuation`
events carry `reason: "dry-run: not applied"` and `dry_run: true` — proving the loop
decided to act but fired nothing.
