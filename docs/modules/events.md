# Events — the audit trail

An append-only record of everything the system observes and does, behind one
simple interface with an in-memory and a durable (JSONL) implementation.

## What it does

`events/store.py` is where every `reading`, `deviation`, `decision`, and
`actuation` is recorded. It answers questions like *"why did the pump run at
3am?"* and provides the **"previous events"** history that will later be fed to
the LLM decision agent as context.

It defines one interface and two implementations behind it:

### `EventStore` (abstract base)

The contract, deliberately tiny:

- **`record(event)`** — append one `Event` (see [models.md](models.md)).
- **`recent(n=50)`** — return up to `n` most recent events, **newest last**.

Because callers depend only on this interface (dependency inversion), a richer
queryable backend can be slotted in later without touching any caller.

### `InMemoryEventStore` (the default)

Keeps the last `capacity` events (default 1000) in a `collections.deque` ring
buffer — when it fills, the oldest events fall off. Thread-safe via a lock. Fast
and zero-config, but **not durable**: everything is lost on restart. This is the
default and is ideal for simulation and tests.

### `JsonlEventStore` (durable)

Appends each event as one JSON line to a file (**JSONL** = one JSON object per
line) and *also* keeps a small in-memory tail (default 1000). So:

- `record` writes to the file (durable across restarts) **and** the tail.
- `recent` reads from the fast in-memory tail, not the file.

This gives a durable audit trail that survives a restart while keeping `recent`
cheap. A fully queryable durable backend is a later sub-project that will slot in
behind the same `EventStore` interface.

### `build_event_store(kind="memory", path=None)` — the factory

Config wiring calls this to pick an implementation:

- `kind="memory"` → `InMemoryEventStore()`.
- `kind="jsonl"` → `JsonlEventStore(path)` (raises `ValueError` if no `path`).
- anything else → a clear `ValueError` naming the valid kinds.

So choosing durable vs. in-memory is a config change (the `event_store` section of
the wiring/policy config), not a code change.

## How to use it

1. **Build a store** — directly, or via `build_event_store(...)` from config.
2. **Record events** as the control cycle produces them (readings, deviations,
   decisions, actuations).
3. **Read history** with `recent(n)` for the web `/events` endpoint or to feed the
   decision layer.

```python
from farm_agent.events.store import build_event_store
from farm_agent.models import Event

# In-memory (default) or durable JSONL, chosen by config:
store = build_event_store("memory")
# store = build_event_store("jsonl", path="/var/lib/farm/events.jsonl")

store.record(Event(type="reading", payload={"sensor_id": "soil_1", "value": 512}))
store.record(Event(type="actuation", payload={"actuator_id": "pump_1", "accepted": True}))

for event in store.recent(n=10):   # newest last
    print(event.type, event.timestamp, event.payload)
```

## What it depends on

- **`farm_agent.models`** — records and returns `Event` objects (and uses
  `event.to_dict()` when serialising to JSONL).
- The Python standard library: `json`, `threading`, `collections.deque`, `abc`.

It depends on nothing else in the framework — the control cycle and web layer
depend on *it*, not the other way round.

## Example

Using the durable JSONL store and reading the tail back:

```python
import tempfile, os
from farm_agent.events.store import build_event_store
from farm_agent.models import Event

path = os.path.join(tempfile.mkdtemp(), "events.jsonl")
store = build_event_store("jsonl", path=path)

store.record(Event(type="decision", payload={"strategy": "local_rules", "commands": 1}))
store.record(Event(type="actuation", payload={"actuator_id": "pump_1", "action": "on"}))

# recent() reads the fast in-memory tail...
print([e.type for e in store.recent()])     # ['decision', 'actuation']

# ...while the file holds the durable audit trail, one JSON object per line:
print(open(path, encoding="utf-8").read())
# {"type": "decision", "payload": {...}, "timestamp": "..."}
# {"type": "actuation", "payload": {...}, "timestamp": "..."}
```

## Where it lives

`farm_agent/events/store.py`

Related docs: [models.md](models.md) (the `Event` record), and the config docs
for the `event_store` setting.
