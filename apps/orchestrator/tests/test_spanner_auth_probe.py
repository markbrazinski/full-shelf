import importlib.util
import os

from google.api_core.exceptions import PermissionDenied


orchestrator_main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "main.py"))
spec = importlib.util.spec_from_file_location("orchestrator_auth_probe_main", orchestrator_main_path)
orchestrator_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orchestrator_main)


class FakeDatabase:
    def __init__(self, error=None):
        self.error = error

    def run_in_transaction(self, callback):
        if self.error:
            raise self.error
        return None


def test_permission_denied_is_the_only_accepted_write_denial(monkeypatch):
    monkeypatch.setattr(
        orchestrator_main,
        "get_spanner_database",
        lambda: FakeDatabase(PermissionDenied("spanner.databases.write denied")),
    )
    result = orchestrator_main.spanner_auth_proof()
    assert result["status"] == "NEGATIVE_AUTHORIZATION_PROVED"
    assert result["error_code"] == "PERMISSION_DENIED"


def test_non_iam_error_is_inconclusive(monkeypatch):
    monkeypatch.setattr(
        orchestrator_main,
        "get_spanner_database",
        lambda: FakeDatabase(ValueError("invalid schema")),
    )
    result = orchestrator_main.spanner_auth_proof()
    assert result == {
        "status": "AUTHORIZATION_PROOF_INCONCLUSIVE",
        "result": "NON_IAM_ERROR",
        "error_type": "ValueError",
    }


def test_authorized_dml_fails_the_boundary_even_when_zero_rows_match(monkeypatch):
    monkeypatch.setattr(
        orchestrator_main,
        "get_spanner_database",
        lambda: FakeDatabase(),
    )
    result = orchestrator_main.spanner_auth_proof()
    assert result["status"] == "AUTHORIZATION_PROOF_FAILED"
    assert result["result"] == "DML_WAS_AUTHORIZED"
