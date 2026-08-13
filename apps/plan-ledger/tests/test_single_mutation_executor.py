import ast
from pathlib import Path


LEDGER_MAIN = Path(__file__).resolve().parents[1] / "src" / "main.py"


def test_plan_ledger_entrypoint_has_no_parallel_spanner_mutation_implementation():
    tree = ast.parse(LEDGER_MAIN.read_text())
    prohibited = {
        "run_in_transaction",
        "execute_update",
        "insert",
        "insert_or_update",
        "update",
        "delete",
    }
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr in prohibited:
            violations.append((node.func.attr, node.lineno))
    assert violations == []
