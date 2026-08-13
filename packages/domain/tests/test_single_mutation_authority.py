import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MUTATION_METHODS = {
    "run_in_transaction",
    "execute_update",
    "insert",
    "insert_or_update",
    "update",
    "delete",
}


def test_only_ledger_executor_implements_authoritative_mutations():
    roots = [
        REPOSITORY_ROOT / "apps" / "orchestrator" / "src",
        REPOSITORY_ROOT / "apps" / "plan-ledger" / "src",
        REPOSITORY_ROOT / "packages" / "domain" / "full_shelf_domain",
    ]
    violations = []
    for root in roots:
        for path in root.rglob("*.py"):
            if path.name == "ledger_executor.py":
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr in MUTATION_METHODS:
                    violations.append(
                        (str(path.relative_to(REPOSITORY_ROOT)), node.func.attr, node.lineno)
                    )
    assert violations == []
