"""Resolve the API token, self-provisioning it into a Kubernetes Secret.

The app needs an ``API_TOKEN`` to guard hardware-moving endpoints. Rather than
require an operator to mint one by hand, a pod running in-cluster provisions it
itself on first start:

1. If ``API_TOKEN`` is set in the environment, use it verbatim (an explicit
   override, and the only path that works off-cluster, e.g. dev / simulation).
2. Otherwise, if running inside Kubernetes, *get-or-create* a Secret in the
   pod's own namespace: read the token if the Secret already has one, else
   generate a random token and write it. Restarts and redeploys reuse the
   stored value, so the token is stable for the life of the Secret.
3. If neither applies (no env var, not in-cluster), return ``None``. The guarded
   endpoints then stay fail-closed (403) — safe, just not callable.

Talking to the API server uses only the standard library and the pod's mounted
ServiceAccount credentials, so no extra dependency is pulled into the image.

Required RBAC (applied to the cluster, not shipped in this repo): the pod's
ServiceAccount needs ``get`` and ``create`` on ``secrets`` in its namespace
(add ``patch`` if a Secret of the same name may pre-exist without the key).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import ssl
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
_TOKEN_FILE = f"{_SA_DIR}/token"
_CA_FILE = f"{_SA_DIR}/ca.crt"
_NAMESPACE_FILE = f"{_SA_DIR}/namespace"


def resolve_api_token() -> str | None:
    """Return the API token to guard the app with, or ``None`` if unavailable."""
    env_token = os.getenv("API_TOKEN")
    if env_token:
        return env_token

    if not _in_cluster():
        logger.warning(
            "No API_TOKEN set and not running in Kubernetes; guarded endpoints "
            "will be disabled (403)."
        )
        return None

    try:
        return _get_or_create_secret_token()
    except Exception:  # never let token provisioning crash the app
        logger.exception(
            "Failed to provision API token from Kubernetes Secret; guarded "
            "endpoints will be disabled (403)."
        )
        return None


def _in_cluster() -> bool:
    return (
        os.path.exists(_TOKEN_FILE)
        and os.getenv("KUBERNETES_SERVICE_HOST") is not None
    )


def _get_or_create_secret_token() -> str | None:
    namespace = os.getenv("API_TOKEN_NAMESPACE") or _read_file(_NAMESPACE_FILE)
    name = os.getenv("API_TOKEN_SECRET_NAME", "farm-agent-api")
    key = os.getenv("API_TOKEN_SECRET_KEY", "API_TOKEN")

    status, body = _api_request("GET", f"/api/v1/namespaces/{namespace}/secrets/{name}")

    if status == 200:
        existing = (body.get("data") or {}).get(key)
        if existing:
            logger.info("Using existing API token from secret %r.", name)
            return base64.b64decode(existing).decode("utf-8")
        # Secret exists but lacks our key: add it.
        token = _new_token()
        _patch_secret_key(namespace, name, key, token)
        logger.info("Added API token to existing secret %r.", name)
        return token

    if status == 404:
        token = _new_token()
        created = _create_secret(namespace, name, key, token)
        if created:
            logger.info("Created secret %r with a new API token.", name)
            return token
        # Lost a create race with another replica: re-read the winner's token.
        status, body = _api_request(
            "GET", f"/api/v1/namespaces/{namespace}/secrets/{name}"
        )
        if status == 200 and (body.get("data") or {}).get(key):
            return base64.b64decode(body["data"][key]).decode("utf-8")
        logger.error("Secret %r unreadable after create conflict.", name)
        return None

    logger.error("Unexpected status %s reading secret %r.", status, name)
    return None


def _create_secret(namespace: str, name: str, key: str, token: str) -> bool:
    """Create the Secret. Returns False on a 409 conflict (someone beat us)."""
    payload = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {"name": name, "namespace": namespace},
        "data": {key: _b64(token)},
    }
    status, _ = _api_request(
        "POST", f"/api/v1/namespaces/{namespace}/secrets", payload
    )
    if status in (200, 201):
        return True
    if status == 409:
        return False
    raise RuntimeError(f"Secret create failed with status {status}.")


def _patch_secret_key(namespace: str, name: str, key: str, token: str) -> None:
    patch = {"data": {key: _b64(token)}}
    status, _ = _api_request(
        "PATCH",
        f"/api/v1/namespaces/{namespace}/secrets/{name}",
        patch,
        content_type="application/merge-patch+json",
    )
    if status not in (200, 201):
        raise RuntimeError(f"Secret patch failed with status {status}.")


def _api_request(
    method: str,
    path: str,
    body: dict | None = None,
    *,
    content_type: str = "application/json",
) -> tuple[int, dict]:
    host = os.environ["KUBERNETES_SERVICE_HOST"]
    port = os.getenv("KUBERNETES_SERVICE_PORT_HTTPS", "443")
    url = f"https://{host}:{port}{path}"

    headers = {"Authorization": f"Bearer {_read_file(_TOKEN_FILE)}", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = content_type

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    context = ssl.create_default_context(cafile=_CA_FILE)
    try:
        with urllib.request.urlopen(request, context=context, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        # 404/409 are expected control-flow signals, not failures.
        return exc.code, json.loads(exc.read() or b"{}")


def _new_token() -> str:
    return secrets.token_hex(32)


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().strip()
