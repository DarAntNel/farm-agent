"""Tests for the event store implementations."""

from __future__ import annotations

import json

from farm_agent.events.store import (
    InMemoryEventStore,
    JsonlEventStore,
    build_event_store,
)
from farm_agent.models import Event


def test_in_memory_records_and_returns_recent():
    store = InMemoryEventStore(capacity=3)
    for i in range(5):
        store.record(Event("reading", {"i": i}))
    recent = store.recent(10)
    assert [e.payload["i"] for e in recent] == [2, 3, 4]  # ring buffer keeps last 3


def test_recent_limit():
    store = InMemoryEventStore()
    for i in range(10):
        store.record(Event("reading", {"i": i}))
    assert len(store.recent(4)) == 4


def test_jsonl_persists_to_disk(tmp_path):
    path = tmp_path / "events.jsonl"
    store = JsonlEventStore(str(path))
    store.record(Event("actuation", {"ok": True}))
    store.record(Event("decision", {"n": 1}))
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["type"] == "actuation"
    assert len(store.recent(10)) == 2


def test_build_event_store_factory(tmp_path):
    assert isinstance(build_event_store("memory"), InMemoryEventStore)
    assert isinstance(build_event_store("jsonl", str(tmp_path / "e.jsonl")), JsonlEventStore)


def test_build_event_store_unknown_raises():
    import pytest

    with pytest.raises(ValueError):
        build_event_store("mystery")
