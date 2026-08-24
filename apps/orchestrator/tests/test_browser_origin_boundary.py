"""Behavioral proof that the browser origin boundary is functional and fail-closed.

The operator UI is a separate origin, so a real browser sends a CORS preflight
before every projection read. Those preflights previously died on the closed
route matrix, which made the configured allowlist unreachable in practice.

These tests exercise the actual middleware stack. They assert both that an
allowlisted origin asking for an already-classified route succeeds, and that
every other shape of OPTIONS request is still refused by the closed matrix.
"""

import importlib
import os
import sys

import pytest
from fastapi.testclient import TestClient

import main


ALLOWED = "https://ops.example.com"
DENIED = "https://evil.example.com"

CLASSIFIED_GET = "/api/v1/projections/demo-beats"
CLASSIFIED_POST = "/api/v1/orchestrator/approvals/approve-and-activate"
UNCLASSIFIED = "/api/v1/not-a-registered-route"


@pytest.fixture(scope="module")
def cors_app():
    """A second import of the app with the allowlist configured.

    FRONTEND_ALLOWED_ORIGINS is read at import time, so the deployed
    configuration cannot be simulated by mutating the already-imported module.
    """
    previous = os.environ.get("FRONTEND_ALLOWED_ORIGINS")
    os.environ["FRONTEND_ALLOWED_ORIGINS"] = ALLOWED
    saved = sys.modules.pop("main")
    try:
        configured = importlib.import_module("main")
        yield configured.app
    finally:
        sys.modules["main"] = saved
        if previous is None:
            os.environ.pop("FRONTEND_ALLOWED_ORIGINS", None)
        else:
            os.environ["FRONTEND_ALLOWED_ORIGINS"] = previous


def preflight(app, path, *, origin, method):
    return TestClient(app).options(
        path,
        headers={"Origin": origin, "Access-Control-Request-Method": method},
    )


# --- positive: the allowlist is actually reachable ---------------------------


@pytest.mark.parametrize("path,method", [
    (CLASSIFIED_GET, "GET"),
    ("/api/v1/projections/stream", "GET"),
    (CLASSIFIED_POST, "POST"),
])
def test_allowlisted_origin_may_preflight_a_classified_route(cors_app, path, method):
    response = preflight(cors_app, path, origin=ALLOWED, method=method)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED


# --- negative: every other shape stays closed --------------------------------


def test_disallowed_origin_is_refused(cors_app):
    response = preflight(cors_app, CLASSIFIED_GET, origin=DENIED, method="GET")
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


def test_unclassified_target_path_is_refused(cors_app):
    response = preflight(cors_app, UNCLASSIFIED, origin=ALLOWED, method="GET")
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


def test_unsupported_requested_method_is_refused(cors_app):
    """DELETE on a classified path is not in the matrix, so it is not classified."""
    response = preflight(cors_app, CLASSIFIED_GET, origin=ALLOWED, method="DELETE")
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


def test_method_classified_only_on_a_different_path_is_refused(cors_app):
    """POST is classified elsewhere, but not on the projections path."""
    response = preflight(cors_app, CLASSIFIED_GET, origin=ALLOWED, method="POST")
    assert response.status_code == 403


def test_ordinary_options_without_preflight_headers_is_refused(cors_app):
    client = TestClient(cors_app)
    assert client.options(CLASSIFIED_GET).status_code == 403
    # Origin alone is not a preflight; the browser must also name the method.
    assert client.options(
        CLASSIFIED_GET, headers={"Origin": ALLOWED}
    ).status_code == 403
    # A requested method without an Origin is not a browser preflight either.
    assert client.options(
        CLASSIFIED_GET, headers={"Access-Control-Request-Method": "GET"}
    ).status_code == 403


def test_preflight_never_returns_a_wildcard_or_credentials(cors_app):
    response = preflight(cors_app, CLASSIFIED_GET, origin=ALLOWED, method="GET")
    assert response.headers["access-control-allow-origin"] != "*"
    assert "access-control-allow-credentials" not in response.headers


def test_preflight_does_not_reach_the_handler_or_widen_the_matrix(cors_app):
    """A preflight is answered by CORSMiddleware and carries no authority."""
    assert not any(
        method == "OPTIONS" for method, _ in main.ROUTE_AUTHENTICATION_MATRIX
    )
    # Still unauthenticated: the preflight grants nothing to the real request.
    assert TestClient(cors_app).get(CLASSIFIED_GET).status_code in (401, 503)


def test_unconfigured_deployment_admits_no_preflight_at_all():
    """With no allowlist configured, no origin can preflight anything."""
    assert main.FRONTEND_ALLOWED_ORIGINS == []
    response = preflight(main.app, CLASSIFIED_GET, origin=ALLOWED, method="GET")
    assert response.status_code == 403


def test_private_plan_ledger_receives_no_cors_configuration():
    ledger_src = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "plan-ledger", "src")
    )
    with open(os.path.join(ledger_src, "main.py")) as handle:
        source = handle.read()
    assert "CORSMiddleware" not in source
    assert "Access-Control-Allow-Origin" not in source
