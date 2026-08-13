"""Fail-closed Cloud KMS approval signing and verification."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from google.cloud import kms_v1

from .models import ApprovalEnvelope, PlanDiff


LIVE_KMS_RESOURCE_PATH = os.getenv(
    "KMS_KEY_VERSION_PATH",
    "projects/preflight-hackathon/locations/us-central1/keyRings/full-shelf-keyring/cryptoKeys/approval-signer/cryptoKeyVersions/1",
)


class KmsApprovalError(RuntimeError):
    """Managed KMS could not produce or validate an approval."""


def compute_plan_diff_hash(diff: PlanDiff) -> str:
    values = {
        "source_revision": diff.source_revision,
        "proposed_revision": diff.proposed_revision,
        "reroute_order_id": diff.reroute_order_id,
        "reroute_cases": diff.reroute_cases,
        "reroute_target_vehicle": diff.reroute_target_vehicle,
        "pickup_order_id": diff.pickup_order_id,
        "pickup_cases": diff.pickup_cases,
    }
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def construct_signed_payload_string(envelope: ApprovalEnvelope) -> str:
    diff = envelope.plan_diff
    return (
        f"{envelope.approval_id}:{envelope.rev_id}:{envelope.principal_id}:"
        f"{envelope.incident_id}:{envelope.plan_id}:{envelope.source_revision}:"
        f"{envelope.proposed_revision}:{diff.reroute_order_id}:{diff.reroute_cases}:"
        f"{diff.reroute_target_vehicle}:{diff.pickup_order_id}:{diff.pickup_cases}:"
        f"{compute_plan_diff_hash(diff)}:{envelope.kms_key_version}:{envelope.expires_at}"
    )


def _parse_expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KmsApprovalError("APPROVAL_EXPIRATION_INVALID") from exc
    if parsed.tzinfo is None:
        raise KmsApprovalError("APPROVAL_EXPIRATION_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def create_signed_approval_envelope(
    *,
    approval_id: str,
    rev_id: str,
    principal_id: str,
    incident_id: str,
    plan_id: str,
    source_revision: str,
    proposed_revision: str,
    reroute_order_id: str,
    reroute_cases: int,
    reroute_target_vehicle: str,
    pickup_order_id: str,
    pickup_cases: int,
    expires_at: str,
    kms_key_version: str = LIVE_KMS_RESOURCE_PATH,
    kms_client_factory: Callable[[], object] = kms_v1.KeyManagementServiceClient,
) -> ApprovalEnvelope:
    """Sign the complete envelope with managed asymmetric Cloud KMS only."""
    if kms_key_version != LIVE_KMS_RESOURCE_PATH:
        raise KmsApprovalError("KMS_KEY_VERSION_NOT_ALLOWED")
    if _parse_expiry(expires_at) <= datetime.now(timezone.utc):
        raise KmsApprovalError("APPROVAL_ALREADY_EXPIRED")
    diff = PlanDiff(
        source_revision=source_revision,
        proposed_revision=proposed_revision,
        reroute_order_id=reroute_order_id,
        reroute_cases=reroute_cases,
        reroute_target_vehicle=reroute_target_vehicle,
        pickup_order_id=pickup_order_id,
        pickup_cases=pickup_cases,
        plan_diff_hash="",
    )
    diff.plan_diff_hash = compute_plan_diff_hash(diff)
    envelope = ApprovalEnvelope(
        approval_id=approval_id,
        rev_id=rev_id,
        principal_id=principal_id,
        incident_id=incident_id,
        plan_id=plan_id,
        source_revision=source_revision,
        proposed_revision=proposed_revision,
        plan_diff=diff,
        kms_key_version=kms_key_version,
        kms_signature="",
        expires_at=expires_at,
    )
    digest = hashlib.sha256(construct_signed_payload_string(envelope).encode()).digest()
    try:
        response = kms_client_factory().asymmetric_sign(
            request={"name": kms_key_version, "digest": {"sha256": digest}}
        )
    except Exception as exc:
        raise KmsApprovalError("MANAGED_KMS_SIGNING_FAILED") from exc
    if not response.signature:
        raise KmsApprovalError("MANAGED_KMS_EMPTY_SIGNATURE")
    envelope.kms_signature = base64.b64encode(response.signature).decode("ascii")
    return envelope


def verify_kms_approval_envelope(
    envelope: ApprovalEnvelope,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    kms_client_factory: Callable[[], object] = kms_v1.KeyManagementServiceClient,
) -> bool:
    """Verify key identity, expiry, diff integrity, and RSA signature; fail closed."""
    if envelope.kms_key_version != LIVE_KMS_RESOURCE_PATH:
        return False
    try:
        if _parse_expiry(envelope.expires_at) <= now():
            return False
        if envelope.plan_diff.plan_diff_hash != compute_plan_diff_hash(envelope.plan_diff):
            return False
        signature = base64.b64decode(envelope.kms_signature, validate=True)
        public_key_response = kms_client_factory().get_public_key(
            request={"name": envelope.kms_key_version}
        )
        public_key = load_pem_public_key(public_key_response.pem.encode("utf-8"))
        public_key.verify(
            signature,
            construct_signed_payload_string(envelope).encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except (Exception, InvalidSignature):
        return False
