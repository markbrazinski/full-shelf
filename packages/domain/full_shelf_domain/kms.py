import hmac
import hashlib
import json
import base64
import os
from typing import Dict, Any, Optional
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from google.cloud import kms_v1

from .models import ApprovalEnvelope, PlanDiff

LIVE_KMS_RESOURCE_PATH = os.getenv(
    "KMS_KEY_VERSION_PATH",
    "projects/preflight-hackathon/locations/us-central1/keyRings/full-shelf-keyring/cryptoKeys/approval-signer/cryptoKeyVersions/1"
)

_cached_public_key_pem = None


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


def get_kms_public_key_pem(kms_key_version: str = LIVE_KMS_RESOURCE_PATH) -> Optional[str]:
    """Retrieves the public key PEM for the asymmetric signing key from Cloud KMS."""
    global _cached_public_key_pem
    if _cached_public_key_pem is not None:
        return _cached_public_key_pem

    try:
        client = kms_v1.KeyManagementServiceClient()
        pub_key_resp = client.get_public_key(request={"name": kms_key_version})
        _cached_public_key_pem = pub_key_resp.pem
        return _cached_public_key_pem
    except Exception as ex:
        print(f"Failed to fetch Cloud KMS public key: {ex}")
        return None


def verify_kms_approval_envelope(
    envelope: ApprovalEnvelope, secret_key: bytes = b"full-shelf-kms-key"
) -> bool:
    """
    Verifies that the KMS approval envelope cryptographically binds:
    - source_revision ('rev07') and proposed_revision ('rev08')
    - O202: 22 cases reassigned to Truck 2
    - O203: 20 cases converted to refrigerated partner pickup
    - plan_diff_hash
    - approver identity, incident ID, expiration, kms_key_version
    Supports both live RSA PKCS1v15 Cloud KMS asymmetric signatures and HMAC fallbacks.
    """
    # 1. Verify internal plan_diff_hash matches the diff contents
    expected_diff_hash = compute_plan_diff_hash(envelope.plan_diff)
    if envelope.plan_diff.plan_diff_hash != expected_diff_hash:
        return False

    # 2. Construct canonical signed payload data
    signed_data = construct_signed_payload_string(envelope).encode("utf-8")

    # 3. Attempt RSA PKCS1v15 Verification via Cloud KMS public key if signature is base64
    try:
        sig_bytes = base64.b64decode(envelope.kms_signature)
        pem = get_kms_public_key_pem(envelope.kms_key_version)
        if pem and len(sig_bytes) == 256:
            pub_key = load_pem_public_key(pem.encode("utf-8"))
            pub_key.verify(
                sig_bytes,
                signed_data,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            return True
    except Exception:
        pass

    # 4. Fallback HMAC-SHA256 signature check
    expected_sig = hmac.new(secret_key, signed_data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(envelope.kms_signature, expected_sig)


def create_signed_approval_envelope(
    approval_id: str = "APP-008",
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
    kms_key_version: str = LIVE_KMS_RESOURCE_PATH,
    secret_key: bytes = b"full-shelf-kms-key",
    use_live_kms: bool = True,
) -> ApprovalEnvelope:
    """Generates a valid signed approval envelope using live Cloud KMS asymmetric RSA signing or HMAC fallback."""
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

    signed_data_str = construct_signed_payload_string(envelope)
    signed_bytes = signed_data_str.encode("utf-8")

    if use_live_kms:
        try:
            client = kms_v1.KeyManagementServiceClient()
            digest = hashlib.sha256(signed_bytes).digest()
            sign_res = client.asymmetric_sign(
                request={"name": kms_key_version, "digest": {"sha256": digest}}
            )
            envelope.kms_signature = base64.b64encode(sign_res.signature).decode("utf-8")
            return envelope
        except Exception as ex:
            print(f"Live Cloud KMS signing note (falling back to HMAC): {ex}")

    # Fallback HMAC-SHA256 signature
    envelope.kms_signature = hmac.new(secret_key, signed_bytes, hashlib.sha256).hexdigest()
    return envelope
