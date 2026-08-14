"""Repository-wide pytest safety boundary for the WP11 regression suite."""

import os


DEFAULT_AUDIT_DATABASE = "full-shelf-audit-wp6-20260813"


def _isolated_database() -> str:
    database_id = os.getenv("FULL_SHELF_TEST_DATABASE_ID", DEFAULT_AUDIT_DATABASE).strip()
    if not database_id or database_id == "full-shelf-main" or "audit" not in database_id:
        raise RuntimeError(
            "Refusing to collect tests without an explicitly named isolated audit database"
        )
    return database_id


# Set this before application modules are imported during test collection. Any accidental
# managed Spanner client construction is therefore pointed away from canonical authority.
os.environ["SPANNER_DATABASE_ID"] = _isolated_database()
os.environ["GRAPH_AUDIT_DATABASE_ID"] = os.environ["SPANNER_DATABASE_ID"]
os.environ["FULL_SHELF_TEST_MODE"] = "1"
