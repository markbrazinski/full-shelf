import os


def test_full_suite_is_forced_onto_named_audit_database():
    database_id = os.environ["SPANNER_DATABASE_ID"]
    assert database_id != "full-shelf-main"
    assert "audit" in database_id
    assert os.environ["GRAPH_AUDIT_DATABASE_ID"] == database_id
    assert os.environ["FULL_SHELF_TEST_MODE"] == "1"
