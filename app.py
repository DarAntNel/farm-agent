from flask import Flask, jsonify
from datetime import datetime, timezone
import random
import os

app = Flask(__name__)

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
    return jsonify({
        "sensor": "simulated-temperature",
        "temperature_c": round(random.uniform(22, 30), 2),
        "humidity_percent": round(random.uniform(40, 70), 2),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))