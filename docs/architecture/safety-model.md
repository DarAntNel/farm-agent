# Safety Model

This is the most important document in the set, because this system drives
**physical hardware** — pumps, relays, valves. A wrong or runaway command can
flood a bed, burn out a pump, or drain a tank. This document explains the single
rule the whole design is built around:

> **Nothing reaches hardware un-guarded. Every command passes through the same
> deterministic chokepoint, and the fail-safe is always "off".**

For the big picture see [overview.md](overview.md); for the reasoning behind
these choices see [design-decisions.md](design-decisions.md).

---

## 1. The one path to hardware

There is exactly **one** way a command can move a physical device:

```
   proposer                 chokepoint                  hardware
   --------                 ----------                  --------
 DecisionStrategy  \
 (local rules /     \
  LLM later)         \
                      >---> ActuatorController.execute() ---> SafetyGuard.review()
 manual HTTP         /         |                                 |
 command            /          |   (accepted + not dry-run)      | clamp / reject
 (/actuators/...)  /           v                                 v
                           Actuator.apply()  <----- approved Command
                               |
                               +--> Watchdog.schedule(auto-off)
                               +--> EventStore.record("actuation")
```

The rule is enforced structurally, not by convention:

- `Actuator.apply(...)` is **never called by the web or decision layers**. The
  module docstrings say so and the code honours it: the web layer only ever calls
  `controller.execute(...)`, and the control cycle routes every proposed command
  through the same `controller.execute(...)`.
- `ActuatorController.execute` is therefore the **single command chokepoint**. If
  it runs, the guard ran, the watchdog was given its chance, dry-run was honoured,
  and an audit event was recorded — all of it, every time.

So whether a command comes from a human hitting `POST /actuators/<id>/command` or
from the decision strategy during a control tick, it gets **identical** safety
treatment.

---

## 2. The SafetyGuard: clamp / cooldown / daily-cap / mutual-exclusion

`SafetyGuard.review(command, actuators)` is deterministic: it does no I/O, and all
time comes from an injected clock. It reads the per-actuator `SafetyLimits` from
**policy config** (`max_runtime_s`, `cooldown_s`, `max_activations_per_day`,
`mutually_exclusive_with`). Here is exactly what it does, in order:

### `off` is always allowed
If the action is `off`, the guard accepts it immediately and never rate-limits it.
**Turning something off is always safe**, so it must never be blocked.

### For an `on` command, in order:

1. **Clamp the duration.** The requested `duration_s` is capped down to
   `max_runtime_s`. If no duration was given at all, it is *filled in* with
   `max_runtime_s`. This means an `on` command can never run longer than policy
   allows, and it can never run *forever* — there is always a finite duration.
   The guard produces a clamped **copy** of the command (`Command.replace`); the
   original immutable command is untouched.

2. **Cooldown.** If the actuator was last activated less than `cooldown_s` ago,
   the command is **rejected** with a reason naming the seconds remaining. This
   stops rapid on/off cycling that can damage a pump.

3. **Daily cap.** The guard counts activations in a rolling 24-hour window. If
   that count has already reached `max_activations_per_day`, the command is
   **rejected**. This bounds total runtime over a day even if every individual
   run is short.

4. **Mutual exclusion.** If any actuator listed in `mutually_exclusive_with` is
   currently on (`actuator.is_on`), the command is **rejected**. This prevents
   combinations that must never run together.

A rejection returns `ActuatorResult(accepted=False, reason=...)`; **nothing
fires**, and over HTTP the caller gets a `422` with the reason. An acceptance
returns the (possibly clamped) command for the controller to apply.

> The guard keeps its own per-actuator activation history. After a successful
> `on`, the controller calls `guard.record_activation(id)` so the next review can
> enforce cooldown and the daily cap. This keeps the guard the single source of
> truth for rate-limiting.

> In code: `farm_agent/safety/guard.py`, limits from
> `farm_agent/safety/limits.py` + policy config.

---

## 3. The auto-off Watchdog: a guaranteed "off"

Clamping the duration is not enough on its own — something still has to *perform*
the off. That is the `Watchdog`.

When the controller successfully applies an `on` command that has a duration, it
schedules a guaranteed auto-off:

```python
if approved.action == "on":
    self._guard.record_activation(approved.actuator_id)
    if approved.duration_s:
        self._watchdog.schedule(
            approved.actuator_id,
            approved.duration_s,
            lambda aid=approved.actuator_id: self._auto_off(aid),
        )
```

