import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import main
from full_shelf_domain.identity import (
    InvalidIdentityToken,
    UnauthorizedIdentity,
    VerifiedGoogleIdentity,
)


HUMAN_AUDIENCE = "human-client.apps.googleusercontent.com"
SERVICE_AUDIENCE = "https://orchestrator.example.run.app"
HUMAN = VerifiedGoogleIdentity(
    subject="mark-subject",
    email="mark@example.com",
    audience=HUMAN_AUDIENCE,
    issuer="https://accounts.google.com",
    expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
)
WORKLOAD = VerifiedGoogleIdentity(
    subject="workload-subject",
    email="orchestrator@example.iam.gserviceaccount.com",
    audience=SERVICE_AUDIENCE,
    issuer="https://accounts.google.com",
    expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
)


class DeterministicBoundaryVerifier:
    def __init__(self, *, audience, allowed_subjects, allowed_emails):
        self.audience = audience

    def verify_authorization(self, authorization):
        if authorization == "Bearer human-signed" and self.audience == HUMAN_AUDIENCE:
            return HUMAN
        if authorization == "Bearer workload-signed" and self.audience == SERVICE_AUDIENCE:
            return WORKLOAD
        if authorization == "Bearer unauthorized-human" and self.audience == HUMAN_AUDIENCE:
            raise UnauthorizedIdentity("subject outside allowlist")
        raise InvalidIdentityToken("signature, audience, or expiry invalid")


@pytest.fixture
def identity_boundaries(monkeypatch):
    monkeypatch.setenv("OPERATOR_OAUTH_CLIENT_ID", HUMAN_AUDIENCE)
    monkeypatch.setenv("ALLOWED_OPERATOR_SUBJECT", HUMAN.subject)
    monkeypatch.setenv("ALLOWED_OPERATOR_EMAIL", HUMAN.email)
    monkeypatch.setattr(main, "MANAGED_CALLBACK_AUDIENCE", SERVICE_AUDIENCE)
    monkeypatch.setattr(main, "MANAGED_CALLBACK_SERVICE_ACCOUNT_SUBJECT", WORKLOAD.subject)
    monkeypatch.setattr(main, "MANAGED_CALLBACK_SERVICE_ACCOUNT_EMAIL", WORKLOAD.email)
    monkeypatch.setattr(main, "GoogleOidcVerifier", DeterministicBoundaryVerifier)


def test_every_registered_route_has_exactly_one_classification():
    registered = main.registered_route_authentication_matrix()
    assert registered == main.ROUTE_AUTHENTICATION_MATRIX
    assert set(registered.values()) == {
        main.PUBLIC_HEALTH,
        main.HUMAN_OPERATOR,
        main.MANAGED_CALLBACK,
        main.PARTNER_CALLBACK,
        main.INTERNAL_WORKLOAD,
        main.DISABLED_OR_REMOVED,
    }
    assert not main.REMOVED_FRAMEWORK_ROUTES.intersection(registered)


def test_sensitive_route_classification_has_matching_authentication_dependency():
    human_dependencies = {
        "/api/v1/orchestrator/approvals/approve-and-activate": "require_human_operator",
        "/api/v1/projections/demo-beats": "require_frontend_authority",
        "/api/v1/projections/stream": "require_frontend_authority",
    }
    expected_by_policy = {
        main.MANAGED_CALLBACK: "require_managed_callback",
        main.PARTNER_CALLBACK: "require_partner_callback",
        main.INTERNAL_WORKLOAD: "require_internal_workload",
    }
    for route in main.app.routes:
        if not isinstance(route, APIRoute):
            continue
        dependencies = {item.call.__name__ for item in route.dependant.dependencies}
        policy = main.ROUTE_AUTHENTICATION_MATRIX[(next(iter(route.methods)), route.path)]
        if policy == main.HUMAN_OPERATOR:
            assert human_dependencies[route.path] in dependencies
        elif policy in expected_by_policy:
            assert expected_by_policy[policy] in dependencies
        else:
            assert not dependencies


def test_newly_registered_route_fails_classification_check():
    original_count = len(main.app.routes)
    main.app.add_api_route("/unclassified-test", lambda: {"unsafe": True}, methods=["GET"])
    try:
        with pytest.raises(RuntimeError, match="UNCLASSIFIED_ORCHESTRATOR_ROUTE"):
            main.registered_route_authentication_matrix()
    finally:
        del main.app.routes[original_count:]


def test_default_deny_and_removed_framework_routes():
    client = TestClient(main.app)
    assert client.get("/not-registered").status_code == 403
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(path).status_code == 403


