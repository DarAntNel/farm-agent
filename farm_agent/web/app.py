"""Flask application factory.

The HTTP layer is deliberately thin: it shapes JSON and maps outcomes to status
codes, delegating all real work to the injected ``SensorHub``,
``ActuatorController`` and ``ControlCycle`` (dependency inversion). Read routes
are open; routes that can move hardware require a token (see :mod:`.auth`).
"""

from __future__ import annotations

from typing import Optional

from flask import Flask, jsonify, request

from farm_agent.control.controller import ActuatorController
from farm_agent.control.cycle import ControlCycle
from farm_agent.events.store import EventStore
from farm_agent.models import Command
from farm_agent.sensors.hub import SensorHub
from farm_agent.web.auth import require_token


def create_app(
    hub: SensorHub,
    controller: ActuatorController,
    cycle: ControlCycle,
    event_store: EventStore,
    *,
    api_token: Optional[str] = None,
) -> Flask:
    app = Flask(__name__)
    if api_token is not None:
        app.config["API_TOKEN"] = api_token

    # -- service info ----------------------------------------------------- #
    @app.get("/")
    def home():
        return jsonify(
            {
                "application": "farm-agent",
                "status": "running",
                "message": "Smart-farm sensor + actuator API",
            }
        )

    @app.get("/health")
    def health():
        return jsonify({"status": "healthy"})

    # -- sensors ---------------------------------------------------------- #
    @app.get("/sensor")
    def sensor_legacy():
        """Back-compat endpoint: combined soil + temperature, as the original app."""
        readings = {r.sensor_id: r for r in hub.read_all()}
        soil = readings.get("soil_1")
        temp = readings.get("temp_1")
        if soil is not None and not soil.ok and (temp is None or not temp.ok):
            return (
                jsonify(
                    {
                        "error": "Unable to read Arduino sensors",
                        "details": soil.error,
                    }
                ),
                503,
            )
        return jsonify(
            {
                "sensor": "capacitive-soil-moisture-and-DS18B20",
                "soil_raw": soil.value if soil else None,
                "temperature_c": temp.value if temp else None,
                "timestamp": (soil or temp).timestamp if (soil or temp) else None,
            }
        )

    @app.get("/sensors")
    def sensors():
        return jsonify({"sensors": [r.to_dict() for r in hub.read_all()]})

    @app.get("/sensors/<sensor_id>")
    def sensor_one(sensor_id: str):
        try:
            reading = hub.read_one(sensor_id)
        except KeyError:
            return jsonify({"error": f"Unknown sensor {sensor_id!r}"}), 404
        return jsonify(reading.to_dict())

    # -- actuators -------------------------------------------------------- #
    @app.get("/actuators")
    def actuators():
        return jsonify({"actuators": controller.states()})

    @app.get("/actuators/<actuator_id>")
    def actuator_one(actuator_id: str):
        try:
            return jsonify(controller.get(actuator_id).state())
        except KeyError:
            return jsonify({"error": f"Unknown actuator {actuator_id!r}"}), 404

    @app.post("/actuators/<actuator_id>/command")
    @require_token
    def actuator_command(actuator_id: str):
        body = request.get_json(silent=True) or {}
        command = Command(
            actuator_id=actuator_id,
            action=body.get("action", "on"),
            duration_s=body.get("duration_s"),
            params=body.get("params", {}),
            source="manual",
        )
        try:
            result = controller.execute(command)
        except KeyError:
            return jsonify({"error": f"Unknown actuator {actuator_id!r}"}), 404
        status = 200 if result.accepted else 422
        return jsonify(result.to_dict()), status

    # -- control ---------------------------------------------------------- #
    @app.post("/control/tick")
    @require_token
    def control_tick():
        return jsonify(cycle.run_once())

    @app.get("/control/status")
    def control_status():
        return jsonify(cycle.status())

    # -- events ----------------------------------------------------------- #
    @app.get("/events")
    def events():
        try:
            n = int(request.args.get("n", 50))
        except ValueError:
            n = 50
        return jsonify({"events": [e.to_dict() for e in event_store.recent(n)]})

    return app
