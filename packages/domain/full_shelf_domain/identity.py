"""Google-signed identity verification for Full Shelf trust boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Collection, Mapping, Optional

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token


GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})


class IdentityConfigurationError(RuntimeError):
    """Raised when a required identity boundary is not configured."""


class MissingIdentityToken(ValueError):
    """Raised when no bearer identity token was supplied."""


class InvalidIdentityToken(ValueError):
    """Raised when token signature or required claims are invalid."""


class UnauthorizedIdentity(PermissionError):
    """Raised when a valid Google identity is outside the allowlist."""


@dataclass(frozen=True)
class VerifiedGoogleIdentity:
    subject: str
    email: str
    audience: str
    issuer: str
    expires_at: datetime


TokenVerifier = Callable[..., Mapping[str, Any]]


def extract_bearer_token(authorization: Optional[str]) -> str:
    """Extract one strict Bearer token without decoding or logging it."""

    if not authorization:
        raise MissingIdentityToken("Google identity token is required")

    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token or " " in token:
        raise MissingIdentityToken("Authorization must contain one Bearer token")
    return token


class GoogleOidcVerifier:
    """Verify a Google ID token and bind it to an exact audience and caller."""

    def __init__(
        self,
        *,
        audience: str,
        allowed_subjects: Collection[str],
        allowed_emails: Collection[str],
        token_verifier: TokenVerifier = id_token.verify_oauth2_token,
        request_factory: Callable[[], GoogleAuthRequest] = GoogleAuthRequest,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        normalized_audience = audience.strip()
        normalized_subjects = frozenset(value.strip() for value in allowed_subjects if value.strip())
        normalized_emails = frozenset(value.strip().lower() for value in allowed_emails if value.strip())

        if not normalized_audience:
            raise IdentityConfigurationError("OIDC audience is required")
        if not normalized_subjects:
            raise IdentityConfigurationError("At least one immutable Google subject is required")
        if not normalized_emails:
            raise IdentityConfigurationError("At least one Google identity email is required")

        self._audience = normalized_audience
        self._allowed_subjects = normalized_subjects
        self._allowed_emails = normalized_emails
        self._token_verifier = token_verifier
        self._request_factory = request_factory
        self._now = now

    def verify_authorization(self, authorization: Optional[str]) -> VerifiedGoogleIdentity:
        return self.verify_token(extract_bearer_token(authorization))

    def verify_token(self, token: str) -> VerifiedGoogleIdentity:
        try:
            claims = self._token_verifier(
                token,
                self._request_factory(),
                audience=self._audience,
                clock_skew_in_seconds=0,
            )
        except Exception as exc:
            raise InvalidIdentityToken("Google identity token verification failed") from exc

        issuer = claims.get("iss")
        audience = claims.get("aud")
        subject = claims.get("sub")
        email = claims.get("email")
        expires_at = claims.get("exp")

        if issuer not in GOOGLE_ISSUERS:
            raise InvalidIdentityToken("Google identity token issuer is invalid")
        if audience != self._audience:
            raise InvalidIdentityToken("Google identity token audience is invalid")
        if not isinstance(expires_at, (int, float)) or expires_at <= self._now().timestamp():
            raise InvalidIdentityToken("Google identity token is expired")
        if not isinstance(subject, str) or not subject:
            raise InvalidIdentityToken("Google identity token subject is missing")
        if not isinstance(email, str) or not email:
            raise InvalidIdentityToken("Google identity token email is missing")
        if claims.get("email_verified") is not True:
            raise InvalidIdentityToken("Google identity token email is not verified")

        if subject not in self._allowed_subjects or email.lower() not in self._allowed_emails:
            raise UnauthorizedIdentity("Google identity is not permitted at this boundary")

        return VerifiedGoogleIdentity(
            subject=subject,
            email=email,
            audience=audience,
            issuer=issuer,
            expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
        )


def fetch_google_id_token(audience: str) -> str:
    """Mint a Google-signed ID token for one explicit target audience."""

    normalized_audience = audience.strip()
    if not normalized_audience:
        raise IdentityConfigurationError("OIDC audience is required")
    return id_token.fetch_id_token(GoogleAuthRequest(), normalized_audience)


# ---------------------------------------------------------------------------
# Identity Platform operator verification — amendment CR-002
#
# The ISOLATED judge environment only. Judges arrive from unfamiliar locations
# at unpredictable times, where a conventional Google account's security
# challenges would make the demonstration unreliable, so a dedicated Identity
# Platform account acts as the operator there.
#
# Identity Platform tokens are Google-signed, but they are a DIFFERENT issuer
# and audience from Google OAuth, so they get their own verifier rather than a
# loosened one. The canonical boundary keeps GoogleOidcVerifier untouched, and
# nothing here can widen it: a token accepted below is rejected by the
# canonical verifier and vice versa.
# ---------------------------------------------------------------------------

IDENTITY_PLATFORM_ISSUER_PREFIX = "https://securetoken.google.com/"

# Identity Platform records how the account authenticated. Only a real
# password sign-in is accepted; anonymous or custom-token sign-ins are not an
# operator.
IDENTITY_PLATFORM_ALLOWED_PROVIDERS = frozenset({"password"})


class IdentityPlatformOperatorVerifier:
    """Verify a Cloud Identity Platform ID token as the isolated judge operator.

    Every claim CR-002 names is checked explicitly rather than trusted from the
    library's defaults: exact issuer, exact audience, allowlisted subject,
    expiry, authentication time, and the sign-in provider. A token that fails
    any of them raises, and the caller commits zero mutations.
    """

    def __init__(
        self,
        *,
        project_id: str,
        allowed_subjects: Collection[str],
        token_verifier: TokenVerifier = id_token.verify_firebase_token,
        request_factory: Callable[[], GoogleAuthRequest] = GoogleAuthRequest,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_auth_age_seconds: int = 12 * 60 * 60,
    ) -> None:
        normalized_project = project_id.strip()
        normalized_subjects = frozenset(
            value.strip() for value in allowed_subjects if value.strip()
        )
        if not normalized_project:
            raise IdentityConfigurationError("Identity Platform project is required")
        if not normalized_subjects:
            raise IdentityConfigurationError(
                "At least one allowlisted judge subject is required"
            )

        self._project_id = normalized_project
        self._issuer = f"{IDENTITY_PLATFORM_ISSUER_PREFIX}{normalized_project}"
        self._allowed_subjects = normalized_subjects
        self._token_verifier = token_verifier
        self._request_factory = request_factory
        self._now = now
        self._max_auth_age_seconds = max_auth_age_seconds

    def verify_authorization(self, authorization: Optional[str]) -> VerifiedGoogleIdentity:
        return self.verify_token(extract_bearer_token(authorization))

    def verify_token(self, token: str) -> VerifiedGoogleIdentity:
        try:
            claims = self._token_verifier(
                token,
                self._request_factory(),
                audience=self._project_id,
                clock_skew_in_seconds=0,
            )
        except Exception as exc:
            raise InvalidIdentityToken(
                "Identity Platform token verification failed"
            ) from exc
        if not claims:
            raise InvalidIdentityToken("Identity Platform token verification failed")

        issuer = claims.get("iss")
        audience = claims.get("aud")
        # Identity Platform carries the stable account id in `user_id`; `sub`
        # holds the same value and both are checked against the allowlist.
        subject = claims.get("user_id") or claims.get("sub")
        expires_at = claims.get("exp")
        authenticated_at = claims.get("auth_time")

        if issuer != self._issuer:
            raise InvalidIdentityToken("Identity Platform token issuer is invalid")
        if audience != self._project_id:
            raise InvalidIdentityToken("Identity Platform token audience is invalid")
        if not isinstance(expires_at, (int, float)) or expires_at <= self._now().timestamp():
            raise InvalidIdentityToken("Identity Platform token is expired")
        if not isinstance(subject, str) or not subject:
            raise InvalidIdentityToken("Identity Platform token subject is missing")

        # A stale authentication must not approve a mutation hours later on a
        # token that merely has not expired yet.
        if not isinstance(authenticated_at, (int, float)):
            raise InvalidIdentityToken("Identity Platform auth_time is missing")
        age = self._now().timestamp() - authenticated_at
        if age < 0 or age > self._max_auth_age_seconds:
            raise InvalidIdentityToken("Identity Platform authentication is stale")

        provider = ((claims.get("firebase") or {}).get("sign_in_provider"))
        if provider not in IDENTITY_PLATFORM_ALLOWED_PROVIDERS:
            raise InvalidIdentityToken(
                "Identity Platform sign-in provider is not permitted"
            )

        if subject not in self._allowed_subjects:
            raise UnauthorizedIdentity(
                "Identity Platform identity is not permitted at this boundary"
            )

        # Email is informational here: the ALLOWLISTED SUBJECT is the identity,
        # and a dedicated judge account may legitimately carry an unverified
        # address. It is never used to make the authorization decision.
        email = claims.get("email") or f"{subject}@identity-platform.local"

        return VerifiedGoogleIdentity(
            subject=subject,
            email=email,
            audience=audience,
            issuer=issuer,
            expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
        )
