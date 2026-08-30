"""Seed or reset the ISOLATED judge Spanner database — amendment CR-002.

Establishes the canonical `rev07` morning starting state so a judge begins
exactly where the filmed demonstration begins, then lets the live five-agent
fleet drive the day from there.

Safety is the whole point of this script, so it refuses rather than trusts:

  * it will not run against `full-shelf-main`, whatever it is told;
  * it will not run against the canonical tenant;
  * it deletes and reseeds ONLY the judge tenant inside the judge database.

`AGENTS.md` forbids resetting or reseeding the shared canonical database. This
script is the sanctioned counterpart: an isolated database, an isolated tenant,
and a hard refusal to touch anything else.

Usage:
    PYTHONPATH=packages/domain .venv/bin/python scripts/seed_judge_environment.py
    ... --reset      # wipe the judge tenant first, then reseed
"""

import argparse
import os
import sys

from google.cloud import spanner

# The judge environment. Both are asserted, not assumed.
JUDGE_DATABASE = "full-shelf-judge"
JUDGE_TENANT = "judge-demo"
CANONICAL_DATABASE = "full-shelf-main"
CANONICAL_TENANT = "east-bay-food-bank"

INSTANCE = os.getenv("SPANNER_INSTANCE_ID", "fef-smoke-spanner")
PROJECT = os.getenv("GCP_PROJECT_ID", "preflight-hackathon")

DAY = "2026-08-14"
PLAN_ID = f"PLAN-{DAY}"
RECALLED_LOT = "LTC-4471"
SAFE_LOT = "LTC-5090"

# Canonical rev07 morning plan, per AGENTS.md. Truck 1 carries O201/O202/O203;
# Truck 2 carries an existing 36 cases. These exact numbers are what make the
# capacity arithmetic true later: 36 + 22 + 20 = 78 exceeds 60, which is why
# both orders cannot fit and O203 becomes a partner pickup.
VEHICLES = [
    # vehicle_id, name, max_capacity_cases, current_load_cases, is_operational
    ["TRUCK-01", "Refrigerated Truck 1", 60, 60, True],
    ["TRUCK-02", "Refrigerated Truck 2", 60, 36, True],
]

ORDERS = [
    # order_id, agency_id, agency_name, cases, lot_id, vehicle, status
    ["O201", "AGENCY-01", "Agency 01", 18, RECALLED_LOT, "TRUCK-01", "PLANNED"],
    ["O202", "AGENCY-02", "Agency 02", 22, RECALLED_LOT, "TRUCK-01", "PLANNED"],
    ["O203", "AGENCY-03", "Agency 03", 20, RECALLED_LOT, "TRUCK-01", "PLANNED"],
    ["O204", "AGENCY-04", "Agency 04", 36, SAFE_LOT, "TRUCK-02", "PLANNED"],
]

# Current-position custody: 24 + 22 + 20 + 10 + 8 + 12 = 96 physical cases.
# O201's 18 are an intermediate historical subtotal and are NOT re-added, and
# Site 01's 8 sit downstream of Agency 01 rather than being counted twice.
CUSTODY_NODES = [
    # node_id, node_type, name, on_hand_cases, acknowledgment_status
    ["N-WH", "WAREHOUSE", "Main Warehouse", 24, "CONFIRMED"],
    ["N-TR2", "VEHICLE", "Truck 2", 22, "CONFIRMED"],
    ["N-STG", "STAGING", "Pickup Staging", 20, "CONFIRMED"],
    ["N-AG01", "AGENCY", "Agency 01", 10, "CONFIRMED"],
    ["N-ST01", "SUBSITE", "Site 01", 8, "UNCONFIRMED"],
    ["N-AG02", "AGENCY", "Agency 02", 12, "CONFIRMED"],
]

CUSTODY_EDGES = [
    # edge_id, source, target, lot, cases, is_sub_distribution
    ["E-WH-TR2", "N-WH", "N-TR2", RECALLED_LOT, 22, False],
    ["E-WH-STG", "N-WH", "N-STG", RECALLED_LOT, 20, False],
    ["E-WH-AG01", "N-WH", "N-AG01", RECALLED_LOT, 18, False],
    ["E-AG01-ST01", "N-AG01", "N-ST01", RECALLED_LOT, 8, True],
    ["E-WH-AG02", "N-WH", "N-AG02", RECALLED_LOT, 12, False],
]

JUDGE_TABLES_CHILD_FIRST = [
    # Deleted parent-first is unnecessary: every child INTERLEAVEs ON DELETE
    # CASCADE, so removing the Tenants row removes the whole tenant subtree.
    "Tenants",
]


