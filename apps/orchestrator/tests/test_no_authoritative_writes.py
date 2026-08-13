import ast
from pathlib import Path


ORCHESTRATOR_MAIN = Path(__file__).resolve().parents[1] / "src" / "main.py"


def test_orchestrator_contains_no_spanner_mutation_calls():
    tree = ast.parse(ORCHESTRATOR_MAIN.read_text())
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
