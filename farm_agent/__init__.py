"""farm_agent — a modular smart-farm sensing and actuation framework.

The package is organised in inward-pointing layers (see
docs/architecture/overview.md):

    web        -> HTTP layer (Flask), depends on ...
    control    -> orchestration (cycle, controller, decision strategies)
    sensors / actuators / safety / events / config  -> building blocks
    models / registry / transport                   -> shared core

Nothing reaches hardware without passing the safety guard, and the whole
system runs without hardware in simulation mode.
"""

__version__ = "0.1.0"
