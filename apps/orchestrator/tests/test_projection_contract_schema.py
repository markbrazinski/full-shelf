"""The published UI projection contract must describe the implemented handler.

These tests validate REAL handler output against the authoritative schema in
packages/contracts/schemas/ui_projection.json, rather than comparing fixtures
to the handler. A fixture can drift with the code and still agree with it; only
the published schema is what a frontend is entitled to rely on.

next_day_draft is genuinely optional, so its presence is asserted by the
documented request condition rather than by an exact top-level key set.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from test_bounded_projection import DAY, T, project


SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages" / "contracts" / "schemas" / "ui_projection.json"
)
SCHEMA = json.loads(SCHEMA_PATH.read_text())

OPENAPI_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages" / "contracts" / "openapi" / "orchestrator.yaml"
)

REQUIRED_BLOCKS = {
    "current_day",
    "agent_activity_as_of",
    "execution_evidence_as_of",
    "carry_forward_obligations",
    "projection_boundary",
}

DOCUMENTED_400S = {
    "INVALID_AS_OF",
    "AS_OF_OUTSIDE_AUTHORITY_OPERATING_DAY",
    "EXPLICIT_AS_OF_REQUIRED_FOR_NON_CURRENT_OPERATING_DAY",
}


def validate(body):
    jsonschema.Draft202012Validator(SCHEMA).validate(body)
    return body


def test_published_schema_is_itself_valid():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_schema_requires_every_implemented_top_level_block():
    assert REQUIRED_BLOCKS <= set(SCHEMA["required"])
    # next_day_draft is optional and must never be required.
    assert "next_day_draft" not in SCHEMA["required"]
    assert "next_day_draft" in SCHEMA["properties"]


# --- real handler output validates against the published schema -------------


@pytest.mark.parametrize("hh,mm", [
    (8, 5), (8, 24), (9, 36), (10, 5), (10, 13), (16, 30), (23, 59),
])
def test_explicit_as_of_response_validates_against_published_schema(hh, mm):
    response = project(T(hh, mm))
    assert response.status_code == 200
    body = validate(response.json())
    assert REQUIRED_BLOCKS <= set(body)


def test_default_response_validates_against_published_schema(monkeypatch):
    """No as_of on the current operating day uses trusted server time."""
    import main as orchestrator_main

    real_datetime = orchestrator_main.datetime

    class FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 8, 14, 23, 59, tzinfo=timezone.utc)

    monkeypatch.setattr(orchestrator_main, "datetime", FrozenDatetime)
    response = project(None)
    assert response.status_code == 200
    body = validate(response.json())
    assert body["projection_boundary"]["mode"] == "LIVE_SERVER_TIME"
    assert REQUIRED_BLOCKS <= set(body)


def test_tomorrow_included_only_when_explicitly_requested_and_still_validates():
    included = validate(project(T(23, 59), include_next_day=True).json())
    assert included["next_day_draft"]["revision"] == "rev01"
    assert included["next_day_draft"]["approval_required"] is True


def test_tomorrow_absent_by_default_and_response_is_still_schema_valid():
    body = validate(project(T(23, 59)).json())
    assert "next_day_draft" not in body


def test_explicit_as_of_is_reported_as_the_boundary_mode():
    body = validate(project(T(10, 13)).json())
    assert body["projection_boundary"]["mode"] == "EXPLICIT_AS_OF"
    assert body["projection_boundary"]["as_of"].startswith("2026-08-14T10:13")


# --- every documented 400 is real ------------------------------------------


def test_invalid_as_of_returns_the_documented_400():
    response = project("not-a-timestamp")
    assert response.status_code == 400
    assert response.json()["detail"] == "INVALID_AS_OF"


def test_as_of_outside_operating_day_returns_the_documented_400():
    response = project(datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc))
    assert response.status_code == 400
    assert response.json()["detail"] == "AS_OF_OUTSIDE_AUTHORITY_OPERATING_DAY"


def test_missing_as_of_on_a_non_current_day_returns_the_documented_400(monkeypatch):
    import main as orchestrator_main

    real_datetime = orchestrator_main.datetime

    class LaterDay(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(orchestrator_main, "datetime", LaterDay)
    response = project(None)
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "EXPLICIT_AS_OF_REQUIRED_FOR_NON_CURRENT_OPERATING_DAY"
    )


# --- the published OpenAPI agrees with the handler --------------------------


def test_openapi_documents_the_parameters_and_every_implemented_400():
    import yaml

    document = yaml.safe_load(OPENAPI_PATH.read_text())
    operation = document["paths"]["/api/v1/projections/demo-beats"]["get"]
    assert {p["name"] for p in operation["parameters"]} == {
        "as_of", "include_next_day_draft"
    }
    draft = next(p for p in operation["parameters"]
                 if p["name"] == "include_next_day_draft")
    assert draft["schema"]["default"] is False
    # Default behavior and the historical-day boundary rule are documented.
    description = operation["description"]
    assert "LIVE_SERVER_TIME" in description
    assert "EXPLICIT_AS_OF_REQUIRED_FOR_NON_CURRENT_OPERATING_DAY" in description
    documented = set(
        operation["responses"]["400"]["content"]["application/json"]
        ["schema"]["properties"]["detail"]["enum"]
    )
    assert documented == DOCUMENTED_400S
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]


def test_openapi_response_schema_points_at_the_authoritative_projection_schema():
    import yaml

    document = yaml.safe_load(OPENAPI_PATH.read_text())
    ref = (document["paths"]["/api/v1/projections/demo-beats"]["get"]
           ["responses"]["200"]["content"]["application/json"]["schema"]["$ref"])
    target = document["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    assert target["$ref"].endswith("ui_projection.json")
