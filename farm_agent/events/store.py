"""Append-only event store.

Every reading, deviation, decision and actuation is recorded here. Today there
are two implementations — an in-memory ring buffer (default) and a JSONL file
(durable audit trail) — behind one :class:`EventStore` interface. A richer
queryable backend is a later sub-project that slots in behind the same
interface.
"""

from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from collections import deque
from typing import Optional

from farm_agent.models import Event


class EventStore(ABC):
    """Records events and returns the most recent ones."""

    @abstractmethod
    def record(self, event: Event) -> None:
        raise NotImplementedError

    @abstractmethod
    def recent(self, n: int = 50) -> list[Event]:
        """Return up to ``n`` most recent events, newest last."""
        raise NotImplementedError


class InMemoryEventStore(EventStore):
    """Keeps the last ``capacity`` events in memory. Thread-safe."""

    def __init__(self, capacity: int = 1000) -> None:
        self._events: deque[Event] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def record(self, event: Event) -> None:
        with self._lock:
            self._events.append(event)

    def recent(self, n: int = 50) -> list[Event]:
        with self._lock:
            items = list(self._events)
        return items[-n:]


class JsonlEventStore(EventStore):
    """Appends events to a JSONL file and keeps a small in-memory tail.

    Durable enough to answer "what happened" after a restart, while ``recent``
    stays fast by reading from the in-memory tail.
    """

    def __init__(self, path: str, tail: int = 1000) -> None:
        self._path = path
        self._tail: deque[Event] = deque(maxlen=tail)
        self._lock = threading.Lock()

    def record(self, event: Event) -> None:
        line = json.dumps(event.to_dict())
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            self._tail.append(event)

    def recent(self, n: int = 50) -> list[Event]:
        with self._lock:
            items = list(self._tail)
        return items[-n:]


def build_event_store(kind: str = "memory", path: Optional[str] = None) -> EventStore:
    """Factory used by config wiring."""
    if kind == "jsonl":
        if not path:
            raise ValueError("JsonlEventStore requires a 'path'")
        return JsonlEventStore(path)
    if kind == "memory":
        return InMemoryEventStore()
    raise ValueError(f"Unknown event store kind {kind!r} (expected 'memory' or 'jsonl').")
