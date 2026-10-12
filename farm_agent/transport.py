"""Serial transport to/from the Arduino.

The Arduino emits one JSON object per line (``{"soil_raw": 512, ...}``) and can
accept command lines. :class:`SerialTransport` owns that connection: it is
thread-safe, reconnects on failure, and *caches the most recent decoded frame*
so that when several serial-backed sensors are read in one cycle the port is
only read once.

The :class:`FrameSource` protocol is the seam that lets tests and simulation
swap in a fake (see ``tests/fakes.py``) without touching any sensor code.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Optional, Protocol, runtime_checkable

import serial


@runtime_checkable
class FrameSource(Protocol):
    """Anything that can yield the latest decoded JSON frame from the device."""

    def current_frame(self, max_age: float = 1.0) -> dict[str, Any]:
        """Return the most recent frame, reading a fresh one if the cached
        frame is older than ``max_age`` seconds."""
        ...


@runtime_checkable
class LineSink(Protocol):
    """Anything that can send a command line to the device."""

    def write_line(self, line: str) -> None:
        ...


class SerialTransport:
    """Thread-safe serial link with reconnect and a short-lived frame cache."""

    def __init__(
        self,
        port: str,
        baud: int = 9600,
        timeout: float = 5.0,
        *,
        serial_factory=serial.Serial,
        clock=time.monotonic,
    ) -> None:
        self._port = port
        self._baud = baud
        self._timeout = timeout
        self._serial_factory = serial_factory
        self._clock = clock

        self._conn = None
        self._lock = threading.Lock()
        self._cached_frame: Optional[dict[str, Any]] = None
        self._cached_at: float = -1e9

    # -- connection management ------------------------------------------- #
    def _ensure_open(self):
        if self._conn is None or not getattr(self._conn, "is_open", False):
            self._conn = self._serial_factory(self._port, self._baud, timeout=self._timeout)
        return self._conn

    def _drop(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def close(self) -> None:
        with self._lock:
            self._drop()

    # -- reading ---------------------------------------------------------- #
    def current_frame(self, max_age: float = 1.0) -> dict[str, Any]:
        """Return the latest decoded JSON object from the Arduino.

        If a frame was read less than ``max_age`` seconds ago it is reused, so a
        batch read of many serial sensors only touches the port once.
        """
        with self._lock:
            age = self._clock() - self._cached_at
            if self._cached_frame is not None and age <= max_age:
                return self._cached_frame
            frame = self._read_frame_locked()
            self._cached_frame = frame
            self._cached_at = self._clock()
            return frame

    def _read_frame_locked(self) -> dict[str, Any]:
        try:
            conn = self._ensure_open()
            # Arduino sends one JSON reading per line; skip malformed/partial
            # lines until a valid JSON object arrives.
            while True:
                raw = conn.readline().decode("utf-8", errors="replace").strip()
                if not raw:
                    raise TimeoutError("No Arduino data received")
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    return data
        except (serial.SerialException, OSError, TimeoutError):
            self._drop()
            raise

    # -- writing ---------------------------------------------------------- #
    def write_line(self, line: str) -> None:
        """Send a single command line (newline-terminated) to the device."""
        with self._lock:
            try:
                conn = self._ensure_open()
                conn.write((line.rstrip("\n") + "\n").encode("utf-8"))
                flush = getattr(conn, "flush", None)
                if callable(flush):
                    flush()
            except (serial.SerialException, OSError) as exc:
                self._drop()
                raise exc
