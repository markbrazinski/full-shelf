"""apps/web must not reference an application entry point that does not exist.

The React client is being built separately. Until it lands, this package holds
only the environment contract and its dependency declaration, and nothing here
may point at a file that was deleted or promise a build that cannot run.
"""

import json
from pathlib import Path

import pytest


WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx"}


def _entry_points():
    src = WEB / "src"
    return [p for p in src.rglob("*")
            if p.suffix in SOURCE_SUFFIXES and p.stem in {"main", "index", "App"}]


def test_no_dangling_html_entry_point_remains():
    """index.html referenced a deleted main.tsx, so it must not exist."""
    assert not (WEB / "index.html").exists()


def test_no_html_file_references_a_missing_module():
    for html in WEB.glob("*.html"):
        text = html.read_text()
        for marker in ('src="/src/', "src='/src/"):
            assert marker not in text, f"{html.name} references a src module"


def test_package_declares_no_build_it_cannot_run():
    package = json.loads((WEB / "package.json").read_text())
    if _entry_points():
        pytest.skip("an application entry point now exists")
    assert "scripts" not in package or not package["scripts"], (
        "apps/web declares build scripts but has no application entry point"
    )


def test_the_prohibited_browser_to_ledger_client_is_not_restored():
    for path in WEB.rglob("*"):
        if path.suffix not in SOURCE_SUFFIXES or "node_modules" in path.parts:
            continue
        text = path.read_text()
        for banned in ("PLAN_LEDGER_URL", "plan-ledger", "LEDGER_URL",
                       "VITE_PLAN_LEDGER"):
            assert banned not in text, (path.name, banned)


def test_environment_contract_still_points_only_at_the_orchestrator():
    env = (WEB / "src" / "env.ts").read_text()
    assert "ORCHESTRATOR_URL" in env
    assert "127.0.0.1:8787" in env  # loopback replay harness only
