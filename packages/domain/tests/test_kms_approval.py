import pytest
from full_shelf_domain.kms import create_signed_approval_envelope, verify_kms_approval_envelope


def test_kms_approval_envelope_valid_signature():
    """Valid KMS approval envelope rev08 verifies successfully."""
    payload = {"action": "CONVERT_TO_PARTNER_PICKUP", "order_id": "O203", "cases": 20, "plan_id": "PLAN-2026-08-07"}
    envelope = create_signed_approval_envelope(
        approval_id="APP-008",
        rev_id="rev08",
        principal_id="director@fullshelf.org",
        incident_id="INC-TRUCK-01",
        plan_id="PLAN-2026-08-07",
        expected_revision="v1",
        action_type="CONVERT_TO_PARTNER_PICKUP",
        target_order_id="O203",
        target_cases=20,
        payload=payload,
        expires_at="2026-08-07T18:00:00Z",
    )

    assert verify_kms_approval_envelope(envelope) is True


def test_kms_approval_envelope_tampered_payload_hash_fails():
    """Tampering with payload hash invalidates signature verification."""
    payload = {"action": "CONVERT_TO_PARTNER_PICKUP", "order_id": "O203", "cases": 20, "plan_id": "PLAN-2026-08-07"}
    envelope = create_signed_approval_envelope(
        approval_id="APP-008",
        rev_id="rev08",
        principal_id="director@fullshelf.org",
        incident_id="INC-TRUCK-01",
        plan_id="PLAN-2026-08-07",
        expected_revision="v1",
        action_type="CONVERT_TO_PARTNER_PICKUP",
        target_order_id="O203",
        target_cases=20,
        payload=payload,
        expires_at="2026-08-07T18:00:00Z",
    )

    # Tamper with payload_hash
    envelope.payload_hash = "tampered_sha256_hash_value_1234567890"
    assert verify_kms_approval_envelope(envelope) is False


def test_kms_approval_envelope_tampered_target_cases_fails():
    """Tampering with case count invalidates signature verification."""
    payload = {"action": "CONVERT_TO_PARTNER_PICKUP", "order_id": "O203", "cases": 20, "plan_id": "PLAN-2026-08-07"}
    envelope = create_signed_approval_envelope(
        approval_id="APP-008",
        rev_id="rev08",
        principal_id="director@fullshelf.org",
        incident_id="INC-TRUCK-01",
        plan_id="PLAN-2026-08-07",
        expected_revision="v1",
        action_type="CONVERT_TO_PARTNER_PICKUP",
        target_order_id="O203",
        target_cases=20,
        payload=payload,
        expires_at="2026-08-07T18:00:00Z",
    )

    # Tamper with target cases (trying to convert 25 cases instead of approved 20)
    envelope.target_cases = 25
    assert verify_kms_approval_envelope(envelope) is False
