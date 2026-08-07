import pytest
from full_shelf_domain.kms import create_signed_approval_envelope, verify_kms_approval_envelope


def test_kms_approval_envelope_valid_rev08_signature():
    """Valid KMS approval envelope rev08 covering complete plan diff verifies successfully."""
    envelope = create_signed_approval_envelope(
        approval_id="APP-008",
        rev_id="rev08",
        principal_id="operations-director@fullshelf.org",
        incident_id="INC-TRUCK-01",
        plan_id="PLAN-2026-08-07",
        source_revision="rev07",
        proposed_revision="rev08",
        reroute_order_id="O202",
        reroute_cases=22,
        reroute_target_vehicle="TRUCK-02",
        pickup_order_id="O203",
        pickup_cases=20,
        expires_at="2026-08-07T18:00:00Z",
    )

    assert verify_kms_approval_envelope(envelope) is True


def test_tamper_source_revision_fails():
    """Tampering with source revision (e.g. rev06 instead of rev07) invalidates verification."""
    envelope = create_signed_approval_envelope(approval_id="APP-008", source_revision="rev07")
    envelope.source_revision = "rev06"
    assert verify_kms_approval_envelope(envelope) is False


def test_tamper_proposed_revision_fails():
    """Tampering with proposed revision (e.g. rev09 instead of rev08) invalidates verification."""
    envelope = create_signed_approval_envelope(approval_id="APP-008", proposed_revision="rev08")
    envelope.proposed_revision = "rev09"
    assert verify_kms_approval_envelope(envelope) is False


def test_tamper_reroute_order_id_fails():
    """Tampering with reroute order ID (e.g. O201 instead of O202) invalidates verification."""
    envelope = create_signed_approval_envelope(approval_id="APP-008", reroute_order_id="O202")
    envelope.plan_diff.reroute_order_id = "O201"
    assert verify_kms_approval_envelope(envelope) is False


def test_tamper_reroute_cases_fails():
    """Tampering with reroute case count (e.g. 25 cases instead of 22) invalidates verification."""
    envelope = create_signed_approval_envelope(approval_id="APP-008", reroute_cases=22)
    envelope.plan_diff.reroute_cases = 25
    assert verify_kms_approval_envelope(envelope) is False


def test_tamper_reroute_target_vehicle_fails():
    """Tampering with reroute vehicle (e.g. TRUCK-01 instead of TRUCK-02) invalidates verification."""
    envelope = create_signed_approval_envelope(approval_id="APP-008", reroute_target_vehicle="TRUCK-02")
    envelope.plan_diff.reroute_target_vehicle = "TRUCK-01"
    assert verify_kms_approval_envelope(envelope) is False


def test_tamper_pickup_order_id_fails():
    """Tampering with pickup order ID (e.g. O205 instead of O203) invalidates verification."""
    envelope = create_signed_approval_envelope(approval_id="APP-008", pickup_order_id="O203")
    envelope.plan_diff.pickup_order_id = "O205"
    assert verify_kms_approval_envelope(envelope) is False


def test_tamper_pickup_cases_fails():
    """Tampering with pickup case count (e.g. 30 cases instead of 20) invalidates verification."""
    envelope = create_signed_approval_envelope(approval_id="APP-008", pickup_cases=20)
    envelope.plan_diff.pickup_cases = 30
    assert verify_kms_approval_envelope(envelope) is False


def test_tamper_plan_diff_hash_fails():
    """Tampering with plan diff hash invalidates verification."""
    envelope = create_signed_approval_envelope(approval_id="APP-008")
    envelope.plan_diff.plan_diff_hash = "bad_sha256_hash_value"
    assert verify_kms_approval_envelope(envelope) is False


def test_tamper_principal_id_fails():
    """Tampering with approver identity invalidates verification."""
    envelope = create_signed_approval_envelope(approval_id="APP-008", principal_id="operations-director@fullshelf.org")
    envelope.principal_id = "attacker@malicious.com"
    assert verify_kms_approval_envelope(envelope) is False


def test_tamper_incident_id_fails():
    """Tampering with incident ID invalidates verification."""
    envelope = create_signed_approval_envelope(approval_id="APP-008", incident_id="INC-TRUCK-01")
    envelope.incident_id = "INC-FAKE-99"
    assert verify_kms_approval_envelope(envelope) is False


def test_tamper_expires_at_fails():
    """Tampering with expiration timestamp invalidates verification."""
    envelope = create_signed_approval_envelope(approval_id="APP-008", expires_at="2026-08-07T18:00:00Z")
    envelope.expires_at = "2026-08-08T18:00:00Z"
    assert verify_kms_approval_envelope(envelope) is False


def test_tamper_kms_key_version_fails():
    """Tampering with KMS key version invalidates verification."""
    envelope = create_signed_approval_envelope(approval_id="APP-008")
    envelope.kms_key_version = "projects/preflight-hackathon/locations/us-central1/keyRings/full-shelf-keyring/cryptoKeys/approval-signer/cryptoKeyVersions/999"
    assert verify_kms_approval_envelope(envelope) is False
