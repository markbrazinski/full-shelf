import importlib.util
import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException


main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "main.py"))
spec = importlib.util.spec_from_file_location("orchestrator_authority_main", main_path)
main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main)


def test_audit_tenant_uses_configured_isolated_database():
    with patch.dict(
        os.environ,
        {
            "SPANNER_DATABASE_ID": "full-shelf-main",
            "AUDIT_SPANNER_DATABASE_ID": "full-shelf-audit",
            "AUDIT_TENANT_IDS": "audit-canonical,audit-altered",
        },
    ):
        scope = main._resolve_authority_scope("audit-altered")

    assert scope.database_id == "full-shelf-audit"
    assert scope.kind == "AUDIT_ISOLATED"


def test_request_cannot_select_an_unconfigured_tenant_or_database():
    with patch.dict(
        os.environ,
        {
            "SPANNER_DATABASE_ID": "full-shelf-main",
            "AUDIT_SPANNER_DATABASE_ID": "full-shelf-audit",
            "AUDIT_TENANT_IDS": "audit-canonical",
        },
    ):
        with pytest.raises(HTTPException) as error:
            main._resolve_authority_scope("full-shelf-main")

    assert error.value.status_code == 403
    assert error.value.detail == "TENANT_SCOPE_NOT_AUTHORIZED"
