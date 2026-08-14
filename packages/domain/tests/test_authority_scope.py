import pytest

from full_shelf_domain.authority import (
    AuthorityConfigurationError,
    AuthorityScopeResolver,
    UnauthorizedAuthorityScope,
    operating_day_authority_id,
)


def test_canonical_and_audit_tenants_resolve_to_distinct_databases():
    resolver = AuthorityScopeResolver(
        canonical_tenant_id="east-bay-food-bank",
        canonical_database_id="full-shelf-main",
        audit_database_id="full-shelf-audit",
        audit_tenant_ids={"audit-canonical", "audit-altered"},
    )

    canonical = resolver.resolve("east-bay-food-bank")
    audit = resolver.resolve("audit-altered")

    assert canonical.database_id == "full-shelf-main"
    assert canonical.kind == "CANONICAL"
    assert audit.database_id == "full-shelf-audit"
    assert audit.kind == "AUDIT_ISOLATED"
    assert resolver.allowed_tenant_ids == frozenset(
        {"east-bay-food-bank", "audit-canonical", "audit-altered"}
    )


def test_unknown_tenant_fails_closed():
    resolver = AuthorityScopeResolver(
        canonical_tenant_id="east-bay-food-bank",
        canonical_database_id="full-shelf-main",
        audit_database_id="full-shelf-audit",
        audit_tenant_ids={"audit-canonical"},
    )

    with pytest.raises(UnauthorizedAuthorityScope, match="TENANT_SCOPE_NOT_AUTHORIZED"):
        resolver.resolve("caller-selected-database")


def test_configured_fresh_operating_day_prefix_resolves_without_static_allowlist():
    resolver = AuthorityScopeResolver(
        canonical_tenant_id="east-bay-food-bank",
        canonical_database_id="full-shelf-main",
        audit_database_id="full-shelf-audit",
        audit_tenant_ids=set(),
        audit_tenant_prefixes={"audit-canonical-", "audit-altered-"},
    )

    scope = resolver.resolve("audit-canonical-20260814-a1b2c3d4e5")

    assert scope.database_id == "full-shelf-audit"
    assert scope.kind == "AUDIT_ISOLATED_FRESH_OPERATING_DAY"
    with pytest.raises(UnauthorizedAuthorityScope):
        resolver.resolve("audit-unconfigured-20260814-a1b2c3d4e5")


def test_operating_day_authority_is_stable_and_changes_only_with_product_identity():
    assert operating_day_authority_id("audit-canonical", "2026-08-14") == (
        "audit-canonical-20260814"
    )
    assert operating_day_authority_id("audit-canonical", "2026-08-15") == (
        "audit-canonical-20260815"
    )
    with pytest.raises(ValueError, match="OPERATING_DAY_INVALID"):
        operating_day_authority_id("audit-canonical", "not-a-day")


def test_canonical_operating_day_authority_routes_only_valid_dates_to_main():
    resolver = AuthorityScopeResolver(
        canonical_tenant_id="east-bay-food-bank",
        canonical_database_id="full-shelf-main",
        audit_database_id="full-shelf-audit",
        audit_tenant_ids=set(),
    )
    scope = resolver.resolve("east-bay-food-bank-20260815")
    assert scope.database_id == "full-shelf-main"
    assert scope.kind == "CANONICAL_OPERATING_DAY"
    with pytest.raises(UnauthorizedAuthorityScope):
        resolver.resolve("east-bay-food-bank-20260230")
    with pytest.raises(UnauthorizedAuthorityScope):
        resolver.resolve("east-bay-food-bank-auditor-selected")


@pytest.mark.parametrize(
    ("canonical_database", "audit_database", "audit_tenants", "error"),
    [
        ("full-shelf-main", "", {"audit-canonical"}, "AUDIT_DATABASE_NOT_CONFIGURED"),
        (
            "full-shelf-main",
            "full-shelf-main",
            {"audit-canonical"},
            "AUDIT_DATABASE_MUST_BE_ISOLATED",
        ),
    ],
)
def test_unsafe_audit_database_configuration_fails_startup_resolution(
    canonical_database, audit_database, audit_tenants, error
):
    with pytest.raises(AuthorityConfigurationError, match=error):
        AuthorityScopeResolver(
            canonical_tenant_id="east-bay-food-bank",
            canonical_database_id=canonical_database,
            audit_database_id=audit_database,
            audit_tenant_ids=audit_tenants,
        )


def test_canonical_tenant_cannot_also_be_an_audit_tenant():
    with pytest.raises(AuthorityConfigurationError, match="AUTHORITY_SCOPE_OVERLAP"):
        AuthorityScopeResolver(
            canonical_tenant_id="east-bay-food-bank",
            canonical_database_id="full-shelf-main",
            audit_database_id="full-shelf-audit",
            audit_tenant_ids={"east-bay-food-bank"},
        )
