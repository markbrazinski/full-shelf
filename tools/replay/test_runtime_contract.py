"""Acceptance tests for the deterministic Golden Runtime Controller.

Proves the section 5 event graph, session sequencing, the single human gate,
approval binding, cursor-gated projection filtering, isolated proof branches,
session-scoped SSE with resume, reset, and isolation between sessions.

Nothing here calls Gemini, ADK, Model Armor, KMS, or Spanner.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import events  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
INDEX = json.loads((FIXTURES / "index.json").read_text())


# --- events -----------------------------------------------------------------


def test_events_cover_the_full_canonical_set():
    assert len(events.CANONICAL_EVENTS) == 25


def test_events_are_gap_free_and_monotonic_in_sequence():
    sequences = [event.sequence for event in events.CANONICAL_EVENTS]
    assert sequences == list(range(1, 26))


def test_events_never_move_backwards_in_scenario_time():
    stamps = [event.effective_at for event in events.CANONICAL_EVENTS]
    assert stamps == sorted(stamps)


def test_events_use_pacific_scenario_time_not_utc():
    """2026-08-14 in America/Los_Angeles is -07:00."""
    for event in events.CANONICAL_EVENTS:
        offset = event.effective_at.utcoffset().total_seconds()
        assert offset == -7 * 3600, event.event_id
    assert events.T(8, 5).isoformat() == "2026-08-14T08:05:00-07:00"


@pytest.mark.parametrize("sequence,hh,mm", [
    (5, 8, 5), (6, 8, 20), (8, 8, 21), (9, 8, 24), (10, 8, 24),
    (11, 9, 36), (18, 10, 10), (20, 10, 10), (22, 10, 13), (24, 17, 0),
])
def test_commission_timeline_lands_on_the_named_minutes(sequence, hh, mm):
    event = events.BY_SEQUENCE[sequence]
    assert (event.effective_at.hour, event.effective_at.minute) == (hh, mm)


def test_exactly_one_interactive_human_gate_exists_in_the_replayed_window():
    """Event 3 is preloaded history; event 9 is the only reachable gate."""
    gates = [event.sequence for event in events.CANONICAL_EVENTS
             if event.trigger_class == "HUMAN_GATE"]
    assert gates == [3, 9]
    reachable = [s for s in gates if s >= events.INITIAL_CURSOR]
    assert reachable == [events.HUMAN_GATE_SEQUENCE]


def test_every_fixture_backed_event_names_a_committed_fixture():
    available = {entry["beat"] for entry in INDEX["beats"]}
    available |= {entry["beat"] for entry in INDEX["proofs"]}
    for event in events.CANONICAL_EVENTS:
        if event.fixture_key is not None:
            assert event.fixture_key in available, event.event_id
    for branch in events.BRANCHES.values():
        assert branch["fixture_key"] in available


def test_event_ids_are_unique_and_contract_prefixed():
    ids = [event.event_id for event in events.CANONICAL_EVENTS]
    assert len(set(ids)) == len(ids)
    for event in events.CANONICAL_EVENTS:
        assert event.event_id.startswith(f"FS-E{event.sequence:03d}-")


def test_branches_carry_the_contract_quantities():
    vague = events.BRANCHES["vague"]
    assert vague["custody"] == {"unique": 96, "confirmed": 88, "unconfirmed": 8}
    assert (vague["domain_mutations"], vague["evidence_mutations"]) == (0, 1)
    complete = events.BRANCHES["complete"]
    assert complete["custody"] == {"unique": 96, "confirmed": 96, "unconfirmed": 0}
    assert (complete["domain_mutations"], complete["evidence_mutations"]) == (2, 1)


def test_branch_ordinals_cannot_collide_with_canonical_sequences():
    for branch in events.BRANCHES.values():
        for event in branch["events"]:
            assert isinstance(event.ordinal, str)
            assert event.ordinal.startswith("b")


def test_envelope_matches_the_contract_shape():
    event = events.BY_SEQUENCE[9]
    frame = events.envelope(event, session_id="fs-replay-test",
                            recorded_at="2026-08-14T08:24:00-07:00")
    assert set(frame) == {
        "schema_version", "event_id", "event_type", "scenario_id", "session_id",
        "sequence", "effective_at", "recorded_at", "trigger_class", "authority",
        "actor", "correlation", "source_refs", "payload", "validation",
        "receipt_refs", "projection_delta", "activity_entry",
        "evidence_classification",
    }
    assert frame["schema_version"] == "full-shelf.demo-event.v2"
    assert frame["evidence_classification"] == "SYNTHETIC_TEST"
    assert frame["trigger_class"] == "HUMAN_GATE"
    assert frame["authority"] == "CANONICAL"
    assert set(frame["correlation"]) == {
        "tenant_id", "operating_day", "plan_id", "incident_id",
        "source_event_id", "agent_run_id"}


def test_no_event_claims_live_or_measured_evidence():
    for event in events.CANONICAL_EVENTS:
        frame = events.envelope(event, session_id="s", recorded_at="t")
        blob = json.dumps(frame)
        assert "OBSERVED_LIVE" not in blob
        assert "RECORDED_LIVE" not in blob
        assert '"MEASURED"' not in blob


def test_no_agent_running_or_waiting_state_is_invented():
    """Contract section 9 forbids invented RUNNING, WAITING, or duration."""
    blob = json.dumps([events.envelope(e, session_id="s", recorded_at="t")
                       for e in events.CANONICAL_EVENTS])
    for banned in ('"RUNNING"', '"WAITING"', '"duration"', '"started_at"'):
        assert banned not in blob


# --- session creation and cursor -------------------------------------------

import session as runtime  # noqa: E402


def new_session():
    return runtime.ReplaySession()


def test_session_creation_starts_at_event_five():
    s = new_session()
    assert s.cursor == events.INITIAL_CURSOR == 5
    assert s.state()["operating_timestamp"] == "2026-08-14T08:05:00-07:00"


def test_session_creation_preloads_history_and_current_event():
    s = new_session()
    assert [f["sequence"] for f in s.history()] == [1, 2, 3, 4]
    assert [f["sequence"] for f in s.feed()] == [1, 2, 3, 4, 5]


def test_session_ids_are_unique_and_opaque():
    ids = {new_session().session_id for _ in range(100)}
    assert len(ids) == 100
    assert all(i.startswith("fs-replay-") for i in ids)


def test_feed_ordinals_are_gap_free():
    s = new_session()
    s.start()
    for _ in range(3):
        s.autoplay_step()
    sequences = [f["sequence"] for f in s.feed()]
    assert sequences == list(range(1, max(sequences) + 1))


def test_feed_never_contains_a_future_event():
    s = new_session()
    s.start()
    s.autoplay_step()
    for frame in s.feed():
        assert frame["sequence"] <= s.cursor


# --- autoplay and the human gate -------------------------------------------


def test_autoplay_begins_at_event_six_and_never_repeats_event_five():
    s = new_session()
    s.start()
    frame = s.autoplay_step()
    assert frame["sequence"] == 6
    assert [f["sequence"] for f in s.feed()].count(5) == 1


def test_autoplay_stops_after_event_eight_before_the_gate():
    s = new_session()
    s.start()
    while s.autoplay_step() is not None:
        pass
    assert s.cursor == 8
    assert s.mode == runtime.PAUSED_HUMAN_GATE


def test_event_nine_and_ten_are_absent_before_approval():
    s = new_session()
    s.start()
    while s.autoplay_step() is not None:
        pass
    sequences = [f["sequence"] for f in s.feed()]
    assert 9 not in sequences and 10 not in sequences


def test_advance_refuses_to_cross_the_gate():
    s = new_session()
    s.start()
    while s.autoplay_step() is not None:
        pass
    with pytest.raises(runtime.ReplayError) as exc:
        s.advance()
    assert exc.value.code == "HUMAN_APPROVAL_REQUIRED"
    assert s.cursor == 8


def test_complete_autoplay_order_after_approval():
    s = drive_to_end()
    sequences = [f["sequence"] for f in s.feed()]
    assert sequences == list(range(1, 26))
    assert s.mode == runtime.COMPLETE


def drive_to_end():
    s = new_session()
    s.start()
    while s.autoplay_step() is not None:
        pass
    s.approve(valid_approval())
    s.mode = runtime.PLAYING
    while s.autoplay_step() is not None:
        pass
    return s


def valid_approval(**overrides):
    body = {
        "plan_id": "PLAN-2026-08-14",
        "incident_id": "INC-2210",
        "expected_revision": "rev07",
        "target_revision": "rev08",
        "actions": [
            {"order_id": "O202", "cases": 22, "disposition": "TRUCK_2"},
            {"order_id": "O203", "cases": 20, "disposition": "PARTNER_PICKUP"},
        ],
        "plan_diff_hash": runtime.CANONICAL_PLAN_DIFF_HASH,
        "idempotency_key": "fixture-key-001",
    }
    body.update(overrides)
    return body


def at_gate():
    s = new_session()
    s.start()
    while s.autoplay_step() is not None:
        pass
    return s


# --- approval ---------------------------------------------------------------


def test_exact_approval_commits_rev08_exactly_once():
    s = at_gate()
    result = s.approve(valid_approval())
    assert result["duplicate"] is False
    # Approval commits event 9 only. Activation is a separate later commit.
    assert [f["sequence"] for f in result["events"]] == [9]
    assert s.cursor == 9
    assert 10 not in [f["sequence"] for f in s.feed()]
    s.advance()
    sequences = [f["sequence"] for f in s.feed()]
    assert sequences.count(9) == 1 and sequences.count(10) == 1
    assert s.cursor == 10


def test_approval_wakes_autoplay_without_committing_activation_itself():
    s = at_gate()
    s.approve(valid_approval())
    assert s.cursor == events.HUMAN_GATE_SEQUENCE
    assert s.mode == runtime.PLAYING
    assert s.autoplay_step()["sequence"] == events.ACTIVATION_SEQUENCE


def test_identical_duplicate_approval_is_idempotent():
    s = at_gate()
    first = s.approve(valid_approval())
    before = s.feed()
    second = s.approve(valid_approval())
    assert second["duplicate"] is True
    assert second["receipt"]["receipt_id"] == first["receipt"]["receipt_id"]
    assert s.feed() == before


@pytest.mark.parametrize("field,value", [
    ("expected_revision", "rev06"),
    ("target_revision", "rev09"),
    ("plan_id", "PLAN-2026-08-15"),
    ("incident_id", "INC-9999"),
    ("actions", [{"order_id": "O202", "cases": 23, "disposition": "TRUCK_2"},
                 {"order_id": "O203", "cases": 20, "disposition": "PARTNER_PICKUP"}]),
    ("actions", [{"order_id": "O202", "cases": 22, "disposition": "TRUCK_2"}]),
    ("plan_diff_hash", "0" * 64),
])
def test_altered_approval_is_denied_with_zero_mutations(field, value):
    s = at_gate()
    before_feed, before_cursor = s.feed(), s.cursor
    with pytest.raises(runtime.ReplayError) as exc:
        s.approve(valid_approval(**{field: value}))
    assert exc.value.code == "APPROVAL_BINDING_MISMATCH"
    assert s.cursor == before_cursor
    assert s.feed() == before_feed
    assert s.approval is None


def test_approval_before_its_boundary_is_refused():
    s = new_session()
    with pytest.raises(runtime.ReplayError) as exc:
        s.approve(valid_approval())
    assert exc.value.code == "APPROVAL_NOT_PERMITTED_AT_CURSOR"
    assert s.cursor == 5


def test_event_ten_cannot_occur_before_event_nine():
    """Contract section 10.4."""
    s = at_gate()
    with pytest.raises(runtime.ReplayError):
        s.advance()
    assert 10 not in [f["sequence"] for f in s.feed()]
    s.approve(valid_approval())
    s.advance()
    sequences = [f["sequence"] for f in s.feed()]
    assert sequences.index(9) < sequences.index(10)


def test_approval_requires_an_idempotency_key():
    s = at_gate()
    body = valid_approval()
    del body["idempotency_key"]
    with pytest.raises(runtime.ReplayError) as exc:
        s.approve(body)
    assert exc.value.code == "IDEMPOTENCY_KEY_REQUIRED"


def test_approval_receipt_discloses_it_is_synthetic():
    s = at_gate()
    receipt = s.approve(valid_approval())["receipt"]
    assert receipt["synthetic"] is True
    assert receipt["classification"] == "SYNTHETIC_TEST"
    assert receipt["receipt_id"].startswith("fixture-")
    assert receipt["actor"]["id"] == "fixture-synthetic-operations-director"
    # The disclosure truthfully denies KMS; it must never claim it.
    assert "no real authentication" in receipt["disclosure"].lower()
    assert "kms" in receipt["disclosure"].lower()
    for key, value in receipt.items():
        if key != "disclosure" and isinstance(value, str):
            assert "kms" not in value.lower()


def test_approval_binds_the_complete_action_set_and_diff_hash():
    receipt = at_gate().approve(valid_approval())["receipt"]
    assert receipt["plan_id"] == "PLAN-2026-08-14"
    assert receipt["incident_id"] == "INC-2210"
    assert receipt["expected_revision"] == "rev07"
    assert receipt["target_revision"] == "rev08"
    assert receipt["actions"] == runtime.CANONICAL_BINDING["actions"]
    assert receipt["plan_diff_hash"] == runtime.CANONICAL_PLAN_DIFF_HASH


# --- projection filtering (no future leakage) -------------------------------


def projection_at(sequence):
    s = new_session()
    s.start()
    while s.cursor < sequence:
        if s.autoplay_step() is None:
            s.approve(valid_approval())
            s.mode = runtime.PLAYING
    return s.projection()


def test_no_rev08_before_event_ten():
    for sequence in (5, 6, 7, 8):
        blob = json.dumps(projection_at(sequence))
        assert "rev08" not in blob, sequence
    assert "rev08" in json.dumps(projection_at(10))


def test_no_recall_before_event_eleven():
    """LTC-4471 is on the rev07 morning manifest all along; the recall is not."""
    for sequence in (5, 8, 10):
        body = projection_at(sequence)
        blob = json.dumps(body)
        assert events.RECALL_INC not in blob, sequence
        assert body.get("recall_intake_as_of") is None, sequence
        assert "E. coli" not in blob, sequence
    assert events.RECALL_INC in json.dumps(projection_at(11))


def test_no_custody_totals_before_event_eighteen():
    for sequence in (5, 10, 15, 17):
        body = projection_at(sequence)
        evidence = body.get("execution_evidence_as_of") or {}
        assert "custody_graph" not in evidence, sequence
    assert "custody_graph" in (projection_at(18).get("execution_evidence_as_of") or {})


def test_no_recovery_result_before_event_twenty():
    for sequence in (5, 10, 18, 19):
        body = projection_at(sequence)
        assert not (body.get("current_day") or {}).get("recovery"), sequence
        assert body.get("carry_forward_obligations") == [], sequence


def test_no_partially_contained_before_event_twenty_two():
    for sequence in (5, 10, 18, 20, 21):
        assert "PARTIALLY_CONTAINED" not in json.dumps(projection_at(sequence)), sequence
    assert "PARTIALLY_CONTAINED" in json.dumps(projection_at(22))


def test_no_saturday_before_event_twenty_four():
    for sequence in (5, 10, 22, 23):
        assert "next_day_draft" not in projection_at(sequence), sequence
    assert "next_day_draft" in projection_at(24)


# --- isolated proof branches ------------------------------------------------


def at_terminal():
    s = new_session()
    s.start()
    while s.cursor < 22:
        if s.autoplay_step() is None:
            s.approve(valid_approval())
            s.mode = runtime.PLAYING
    return s


def test_branch_entry_is_denied_before_event_twenty_two():
    s = at_gate()
    for name in ("vague", "complete"):
        with pytest.raises(runtime.ReplayError) as exc:
            s.enter_branch(name)
        assert exc.value.code == "PROOF_BRANCH_NOT_AVAILABLE_YET"
    assert s.branch is None


def test_unknown_branch_is_rejected():
    with pytest.raises(runtime.ReplayError) as exc:
        at_terminal().enter_branch("fabricated")
    assert exc.value.code == "UNKNOWN_PROOF_BRANCH"


@pytest.mark.parametrize("name", ["vague", "complete"])
def test_branch_never_moves_the_canonical_cursor_or_feed(name):
    s = at_terminal()
    before_cursor, before_feed = s.cursor, s.feed()
    s.enter_branch(name)
    assert s.cursor == before_cursor
    assert s.feed() == before_feed
    s.exit_branch()
    assert s.cursor == before_cursor
    assert s.feed() == before_feed


def test_complete_branch_shows_96_96_while_canonical_stays_88_96():
    s = at_terminal()
    canonical = s.projection()
    canonical_graph = canonical["execution_evidence_as_of"]["custody_graph"]
    assert (canonical_graph["unique_current_cases"],
            canonical_graph["confirmed_cases"],
            canonical_graph["unconfirmed_cases"]) == (96, 88, 8)

    s.enter_branch("complete")
    branch_graph = s.projection()["execution_evidence_as_of"]["custody_graph"]
    assert (branch_graph["unique_current_cases"],
            branch_graph["confirmed_cases"],
            branch_graph["unconfirmed_cases"]) == (96, 96, 0)

    s.exit_branch()
    assert s.projection() == canonical


def test_vague_branch_denies_with_zero_domain_mutations():
    s = at_terminal()
    result = s.enter_branch("vague")
    assert result["domain_mutations"] == 0
    assert result["evidence_mutations"] == 1
    assert result["custody"] == {"unique": 96, "confirmed": 88, "unconfirmed": 8}
    assert result["events"][-1]["validation"]["status"] == "DENIED"


def test_canonical_return_remains_88_96_and_partially_contained():
    s = at_terminal()
    before = s.projection()
    for name in ("vague", "complete", "vague"):
        s.enter_branch(name)
        s.exit_branch()
    after = s.projection()
    assert after == before
    graph = after["execution_evidence_as_of"]["custody_graph"]
    assert (graph["confirmed_cases"], graph["unique_current_cases"]) == (88, 96)
    statuses = [i["status"] for i in after["current_day"]["incidents"]
                if i["incident_id"] == events.RECALL_INC]
    assert statuses == ["PARTIALLY_CONTAINED"]


def test_branch_events_are_isolated_and_cannot_collide_with_canonical_ids():
    s = at_terminal()
    s.enter_branch("complete")
    canonical_ids = {f["sequence"] for f in s.feed()}
    for frame in s.branch_feed():
        assert frame["authority"] == "ISOLATED"
        assert frame["sequence"] not in canonical_ids
        assert str(frame["sequence"]).startswith("b")
    assert all(f["authority"] == "CANONICAL" for f in s.feed())


def test_canonical_advance_is_blocked_while_a_branch_is_open():
    s = at_terminal()
    s.enter_branch("vague")
    with pytest.raises(runtime.ReplayError) as exc:
        s.advance()
    assert exc.value.code == "CANONICAL_ADVANCE_BLOCKED_IN_BRANCH"


def test_branch_does_not_alter_incident_barrier_or_shortfall():
    s = at_terminal()
    before = json.dumps(s.projection()["current_day"], sort_keys=True)
    s.enter_branch("complete")
    s.exit_branch()
    assert json.dumps(s.projection()["current_day"], sort_keys=True) == before


# --- reset and session isolation --------------------------------------------


def test_reset_returns_exactly_to_event_five():
    store = runtime.SessionStore()
    s = store.create()
    s.start()
    while s.autoplay_step() is not None:
        pass
    s.approve(valid_approval())
    s.mode = runtime.PLAYING
    fresh = store.reset(s.session_id)
    assert fresh.cursor == 5
    assert fresh.mode == runtime.IDLE
    assert fresh.approval is None
    assert fresh.branch is None
    assert [f["sequence"] for f in fresh.feed()] == [1, 2, 3, 4, 5]
    assert fresh.state()["operating_timestamp"] == "2026-08-14T08:05:00-07:00"


def test_reset_mints_a_new_opaque_session_id():
    store = runtime.SessionStore()
    s = store.create()
    fresh = store.reset(s.session_id)
    assert fresh.session_id != s.session_id
    with pytest.raises(runtime.ReplayError) as exc:
        store.get(s.session_id)
    assert exc.value.code == "UNKNOWN_SESSION"


def test_reset_is_deterministic_across_repetition():
    store = runtime.SessionStore()
    shapes = []
    for _ in range(3):
        s = store.create()
        shapes.append(json.dumps(s.projection(), sort_keys=True))
    assert len(set(shapes)) == 1


def test_two_sessions_advance_independently():
    store = runtime.SessionStore()
    a, b = store.create(), store.create()
    a.start()
    while a.autoplay_step() is not None:
        pass
    a.approve(valid_approval())
    a.advance()
    assert a.cursor == 10
    assert b.cursor == 5
    assert b.approval is None
    assert [f["sequence"] for f in b.feed()] == [1, 2, 3, 4, 5]


def test_reset_cannot_mutate_another_session():
    store = runtime.SessionStore()
    a, b = store.create(), store.create()
    b.start()
    b.autoplay_step()
    before = b.feed()
    store.reset(a.session_id)
    assert b.feed() == before
    assert b.cursor == 6


def test_a_branch_in_one_session_does_not_touch_another():
    store = runtime.SessionStore()
    a, b = store.create(), store.create()
    for s in (a, b):
        s.start()
        while s.cursor < 22:
            if s.autoplay_step() is None:
                s.approve(valid_approval())
                s.mode = runtime.PLAYING
    before = b.projection()
    a.enter_branch("complete")
    assert b.branch is None
    assert b.projection() == before


# --- SSE --------------------------------------------------------------------


def collect(gen):
    return list(gen)


def parse_blocks(blocks):
    parsed = []
    for block in blocks:
        lines = block.strip().split("\n")
        ident = lines[0].split(": ", 1)[1]
        data = json.loads(lines[2].split(": ", 1)[1])
        parsed.append((ident, data))
    return parsed


def test_sse_emits_gap_free_ordinals():
    s = at_gate()
    parsed = parse_blocks(collect(runtime.stream(s, max_frames=8)))
    assert [int(i) for i, _ in parsed] == list(range(1, 9))
    assert [d["sequence"] for _, d in parsed] == list(range(1, 9))


def test_sse_resume_returns_strictly_later_events_in_order():
    s = at_gate()
    parsed = parse_blocks(collect(runtime.stream(s, last_event_id="5", max_frames=3)))
    assert [int(i) for i, _ in parsed] == [6, 7, 8]


def test_sse_resume_from_the_end_yields_nothing_then_waits():
    s = at_gate()
    assert collect(runtime.stream(s, last_event_id="8", idle_timeout=0.05)) == []


def test_sse_rejects_a_malformed_last_event_id():
    s = at_gate()
    for bad in ("abc", "-1", "999", "b1"):
        with pytest.raises(runtime.ReplayError) as exc:
            collect(runtime.stream(s, last_event_id=bad))
        assert exc.value.code == "INVALID_LAST_EVENT_ID"


def test_sse_stays_open_and_delivers_a_later_commit():
    import threading as _t
    s = at_gate()
    seen = []

    def reader():
        seen.extend(parse_blocks(collect(
            runtime.stream(s, last_event_id="8", max_frames=2))))

    t = _t.Thread(target=reader, daemon=True)
    t.start()
    s.approve(valid_approval())
    s.mode = runtime.PLAYING
    s.autoplay_step()
    t.join(timeout=5)
    assert [int(i) for i, _ in seen] == [9, 10]


def test_sse_never_leaks_a_future_event():
    s = at_gate()
    parsed = parse_blocks(collect(runtime.stream(s, max_frames=8)))
    assert max(d["sequence"] for _, d in parsed) <= s.cursor
    blob = json.dumps([d for _, d in parsed])
    assert "PARTIALLY_CONTAINED" not in blob
    assert "next_day_draft" not in blob


def test_sse_never_carries_raw_partner_or_recall_source_text():
    s = drive_to_end()
    blob = json.dumps(parse_blocks(collect(runtime.stream(s, max_frames=25))))
    assert "We pulled the remaining lettuce" not in blob
    assert "Should be all good" not in blob
    for _, data in parse_blocks(collect(runtime.stream(s, max_frames=25))):
        assert data["source_refs"] == []


def test_canonical_sse_contains_canonical_events_only():
    s = at_terminal()
    s.enter_branch("complete")
    parsed = parse_blocks(collect(runtime.stream(s, max_frames=22)))
    assert all(d["authority"] == "CANONICAL" for _, d in parsed)
    assert all(isinstance(d["sequence"], int) for _, d in parsed)


def test_branch_stream_uses_a_separate_ordinal_namespace():
    s = at_terminal()
    s.enter_branch("vague")
    canonical_ids = {i for i, _ in parse_blocks(collect(runtime.stream(s, max_frames=22)))}
    branch_ids = {i for i, _ in parse_blocks(collect(runtime.branch_stream(s)))}
    assert branch_ids.isdisjoint(canonical_ids)
    assert all(i.startswith("b") for i in branch_ids)


def test_sse_is_session_scoped():
    store = runtime.SessionStore()
    a, b = store.create(), store.create()
    a.start()
    a.autoplay_step()
    a_frames = parse_blocks(collect(runtime.stream(a, max_frames=6)))
    b_frames = parse_blocks(collect(runtime.stream(b, max_frames=5)))
    assert len(a_frames) == 6 and len(b_frames) == 5
    assert all(d["session_id"] == a.session_id for _, d in a_frames)
    assert all(d["session_id"] == b.session_id for _, d in b_frames)


# --- HTTP transport ---------------------------------------------------------

import runtime_server  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNTIME_SOURCES = ["events.py", "session.py", "runtime_server.py"]


def test_runtime_binds_loopback_only():
    assert runtime_server.LOOPBACK == "127.0.0.1"
    for name in RUNTIME_SOURCES:
        assert "0.0.0.0" not in (pathlib.Path(__file__).parent / name).read_text()


def test_runtime_calls_no_google_service():
    banned = ("google.cloud", "spanner", "aiplatform", "vertexai",
              "model_armor", "run_fleet", "httpx", "requests")
    for name in RUNTIME_SOURCES:
        source = (pathlib.Path(__file__).parent / name).read_text()
        for token in banned:
            assert token not in source, f"{name} must not reference {token}"


def test_runtime_is_absent_from_deployment_configuration():
    for config in ("cloudbuild.yaml", "cloudbuild-orchestrator.yaml",
                   "cloudbuild-ledger.yaml"):
        text = (REPO / config).read_text()
        assert "tools/replay" not in text
        assert "runtime_server" not in text
    for dockerfile in REPO.glob("apps/*/Dockerfile"):
        assert "tools/replay" not in dockerfile.read_text()


def test_runtime_never_claims_kms_or_real_identity():
    for name in RUNTIME_SOURCES:
        source = (pathlib.Path(__file__).parent / name).read_text()
        assert "OBSERVED_LIVE" not in source
        assert "RECORDED_LIVE" not in source


# --- end to end over real HTTP ---------------------------------------------

import http.client  # noqa: E402
import threading as _threading  # noqa: E402
import time  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402


@pytest.fixture(scope="module")
def live():
    runtime_server.STORE = runtime.SessionStore()
    server = ThreadingHTTPServer((runtime_server.LOOPBACK, 0),
                                 runtime_server.RuntimeHandler)
    thread = _threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


def call(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection(runtime_server.LOOPBACK, port, timeout=5)
    payload = json.dumps(body) if body is not None else None
    conn.request(method, path, body=payload,
                 headers={"Content-Type": "application/json", **(headers or {})})
    response = conn.getresponse()
    raw = response.read().decode("utf-8")
    conn.close()
    return response.status, (json.loads(raw) if raw else {})


def test_http_session_lifecycle_pauses_at_the_gate_and_resumes(live):
    status, created = call(live, "POST", "/api/v1/replay/sessions")
    assert status == 201
    sid = created["session_id"]
    assert created["cursor"] == 5
    assert [f["sequence"] for f in created["feed"]] == [1, 2, 3, 4, 5]

    base = f"/api/v1/replay/sessions/{sid}"
    for _ in range(3):
        assert call(live, "POST", base + "/advance")[0] == 200
    status, denied = call(live, "POST", base + "/advance")
    assert status == 409 and denied["detail"] == "HUMAN_APPROVAL_REQUIRED"

    status, approved = call(live, "POST", base + "/approve", valid_approval())
    assert status == 200
    assert [f["sequence"] for f in approved["events"]] == [9]
    assert call(live, "GET", base)[1]["cursor"] == 9
    # Presenter mode: activation needs the next explicit advance.
    assert call(live, "POST", base + "/advance")[1]["sequence"] == 10

    status, dup = call(live, "POST", base + "/approve", valid_approval())
    assert status == 200 and dup["duplicate"] is True

    status, mismatch = call(live, "POST", base + "/approve",
                            valid_approval(target_revision="rev09"))
    assert status == 409 and mismatch["detail"] == "APPROVAL_BINDING_MISMATCH"


def test_http_rejects_unknown_session_and_route(live):
    assert call(live, "GET", "/api/v1/replay/sessions/nope")[0] == 404
    assert call(live, "GET", "/api/v1/replay/fabricated")[0] == 404


def test_http_branch_requires_the_terminal_state(live):
    _, created = call(live, "POST", "/api/v1/replay/sessions")
    base = f"/api/v1/replay/sessions/{created['session_id']}"
    status, denied = call(live, "POST", base + "/branch", {"proof": "complete"})
    assert status == 409 and denied["detail"] == "PROOF_BRANCH_NOT_AVAILABLE_YET"


def test_http_reset_issues_a_new_session_at_event_five(live):
    _, created = call(live, "POST", "/api/v1/replay/sessions")
    old = created["session_id"]
    call(live, "POST", f"/api/v1/replay/sessions/{old}/advance")
    status, fresh = call(live, "POST", f"/api/v1/replay/sessions/{old}/reset")
    assert status == 201
    assert fresh["cursor"] == 5
    assert fresh["session_id"] != old
    assert call(live, "GET", f"/api/v1/replay/sessions/{old}")[0] == 404


def test_http_sse_streams_and_resumes(live):
    _, created = call(live, "POST", "/api/v1/replay/sessions")
    sid = created["session_id"]
    conn = http.client.HTTPConnection(runtime_server.LOOPBACK, live, timeout=5)
    conn.request("GET", f"/api/v1/replay/sessions/{sid}/stream",
                 headers={"Last-Event-ID": "3"})
    response = conn.getresponse()
    assert response.status == 200
    assert response.getheader("Content-Type") == "text/event-stream"
    chunk = response.read(220).decode("utf-8")
    conn.close()
    assert "id: 4" in chunk
    assert "event: replay_event" in chunk
    assert "id: 3" not in chunk


def test_http_sse_rejects_a_malformed_resume_cursor(live):
    _, created = call(live, "POST", "/api/v1/replay/sessions")
    status, body = call(live, "GET",
                        f"/api/v1/replay/sessions/{created['session_id']}/stream",
                        headers={"Last-Event-ID": "not-a-cursor"})
    assert status == 400 and body["detail"] == "INVALID_LAST_EVENT_ID"


def test_http_projection_is_cursor_gated(live):
    _, created = call(live, "POST", "/api/v1/replay/sessions")
    _, body = call(live, "GET",
                   f"/api/v1/replay/sessions/{created['session_id']}/projection")
    blob = json.dumps(body)
    assert "rev08" not in blob
    assert "next_day_draft" not in body
    assert events.RECALL_INC not in blob


def test_http_sessions_are_isolated(live):
    _, a = call(live, "POST", "/api/v1/replay/sessions")
    _, b = call(live, "POST", "/api/v1/replay/sessions")
    call(live, "POST", f"/api/v1/replay/sessions/{a['session_id']}/advance")
    _, b_state = call(live, "GET", f"/api/v1/replay/sessions/{b['session_id']}")
    assert b_state["cursor"] == 5


def test_http_autoplay_thread_survives_the_gate_and_reaches_the_end(live):
    """The autoplay thread must resume after approval, not strand at event 10."""
    _, created = call(live, "POST", "/api/v1/replay/sessions")
    base = f"/api/v1/replay/sessions/{created['session_id']}"
    call(live, "POST", base + "/start", {"interval_ms": 5})

    deadline = time.time() + 10
    while time.time() < deadline:
        state = call(live, "GET", base)[1]
        if state["mode"] == "PAUSED_HUMAN_GATE":
            break
        time.sleep(0.05)
    assert state["cursor"] == 8

    call(live, "POST", base + "/approve", valid_approval())

    deadline = time.time() + 10
    while time.time() < deadline:
        state = call(live, "GET", base)[1]
        if state["mode"] == "COMPLETE":
            break
        time.sleep(0.05)
    assert state["cursor"] == events.LAST_SEQUENCE == 25
    assert state["mode"] == "COMPLETE"
    assert [f["sequence"] for f in call(live, "GET", base)[1]["feed"]] == list(range(1, 26))


def test_http_pause_stops_autoplay(live):
    _, created = call(live, "POST", "/api/v1/replay/sessions")
    base = f"/api/v1/replay/sessions/{created['session_id']}"
    call(live, "POST", base + "/start", {"interval_ms": 5})
    time.sleep(0.1)
    call(live, "POST", base + "/pause")
    settled = call(live, "GET", base)[1]["cursor"]
    time.sleep(0.4)
    assert call(live, "GET", base)[1]["cursor"] == settled


# --- P1 repair 1: the plan-diff hash is part of the binding ------------------


def test_approval_without_a_plan_diff_hash_is_refused():
    s = at_gate()
    body = valid_approval()
    del body["plan_diff_hash"]
    before_feed, before_cursor = s.feed(), s.cursor
    with pytest.raises(runtime.ReplayError) as exc:
        s.approve(body)
    assert exc.value.status == 409
    assert exc.value.code == "APPROVAL_BINDING_MISMATCH"
    assert s.approval is None
    assert s.cursor == before_cursor
    assert s.feed() == before_feed


@pytest.mark.parametrize("bad", [None, "", "0" * 64, "not-a-hash",
                                 runtime.CANONICAL_PLAN_DIFF_HASH.upper()])
def test_approval_with_an_altered_plan_diff_hash_is_refused(bad):
    s = at_gate()
    before_feed, before_cursor = s.feed(), s.cursor
    with pytest.raises(runtime.ReplayError) as exc:
        s.approve(valid_approval(plan_diff_hash=bad))
    assert exc.value.status == 409
    assert s.approval is None
    assert s.cursor == before_cursor
    assert s.feed() == before_feed


def test_hash_denial_creates_no_receipt_and_a_later_valid_approval_still_works():
    s = at_gate()
    body = valid_approval()
    del body["plan_diff_hash"]
    with pytest.raises(runtime.ReplayError):
        s.approve(body)
    result = s.approve(valid_approval())
    assert result["duplicate"] is False
    assert [f["sequence"] for f in result["events"]] == [9]


def test_http_approval_without_hash_is_409(live):
    _, created = call(live, "POST", "/api/v1/replay/sessions")
    base = f"/api/v1/replay/sessions/{created['session_id']}"
    for _ in range(3):
        call(live, "POST", base + "/advance")
    body = valid_approval()
    del body["plan_diff_hash"]
    status, payload = call(live, "POST", base + "/approve", body)
    assert status == 409
    assert payload["detail"] == "APPROVAL_BINDING_MISMATCH"
    assert call(live, "GET", base)[1]["cursor"] == 8


# --- P1 repair 2: the stream stays open --------------------------------------


def test_caught_up_stream_stays_open_and_receives_the_next_event():
    """Last-Event-ID at the current cursor must not end the stream."""
    import threading as _t
    s = at_gate()
    seen, opened = [], _t.Event()

    def reader():
        for block in runtime.stream(s, last_event_id=str(s.cursor),
                                    max_frames=1, keepalive=0.05):
            if block.startswith(": keep-alive"):
                opened.set()
                continue
            seen.append(parse_blocks([block])[0])

    t = _t.Thread(target=reader, daemon=True)
    t.start()
    assert opened.wait(timeout=5), "stream closed instead of waiting"
    s.approve(valid_approval())
    t.join(timeout=5)
    assert not t.is_alive()
    assert [int(i) for i, _ in seen] == [9]


def test_caught_up_stream_emits_keepalive_rather_than_closing():
    s = at_gate()
    blocks = []
    for block in runtime.stream(s, last_event_id=str(s.cursor),
                                idle_timeout=0.3, keepalive=0.05):
        blocks.append(block)
    assert blocks, "expected keepalives while waiting"
    assert all(b.startswith(": keep-alive") for b in blocks)


def test_idle_timeout_is_a_bounded_test_seam_only():
    s = at_gate()
    assert collect(runtime.stream(s, last_event_id=str(s.cursor),
                                  idle_timeout=0.05, keepalive=10)) == []


def test_stream_ends_when_the_session_closes():
    import threading as _t
    s = at_gate()
    done = _t.Event()

    def reader():
        collect(runtime.stream(s, last_event_id=str(s.cursor), keepalive=0.05))
        done.set()

    _t.Thread(target=reader, daemon=True).start()
    time.sleep(0.2)
    s.close()
    assert done.wait(timeout=5), "closing the session must end the stream"


def test_server_stream_uses_no_bounded_seam():
    """The transport must not pass max_frames or idle_timeout."""
    source = (pathlib.Path(__file__).parent / "runtime_server.py").read_text()
    assert "max_frames" not in source
    assert "idle_timeout" not in source


# --- P1 repair 3: runtime projection timestamps are Pacific -----------------


def stamps(node, found=None):
    found = [] if found is None else found
    if isinstance(node, dict):
        for value in node.values():
            stamps(value, found)
    elif isinstance(node, list):
        for item in node:
            stamps(item, found)
    elif isinstance(node, str) and runtime._UTC_STAMP.match(node):
        found.append(node)
    return found


@pytest.mark.parametrize("sequence,label", [
    (5, "healthy"), (10, "approval"), (11, "recall"),
    (20, "recovery"), (22, "refusal"), (24, "saturday"),
])
def test_runtime_projection_carries_no_utc_timestamps(sequence, label):
    body = projection_at(sequence)
    assert stamps(body) == [], f"{label} still emits UTC stamps"
    assert "-07:00" in json.dumps(body)


def test_runtime_projection_preserves_scenario_wall_clock():
    """08:05Z must become 08:05-07:00, never 01:05-07:00."""
    boundary = projection_at(5)["projection_boundary"]["as_of"]
    assert boundary == "2026-08-14T08:05:00-07:00"
    assert projection_at(22)["projection_boundary"]["as_of"] == \
        "2026-08-14T10:13:00-07:00"
    assert projection_at(24)["projection_boundary"]["as_of"] == \
        "2026-08-14T17:00:00-07:00"


def test_runtime_retimes_every_timestamp_shape():
    assert runtime._retime("2026-08-14T08:05:00+00:00") == "2026-08-14T08:05:00-07:00"
    assert runtime._retime("2026-08-14 20:00:00+00:00") == "2026-08-14 20:00:00-07:00"
    assert runtime._retime("2026-08-14T09:36:00Z") == "2026-08-14T09:36:00-07:00"
    # Non-timestamps and already-Pacific values are untouched.
    assert runtime._retime("LTC-4471") == "LTC-4471"
    assert runtime._retime("2026-08-14T08:05:00-07:00") == "2026-08-14T08:05:00-07:00"


def test_branch_projection_is_also_retimed():
    s = at_terminal()
    s.enter_branch("complete")
    assert stamps(s.projection()) == []


def test_legacy_selector_timestamps_are_untouched():
    """The legacy fixture selector must keep emitting UTC."""
    import server as legacy
    body = legacy._select("2026-08-14T10:13:00+00:00", False)
    assert body["projection_boundary"]["as_of"] == "2026-08-14T10:13:00+00:00"
    assert stamps(body), "legacy selector must still carry UTC stamps"


def test_committed_fixtures_on_disk_are_unmodified():
    for entry in INDEX["beats"]:
        raw = (FIXTURES / entry["fixture"]).read_text()
        assert "-07:00" not in raw, f"{entry['fixture']} was rewritten"


# --- P1 repair 4: approval and activation are separate commits --------------


def test_approval_commits_event_nine_only():
    s = at_gate()
    result = s.approve(valid_approval())
    assert [f["sequence"] for f in result["events"]] == [9]
    assert s.cursor == 9
    assert result["state"]["cursor"] == 9


def test_presenter_mode_requires_advance_for_activation():
    s = at_gate()
    s.approve(valid_approval())
    assert s.cursor == 9
    frame = s.advance()
    assert frame["sequence"] == 10
    assert s.cursor == 10


def test_event_nine_carries_the_approval_receipt_reference():
    s = at_gate()
    receipt = s.approve(valid_approval())["receipt"]
    gate = [f for f in s.feed() if f["sequence"] == 9][0]
    assert gate["receipt_refs"] == [receipt["receipt_id"]]


def test_sse_delivers_nine_and_ten_as_separate_frames():
    import threading as _t
    s = at_gate()
    seen = []

    def reader():
        for block in runtime.stream(s, last_event_id="8", max_frames=2,
                                    keepalive=0.05):
            if not block.startswith(": keep-alive"):
                seen.append(parse_blocks([block])[0])

    t = _t.Thread(target=reader, daemon=True)
    t.start()
    s.approve(valid_approval())
    time.sleep(0.15)
    s.mode = runtime.PLAYING
    s.autoplay_step()
    t.join(timeout=5)
    assert [int(i) for i, _ in seen] == [9, 10]
    assert len({d["event_id"] for _, d in seen}) == 2


def test_http_autoplay_resumes_activation_after_the_configured_interval(live):
    _, created = call(live, "POST", "/api/v1/replay/sessions")
    base = f"/api/v1/replay/sessions/{created['session_id']}"
    call(live, "POST", base + "/start", {"interval_ms": 30})

    deadline = time.time() + 10
    while time.time() < deadline:
        state = call(live, "GET", base)[1]
        if state["mode"] == "PAUSED_HUMAN_GATE":
            break
        time.sleep(0.05)
    assert state["cursor"] == 8

    approved = call(live, "POST", base + "/approve", valid_approval())[1]
    assert [f["sequence"] for f in approved["events"]] == [9]

    deadline = time.time() + 10
    while time.time() < deadline:
        state = call(live, "GET", base)[1]
        if state["cursor"] >= 10:
            break
        time.sleep(0.05)
    assert state["cursor"] >= 10, "autoplay did not resume after approval"


def test_duplicate_and_altered_binding_survive_the_split(live):
    _, created = call(live, "POST", "/api/v1/replay/sessions")
    base = f"/api/v1/replay/sessions/{created['session_id']}"
    for _ in range(3):
        call(live, "POST", base + "/advance")
    first = call(live, "POST", base + "/approve", valid_approval())[1]
    dup = call(live, "POST", base + "/approve", valid_approval())[1]
    assert dup["duplicate"] is True
    assert dup["receipt"]["receipt_id"] == first["receipt"]["receipt_id"]
    status, denied = call(live, "POST", base + "/approve",
                          valid_approval(target_revision="rev09"))
    assert status == 409 and denied["detail"] == "APPROVAL_BINDING_MISMATCH"
