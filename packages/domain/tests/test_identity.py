from datetime import datetime, timezone

import pytest

from full_shelf_domain.identity import (
    GoogleOidcVerifier,
    IdentityConfigurationError,
    InvalidIdentityToken,
    MissingIdentityToken,
    UnauthorizedIdentity,
    extract_bearer_token,
)


AUDIENCE = "https://full-shelf-plan-ledger.example.run.app"
SUBJECT = "105774551577568412756"
EMAIL = "full-shelf-orchestrator-sa@example.iam.gserviceaccount.com"
NOW = datetime(2026, 8, 13, 21, 0, tzinfo=timezone.utc)


def valid_claims(**overrides):
    claims = {
        "iss": "https://accounts.google.com",
        "aud": AUDIENCE,
        "sub": SUBJECT,
        "email": EMAIL,
        "email_verified": True,
        "exp": int(NOW.timestamp()) + 300,
    }
    claims.update(overrides)
    return claims


def verifier_for(claims=None, error=None):
    def verify(token, request, audience, clock_skew_in_seconds):
        assert token == "signed-token"
        assert audience == AUDIENCE
        assert clock_skew_in_seconds == 0
        if error:
            raise error
        return claims or valid_claims()

    return GoogleOidcVerifier(
        audience=AUDIENCE,
        allowed_subjects={SUBJECT},
        allowed_emails={EMAIL},
        token_verifier=verify,
        request_factory=lambda: object(),
        now=lambda: NOW,
    )


def test_missing_authorization_is_rejected():
    with pytest.raises(MissingIdentityToken):
        verifier_for().verify_authorization(None)


@pytest.mark.parametrize(
    "authorization",
    ["signed-token", "Basic signed-token", "Bearer", "Bearer one two"],
)
def test_malformed_authorization_is_rejected(authorization):
    with pytest.raises(MissingIdentityToken):
        extract_bearer_token(authorization)


def test_unsigned_or_bad_signature_is_rejected():
    with pytest.raises(InvalidIdentityToken):
        verifier_for(error=ValueError("signature verification failed")).verify_token("signed-token")


@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"iss": "https://attacker.example"},
        {"aud": "https://wrong-audience.example"},
        {"exp": int(NOW.timestamp())},
        {"email_verified": False},
    ],
)
def test_invalid_required_claim_is_rejected(claim_overrides):
    with pytest.raises(InvalidIdentityToken):
        verifier_for(valid_claims(**claim_overrides)).verify_token("signed-token")


@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"sub": None},
        {"sub": ""},
        {"email": None},
        {"email": ""},
        {"exp": "not-a-timestamp"},
    ],
)
def test_missing_or_malformed_identity_claim_is_rejected(claim_overrides):
    with pytest.raises(InvalidIdentityToken):
        verifier_for(valid_claims(**claim_overrides)).verify_token("signed-token")


def test_unauthorized_subject_is_forbidden():
    with pytest.raises(UnauthorizedIdentity):
        verifier_for(valid_claims(sub="999999999999999999999")).verify_token("signed-token")


def test_unauthorized_email_is_forbidden():
    with pytest.raises(UnauthorizedIdentity):
        verifier_for(valid_claims(email="other@example.com")).verify_token("signed-token")


def test_correct_identity_is_returned():
    identity = verifier_for().verify_authorization("Bearer signed-token")
    assert identity.subject == SUBJECT
    assert identity.email == EMAIL
    assert identity.audience == AUDIENCE


@pytest.mark.parametrize(
    "audience,subjects,emails",
    [("", {SUBJECT}, {EMAIL}), (AUDIENCE, set(), {EMAIL}), (AUDIENCE, {SUBJECT}, set())],
)
def test_missing_boundary_configuration_fails_closed(audience, subjects, emails):
    with pytest.raises(IdentityConfigurationError):
        GoogleOidcVerifier(audience=audience, allowed_subjects=subjects, allowed_emails=emails)
