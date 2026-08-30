"""CR-002 state-boundary guard for the isolated judge environment.

A judge deployment that is accidentally pointed at canonical state is the one
failure this amendment cannot tolerate: it would let a demonstration mutate the
evidence the submission rests on. Configuration alone is not protection —
someone copies a deploy command, forgets one flag, and the service comes up
happily talking to `full-shelf-main`.

So the guard runs at STARTUP and fails closed. A judge deployment that names
any canonical resource never becomes healthy, which means Cloud Run never
routes traffic to it, which means it cannot be reached to do harm.

The canonical deployments are unaffected: the guard only engages when a
deployment declares itself a judge deployment.
"""

from __future__ import annotations

import os
from typing import Mapping, Optional

# Canonical resources. A judge deployment naming any of these is misconfigured.
CANONICAL_DATABASE = "full-shelf-main"
CANONICAL_TENANT = "east-bay-food-bank"
CANONICAL_SERVICE_MARKERS = (
    "full-shelf-orchestrator-",
    "full-shelf-plan-ledger-",
)
# The canonical human operator. A judge deployment must never be able to act
# with, or accept, the canonical operator's identity.
CANONICAL_OPERATOR_EMAIL = "markbrazinski@gmail.com"
CANONICAL_OPERATOR_SUBJECT = "108080450585792522893"

# Everything a judge deployment is allowed to point at.
JUDGE_DATABASE = "full-shelf-judge"

# Variables that name a database, a tenant, or a peer service URL.
_RESOURCE_VARS = (
    "SPANNER_DATABASE_ID",
    "GRAPH_AUDIT_DATABASE_ID",
    "AUDIT_SPANNER_DATABASE_ID",
    "PLAN_LEDGER_URL",
    "PLAN_LEDGER_AUDIENCE",
    "ORCHESTRATOR_URL",
    "MANAGED_CALLBACK_AUDIENCE",
    "FRONTEND_AUTHORITY_AUDIENCE",
)
_TENANT_VARS = (
    "CANONICAL_TENANT_ID",
    "FRONTEND_AUTHORITY_TENANT_ID",
)
_OPERATOR_VARS = (
    "ALLOWED_OPERATOR_EMAIL",
    "FRONTEND_AUTHORITY_EMAIL",
)


class JudgeIsolationError(RuntimeError):
    """A judge deployment is configured to reach canonical state."""


def is_judge_deployment(env: Optional[Mapping[str, str]] = None) -> bool:
    """True when this process declares itself part of the judge environment."""
    env = os.environ if env is None else env
    return env.get("FULL_SHELF_JUDGE_ENVIRONMENT", "").strip() == "1"


def assert_judge_isolation(env: Optional[Mapping[str, str]] = None) -> None:
    """Fail closed if a judge deployment names any canonical resource.

    Called from each judge service's startup hook. On the canonical
    deployments it returns immediately, so canonical behavior is unchanged.
    """
    env = os.environ if env is None else env
    if not is_judge_deployment(env):
        return

    violations = []

    for var in _RESOURCE_VARS:
        value = (env.get(var) or "").strip()
        if not value:
            continue
        if CANONICAL_DATABASE in value:
            violations.append(f"{var} names the canonical database")
        for marker in CANONICAL_SERVICE_MARKERS:
            if marker in value:
                violations.append(f"{var} names a canonical service URL")

    for var in _TENANT_VARS:
        value = (env.get(var) or "").strip()
        if value and CANONICAL_TENANT in value:
            violations.append(f"{var} names the canonical tenant")

    for var in _OPERATOR_VARS:
        value = (env.get(var) or "").strip().lower()
        if value and value == CANONICAL_OPERATOR_EMAIL:
            violations.append(f"{var} names the canonical operator")

    # The canonical operator's Google subject must not be an allowed operator
    # here. The judge environment's operator is the Identity Platform account.
    if (env.get("ALLOWED_OPERATOR_SUBJECT") or "").strip() == CANONICAL_OPERATOR_SUBJECT:
        violations.append("ALLOWED_OPERATOR_SUBJECT names the canonical operator")

    # A judge deployment must positively name the judge database rather than
    # merely avoid naming the canonical one, so an unset value cannot fall
    # through to a default that points somewhere else.
    database = (env.get("SPANNER_DATABASE_ID") or "").strip()
    if database != JUDGE_DATABASE:
        violations.append(
            f"SPANNER_DATABASE_ID must be {JUDGE_DATABASE!r}, got {database!r}"
        )

    if violations:
        raise JudgeIsolationError(
            "Judge deployment is not isolated from canonical state: "
            + "; ".join(sorted(set(violations)))
        )
