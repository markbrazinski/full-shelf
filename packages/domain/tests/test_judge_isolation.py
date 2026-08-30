"""CR-002: a judge deployment must fail closed rather than reach canonical.

Each canonical resource gets its own rejection test. The guard runs at startup,
so a failure here means the container never becomes healthy and Cloud Run never
routes traffic to it — the misconfiguration cannot do harm.
"""

import pytest

from full_shelf_domain.judge_isolation import (
    JudgeIsolationError,
    assert_judge_isolation,
    is_judge_deployment,
)

JUDGE_LEDGER = "https://full-shelf-judge-ledger-620464070103.us-central1.run.app"
JUDGE_ORCH = "https://full-shelf-judge-orchestrator-620464070103.us-central1.run.app"


def good(**overrides):
    env = {
        "FULL_SHELF_JUDGE_ENVIRONMENT": "1",
        "SPANNER_DATABASE_ID": "full-shelf-judge",
        "CANONICAL_TENANT_ID": "judge-demo",
        "FRONTEND_AUTHORITY_TENANT_ID": "judge-demo",
        "PLAN_LEDGER_URL": JUDGE_LEDGER,
        "PLAN_LEDGER_AUDIENCE": JUDGE_LEDGER,
        "ORCHESTRATOR_URL": JUDGE_ORCH,
        "ALLOWED_OPERATOR_SUBJECT": "MhC4YEY4suYgXHZgsY4UgMvJ1Az1",
    }
    env.update(overrides)
    return env


def test_a_correctly_isolated_judge_deployment_starts():
    assert_judge_isolation(good())


def test_canonical_deployments_are_untouched_by_the_guard():
    """Without the judge flag the guard does nothing, whatever is configured."""
    assert_judge_isolation({
        "SPANNER_DATABASE_ID": "full-shelf-main",
        "CANONICAL_TENANT_ID": "east-bay-food-bank",
        "ALLOWED_OPERATOR_EMAIL": "markbrazinski@gmail.com",
    })
    assert is_judge_deployment({}) is False


def test_the_canonical_database_is_refused():
    with pytest.raises(JudgeIsolationError, match="canonical database"):
        assert_judge_isolation(good(SPANNER_DATABASE_ID="full-shelf-main"))


def test_an_unset_database_is_refused():
    """A judge deployment must NAME the judge database, not merely avoid main."""
    with pytest.raises(JudgeIsolationError, match="SPANNER_DATABASE_ID"):
        assert_judge_isolation(good(SPANNER_DATABASE_ID=""))


def test_a_graph_database_pointing_at_canonical_is_refused():
    with pytest.raises(JudgeIsolationError, match="canonical database"):
        assert_judge_isolation(good(GRAPH_AUDIT_DATABASE_ID="full-shelf-main"))


def test_the_canonical_tenant_is_refused():
    with pytest.raises(JudgeIsolationError, match="canonical tenant"):
        assert_judge_isolation(good(CANONICAL_TENANT_ID="east-bay-food-bank"))
    with pytest.raises(JudgeIsolationError, match="canonical tenant"):
        assert_judge_isolation(good(FRONTEND_AUTHORITY_TENANT_ID="east-bay-food-bank"))


def test_a_canonical_service_url_is_refused():
    canonical_ledger = "https://full-shelf-plan-ledger-620464070103.us-central1.run.app"
    canonical_orch = "https://full-shelf-orchestrator-620464070103.us-central1.run.app"
    with pytest.raises(JudgeIsolationError, match="canonical service URL"):
        assert_judge_isolation(good(PLAN_LEDGER_URL=canonical_ledger))
    with pytest.raises(JudgeIsolationError, match="canonical service URL"):
        assert_judge_isolation(good(ORCHESTRATOR_URL=canonical_orch))
    with pytest.raises(JudgeIsolationError, match="canonical service URL"):
        assert_judge_isolation(good(PLAN_LEDGER_AUDIENCE=canonical_ledger))


def test_the_canonical_operator_is_refused():
    with pytest.raises(JudgeIsolationError, match="canonical operator"):
        assert_judge_isolation(good(ALLOWED_OPERATOR_EMAIL="markbrazinski@gmail.com"))
    with pytest.raises(JudgeIsolationError, match="canonical operator"):
        assert_judge_isolation(good(ALLOWED_OPERATOR_SUBJECT="108080450585792522893"))


def test_every_violation_is_reported_at_once():
    """One startup failure should name everything wrong, not just the first."""
    with pytest.raises(JudgeIsolationError) as exc:
        assert_judge_isolation(good(
            SPANNER_DATABASE_ID="full-shelf-main",
            CANONICAL_TENANT_ID="east-bay-food-bank",
        ))
    message = str(exc.value)
    assert "canonical database" in message
    assert "canonical tenant" in message
