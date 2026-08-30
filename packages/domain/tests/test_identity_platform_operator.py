"""CR-002: Identity Platform operator verification for the isolated judge env.

Every claim the amendment names is asserted here, and each is asserted by
REJECTION: a token that differs in exactly one claim must fail. A verifier
that silently stopped checking one of them would pass a happy-path test and
fail these.

The canonical Google OAuth boundary must remain unable to accept an Identity
Platform token, and vice versa; the last two tests pin that separation.
"""

import time

import pytest

from full_shelf_domain.identity import (
    GoogleOidcVerifier,
    IdentityConfigurationError,
    IdentityPlatformOperatorVerifier,
    InvalidIdentityToken,
    UnauthorizedIdentity,
)

PROJECT = "preflight-hackathon"
JUDGE_SUBJECT = "MhC4YEY4suYgXHZgsY4UgMvJ1Az1"
ISSUER = f"https://securetoken.google.com/{PROJECT}"


def claims(**overrides):
    now = int(time.time())
    base = {
        "iss": ISSUER,
        "aud": PROJECT,
        "user_id": JUDGE_SUBJECT,
        "sub": JUDGE_SUBJECT,
        "exp": now + 3600,
        "auth_time": now - 60,
        "email": "judge@fullshelf.demo",
        "firebase": {"sign_in_provider": "password"},
    }
    base.update(overrides)
    return base


def verifier(returned, **kwargs):
    """A verifier whose token library returns exactly `returned`."""
    return IdentityPlatformOperatorVerifier(
        project_id=kwargs.pop("project_id", PROJECT),
        allowed_subjects=kwargs.pop("allowed_subjects", {JUDGE_SUBJECT}),
        token_verifier=lambda *a, **k: returned,
        request_factory=lambda: object(),
        **kwargs,
    )


def test_a_well_formed_judge_token_is_accepted():
    identity = verifier(claims()).verify_token("t")
    assert identity.subject == JUDGE_SUBJECT
    assert identity.issuer == ISSUER
    assert identity.audience == PROJECT


def test_configuration_requires_a_project_and_a_subject():
    with pytest.raises(IdentityConfigurationError):
        IdentityPlatformOperatorVerifier(project_id="", allowed_subjects={JUDGE_SUBJECT})
    with pytest.raises(IdentityConfigurationError):
        IdentityPlatformOperatorVerifier(project_id=PROJECT, allowed_subjects=set())


def test_a_foreign_issuer_is_rejected():
    """Another Identity Platform project must not authorize this one."""
    bad = claims(iss="https://securetoken.google.com/some-other-project")
    with pytest.raises(InvalidIdentityToken):
        verifier(bad).verify_token("t")


def test_a_google_oauth_issuer_is_rejected():
    """A conventional Google account is not the judge operator."""
    with pytest.raises(InvalidIdentityToken):
        verifier(claims(iss="https://accounts.google.com")).verify_token("t")


def test_a_foreign_audience_is_rejected():
    with pytest.raises(InvalidIdentityToken):
        verifier(claims(aud="another-project")).verify_token("t")


def test_an_expired_token_is_rejected():
    with pytest.raises(InvalidIdentityToken):
        verifier(claims(exp=int(time.time()) - 1)).verify_token("t")


def test_a_missing_auth_time_is_rejected():
    with pytest.raises(InvalidIdentityToken):
        verifier(claims(auth_time=None)).verify_token("t")


def test_a_stale_authentication_is_rejected():
    """An unexpired token whose sign-in happened long ago cannot approve."""
    stale = claims(auth_time=int(time.time()) - (13 * 60 * 60))
    with pytest.raises(InvalidIdentityToken):
        verifier(stale).verify_token("t")


def test_a_non_password_provider_is_rejected():
    """Anonymous and custom-token sign-ins are not an operator."""
    for provider in ("anonymous", "custom", None):
        bad = claims(firebase={"sign_in_provider": provider})
        with pytest.raises(InvalidIdentityToken):
            verifier(bad).verify_token("t")


def test_an_unlisted_subject_is_rejected():
    """Any other Identity Platform account in the same project is refused."""
    with pytest.raises(UnauthorizedIdentity):
        verifier(claims(user_id="someone-else", sub="someone-else")).verify_token("t")


def test_a_missing_subject_is_rejected():
    with pytest.raises(InvalidIdentityToken):
        verifier(claims(user_id=None, sub=None)).verify_token("t")


def test_a_failing_library_verification_is_rejected():
    """A bad signature surfaces as a refusal, never as an accepted identity."""
    def explode(*a, **k):
        raise ValueError("bad signature")

    v = IdentityPlatformOperatorVerifier(
        project_id=PROJECT,
        allowed_subjects={JUDGE_SUBJECT},
        token_verifier=explode,
        request_factory=lambda: object(),
    )
    with pytest.raises(InvalidIdentityToken):
        v.verify_token("t")


def test_the_canonical_verifier_cannot_accept_a_judge_token():
    """The canonical boundary is unchanged and rejects Identity Platform.

    This is the separation that keeps CR-002 isolated: the judge identity has
    no authority at the canonical boundary.
    """
    canonical = GoogleOidcVerifier(
        audience="canonical-oauth-client-id",
        allowed_subjects={"108080450585792522893"},
        allowed_emails={"markbrazinski@gmail.com"},
        token_verifier=lambda *a, **k: claims(),
        request_factory=lambda: object(),
    )
    with pytest.raises((InvalidIdentityToken, UnauthorizedIdentity)):
        canonical.verify_token("t")


def test_the_judge_verifier_cannot_accept_a_canonical_operator_token():
    """And the canonical operator has no authority at the judge boundary."""
    canonical_claims = {
        "iss": "https://accounts.google.com",
        "aud": "canonical-oauth-client-id",
        "sub": "108080450585792522893",
        "email": "markbrazinski@gmail.com",
        "email_verified": True,
        "exp": int(time.time()) + 3600,
    }
    with pytest.raises(InvalidIdentityToken):
        verifier(canonical_claims).verify_token("t")
