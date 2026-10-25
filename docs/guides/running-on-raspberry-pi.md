# Running on a Raspberry Pi (real hardware)

This guide takes the app from simulation to a **real farm**: wiring the hardware,
enabling the Pi's interfaces, installing, configuring the ports, and running
safely — first in dry-run, then live, then as a service that starts on boot.

> **Read this first — the safe bring-up order.** Never jump straight to driving a
> pump. The sequence is always: **simulation on a laptop → `DRY_RUN=true` on the
> Pi (real sensors, actuators only logged) → live.** Each step catches a class of
> mistake before anything can move water.

---

## 0 — How hardware maps to the app

The framework reads sensors two ways and drives actuators through GPIO or the
Arduino (see [../architecture/overview.md](../architecture/overview.md)):

| Thing | How it connects | App piece | Default port in config |
|-------|-----------------|-----------|------------------------|
| Soil + temperature (via Arduino) | Arduino sends one JSON line per reading over USB serial | `soil_moisture`, `temperature` (serial sensors) | serial `/dev/arduino` |
| Soil moisture (direct) | Capacitive probe → ADS1115 ADC over **I2C** | `ads1115_soil` (direct sensor) | address `0x48`, channel `0` |
| Temperature (direct) | DS18B20 on a **1-Wire** GPIO | `ds18b20` (direct sensor) | `device_id` |
| Water pump / valve / light | Relay module on a **GPIO pin** | `relay` actuator | BCM pin `17` |
| Pump/valve via Arduino | Command line written over serial | `serial_actuator` | `command` prefix |

You only wire up the devices you actually use, and you list exactly those in the
wiring config (Step 4). Everything else is ignored.

---

## 1 — Wire the hardware (power off)

Minimum for the default config (Arduino for sensing + one relay-driven pump):

- **Arduino** → Pi USB. It appears as `/dev/ttyACM0` (Uno/Mega) or `/dev/ttyUSB0`
  (boards with an FTDI/CH340 chip). It must be flashed with firmware that prints
  one JSON object per line, e.g. `{"soil_raw": 512, "temperature_c": 21.5}`.
- **Relay module** → a GPIO pin (default **BCM 17**, physical pin 11), plus 5V and
  GND. The relay switches the pump's own power supply — **the Pi never powers the
  pump directly.**

If you use direct sensors instead of the Arduino:

- **ADS1115** → I2C: `SDA`→GPIO2 (pin 3), `SCL`→GPIO3 (pin 5), plus 3V3 and GND.
  Default address `0x48` (ADDR→GND).
- **DS18B20** → data to **GPIO4** (pin 7) with a 4.7kΩ pull-up to 3V3.

> **Relay wiring tip (fail-safe):** wire the pump through the relay's
> **normally-open (NO)** contact, so a power loss or a crashed app leaves the pump
> **off**. The software watchdog guarantees an auto-off too, but hardware
> fail-safe is your last line of defence.

---

## 2 — Enable the Pi's interfaces

On Raspberry Pi OS, run `sudo raspi-config` → **Interface Options** and enable
what you need:

- **Serial Port**: *login shell over serial?* → **No**. *Serial hardware
  enabled?* → **Yes** (only needed for a GPIO-pin UART; USB Arduinos work
  regardless).
- **I2C**: **Yes** (only if using the ADS1115).
- **1-Wire**: **Yes** (only if using the DS18B20).

Then add your user to the hardware groups and reboot:

```bash
sudo usermod -aG dialout,gpio,i2c pi   # 'pi' = your username
sudo reboot
```

Verify the interfaces after reboot:

```bash
ls -l /dev/ttyACM0 /dev/ttyUSB0 2>/dev/null   # the Arduino serial device
i2cdetect -y 1                                # ADS1115 shows at 48
ls /sys/bus/w1/devices/                       # DS18B20 shows as 28-xxxxxxxx
```

### Give the Arduino a stable name (recommended)

USB device names can shift between `ttyACM0`/`ttyUSB0` on reboot. Pin it to
`/dev/arduino` (the config default) with a udev rule. Find its IDs:

