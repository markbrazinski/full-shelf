"""CR-001 boundary regressions for the judge gateway.

Amendment CR-001 permits a third service only within a closed scope. These
tests assert the prohibitions structurally, so a future edit that quietly
turns the gateway into a second source of truth fails here rather than in
production.
"""

import ast
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "main.py"
DOCKERFILE = pathlib.Path(__file__).resolve().parents[1] / "Dockerfile"
TEXT = SRC.read_text()
TREE = ast.parse(TEXT)


def _imported_modules():
    """Every module actually imported, ignoring prose in comments/docstrings."""
    names = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_no_agent_logic_is_importable():
    """CR-001: the gateway may not contain agent logic."""
    for module in _imported_modules():
        assert not module.startswith("google.adk"), module
        assert not module.startswith("google.genai"), module
        assert "vertexai" not in module, module


def test_no_direct_spanner_client():
    """CR-001: the gateway may not mutate Spanner directly."""
    for module in _imported_modules():
        assert "spanner" not in module.lower(), module


def test_no_plan_ledger_address_in_code():
    """CR-001: the gateway may not call the plan ledger directly.

    The cleanest enforcement is having no address for it, so the name may
    appear only in a comment explaining the absence — never in code that
    could read it from the environment.
    """
    code_lines = [
        line for line in TEXT.splitlines()
        if "PLAN_LEDGER" in line and not line.lstrip().startswith("#")
    ]
    assert code_lines == [], code_lines


def test_ledger_url_is_not_supplied_to_the_image():
    """The deployment must not hand the gateway a ledger address either."""
    assert "PLAN_LEDGER" not in DOCKERFILE.read_text()


def test_every_protected_route_verifies_a_token():
    """No protected route may trust a header instead of verifying a token.

    `_session_or_401` is the single gate; the readiness probe and the static
    frontend are the only surfaces deliberately outside it.
    """
    assert "_session_or_401" in TEXT
    # The verifier must be Google's own, never a hand-rolled comparison.
    assert "verify_firebase_token" in TEXT
    assert re.search(r"def verify_judge", TEXT)


def test_no_homemade_password_comparison():
    """Passwords are Identity Platform's business; this gateway never sees one.

    Checked against the parsed source rather than the raw text, so the prose
    explaining WHY there is no password handling cannot trip the guard. What
    matters is that no string literal or comparison in real code touches a
    password value.
    """
    for node in ast.walk(TREE):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Docstrings are prose; they are allowed to discuss passwords.
            continue
        if isinstance(node, ast.Name):
            assert "password" not in node.id.lower(), node.id
        if isinstance(node, ast.Attribute):
            assert "password" not in node.attr.lower(), node.attr


def test_login_event_carries_no_credential_material():
    """The structured login event must never carry a secret.

    It records who and which session, not what was presented.
    """
    # The EMIT call, not the docstring that first mentions the event name.
    start = TEXT.index('emit("NOTICE", "judge_login_success"')
    block = TEXT[start:start + 500]
    for banned in ("token", "password", "authorization", "credential"):
        assert banned not in block.lower().split("# deliberately")[0], banned
    for required in ("demo_session_id", "deployed_revision", "auth_provider"):
        assert required in block, required
