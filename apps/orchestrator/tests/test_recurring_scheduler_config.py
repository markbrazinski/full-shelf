import importlib.util
from pathlib import Path

from full_shelf_domain.ledger_commands import RecurringDailyRequest


ROOT = Path(__file__).resolve().parents[3]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


configure = _load(
    "configure_operating_day_scheduler",
    ROOT / "scripts" / "configure_operating_day_scheduler.py",
)
inventory = _load(
    "configure_micro1a_recurring_jobs",
    ROOT / "scripts" / "configure_micro1a_recurring_jobs.py",
)


def test_scheduler_body_is_date_free_strict_recurring_contract():
    body = configure.build_recurring_request(
        fixture="canonical", tenant_id="audit-canonical-builder-m1a"
    )
    request = RecurringDailyRequest.model_validate(body)
    assert request.tenant_id == "audit-canonical-builder-m1a"
    assert "operating_day" not in body
    assert "qualification_profile" not in body
    assert "timestamp" not in body


def test_inventory_has_distinct_builder_and_two_untouched_auditor_jobs():
    builder = [job for job in inventory.JOBS if job["role"] == "BUILDER_QUALIFICATION"]
    auditors = [
        job for job in inventory.JOBS
        if job["role"] == "AUDITOR_RESERVED_DO_NOT_TRIGGER"
    ]
    assert len(builder) == 1
    assert len(auditors) == 2
    assert len({job["tenant"] for job in [*builder, *auditors]}) == 3
    assert all(job["job"].endswith("-daily") for job in auditors)