def test_only_health_routes_succeed_without_identity(identity_boundaries, monkeypatch):
    client = TestClient(main.app)
    assert client.get("/").status_code == 200
    assert client.get("/healthz").status_code == 200

    monkeypatch.setenv("FRONTEND_AUTHORITY_TENANT_ID", "audit-final-canonical-20260814")
    monkeypatch.setenv("FRONTEND_AUTHORITY_OPERATING_DAY", "2026-08-14")
    assert client.get("/api/v1/projections/demo-beats").status_code == 401
    assert client.post("/api/v1/orchestrator/pubsub/push", json={}).status_code == 401
    assert client.get("/api/v1/evidence/system").status_code == 401
    assert client.get(
        "/api/v1/evidence/system",
        headers={"X-Full-Shelf-API-Key": "retired-key"},
    ).status_code == 401
    assert client.get(
        "/api/v1/evidence/system",
        headers={"X-Goog-Authenticated-User-Id": "accounts.google.com:mark-subject"},
    ).status_code == 401


def test_human_callback_and_internal_tokens_are_not_interchangeable(identity_boundaries):
    assert main._verify_operator("Bearer human-signed") == HUMAN
    assert main._verify_managed_callback("Bearer workload-signed") == WORKLOAD
    assert main._verify_internal_workload("Bearer workload-signed") == WORKLOAD

    with pytest.raises(HTTPException) as human_to_callback:
        main._verify_managed_callback("Bearer human-signed")
    assert human_to_callback.value.status_code == 401
    with pytest.raises(HTTPException) as human_to_internal:
        main._verify_internal_workload("Bearer human-signed")
    assert human_to_internal.value.status_code == 401
    with pytest.raises(HTTPException) as workload_to_human:
        main._verify_operator("Bearer workload-signed")
    assert workload_to_human.value.status_code == 401
    with pytest.raises(HTTPException) as unauthorized_human:
        main._verify_operator("Bearer unauthorized-human")
    assert unauthorized_human.value.status_code == 403
    with pytest.raises(HTTPException) as forged_human:
        main._verify_operator("Bearer forged")
    assert forged_human.value.status_code == 401


def test_correct_callback_reaches_callback_logic(identity_boundaries):
    response = TestClient(main.app).post(
        "/api/v1/orchestrator/pubsub/push",
        headers={"Authorization": "Bearer workload-signed"},
        json={},
    )
    assert response.status_code == 200
    assert response.json()["mutations_applied"] == 0


def test_correct_internal_workload_reaches_request_validation(identity_boundaries):
    response = TestClient(main.app).get(
        "/api/v1/orchestrator/custody/graph",
        headers={"Authorization": "Bearer workload-signed"},
    )
    assert response.status_code == 422


def test_correct_human_token_reaches_approval_and_is_forwarded_unchanged(
    identity_boundaries, monkeypatch
):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"approval_receipt": {}, "activation_receipt": {}}

    observed = {}

    def post_to_ledger(path, *, payload, trace_id, operator_authorization):
        observed.update(path=path, operator_authorization=operator_authorization)
        return Response()

    monkeypatch.setattr(main, "_resolve_authority_scope", lambda tenant: object())
    monkeypatch.setattr(main, "post_to_plan_ledger", post_to_ledger)
    response = TestClient(main.app).post(
        "/api/v1/orchestrator/approvals/approve-and-activate",
        headers={"Authorization": "Bearer human-signed"},
        json={
            "command_id": "CMD-MICRO4",
            "idempotency_key": "micro4:approval",
            "tenant_id": "audit-final-canonical-20260814",
            "operating_day": "2026-08-14",
            "incident_id": "INC-MICRO4",
            "plan_id": "PLAN-AUDIT-CANONICAL",
            "source_revision": "rev07",
            "proposed_revision": "rev08",
            "approval_id": "APR-MICRO4",
            "expires_at": "2026-08-14T23:00:00Z",
            "plan_diff": {
                "reroute_order_id": "O202",
                "reroute_cases": 22,
                "reroute_target_vehicle": "TRUCK-2",
                "pickup_order_id": "O203",
                "pickup_cases": 20,
            },
        },
    )
    assert response.status_code == 200
    assert observed["operator_authorization"] == "Bearer human-signed"
    assert response.json()["verified_operator_subject"] == HUMAN.subject


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/orchestrator/s2s-dispatch",
        "/api/v1/orchestrator/recall/execute-hero-loop",
        "/api/v1/demo/reset",
        "/api/v1/demo/seed",
        "/api/v1/demo/replay",
    ],
)
def test_disabled_routes_return_contracted_response(path):
    response = TestClient(main.app).post(path)
    assert response.status_code == 410
