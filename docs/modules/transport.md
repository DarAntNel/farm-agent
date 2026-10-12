# Transport — the serial link to the Arduino

Owns the one serial connection to the Arduino: it reconnects on failure and
caches the latest frame so the port is read only once per control cycle.

## What it does

The Arduino emits **one JSON object per line** over the serial port, e.g.:

```
{"soil_raw": 512, "temperature_c": 21.4}
```

`SerialTransport` is the single object that owns that connection. It provides:

- **`current_frame(max_age=1.0)`** — return the most recent decoded JSON frame as
  a `dict`. If a frame was read less than `max_age` seconds ago, the *cached*
  frame is returned; otherwise a fresh line is read from the port.
- **`write_line(line)`** — send one newline-terminated command line to the device
  (used by serial-backed actuators).
- **`close()`** — drop the underlying connection.

Three things make it robust:

1. **Connect / reconnect.** The connection is opened lazily on first use
   (`_ensure_open`). If a read or write fails with a serial/OS error, the
   connection is dropped (`_drop`) and will be re-opened on the next call. The
   caller just retries next cycle — there is no manual reconnect step.
2. **The frame cache.** Several serial sensors (soil moisture, temperature, ...)
   all read from the *same* JSON line. Without caching, reading three sensors in
   one cycle would consume three separate lines from the port and get three
   different frames. The cache means the port is read **once per cycle** and
   every sensor that reads within `max_age` seconds sees the *same* frame. This
   is why `SensorHub` does not need any special "read the port once" logic — it
   falls out of the cache for free.
3. **Thread safety.** A `threading.Lock` guards every read and write, so the web
   layer, the control cycle, and the watchdog can touch the transport
   concurrently without corrupting a partial line.

When reading, malformed or partial lines are skipped until a valid JSON object
arrives; an empty line (a timeout) raises `TimeoutError`, which the calling
sensor turns into a failed `Reading` rather than a crash.

### The test seam: `FrameSource` and `LineSink`

`transport.py` also defines two tiny `Protocol` classes — the interfaces the rest
of the code actually depends on:

- **`FrameSource`** — anything with `current_frame(max_age)`. Serial sensors
  depend on this, not on `SerialTransport` directly.
- **`LineSink`** — anything with `write_line(line)`. Serial actuators depend on
  this.

`SerialTransport` satisfies both protocols. Because sensors and actuators depend
only on the protocol, tests and simulation can inject a fake (e.g.
`FakeSerialTransport`, which returns scripted frames or raises on demand) without
touching any sensor or actuator code. This is the seam that lets the whole
framework run with no hardware (see
[simulation-and-dry-run.md](../guides/simulation-and-dry-run.md)).

## How to use it

1. **Construct one transport per Arduino**, from the serial section of the wiring
   config (port, baud, timeout).
2. **Pass it to the sensor/actuator factories** — they store it as a
   `FrameSource` / `LineSink`. You rarely call it directly.
3. **Read frames** via `current_frame()`. Tune `max_age` to control how long a
   cached frame is considered fresh.
4. **Send commands** via `write_line()`.
5. In tests, **substitute any object** that implements `current_frame` /
   `write_line` — no subclassing required.

```python
from farm_agent.transport import SerialTransport

transport = SerialTransport(port="/dev/arduino", baud=9600, timeout=5.0)

frame = transport.current_frame(max_age=1.0)   # {"soil_raw": 512, ...}
transport.write_line("pump on 180")            # send a command to the Arduino
transport.close()
```

The constructor also accepts `serial_factory` and `clock` keyword arguments
(defaulting to `serial.Serial` and `time.monotonic`). Tests inject a fake serial
factory and a controllable clock to exercise caching and reconnection
deterministically.

## What it depends on

- **`pyserial`** (`import serial`) — the underlying serial driver. This is the
  only hardware-facing dependency, and it is imported at module load; on a dev
  machine it is a pure-Python package, so importing `transport.py` is safe even
  with no device attached.
- The Python standard library: `json`, `threading`, `time`.

It does **not** depend on `models`, sensors, or actuators — transport sits near
the bottom of the stack. The relationship is the other way round: sensors and
actuators depend on its `FrameSource` / `LineSink` protocols.

## Example

Two serial sensors reading in one cycle, showing that the port is touched only
once thanks to the cache:

```python
from farm_agent.transport import SerialTransport
from farm_agent.sensors.soil_moisture import SoilMoistureSensor
from farm_agent.sensors.temperature import TemperatureSensor

transport = SerialTransport(port="/dev/arduino")

soil = SoilMoistureSensor("soil_1", "Soil moisture", transport)
temp = TemperatureSensor("temp_1", "Temperature", transport)

# First read pulls a fresh frame from the port and caches it.
r_soil = soil.read()
# Second read (within max_age) reuses the SAME cached frame — no second port read.
r_temp = temp.read()

print(r_soil.value, r_temp.value)
```

## Where it lives

`farm_agent/transport.py`

Related docs: [sensors.md](sensors.md), [actuators.md](actuators.md),
[models.md](models.md).
