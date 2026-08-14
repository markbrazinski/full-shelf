"""Resolve a tenant to exactly one configured authoritative Spanner database.

The tenant identifier is the authority-scope identifier in Full Shelf.  This
module deliberately does not accept a database identifier from a request: the
mapping is deployment configuration, and an unknown tenant fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import os
import re


class AuthorityConfigurationError(RuntimeError):
    """The deployment cannot safely resolve an authority scope."""


class UnauthorizedAuthorityScope(PermissionError):
    """A caller selected a tenant outside the configured authority scopes."""


@dataclass(frozen=True)
class AuthorityScope:
    tenant_id: str
    database_id: str
    kind: str


class AuthorityScopeResolver:
    """Map configured canonical and audit tenants to immutable DB boundaries."""

    def __init__(
        self,
        *,
        canonical_tenant_id: str,
        canonical_database_id: str,
        audit_database_id: str,
        audit_tenant_ids: set[str],
        audit_tenant_prefixes: set[str] | None = None,
    ) -> None:
        self._canonical_tenant_id = canonical_tenant_id.strip()
        self._canonical_database_id = canonical_database_id.strip()
        self._audit_database_id = audit_database_id.strip()
        self._audit_tenant_ids = frozenset(
            tenant_id.strip() for tenant_id in audit_tenant_ids if tenant_id.strip()
        )
        self._audit_tenant_prefixes = frozenset(
            prefix.strip() for prefix in (audit_tenant_prefixes or set())
            if prefix.strip()
        )
        if not self._canonical_tenant_id or not self._canonical_database_id:
            raise AuthorityConfigurationError(
                "CANONICAL_AUTHORITY_SCOPE_NOT_CONFIGURED"
            )
        if self._canonical_tenant_id in self._audit_tenant_ids:
            raise AuthorityConfigurationError("AUTHORITY_SCOPE_OVERLAP")
        if (self._audit_tenant_ids or self._audit_tenant_prefixes) and not self._audit_database_id:
            raise AuthorityConfigurationError("AUDIT_DATABASE_NOT_CONFIGURED")
        if (self._audit_database_id == self._canonical_database_id
                and (self._audit_tenant_ids or self._audit_tenant_prefixes)):
            raise AuthorityConfigurationError("AUDIT_DATABASE_MUST_BE_ISOLATED")

    @classmethod
    def from_environment(cls) -> "AuthorityScopeResolver":
        audit_tenants = {
            value.strip()
            for value in os.getenv("AUDIT_TENANT_IDS", "").split(",")
            if value.strip()
        }
        audit_prefixes = {
            value.strip()
            for value in os.getenv("AUDIT_TENANT_PREFIXES", "").split(",")
            if value.strip()
        }
        return cls(
            canonical_tenant_id=os.getenv(
                "CANONICAL_TENANT_ID", "east-bay-food-bank"
            ),
            canonical_database_id=os.getenv(
                "SPANNER_DATABASE_ID", "full-shelf-main"
            ),
            audit_database_id=os.getenv("AUDIT_SPANNER_DATABASE_ID", ""),
            audit_tenant_ids=audit_tenants,
            audit_tenant_prefixes=audit_prefixes,
        )

    @property
    def allowed_tenant_ids(self) -> frozenset[str]:
        return frozenset({self._canonical_tenant_id, *self._audit_tenant_ids})

    def resolve(self, tenant_id: str) -> AuthorityScope:
        requested = tenant_id.strip()
        if requested == self._canonical_tenant_id:
            return AuthorityScope(
                tenant_id=requested,
                database_id=self._canonical_database_id,
                kind="CANONICAL",
            )
        canonical_day_prefix = f"{self._canonical_tenant_id}-"
        if requested.startswith(canonical_day_prefix):
            date_token = requested[len(canonical_day_prefix):]
            try:
                parsed_day = date.fromisoformat(
                    f"{date_token[:4]}-{date_token[4:6]}-{date_token[6:]}"
                )
            except ValueError:
                parsed_day = None
            if parsed_day is not None and parsed_day.strftime("%Y%m%d") == date_token:
                return AuthorityScope(
                    tenant_id=requested,
                    database_id=self._canonical_database_id,
                    kind="CANONICAL_OPERATING_DAY",
                )
        if requested in self._audit_tenant_ids:
            return AuthorityScope(
                tenant_id=requested,
                database_id=self._audit_database_id,
                kind="AUDIT_ISOLATED",
            )
        if (
            re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", requested)
            and any(requested.startswith(prefix) and len(requested) > len(prefix)
                    for prefix in self._audit_tenant_prefixes)
        ):
            return AuthorityScope(
                tenant_id=requested,
                database_id=self._audit_database_id,
                kind="AUDIT_ISOLATED_FRESH_OPERATING_DAY",
            )
        raise UnauthorizedAuthorityScope("TENANT_SCOPE_NOT_AUTHORIZED")


def operating_day_authority_id(logical_tenant_id: str, operating_day: str) -> str:
    """Return the stable storage authority for one tenant operating day.

    The relational model isolates an operating day as a tenant-shaped authority
    scope.  This identifier is product identity, not delivery identity: Pub/Sub
    message IDs, publish timestamps, and qualification labels never participate.
    """

    tenant = logical_tenant_id.strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,54}", tenant):
        raise ValueError("OPERATING_DAY_TENANT_INVALID")
    try:
        parsed_day = date.fromisoformat(operating_day)
    except (TypeError, ValueError) as exc:
        raise ValueError("OPERATING_DAY_INVALID") from exc
    return f"{tenant}-{parsed_day.strftime('%Y%m%d')}"
