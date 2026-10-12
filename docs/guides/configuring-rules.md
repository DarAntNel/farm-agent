# Configuring Rules

This guide is about **policy config**: the file that decides *what the farm should
do*. You will set target ranges per sensor, map deviations to actuator commands, set
per-actuator safety limits, choose the decision strategy, and point `POLICY_CONFIG`
at your file. It ends by tracing exactly how a dry soil reading becomes a pump
command.

Policy is deliberately separate from **wiring** config:

- **Wiring** = which devices exist and their ports (hardware topology). See
  [adding-a-sensor.md](adding-a-sensor.md).
- **Policy** = behaviour: targets, rules, safety, strategy. That is this guide.

Changing behaviour therefore never requires touching hardware config or code.

---

## The four parts of a policy

A policy JSON file has four top-level keys:

| Key | Purpose |
|-----|---------|
| `strategy` | Which decision maker to use (`"local_rules"` today). |
| `targets` | The acceptable `low`/`high` range per **sensor id**. Outside it = a *deviation*. |
| `rules` | Maps a deviation (`sensor id` + `direction`) to an actuator **command**. |
| `safety` | Per-**actuator** limits the guard enforces on every command. |

Here is a complete, valid policy you can copy as a starting point. It mirrors the
built-in defaults in `farm_agent/config/defaults.py`:

```json
{
  "strategy": "local_rules",

  "targets": {
    "soil_1": {"low": 400, "high": 800},
    "temp_1": {"low": 5,   "high": 35}
  },

  "rules": {
    "soil_1": {
      "low":  {"actuator_id": "pump_1", "action": "on", "duration_s": 180}
    }
  },

  "safety": {
    "pump_1": {
      "max_runtime_s": 300,
      "cooldown_s": 600,
      "max_activations_per_day": 24,
      "mutually_exclusive_with": []
    }
  }
}
```

---

## Step 1 — Set target ranges per sensor

Under `targets`, key each entry by the sensor's **id** (the `id` from wiring, e.g.
`soil_1`), and give it a `low` and a `high`:

```json
"targets": {
  "soil_1": {"low": 400, "high": 800}
}
```

Meaning: a soil reading **below 400** is a deviation with `direction: "low"`; a
reading **above 800** is `direction: "high"`; anything in `[400, 800]` is fine. The
loader rejects a target where `low > high`, so you get a clear error at startup
rather than silent nonsense.

Sensors with no target entry are simply never assessed (no deviation is ever raised
for them). Failed readings (`ok=false`) are also skipped.

---

## Step 2 — Map a deviation to an actuator command (rules)

Under `rules`, key by **sensor id**, then by **direction** (`"low"` or `"high"`), and
give the command to issue:

```json
"rules": {
  "soil_1": {
    "low": {"actuator_id": "pump_1", "action": "on", "duration_s": 180}
  }
}
```

Meaning: when `soil_1` reads *low* (too dry), propose turning `pump_1` **on** for
**180 seconds**. The command fields:

- `actuator_id` — which actuator to drive (must match a wiring `id`). Required.
- `action` — `"on"`, `"off"`, or `"set"`. Defaults to `"on"`.
- `duration_s` — how long (seconds). Optional; used with `"on"`. The safety guard
  clamps this to the actuator's `max_runtime_s`.
- `params` — optional dict passed through for actuators that need extra arguments.

You can map the other direction too. For example, if high soil moisture should open a
drain valve: `"high": {"actuator_id": "drain_1", "action": "on", "duration_s": 60}`.
A direction with no rule simply produces no command.

---

## Step 3 — Set per-actuator safety limits

Under `safety`, key by **actuator id**. These limits are enforced by the deterministic
safety guard on **every** command — whether it came from a rule, a manual API call,
or (later) an LLM. The guard is the single chokepoint; nothing bypasses it.

```json
"safety": {
  "pump_1": {
    "max_runtime_s": 300,
    "cooldown_s": 600,
    "max_activations_per_day": 24,
    "mutually_exclusive_with": []
  }
}
```

What each limit does:

- **`max_runtime_s`** — an `on` command's `duration_s` is **clamped** down to this.
  (A rule asking for 180s against a 300s cap runs 180s; a rule asking for 600s is
  clamped to 300s.)
- **`cooldown_s`** — minimum seconds between activations; a command arriving too soon
  is **rejected** with a reason.
- **`max_activations_per_day`** — hard cap on activations in a rolling 24 hours;
  over-cap commands are **rejected**.
- **`mutually_exclusive_with`** — a list of actuator ids that must not be on at the
  same time; a command is **rejected** if any listed actuator is currently on. (Use
  this for, say, a pump and a drain that must never run together:
  `"mutually_exclusive_with": ["drain_1"]`.)

