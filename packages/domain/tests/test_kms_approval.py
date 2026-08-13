from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, utils

from full_shelf_domain.kms import (
    KmsApprovalError,
    create_signed_approval_envelope,
    verify_kms_approval_envelope,
)


PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_PEM = PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()


class ManagedKmsDouble:
    def asymmetric_sign(self, request):
        digest = request["digest"]["sha256"]
        return SimpleNamespace(signature=PRIVATE_KEY.sign(
            digest, padding.PKCS1v15(), utils.Prehashed(hashes.SHA256())
        ))

    def get_public_key(self, request):
        return SimpleNamespace(pem=PUBLIC_PEM)


def envelope():
    return create_signed_approval_envelope(
        approval_id="APP-008", rev_id="rev08", principal_id="108080450585792522893",
        incident_id="INC-TRUCK-01", plan_id="PLAN-2026-08-07",
        source_revision="rev07", proposed_revision="rev08",
        reroute_order_id="O202", reroute_cases=22,
        reroute_target_vehicle="TRUCK-02", pickup_order_id="O203",
        pickup_cases=20, expires_at="2099-08-13T23:00:00Z",
        kms_client_factory=ManagedKmsDouble,
    )


def verify(value):
    return verify_kms_approval_envelope(
        value,
        now=lambda: datetime(2099, 8, 13, 22, tzinfo=timezone.utc),
        kms_client_factory=ManagedKmsDouble,
    )


def test_managed_signature_verifies():
    assert verify(envelope()) is True


@pytest.mark.parametrize(("path", "value"), [
    ("source_revision", "rev06"), ("proposed_revision", "rev09"),
    ("principal_id", "attacker"), ("incident_id", "INC-FAKE"),
    ("plan_id", "PLAN-FAKE"), ("expires_at", "2099-08-14T23:00:00Z"),
    ("plan_diff.reroute_order_id", "O201"), ("plan_diff.reroute_cases", 25),
    ("plan_diff.reroute_target_vehicle", "TRUCK-01"),
    ("plan_diff.pickup_order_id", "O205"), ("plan_diff.pickup_cases", 30),
    ("plan_diff.plan_diff_hash", "0" * 64),
])
def test_every_bound_field_tamper_fails(path, value):
    signed = envelope()
    target = signed
    parts = path.split(".")
    for part in parts[:-1]:
        target = getattr(target, part)
    setattr(target, parts[-1], value)
    assert verify(signed) is False


def test_expired_approval_fails():
    assert verify_kms_approval_envelope(
        envelope(),
        now=lambda: datetime(2100, 1, 1, tzinfo=timezone.utc),
        kms_client_factory=ManagedKmsDouble,
    ) is False


def test_wrong_key_version_fails():
    signed = envelope()
    signed.kms_key_version += "-wrong"
    assert verify(signed) is False


def test_managed_signing_failure_has_no_hmac_fallback():
    class FailedKms:
        def asymmetric_sign(self, request):
            raise RuntimeError("managed outage")

    with pytest.raises(KmsApprovalError, match="MANAGED_KMS_SIGNING_FAILED"):
        create_signed_approval_envelope(
            approval_id="APP-X", rev_id="rev08", principal_id="sub",
            incident_id="INC-X", plan_id="PLAN-X", source_revision="rev07",
            proposed_revision="rev08", reroute_order_id="O202", reroute_cases=22,
            reroute_target_vehicle="TRUCK-02", pickup_order_id="O203",
            pickup_cases=20, expires_at="2099-08-13T23:00:00Z",
            kms_client_factory=FailedKms,
        )
