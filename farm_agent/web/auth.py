"""Minimal token auth for state-changing endpoints.

This is a *starter seam*, not a hardened auth system (see
docs/modules/web-api.md): a single bearer token from the ``API_TOKEN`` env var
protects every route that can move hardware. If no token is configured the
guarded routes are refused outright (fail-closed) rather than left open.
"""

from __future__ import annotations

import functools
import os

from flask import current_app, jsonify, request


def require_token(view):
    """Decorator: reject the request unless it carries the configured token."""

    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        configured = current_app.config.get("API_TOKEN") or os.getenv("API_TOKEN")
        if not configured:
            return (
                jsonify(
                    {
                        "error": "This endpoint is disabled because no API_TOKEN "
                        "is configured."
                    }
                ),
                403,
            )
        provided = _extract_token(request)
        if provided != configured:
            return jsonify({"error": "Invalid or missing API token."}), 403
        return view(*args, **kwargs)

    return wrapper


def _extract_token(req) -> str | None:
    header = req.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer ") :].strip()
    return req.headers.get("X-API-Token")