Key properties:

- **It cannot be forgotten.** The timer is independent of the decision layer. Even
  if the strategy crashes, or no further control tick ever runs, the off still
  fires after the duration elapses. The auto-off itself records an `actuation`
  event (`auto_off: True`).
- **One pending off per actuator.** Timers are keyed by actuator id; scheduling a
  new one cancels any previous timer first, so there is never a stale off waiting.
- **It never hangs the process.** Real timer threads are marked `daemon`, so a
  pending auto-off can never keep a script, test, or shutting-down server alive.
- **An explicit `off` cancels the timer.** If a command turns the actuator off
  before the timer fires, the controller cancels the pending auto-off.
- **Testable.** The timer constructor is injected (`timer_factory`), so tests
  drive auto-off deterministically instead of waiting on real time.

> In code: `farm_agent/safety/watchdog.py`,
> `farm_agent/control/controller.py` (`_auto_off`).

---

## 4. `safe_init` at startup: never boot into an unknown state

Hardware can retain state across a restart — a relay might still be closed when
the process comes back up. So the system refuses to trust the hardware's starting
state.

At the end of wiring the system, `bootstrap.build_system` calls
`controller.safe_init()`, which:

1. cancels every pending watchdog timer, then
2. forces **every** actuator to `safe_off()`.

The comment in the composition root is blunt: *"never boot into an unknown 'on'
state."* Whatever the hardware was doing before, after startup everything is
known-off.

On shutdown, `controller.shutdown()` cancels all pending timers as well.

> In code: `farm_agent/control/controller.py` (`safe_init`, `shutdown`),
> called from `farm_agent/bootstrap.py`.

---

## 5. Fail-safe = off, everywhere

"Fail-safe = off" is not a slogan; it is how the pieces actually behave when
something goes wrong:

- **Guard, when in doubt -> reject.** A rejected command does not fire. Doing
  nothing is the safe outcome.
- **`off` is never blocked.** The guard always allows an off, uncapped and
  un-cooled, so you can always stop a device.
- **`safe_off()` forces off** regardless of tracked state.
- **The watchdog guarantees an eventual off** even if higher layers fail.
- **Startup forces off** before trusting anything.
- **Hardware errors become clean rejections.** If a device raises while applying a
  command, `Actuator.apply` catches it and returns
  `ActuatorResult(accepted=False, reason="hardware error: ...")` instead of
  letting the exception escape — the system stays in a known state.
- **`DRY_RUN=true`** runs the full assess/decide/guard/log path but **does not
  fire** actuators; `execute` returns an accepted result marked
  `"dry-run: not applied"`. This lets you watch intended behaviour on real
  hardware without moving anything. (See runtime modes in
  [overview.md](overview.md#4-runtime-modes).)

---

## 6. What the LLM can and cannot do

The decision layer — today's `LocalRulesStrategy`, tomorrow's `LlmStrategy` — is
intentionally boxed in. (`LlmStrategy` currently ships as a stub that proposes no
commands and is marked `wired = False`; the control cycle records a note saying it
is not yet wired.)

**The LLM / decision strategy CAN:**

- Read the current `readings`, the `deviations`, and recent `history`.
- **Propose** a list of `Command` objects (which actuator, on/off/set, a requested
  duration).

**The LLM / decision strategy CANNOT:**

- Call an actuator directly — it has no reference to one, and `apply` is only
  reached through the controller.
- Bypass the `SafetyGuard`. Every proposal it returns is reviewed, clamped, and
  possibly rejected exactly like a manual command.
- Exceed `max_runtime_s` — any duration it asks for is clamped down.
- Run faster than `cooldown_s`, more often than `max_activations_per_day`, or
  alongside a mutually-exclusive actuator — all enforced by the guard.
- Prevent the guaranteed auto-off, keep an actuator on past its clamped duration,
  or stop `safe_init` from forcing everything off at startup.

In short: the LLM gets to be *smart about what to suggest*, and the deterministic
safety spine stays *in charge of what actually happens*. That separation is the
whole point — see **"the decision layer proposes; the safety guard disposes"** in
[design-decisions.md](design-decisions.md#3-the-decision-layer-proposes-the-safety-guard-disposes).

---

## 7. Where to go next

- **The full-system loop and layers** -> [overview.md](overview.md)
- **Why it is built this way** -> [design-decisions.md](design-decisions.md)
- **Map of all documentation** -> [../README.md](../README.md)
