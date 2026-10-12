# Safety Guard

The deterministic chokepoint that clamps and rejects proposed actuator commands so nothing unsafe ever reaches hardware.

## What it does

The safety guard is where the project's core rule lives: **the decision layer proposes, the guard disposes.** A decision strategy (local rules today, an LLM later) only ever *suggests* commands. Before any command can move a pump or a valve, it must pass through `SafetyGuard.review`. The guard has no idea who proposed a command and does not care — it applies the same deterministic checks to all of them.

It is driven by two pieces:

**`SafetyLimits`** (a frozen dataclass, one per actuator, loaded from policy config) holds four fields:

| Field | Meaning | Default |
|-------|---------|---------|
| `max_runtime_s` | An `on` command's `duration_s` is clamped down to this. | `300.0` |
| `cooldown_s` | Minimum seconds that must pass after the previous activation started before another `on` is allowed. | `0.0` |
| `max_activations_per_day` | Hard cap on activations in a rolling 24-hour window. | `1_000_000` |
| `mutually_exclusive_with` | List of actuator ids that must not be `on` at the same time as this one. | `[]` (empty) |

**`SafetyGuard.review(command, actuators)`** returns an `ActuatorResult`:

- **`off` is always allowed** and never rate-limited. Turning things off is the fail-safe action, so the guard never blocks it.
- Any action that is not `on` (e.g. `set`) is passed through unchanged.
- For an `on` command the guard, in order:
  1. **Clamps** `duration_s` down to `max_runtime_s`. A missing duration is *filled in* with `max_runtime_s` (never left unbounded).
  2. **Rejects** if the actuator is still inside its cooldown window (measured from the last recorded activation start).
  3. **Rejects** if the rolling-24h activation count has already reached `max_activations_per_day`.
  4. **Rejects** if any actuator named in `mutually_exclusive_with` is currently `on`.
  5. Otherwise returns `ActuatorResult.ok(...)` carrying the (possibly clamped) command.

The guard is **pure and deterministic**: it does no I/O, and every notion of "now" comes from an injected `clock` callable (default `time.monotonic`). That is what makes cooldown and daily-cap behaviour reproducible in tests.

Because the guard needs to know *when* activations happened, it keeps its own per-actuator history of start times. The controller calls **`record_activation(actuator_id)`** after a successful `on` so the next `review` can enforce cooldown and the daily cap.

## How to use it

You normally never call the guard yourself — the `ActuatorController` owns it (see [controller.md](controller.md)). This shows what the controller does under the hood.

1. Build a `FarmPolicy` (see [config.md](config.md)) so the guard can look up limits via `policy.limits_for(actuator_id)`.
2. Construct the guard, optionally injecting a clock for tests.
3. Call `review` with the proposed command and the live map of actuators (`{id: Actuator}`).
4. Inspect `result.accepted`. If accepted, apply `result.applied` (the clamped command). After a successful `on`, call `record_activation`.

```python
from farm_agent.config.policy import FarmPolicy
from farm_agent.config.defaults import DEFAULT_POLICY
from farm_agent.models import Command
from farm_agent.safety.guard import SafetyGuard

policy = FarmPolicy(DEFAULT_POLICY)
guard = SafetyGuard(policy)          # clock defaults to time.monotonic

cmd = Command(actuator_id="pump_1", action="on", duration_s=999, source="local_rules")
result = guard.review(cmd, actuators={})   # actuators map used only for mutual-exclusion

if result.accepted:
    applied = result.applied         # duration_s clamped to 300 (pump_1's max_runtime_s)
    # ... controller applies `applied` to the actuator, then:
    guard.record_activation("pump_1")
else:
    print("rejected:", result.reason)
```

## What it depends on

- `farm_agent.models.Command` and `farm_agent.models.ActuatorResult` — the request/response value objects.
- `farm_agent.config.policy.FarmPolicy` — supplies per-actuator `SafetyLimits` via `limits_for`. (Imported only for type checking to avoid a circular import.)
- `farm_agent.safety.limits.SafetyLimits` / `DEFAULT_LIMITS` — the limit fields, built from policy config by `SafetyLimits.from_dict`.
- `farm_agent.actuators.base.Actuator` — the guard reads each actuator's `is_on` for mutual-exclusion checks.
- An injected `clock: Callable[[], float]` (default `time.monotonic`) — the *only* source of time, so behaviour is deterministic.

## Example

A pump with `cooldown_s=600` is asked to run twice in quick succession, using a fake clock so the test is deterministic:

```python
from farm_agent.config.policy import FarmPolicy
from farm_agent.models import Command
from farm_agent.safety.guard import SafetyGuard

policy = FarmPolicy({
    "safety": {"pump_1": {"max_runtime_s": 300, "cooldown_s": 600,
                          "max_activations_per_day": 24}}
})

now = [0.0]                           # a mutable "clock" we control
guard = SafetyGuard(policy, clock=lambda: now[0])

cmd = Command(actuator_id="pump_1", action="on", duration_s=180, source="local_rules")

first = guard.review(cmd, {})         # accepted
assert first.accepted
guard.record_activation("pump_1")     # controller records the start

now[0] = 60.0                         # only 60s later, still inside 600s cooldown
second = guard.review(cmd, {})
assert not second.accepted
print(second.reason)                  # "in cooldown: 540s remaining"

# An `off` is never blocked, even mid-cooldown:
off = guard.review(Command(actuator_id="pump_1", action="off"), {})
assert off.accepted
```

## Where it lives

- `farm_agent/safety/guard.py` — `SafetyGuard` (`review`, `record_activation`).
- `farm_agent/safety/limits.py` — `SafetyLimits` and `DEFAULT_LIMITS`.
