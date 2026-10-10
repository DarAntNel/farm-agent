from flask import Flask, jsonify
from datetime import datetime, timezone
import json
import os
import threading
import serial

app = Flask(__name__)

SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/arduino")
SERIAL_BAUD = int(os.getenv("SERIAL_BAUD", "9600"))

arduino = None
serial_lock = threading.Lock()


def read_sensor_data():
    global arduino

    with serial_lock:
        try:
            if arduino is None or not arduino.is_open:
                arduino = serial.Serial(
                    SERIAL_PORT,
                    SERIAL_BAUD,
                    timeout=5
                )

            # Arduino sends one JSON reading per line.
            while True:
                line = arduino.readline().decode(
                    "utf-8", errors="replace"
                ).strip()

                if not line:
                    raise TimeoutError("No Arduino data received")

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    # Ignore malformed or incomplete serial lines.
                    continue

                if not isinstance(data, dict):
                    continue

                # Validate soil moisture reading.
                try:
                    soil_raw = int(data["soil_raw"])
                except (KeyError, TypeError, ValueError):
                    continue

                if not 0 <= soil_raw <= 1023:
                    continue

                # Read DS18B20 temperature.
                temperature_c = data.get("temperature_c")

                if temperature_c is not None:
                    try:
                        temperature_c = float(temperature_c)
                    except (TypeError, ValueError):
                        temperature_c = None

                    # DS18B20 operating range is -55 to 125 °C.
                    if (
                        temperature_c is not None
                        and not -55 <= temperature_c <= 125
                    ):
                        temperature_c = None

                return {
                    "soil_raw": soil_raw,
                    "temperature_c": temperature_c
                }

        except (serial.SerialException, OSError, TimeoutError):
            if arduino is not None:
                try:
                    arduino.close()
                except Exception:
                    pass
                arduino = None
            raise


@app.get("/")
def home():
    return jsonify({
        "application": "pi-sensor-api",
        "status": "running",
        "message": "Sensor API is ready"
    })


@app.get("/health")
def health():
    return jsonify({"status": "healthy"})


@app.get("/sensor")
def sensor():
    try:
        data = read_sensor_data()

        return jsonify({
            "sensor": "capacitive-soil-moisture-and-DS18B20",
            "soil_raw": data["soil_raw"],
            "temperature_c": data["temperature_c"],
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    except (serial.SerialException, OSError, TimeoutError) as e:
        app.logger.exception("Arduino sensor read failed")
        return jsonify({
            "error": "Unable to read Arduino sensors",
            "details": str(e),
            "serial_port": SERIAL_PORT
        }), 503


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080"))
    )