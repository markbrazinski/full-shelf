import pytest

from full_shelf_domain import spanner as spanner_module


class EmptySnapshot:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute_sql(self, sql, params, param_types):
        return []


class EmptyDatabase:
    def snapshot(self):
        return EmptySnapshot()


def test_missing_active_revision_never_falls_back_to_rev07(monkeypatch):
    monkeypatch.setattr(spanner_module, "get_spanner_database", lambda: EmptyDatabase())
    with pytest.raises(LookupError, match="No active plan revision"):
        spanner_module.get_active_plan_revision("audit-tenant-with-no-plan")