If you omit a `safety` block for an actuator, conservative defaults apply:
`max_runtime_s = 300`, `cooldown_s = 0`, effectively unlimited activations, no
exclusions. It is good practice to set limits explicitly for anything that moves
water or draws power.

---

## Step 4 — Choose the strategy

`strategy` selects the decision maker:

- `"local_rules"` (default, implemented) — `LocalRulesStrategy`. Deterministic: it
  applies the `rules` above. This is the always-available, offline behaviour.
- `"llm"` (stub) — `LlmStrategy`. Implements the interface but proposes **no
  commands** yet; a control tick records a note that the LLM strategy is "not yet
  wired". It exists so the future LLM agent can be swapped in by config alone.

```json
"strategy": "local_rules"
```

An unknown strategy name fails at startup with a clear error listing the valid
choices.

---

## Step 5 — Point POLICY_CONFIG at your file

Save your policy as, say, `my-policy.json` at the repo root, then set the env var:

```bash
# Git Bash / macOS / Linux
SIMULATE=true API_TOKEN=dev-secret POLICY_CONFIG=my-policy.json python app.py
```

```powershell
# Windows PowerShell
$env:SIMULATE = "true"; $env:API_TOKEN = "dev-secret"; $env:POLICY_CONFIG = "my-policy.json"
./.venv/Scripts/python.exe app.py
```

If `POLICY_CONFIG` is unset, the built-in defaults are used, so the app always runs.
The file is validated on load; a bad target (`low > high`) or missing `low`/`high`
raises a specific error naming the offending sensor.

---

## Worked trace: how a dry soil reading becomes a pump command

With the policy above, here is the full chain the control cycle runs on
`POST /control/tick` (or on every scheduled tick, later):

1. **Sense.** The hub reads all sensors. Say `soil_1` reads `300`.
2. **Assess.** `find_deviations` compares `300` to its target `[400, 800]`. Since
   `300 < 400`, it emits a `Deviation(sensor_id="soil_1", direction="low", ...)`.
3. **Decide.** `LocalRulesStrategy` looks up `rules["soil_1"]["low"]` and finds
   `{actuator_id: "pump_1", action: "on", duration_s: 180}`. It proposes that
   `Command` (source `"local_rules"`). The strategy only *proposes*; it cannot act.
4. **Guard.** The `ActuatorController` passes the command to the `SafetyGuard`, which
   checks `pump_1`'s limits: clamps `duration_s` to `max_runtime_s` (180 <= 300, so
   unchanged), and rejects if the pump is in cooldown, over its daily cap, or a
   mutually-exclusive actuator is on. If it passes, an approved (possibly clamped)
   command comes back.
5. **Act.** Unless `DRY_RUN=true`, the controller applies the command to the pump,
   records the activation, and the **watchdog** schedules a guaranteed auto-off after
   180s so the pump can never be left running. An `actuation` event is recorded.
6. **Audit.** Every step above is written to the event store, visible at
   `GET /events`.

> In short: **dry soil (reading 300) -> deviation (low) -> rule -> pump on 180s ->
> guard clamps/approves -> pump runs, auto-off scheduled -> events logged.** The
> "LLM proposes, deterministic code disposes" principle means the guard always has
> the final say.

---

## Try it and verify

Simulation reports a mid-range soil value (`300`) by default, which is **below** the
`400` target — so the loop should fire the pump. Start the app as in Step 5, then:

```bash
# run one cycle (needs the token)
curl -X POST http://localhost:8080/control/tick -H "Authorization: Bearer dev-secret"
```

Expected: the response summary contains a `deviation` for `soil_1` (direction
`low`), a proposed `command` for `pump_1`, and a `result` with `accepted: true`.

Then inspect the audit trail and the pump state:

```bash
curl "http://localhost:8080/events?n=20"   # reading, deviation, decision, actuation events
curl http://localhost:8080/actuators/pump_1
```

You configured rules correctly when:

1. The app starts with no policy validation errors.
2. `POST /control/tick` returns a deviation for the out-of-range sensor and a command
   for the mapped actuator.
3. The command's result is `accepted: true` (or `422`/rejected with a clear reason if
   a safety limit blocked it — which is also correct behaviour).
4. `GET /events` shows the `reading -> deviation -> decision -> actuation` sequence.

To make the loop fire nothing, widen the target range (e.g. `"soil_1": {"low": 0,
"high": 1023}`) and tick again — you should see no deviation and no command.

See also [simulation-and-dry-run.md](simulation-and-dry-run.md) to run this loop
safely against real hardware before trusting it on a farm.