```bash
udevadm info -a -n /dev/ttyACM0 | grep -E "idVendor|idProduct" | head -2
```

Create `/etc/udev/rules.d/99-arduino.rules`:

```
SUBSYSTEM=="tty", ATTRS{idVendor}=="2341", ATTRS{idProduct}=="0043", SYMLINK+="arduino"
```

(Use the vendor/product you found.) Then:

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
ls -l /dev/arduino   # -> points at your ttyACM0/ttyUSB0
```

---

## 3 — Install the app

```bash
git clone <your-repo-url> farm-agent && cd farm-agent
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

On the Pi (ARM), `pip` now **does** install `RPi.GPIO` and the Adafruit
libraries, because they are no longer skipped as they are on a PC. `adafruit-blinka`
may need a couple of system packages; if its install complains, run
`sudo apt install -y python3-dev libgpiod2` and retry.

Quick smoke test that it imports cleanly:

```bash
python -c "import farm_agent, RPi.GPIO; print('ok')"
```

---

## 4 — Configure your ports and policy

Create two JSON files. **Wiring** = what hardware exists and where
([../reference/config-schema.md](../reference/config-schema.md)):

`/home/pi/farm/wiring.json`
```json
{
  "serial": {"port": "/dev/arduino", "baud": 9600, "timeout": 5},
  "sensors": [
    {"type": "soil_moisture", "id": "soil_1", "name": "Bed 1 soil", "field": "soil_raw"},
    {"type": "temperature",   "id": "temp_1", "name": "Bed 1 temp", "field": "temperature_c"}
  ],
  "actuators": [
    {"type": "relay", "id": "pump_1", "name": "Bed 1 pump", "pin": 17}
  ],
  "event_store": {"kind": "jsonl", "path": "/home/pi/farm/events.jsonl"}
}
```

**Policy** = the farming behaviour: target ranges, the rule that fires the pump,
and the safety limits ([configuring-rules.md](configuring-rules.md)):

`/home/pi/farm/policy.json`
```json
{
  "strategy": "local_rules",
  "targets": { "soil_1": {"low": 400, "high": 800} },
  "rules":   { "soil_1": {"low": {"actuator_id": "pump_1", "action": "on", "duration_s": 180}} },
  "safety":  { "pump_1": {"max_runtime_s": 300, "cooldown_s": 1800, "max_activations_per_day": 12} }
}
```

> The `safety` block is enforced by the deterministic guard regardless of what any
> rule (or, later, an LLM) asks for — durations are clamped to `max_runtime_s`,
> and activations are blocked during `cooldown_s` or over the daily cap. See
> [../architecture/safety-model.md](../architecture/safety-model.md).

Point the app at both files and set a token for the endpoints that can move
hardware:

```bash
export WIRING_CONFIG=/home/pi/farm/wiring.json
export POLICY_CONFIG=/home/pi/farm/policy.json
export API_TOKEN="choose-a-long-random-token"
```

---

## 5 — Bring-up: dry-run, then live

**First run in dry-run** — this reads your *real* sensors but only **logs** what
it would do to actuators (nothing fires):

```bash
DRY_RUN=true WIRING_CONFIG=$WIRING_CONFIG POLICY_CONFIG=$POLICY_CONFIG \
  API_TOKEN=$API_TOKEN python app.py
```

From another terminal, confirm real readings and a safe decision:

```bash
curl http://localhost:8080/sensors            # real soil/temp values, ok:true
curl -X POST http://localhost:8080/control/tick -H "Authorization: Bearer $API_TOKEN"
curl "http://localhost:8080/events?n=20"      # see the 'actuation' events marked dry_run
```

Check: readings look physically sane, and if soil is below target the tick shows a
pump command **accepted** with `"reason": "dry-run: not applied"` and the pump
`is_on` stays `false`.

**Then go live** by dropping `DRY_RUN` (a short test duration first is wise):

```bash
WIRING_CONFIG=$WIRING_CONFIG POLICY_CONFIG=$POLICY_CONFIG \
  API_TOKEN=$API_TOKEN python app.py
```

