"""Run the complete local suite behind the WP11 isolated-database boundary."""

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_DATABASE = "full-shelf-audit-wp6-20260813"


def isolated_database(env):
    database_id = env.get("FULL_SHELF_TEST_DATABASE_ID", DEFAULT_AUDIT_DATABASE).strip()
    if not database_id or database_id == "full-shelf-main" or "audit" not in database_id:
        raise RuntimeError(
            "Refusing to run tests without an explicitly named isolated audit database"
        )
    return database_id


def main():
    env = os.environ.copy()
    paths = [
        ROOT / "packages/domain",
        ROOT / "packages/observability",
        ROOT / "apps/orchestrator/src",
        ROOT / "apps/plan-ledger/src",
    ]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        env["PYTHONPATH"] = os.pathsep.join(str(path) for path in paths) + os.pathsep + existing_pythonpath
    else:
        env["PYTHONPATH"] = os.pathsep.join(str(path) for path in paths)
    env["SPANNER_DATABASE_ID"] = isolated_database(env)
    env["GRAPH_AUDIT_DATABASE_ID"] = env["SPANNER_DATABASE_ID"]
    env["FULL_SHELF_TEST_MODE"] = "1"

    print("=== Full Shelf WP11 isolated regression suite ===", flush=True)
    print(f"database boundary: {env['SPANNER_DATABASE_ID']}", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=ROOT,
        env=env,
        check=False,
    )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
