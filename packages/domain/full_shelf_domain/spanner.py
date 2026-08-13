"""Read-only access to Full Shelf's authoritative Spanner database."""

import os

from google.cloud import spanner


INSTANCE_ID = os.getenv("SPANNER_INSTANCE_ID", "fef-smoke-spanner")
DATABASE_ID = os.getenv("SPANNER_DATABASE_ID", "full-shelf-main")
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "preflight-hackathon")

_client = None


def get_spanner_database():
    global _client
    if _client is None:
        _client = spanner.Client(project=PROJECT_ID)
    instance = _client.instance(INSTANCE_ID)
    return instance.database(DATABASE_ID)


def get_active_plan_revision(tenant_id: str = "east-bay-food-bank") -> str:
    """Read the active plan revision; never fabricate a canonical fallback."""

    database = get_spanner_database()
    with database.snapshot() as snapshot:
        results = list(
            snapshot.execute_sql(
                "SELECT revision FROM PlanRevisions "
                "WHERE tenant_id = @tenant_id AND status = 'ACTIVE' "
                "ORDER BY created_at DESC LIMIT 1",
                params={"tenant_id": tenant_id},
                param_types={"tenant_id": spanner.param_types.STRING},
            )
        )
    if results:
        return results[0][0]
    raise LookupError(f"No active plan revision exists for tenant {tenant_id}")
