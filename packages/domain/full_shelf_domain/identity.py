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
