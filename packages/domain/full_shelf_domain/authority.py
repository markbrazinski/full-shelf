"""Resolve a tenant to exactly one configured authoritative Spanner database.

The tenant identifier is the authority-scope identifier in Full Shelf.  This
module deliberately does not accept a database identifier from a request: the
mapping is deployment configuration, and an unknown tenant fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


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
    ) -> None:
        self._canonical_tenant_id = canonical_tenant_id.strip()
        self._canonical_database_id = canonical_database_id.strip()
        self._audit_database_id = audit_database_id.strip()
        self._audit_tenant_ids = frozenset(
            tenant_id.strip() for tenant_id in audit_tenant_ids if tenant_id.strip()
        )
        if not self._canonical_tenant_id or not self._canonical_database_id:
            raise AuthorityConfigurationError(
                "CANONICAL_AUTHORITY_SCOPE_NOT_CONFIGURED"
            )
        if self._canonical_tenant_id in self._audit_tenant_ids:
            raise AuthorityConfigurationError("AUTHORITY_SCOPE_OVERLAP")
        if self._audit_tenant_ids and not self._audit_database_id:
            raise AuthorityConfigurationError("AUDIT_DATABASE_NOT_CONFIGURED")
        if self._audit_database_id == self._canonical_database_id and self._audit_tenant_ids:
            raise AuthorityConfigurationError("AUDIT_DATABASE_MUST_BE_ISOLATED")

    @classmethod
    def from_environment(cls) -> "AuthorityScopeResolver":
        audit_tenants = {
            value.strip()
            for value in os.getenv("AUDIT_TENANT_IDS", "").split(",")
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
        if requested in self._audit_tenant_ids:
            return AuthorityScope(
                tenant_id=requested,
                database_id=self._audit_database_id,
                kind="AUDIT_ISOLATED",
            )
        raise UnauthorizedAuthorityScope("TENANT_SCOPE_NOT_AUTHORIZED")
