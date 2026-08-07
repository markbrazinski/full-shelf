import hmac
import hashlib
import json
from typing import Dict, Any
from .models import ApprovalEnvelope


def compute_approval_payload_hash(payload: Dict[str, Any]) -> str:
    """Computes deterministic SHA-256 hash of approval payload dictionary."""
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def verify_kms_approval_envelope(envelope: ApprovalEnvelope, secret_key: bytes = b"full-shelf-kms-key") -> bool:
    """
    Verifies that the KMS approval envelope cryptographically binds:
    - approval_id and rev_id ("rev08")
    - incident_id and plan_id
    - expected_revision ("v1")
    - action_type ("CONVERT_TO_PARTNER_PICKUP")
    - target_order_id ("O203") and target_cases (20)
    - payload_hash
    """
    # Reconstruct canonical signed body
    signed_data = f"{envelope.approval_id}:{envelope.rev_id}:{envelope.incident_id}:{envelope.plan_id}:{envelope.expected_revision}:{envelope.action_type}:{envelope.target_order_id}:{envelope.target_cases}:{envelope.payload_hash}"
    expected_sig = hmac.new(secret_key, signed_data.encode("utf-8"), hashlib.sha256).hexdigest()
    
    return hmac.compare_digest(envelope.kms_signature, expected_sig)


def create_signed_approval_envelope(
    approval_id: str,
    rev_id: str,
    principal_id: str,
    incident_id: str,
    plan_id: str,
    expected_revision: str,
    action_type: str,
    target_order_id: str,
    target_cases: int,
    payload: Dict[str, Any],
    expires_at: str,
    secret_key: bytes = b"full-shelf-kms-key",
) -> ApprovalEnvelope:
    """Generates a valid signed approval envelope for testing & ledger verification."""
    p_hash = compute_approval_payload_hash(payload)
    signed_data = f"{approval_id}:{rev_id}:{incident_id}:{plan_id}:{expected_revision}:{action_type}:{target_order_id}:{target_cases}:{p_hash}"
    sig = hmac.new(secret_key, signed_data.encode("utf-8"), hashlib.sha256).hexdigest()

    return ApprovalEnvelope(
        approval_id=approval_id,
        rev_id=rev_id,
        principal_id=principal_id,
        incident_id=incident_id,
        plan_id=plan_id,
        expected_revision=expected_revision,
        action_type=action_type,
        target_order_id=target_order_id,
        target_cases=target_cases,
        payload_hash=p_hash,
        kms_signature=sig,
        expires_at=expires_at,
    )