On startup the controller runs `safe_init()` — every actuator is forced **off**,
so the system never boots into an unknown state. Trigger one real activation and
watch the relay click and the pump run, then auto-off after the duration:

```bash
curl -X POST http://localhost:8080/actuators/pump_1/command \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "on", "duration_s": 5}'
```

---

## 6 — Run it as a service (starts on boot)

Create `/etc/systemd/system/farm-agent.service`:

```ini
[Unit]
Description=Farm Agent
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/farm-agent
EnvironmentFile=/home/pi/farm/farm-agent.env
ExecStart=/home/pi/farm-agent/.venv/bin/python app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Put the environment in `/home/pi/farm/farm-agent.env` (no `export`, one per line):

```ini
WIRING_CONFIG=/home/pi/farm/wiring.json
POLICY_CONFIG=/home/pi/farm/policy.json
API_TOKEN=choose-a-long-random-token
PORT=8080
# DRY_RUN=true   # uncomment while commissioning
```

Enable and start it, then watch the logs:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now farm-agent
journalctl -u farm-agent -f
```

> Because the service auto-restarts, the watchdog's auto-off still applies after a
> crash: on restart `safe_init()` forces actuators off, and any mid-run pump has
> no lingering timer. Keep `cooldown_s` sensible so a crash-loop can't rapidly
> re-activate a pump.

---

## 7 — Docker on the Pi (optional)

Running natively via systemd (Step 6) is the simplest path for GPIO. If you prefer
Docker, you must pass the hardware devices into the container:

```bash
docker build -t farm-agent .

docker run --rm -p 8080:8080 \
  --device /dev/arduino \            # serial (or /dev/ttyACM0)
  --device /dev/gpiomem \            # GPIO (RPi.GPIO relay)
  --device /dev/i2c-1 \              # only if using ADS1115
  --group-add dialout --group-add gpio --group-add i2c \
  -e WIRING_CONFIG=/cfg/wiring.json -e POLICY_CONFIG=/cfg/policy.json \
  -e API_TOKEN=choose-a-long-random-token \
  -v /home/pi/farm:/cfg \
  farm-agent
```

Notes:
- 1-Wire (DS18B20) is awkward in Docker because it needs `/sys/bus/w1`; prefer the
  Arduino or ADS1115 path, or run natively, if you need DS18B20.
- The image already copies the `farm_agent/` package (don't remove that line from
  the `Dockerfile`, or the container fails with `ModuleNotFoundError: farm_agent`).

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `/sensors` shows `ok:false`, `field ... missing` | Arduino not sending that JSON field, or wrong `field` in wiring. Check `cat /dev/arduino` shows JSON lines. |
| `Unable to read` / serial errors | Wrong `serial.port`, or user not in `dialout`. Check `ls -l /dev/arduino` and `groups`. |
| `RPi.GPIO ... RuntimeError` / permission | User not in `gpio`, or (in Docker) `/dev/gpiomem` not passed. |
| ADS1115 not found | `i2cdetect -y 1` doesn't show `48` → check wiring/address and that I2C is enabled. |
| DS18B20 not found | `ls /sys/bus/w1/devices/` empty → enable 1-Wire, check the pull-up resistor and `device_id`. |
| Pump won't turn on, `422` with a reason | The safety guard rejected it (cooldown / daily cap / mutual exclusion). The `reason` says which. |
| Guarded endpoint returns `403` | `API_TOKEN` not set, or the request's `Authorization: Bearer` token doesn't match. |

---

## Verify it worked

1. `curl http://localhost:8080/sensors` returns your real sensors with `ok:true`.
2. In `DRY_RUN`, a dry-soil tick proposes a pump command but the pump stays off.
3. Live, a manual `pump_1` command physically runs the pump and it **auto-offs**
   after the duration.
4. `sudo systemctl status farm-agent` is `active (running)` and survives a reboot.

Related: [configuring-rules.md](configuring-rules.md) ·
[simulation-and-dry-run.md](simulation-and-dry-run.md) ·
[../architecture/safety-model.md](../architecture/safety-model.md) ·
[../reference/config-schema.md](../reference/config-schema.md)
