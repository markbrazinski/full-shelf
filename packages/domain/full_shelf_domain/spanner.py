import os
from google.cloud import spanner
from google.api_core.exceptions import PermissionDenied, NotFound
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

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


def seed_initial_spanner_data(tenant_id: str = "east-bay-food-bank"):
    """Seeds initial Tenant, Lots, Vehicles, and rev07 PlanRevision if not present."""
    db = get_spanner_database()
    
    def _seed_txn(transaction):
        # 1. Check if tenant exists
        results = list(transaction.execute_sql(
            "SELECT tenant_id FROM Tenants WHERE tenant_id = @tenant_id",
            params={"tenant_id": tenant_id},
            param_types={"tenant_id": spanner.param_types.STRING}
        ))
        if results:
            return

        now = datetime.now(timezone.utc)
        
        # Insert Tenant
        transaction.insert(
            table="Tenants",
            columns=["tenant_id", "name", "created_at"],
            values=[[tenant_id, "East Bay Food Bank", now]]
        )
        
        # Insert Lots
        transaction.insert(
            table="Lots",
            columns=["tenant_id", "lot_id", "code", "produce_type", "hazard_status", "total_cases", "created_at"],
            values=[
                [tenant_id, "LTC-4471", "LOT-REMAINE-4471", "Romaine Lettuce", "RECALLED_ECOLI", 96, now],
                [tenant_id, "LTC-5090", "LOT-ROMAINE-5090", "Romaine Lettuce", "CLEAR_SAFE", 100, now],
            ]
        )

        # Insert Vehicles
        transaction.insert(
            table="Vehicles",
            columns=["tenant_id", "vehicle_id", "name", "max_capacity_cases", "current_load_cases", "is_operational"],
            values=[
                [tenant_id, "TRUCK-01", "Refrigerated Truck 1", 60, 60, True],
                [tenant_id, "TRUCK-02", "Refrigerated Truck 2", 60, 36, True],
            ]
        )

        # Insert PlanRevisions (rev07)
        transaction.insert(
            table="PlanRevisions",
            columns=["tenant_id", "plan_id", "revision", "status", "created_at"],
            values=[
                [tenant_id, "PLAN-2026-08-07", "rev07", "ACTIVE", now],
            ]
        )

        # Insert Orders
        transaction.insert(
            table="Orders",
            columns=["tenant_id", "plan_id", "revision", "order_id", "destination_agency_id", "destination_agency_name", "cases", "lot_id", "assigned_vehicle_id", "status"],
            values=[
                [tenant_id, "PLAN-2026-08-07", "rev07", "O201", "AG01", "Agency 01", 18, "LTC-4471", "TRUCK-01", "SCHEDULED"],
                [tenant_id, "PLAN-2026-08-07", "rev07", "O202", "AG02", "Agency 02", 22, "LTC-4471", "TRUCK-01", "SCHEDULED"],
                [tenant_id, "PLAN-2026-08-07", "rev07", "O203", "AG03", "Agency 03", 20, "LTC-4471", "TRUCK-01", "SCHEDULED"],
                [tenant_id, "PLAN-2026-08-07", "rev07", "O204", "AG04", "Agency 04", 15, "LTC-5090", "TRUCK-02", "SCHEDULED"],
                [tenant_id, "PLAN-2026-08-07", "rev07", "O205", "AG05", "Agency 05", 21, "LTC-5090", "TRUCK-02", "SCHEDULED"],
            ]
        )

    try:
        db.run_in_transaction(_seed_txn)
    except Exception as e:
        print(f"Seed transaction note: {e}")


def get_active_plan_revision(tenant_id: str = "east-bay-food-bank") -> str:
    """Reads current active plan revision from Spanner PlanRevisions table."""
    db = get_spanner_database()
    with db.snapshot() as snapshot:
        results = list(snapshot.execute_sql(
            "SELECT revision FROM PlanRevisions WHERE tenant_id = @tenant_id AND status = 'ACTIVE' ORDER BY created_at DESC LIMIT 1",
            params={"tenant_id": tenant_id},
            param_types={"tenant_id": spanner.param_types.STRING}
        ))
        if results:
            return results[0][0]
        return "rev07"


def attempt_spanner_write_mutation(tenant_id: str = "east-bay-food-bank") -> Dict[str, Any]:
    """
    Attempts a Spanner write mutation.
    When executed under full-shelf-orchestrator-sa (roles/spanner.databaseReader),
    this MUST raise PermissionDenied (403).
    """
    db = get_spanner_database()
    now = datetime.now(timezone.utc)
    
    def _tx(transaction):
        transaction.insert(
            table="Tenants",
            columns=["tenant_id", "name", "created_at"],
            values=[["unauthorized-tenant-proof", "Unauthorized Mutation Test", now]]
        )

    try:
        db.run_in_transaction(_tx)
        return {"status": "UNEXPECTED_MUTATION_SUCCESS", "mutated": True}
    except PermissionDenied as pd:
        return {
            "status": "PERMISSION_DENIED",
            "mutated": False,
            "error_code": 403,
            "message": str(pd),
        }
    except Exception as ex:
        # Check if error message contains 403 or PermissionDenied
        if "403" in str(ex) or "PermissionDenied" in str(ex) or "permission" in str(ex).lower():
            return {
                "status": "PERMISSION_DENIED",
                "mutated": False,
                "error_code": 403,
                "message": str(ex),
            }
        raise ex
