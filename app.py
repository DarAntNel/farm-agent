
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


def read_soil_sensor():
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
            # Ignore any malformed or empty lines.
            while True:
                line = arduino.readline().decode(
                    "utf-8", errors="replace"
                ).strip()

                if not line:
                    raise TimeoutError("No Arduino data received")

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if "soil_raw" not in data:
                    continue

                value = int(data["soil_raw"])
                if not 0 <= value <= 1023:
                    continue

                return value

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
        soil_raw = read_soil_sensor()
        return jsonify({
            "sensor": "capacitive-soil-moisture",
            "soil_raw": soil_raw,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    except (serial.SerialException, OSError, TimeoutError) as e:
        app.logger.exception("Arduino soil sensor read failed")
        return jsonify({
            "error": "Unable to read Arduino soil sensor-n",
            "details": str(e),
            "serial_port": SERIAL_PORT
        }), 503


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080"))
    )