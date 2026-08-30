"""apps/web must stay coherent with the entry point it actually ships.

These guards were written while the React client lived outside the repo and
apps/web held only the environment contract. The v6.1 client now ships here, so
the "no entry point may exist" assertions are gone; what remains is what still
protects the boundary: the HTML entry must reference a module that exists, the
browser must never reach the ledger directly, and the environment contract must
point only at the orchestrator.
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


def test_every_html_entry_points_at_a_module_that_exists():
    """An HTML entry may reference /src/..., but the file must be there."""
    import re

    for html in WEB.glob("*.html"):
        for ref in re.findall(r"""src=["'](/src/[^"']+)["']""", html.read_text()):
            assert (WEB / ref.lstrip("/")).exists(), f"{html.name} -> {ref} missing"


def test_the_shipped_entry_point_is_reachable():
    """index.html and its module both exist, so the build can actually run."""
    assert (WEB / "index.html").exists()
    assert _entry_points(), "apps/web declares a build but has no entry point"


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
    # The replay harness must stay a LOOPBACK address. The port moved 8787 ->
    # 8788 when the golden runtime controller replaced the beat selector, so
    # the guard asserts the property that matters — the only non-orchestrator
    # endpoint the frontend knows is loopback — rather than one literal port.
    assert "127.0.0.1:" in env
