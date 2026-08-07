import hmac
import hashlib
import json
from typing import Dict, Any
from .models import ApprovalEnvelope, PlanDiff


def compute_plan_diff_hash(diff: PlanDiff) -> str:
    """Computes deterministic SHA-256 hash of the complete PlanDiff."""
    diff_dict = {
        "source_revision": diff.source_revision,
        "proposed_revision": diff.proposed_revision,
        "reroute_order_id": diff.reroute_order_id,
        "reroute_cases": diff.reroute_cases,
        "reroute_target_vehicle": diff.reroute_target_vehicle,
        "pickup_order_id": diff.pickup_order_id,
        "pickup_cases": diff.pickup_cases,
    }
    canonical_json = json.dumps(diff_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def construct_signed_payload_string(envelope: ApprovalEnvelope) -> str:
    """Constructs the canonical signed payload string covering all rev08 plan diff fields."""
    d = envelope.plan_diff
    computed_diff_hash = compute_plan_diff_hash(d)
    
    return (
        f"{envelope.approval_id}:{envelope.rev_id}:{envelope.principal_id}:{envelope.incident_id}:"
        f"{envelope.plan_id}:{envelope.source_revision}:{envelope.proposed_revision}:"
        f"{d.reroute_order_id}:{d.reroute_cases}:{d.reroute_target_vehicle}:"
        f"{d.pickup_order_id}:{d.pickup_cases}:{computed_diff_hash}:{envelope.kms_key_version}:{envelope.expires_at}"
    )


def verify_kms_approval_envelope(envelope: ApprovalEnvelope, secret_key: bytes = b"full-shelf-kms-key") -> bool:
    """
    Verifies that the KMS approval envelope cryptographically binds:
    - source_revision ('rev07') and proposed_revision ('rev08')
    - O202: 22 cases reassigned to Truck 2
    - O203: 20 cases converted to refrigerated partner pickup
    - plan_diff_hash
    - approver identity, incident ID, expiration, kms_key_version
    """
    # 1. Verify internal plan_diff_hash matches the diff contents
    expected_diff_hash = compute_plan_diff_hash(envelope.plan_diff)
    if envelope.plan_diff.plan_diff_hash != expected_diff_hash:
        return False

    # 2. Verify HMAC / KMS signature over canonical signed string
    signed_data = construct_signed_payload_string(envelope)
    expected_sig = hmac.new(secret_key, signed_data.encode("utf-8"), hashlib.sha256).hexdigest()
    
    return hmac.compare_digest(envelope.kms_signature, expected_sig)


def create_signed_approval_envelope(
    approval_id: str,
    rev_id: str = "rev08",
    principal_id: str = "operations-director@fullshelf.org",
    incident_id: str = "INC-TRUCK-01",
    plan_id: str = "PLAN-2026-08-07",
    source_revision: str = "rev07",
    proposed_revision: str = "rev08",
    reroute_order_id: str = "O202",
    reroute_cases: int = 22,
    reroute_target_vehicle: str = "TRUCK-02",
    pickup_order_id: str = "O203",
    pickup_cases: int = 20,
    expires_at: str = "2026-08-07T18:00:00Z",
    kms_key_version: str = "projects/preflight-hackathon/locations/us-central1/keyRings/full-shelf-keyring/cryptoKeys/approval-signer/cryptoKeyVersions/1",
    secret_key: bytes = b"full-shelf-kms-key",
) -> ApprovalEnvelope:
    """Generates a valid signed approval envelope covering the complete plan diff."""
    temp_diff = PlanDiff(
        source_revision=source_revision,
        proposed_revision=proposed_revision,
        reroute_order_id=reroute_order_id,
        reroute_cases=reroute_cases,
        reroute_target_vehicle=reroute_target_vehicle,
        pickup_order_id=pickup_order_id,
        pickup_cases=pickup_cases,
        plan_diff_hash="",
    )
    p_hash = compute_plan_diff_hash(temp_diff)
    temp_diff.plan_diff_hash = p_hash

    envelope = ApprovalEnvelope(
        approval_id=approval_id,
        rev_id=rev_id,
        principal_id=principal_id,
        incident_id=incident_id,
        plan_id=plan_id,
        source_revision=source_revision,
        proposed_revision=proposed_revision,
        plan_diff=temp_diff,
        kms_key_version=kms_key_version,
        kms_signature="",
        expires_at=expires_at,
    )

    signed_data = construct_signed_payload_string(envelope)
    envelope.kms_signature = hmac.new(secret_key, signed_data.encode("utf-8"), hashlib.sha256).hexdigest()
    return envelope