def _assert_isolated(database_id, tenant_id):
    """Refuse to touch canonical state, whatever the arguments say."""
    problems = []
    if database_id != JUDGE_DATABASE:
        problems.append(f"database must be {JUDGE_DATABASE!r}, got {database_id!r}")
    if CANONICAL_DATABASE in database_id:
        problems.append("refusing to operate on the canonical database")
    if tenant_id != JUDGE_TENANT:
        problems.append(f"tenant must be {JUDGE_TENANT!r}, got {tenant_id!r}")
    if CANONICAL_TENANT in tenant_id:
        problems.append("refusing to operate on the canonical tenant")
    if problems:
        raise SystemExit("REFUSED: " + "; ".join(problems))


def wipe(database, tenant_id):
    """Remove the judge tenant. CASCADE takes its whole subtree with it."""
    def _delete(transaction):
        transaction.execute_update(
            "DELETE FROM Tenants WHERE tenant_id = @t",
            params={"t": tenant_id},
            param_types={"t": spanner.param_types.STRING},
        )
    database.run_in_transaction(_delete)


def seed(database, tenant_id):
    """Write the canonical rev07 morning state for the judge tenant."""
    with database.batch() as batch:
        batch.insert(
            "Tenants", ["tenant_id", "name", "created_at"],
            [[tenant_id, "Full Shelf judge environment", spanner.COMMIT_TIMESTAMP]],
        )
        batch.insert(
            "Lots",
            ["tenant_id", "lot_id", "code", "produce_type", "hazard_status",
             "total_cases", "created_at"],
            [
                [tenant_id, RECALLED_LOT, RECALLED_LOT, "Romaine lettuce",
                 "NONE", 96, spanner.COMMIT_TIMESTAMP],
                [tenant_id, SAFE_LOT, SAFE_LOT, "Romaine lettuce",
                 "NONE", 60, spanner.COMMIT_TIMESTAMP],
            ],
        )
        batch.insert(
            "Vehicles",
            ["tenant_id", "vehicle_id", "name", "max_capacity_cases",
             "current_load_cases", "is_operational"],
            [[tenant_id, v[0], v[1], v[2], v[3], v[4]] for v in VEHICLES],
        )
        batch.insert(
            "PlanRevisions",
            ["tenant_id", "plan_id", "revision", "status", "created_at"],
            [[tenant_id, PLAN_ID, "rev07", "ACTIVE", spanner.COMMIT_TIMESTAMP]],
        )
        batch.insert(
            "Orders",
            ["tenant_id", "plan_id", "revision", "order_id",
             "destination_agency_id", "destination_agency_name", "cases",
             "lot_id", "assigned_vehicle_id", "status"],
            [[tenant_id, PLAN_ID, "rev07", o[0], o[1], o[2], o[3], o[4], o[5], o[6]]
             for o in ORDERS],
        )
        batch.insert(
            "CustodyNodes",
            ["tenant_id", "node_id", "node_type", "name", "on_hand_cases",
             "acknowledgment_status"],
            [[tenant_id, n[0], n[1], n[2], n[3], n[4]] for n in CUSTODY_NODES],
        )
        batch.insert(
            "CustodyEdges",
            ["tenant_id", "edge_id", "source_node_id", "target_node_id",
             "lot_id", "case_count", "is_sub_distribution"],
            [[tenant_id, e[0], e[1], e[2], e[3], e[4], e[5]]
             for e in CUSTODY_EDGES],
        )


def summarize(database, tenant_id):
    # A fresh snapshot per table: a single-use snapshot is exhausted by the
    # first read, and reusing one reports every later table as unavailable
    # even though the data is there.
    for table in ("Lots", "Vehicles", "PlanRevisions", "Orders",
                  "CustodyNodes", "CustodyEdges", "Incidents", "Receipts"):
        try:
            with database.snapshot() as snap:
                rows = list(snap.execute_sql(
                    f"SELECT COUNT(*) FROM {table} WHERE tenant_id = @t",
                    params={"t": tenant_id},
                    param_types={"t": spanner.param_types.STRING},
                ))
            print(f"  {table}: {rows[0][0]}")
        except Exception as exc:  # noqa: BLE001 - reporting only
            print(f"  {table}: unavailable ({type(exc).__name__})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=JUDGE_DATABASE)
    parser.add_argument("--tenant", default=JUDGE_TENANT)
    parser.add_argument("--reset", action="store_true",
                        help="wipe the judge tenant before seeding")
    args = parser.parse_args()

    _assert_isolated(args.database, args.tenant)

    client = spanner.Client(project=PROJECT)
    database = client.instance(INSTANCE).database(args.database)

    print(f"judge environment: {PROJECT}/{INSTANCE}/{args.database} "
          f"tenant={args.tenant}")
    if args.reset:
        print("resetting the judge tenant...")
        wipe(database, args.tenant)
    print("seeding canonical rev07 morning state...")
    seed(database, args.tenant)
    print("seeded:")
    summarize(database, args.tenant)
    print("canonical state was not touched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
