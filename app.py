"""Thin entrypoint.

All wiring lives in :func:`farm_agent.bootstrap.build_system`; this module just
builds the app and runs it, so the Docker ``CMD ["python", "app.py"]`` is
unchanged. Configure behaviour with env vars:

    SERIAL_PORT / SERIAL_BAUD   (via WIRING_CONFIG for full control)
    WIRING_CONFIG, POLICY_CONFIG  paths to JSON overrides
    SIMULATE=true               run with no hardware
    DRY_RUN=true                decide + log but do not fire actuators
    API_TOKEN=...               required to call actuator/control endpoints
    PORT=8080
"""

import os

from farm_agent.bootstrap import build_system

app, cycle, controller, hub, event_store = build_system()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
