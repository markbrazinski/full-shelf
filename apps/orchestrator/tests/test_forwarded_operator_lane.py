"""CR-002: the forwarded operator lane must be a delivery detail, not a hole.

The judge gateway cannot put the human token in `Authorization` — Cloud Run
claims that header for its own invoker check on a private service — so the
token travels in `X-Full-Shelf-Operator-Authorization` instead.

That is only safe if the forwarded lane is verified exactly as strictly as the
direct one, and if the ORIGINAL token is what continues on to the ledger. A
lane that skipped verification, or a hop that substituted the gateway's own
service identity, would let the gateway approve on a judge's behalf — which is
precisely what the authority model forbids.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import main as orchestrator_main


@pytest.fixture(autouse=True)
def _scope(monkeypatch):
    monkeypatch.setenv("FRONTEND_AUTHORITY_TENANT_ID", "judge-demo")
    monkeypatch.setenv("FRONTEND_AUTHORITY_OPERATING_DAY", "2026-08-14")


def test_the_forwarded_lane_is_verified_not_trusted():
    """A token in the forwarded header goes through the SAME verifier."""
    seen = []

    def verifier(token):
        seen.append(token)
        return MagicMock(subject="judge-subject", email="judge@fullshelf.demo")

    with (
        patch.object(orchestrator_main, "_verify_operator", verifier),
        patch.object(orchestrator_main, "_resolve_authority_scope",
                     return_value=MagicMock()),
    ):
        orchestrator_main.require_frontend_authority(
            authorization=None,
            operator_authorization="Bearer judge-token",
        )

    assert seen == ["Bearer judge-token"], "the forwarded token must be verified"


def test_a_rejected_forwarded_token_is_refused():
    """Arriving in the forwarded lane grants nothing on its own."""
    def verifier(_token):
        raise HTTPException(401, "OPERATOR_GOOGLE_ID_TOKEN_INVALID")

    with (
        patch.object(orchestrator_main, "_verify_operator", verifier),
        patch.object(orchestrator_main, "_resolve_authority_scope",
                     return_value=MagicMock()),
        pytest.raises(HTTPException) as exc,
    ):
        orchestrator_main.require_frontend_authority(
            authorization=None,
            operator_authorization="Bearer forged",
        )
    assert exc.value.status_code == 401


def test_no_operator_token_in_either_lane_is_refused():
    def verifier(token):
        if not token:
            raise HTTPException(401, "OPERATOR_GOOGLE_ID_TOKEN_REQUIRED")
        return MagicMock(subject="s", email="e")

    with (
        patch.object(orchestrator_main, "_verify_operator", verifier),
        patch.object(orchestrator_main, "_resolve_authority_scope",
                     return_value=MagicMock()),
        pytest.raises(HTTPException) as exc,
    ):
        orchestrator_main.require_frontend_authority(
            authorization=None, operator_authorization=None,
        )
    assert exc.value.status_code == 401


def test_the_direct_lane_still_works():
    """An operator calling the service directly is unaffected."""
    seen = []

    def verifier(token):
        seen.append(token)
        return MagicMock(subject="operator", email="op@example.com")

    with (
        patch.object(orchestrator_main, "_verify_operator", verifier),
        patch.object(orchestrator_main, "_resolve_authority_scope",
                     return_value=MagicMock()),
    ):
        orchestrator_main.require_frontend_authority(
            authorization="Bearer direct-token", operator_authorization=None,
        )
    assert seen == ["Bearer direct-token"]


def test_approval_forwards_the_original_human_token_to_the_ledger():
    """The ledger must receive the JUDGE's token, not a re-minted one.

    The ledger verifies the human identity independently before KMS signing.
    Substituting the orchestrator's own service identity here would prove only
    that this service asked, which is not human approval.
    """
    captured = {}

    def fake_post(path, *, payload, trace_id=None, operator_authorization=None,
                  timeout=15.0):
        captured["operator_authorization"] = operator_authorization
        response = MagicMock()
        response.json.return_value = {"receipt_id": "RCT-TEST"}
        return response

    proposal = MagicMock()
    proposal.source_revision = "rev07"
    proposal.proposed_revision = "rev08"
    proposal.tenant_id = "judge-demo"
    proposal.model_dump.return_value = {}

    with (
        patch.object(orchestrator_main, "post_to_plan_ledger", fake_post),
        patch.object(orchestrator_main, "_resolve_authority_scope",
                     return_value=MagicMock()),
    ):
        orchestrator_main.approve_and_activate(
            proposal=proposal,
            authorization=None,
            operator_authorization="Bearer judge-original-token",
            operator=MagicMock(subject="judge-subject",
                               email="judge@fullshelf.demo"),
        )

    assert captured["operator_authorization"] == "Bearer judge-original-token"
