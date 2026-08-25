"""Session-scoped deterministic runtime for the Full Shelf golden demo.

Holds presentation cursor state only. It owns no authoritative operational
state, mutates nothing canonical, and calls no Google service. Every identifier
it mints is fixture-prefixed and every event it emits is SYNTHETIC_TEST.

The state machine enforces the ordering the transport must not be trusted with:
autoplay cannot cross the human gate, event 10 cannot precede event 9's receipt,
a proof branch cannot open before the canonical terminal state, and no field
belonging to a later event crosses the boundary early.
"""

import copy
import json
import pathlib
import re
import threading
import uuid
from datetime import datetime, timezone

import events
import locations

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

# Canonical scenario zone offset on the operating day, 2026-08-14.
PACIFIC_SUFFIX = "-07:00"

# Session lifecycle.
IDLE = "IDLE"
PLAYING = "PLAYING"
PAUSED = "PAUSED"
PAUSED_HUMAN_GATE = "PAUSED_HUMAN_GATE"
COMPLETE = "COMPLETE"

# The exact repair diff the approval must bind, per the canonical scenario.
CANONICAL_BINDING = {
    "plan_id": events.PLAN_ID,
    "incident_id": events.FLEET_INC,
    "expected_revision": "rev07",
    "target_revision": "rev08",
    "actions": [
        {"order_id": "O202", "cases": 22, "disposition": "TRUCK_2"},
        {"order_id": "O203", "cases": 20, "disposition": "PARTNER_PICKUP"},
    ],
}
CANONICAL_PLAN_DIFF_HASH = events.plan_diff_hash(CANONICAL_BINDING)
BINDING_FIELDS = ("plan_id", "incident_id", "expected_revision",
                  "target_revision", "actions")


class ReplayError(Exception):
    """Refusal carrying the HTTP status the transport should surface."""

    def __init__(self, status, code, detail=None):
        super().__init__(code)
        self.status = status
        self.code = code
        self.detail = detail

    def body(self):
        payload = {"detail": self.code}
        if self.detail:
            payload["reason"] = self.detail
        return payload


_FIXTURE_CACHE = {}


def load_fixture(key):
    """Read a committed projection fixture, cached and copied on hand-out."""
    if key not in _FIXTURE_CACHE:
        _FIXTURE_CACHE[key] = json.loads((FIXTURES / f"{key}.json").read_text())
    return copy.deepcopy(_FIXTURE_CACHE[key])


def _now():
    return datetime.now(timezone.utc).isoformat()


_UTC_STAMP = re.compile(
    r"^(\d{4}-\d{2}-\d{2})([T ])(\d{2}:\d{2}:\d{2}(?:\.\d+)?)(Z|\+00:00)$")


def _retime(value):
    """Relabel a fixture's UTC stamp as the same canonical Pacific wall clock.

    The committed fixtures serialize scenario wall-clock time with a UTC suffix,
    so 08:05 is stamped 08:05+00:00. The runtime states the canonical zone
    truthfully without shifting the clock: 08:05+00:00 becomes 08:05-07:00, not
    01:05-07:00. Legacy fixtures and the legacy selector are untouched.
    """
    match = _UTC_STAMP.match(value)
    if not match:
        return value
    date, separator, clock, _ = match.groups()
    return f"{date}{separator}{clock}{PACIFIC_SUFFIX}"


def retime_projection(node):
    """Restamp every UTC timestamp in a runtime projection as Pacific."""
    if isinstance(node, dict):
        return {key: retime_projection(value) for key, value in node.items()}
    if isinstance(node, list):
        return [retime_projection(item) for item in node]
    if isinstance(node, str):
        return _retime(node)
    return node


def _strip_recall_incident(body):
    """Remove the recall incident from a projection that reveals it too early."""
    current = body.get("current_day")
    if isinstance(current, dict) and isinstance(current.get("incidents"), list):
        current["incidents"] = [
            incident for incident in current["incidents"]
            if incident.get("incident_id") != events.RECALL_INC
        ]


def filter_projection(body, cursor):
    """Remove every field whose establishing event has not yet committed.

    Blocking future envelopes is not enough: a backing fixture legitimately
    carries later fields, so the projection itself is gated on the cursor.
    """
    body = copy.deepcopy(body)
    current = body.get("current_day")

    if cursor < events.REV08_SEQUENCE:
        if isinstance(current, dict):
            current.pop("repair_proposal", None)
            if current.get("active_plan_revision") == "rev08":
                current["active_plan_revision"] = "rev07"
            revisions = current.get("plan_revisions")
            if isinstance(revisions, list):
                current["plan_revisions"] = [
                    revision for revision in revisions
                    if (revision.get("revision") if isinstance(revision, dict)
                        else revision) != "rev08"
                ]

    if cursor < events.RECALL_SEQUENCE:
        _strip_recall_incident(body)
        body["recall_intake_as_of"] = None
        body["partner_evidence_as_of"] = None

    if cursor < events.CUSTODY_SEQUENCE:
        evidence = body.get("execution_evidence_as_of")
        if isinstance(evidence, dict):
            evidence.pop("custody_graph", None)

    if cursor < events.RECOVERY_SEQUENCE:
        if isinstance(current, dict):
            current.pop("recovery", None)
        body["carry_forward_obligations"] = []

    if cursor < events.TERMINAL_SEQUENCE:
        if isinstance(current, dict) and isinstance(current.get("incidents"), list):
            for incident in current["incidents"]:
                if incident.get("status") == "PARTIALLY_CONTAINED":
                    incident["status"] = "CONTAINMENT_IN_PROGRESS"

    if cursor < events.SATURDAY_SEQUENCE:
        body.pop("next_day_draft", None)

    return body


# ---------------------------------------------------------------------------
# Projection enrichment
#
# The committed fixtures were generated for the legacy beat selector and do not
# expose a structured repair proposal, a Truck 1 record, an advisory recovery
# proposal, or any geography. The runtime derives those surfaces here from
# canonical scenario data that already exists in the fixtures, so the frontend
# never has to scrape prose or recompute an invariant.
#
# Nothing here invents a quantity. Every number is the canonical scenario value
# asserted in AGENTS.md and GOLDEN_DEMO_EVENT_CONTRACT.md section 2.
# ---------------------------------------------------------------------------

# Truck 1: refrigerated, capacity 60, carries O201/O202/O203 under rev07.
# It is never repaired within the canonical day; after event 6 it stays
# unavailable with its refrigeration alarm raised.
TRUCK_1_ID = "TRUCK-01"
TRUCK_2_ID = "TRUCK-02"
VEHICLE_CAPACITY = 60
# rev07 load on Truck 2 before the repair, per contract section 2.
TRUCK_2_BASE_CASES = 36
REPAIR_MOVED_CASES = 22          # O202
PARTNER_PICKUP_CASES = 20        # O203


def _orders_for(commitments, vehicle_id, revision):
    return [c["order_id"] for c in commitments
            if c.get("vehicle") == vehicle_id and c.get("revision") == revision]


def _vehicle_projection(cursor, commitments):
    """Both vehicles at every cursor, with honest alarm and capability state."""
    rev = "rev08" if cursor >= events.REV08_SEQUENCE else "rev07"
    truck1_failed = cursor >= 6

    truck1_orders = _orders_for(commitments, TRUCK_1_ID, "rev07")
    truck1_cases = sum(c["cases"] for c in commitments
                       if c.get("vehicle") == TRUCK_1_ID and c.get("revision") == "rev07"
                       and c.get("status") != "DELIVERED")

    if rev == "rev08":
        truck2_cases = TRUCK_2_BASE_CASES + REPAIR_MOVED_CASES
        truck2_orders = _orders_for(commitments, TRUCK_2_ID, "rev08")
    else:
        truck2_cases = TRUCK_2_BASE_CASES
        truck2_orders = _orders_for(commitments, TRUCK_2_ID, "rev07")

    return [
        {
            "vehicle_id": TRUCK_1_ID,
            "display_name": "Refrigerated Truck 1",
            "refrigeration_capable": True,
            # The failure removes refrigerated capability; it is never restored
            # inside the canonical day, so this must not silently flip back.
            "refrigeration_operational": not truck1_failed,
            "is_operational": not truck1_failed,
            "status": "REFRIGERATION_FAILURE" if truck1_failed else "AVAILABLE",
            "alarm": {
                "active": truck1_failed,
                "kind": "REFRIGERATION_FAILURE" if truck1_failed else None,
                "incident_id": events.FLEET_INC if truck1_failed else None,
                "raised_at_event": 6 if truck1_failed else None,
            },
            "capacity_cases": VEHICLE_CAPACITY,
            "manifest_cases": 0 if rev == "rev08" else truck1_cases,
            "remaining_cases": (VEHICLE_CAPACITY if rev == "rev08"
                                else VEHICLE_CAPACITY - truck1_cases),
            "assigned_orders": [] if rev == "rev08" else truck1_orders,
            "revision": rev,
            "telemetry": {
                "live_gps": False,
                "position_available": False,
                "basis": "SIMULATED_FLEET_TELEMATICS",
                "disclosure": ("Simulated fleet telematics. No live GPS position "
                               "is available or claimed."),
            },
        },
        {
            "vehicle_id": TRUCK_2_ID,
            "display_name": "Refrigerated Truck 2",
            "refrigeration_capable": True,
            "refrigeration_operational": True,
            "is_operational": True,
            "status": "AVAILABLE",
            "alarm": {"active": False, "kind": None, "incident_id": None,
                      "raised_at_event": None},
            "capacity_cases": VEHICLE_CAPACITY,
            "manifest_cases": truck2_cases,
            "remaining_cases": VEHICLE_CAPACITY - truck2_cases,
            "assigned_orders": truck2_orders,
            "revision": rev,
            "telemetry": {
                "live_gps": False,
                "position_available": False,
                "basis": "SIMULATED_FLEET_TELEMATICS",
                "disclosure": ("Simulated fleet telematics. No live GPS position "
                               "is available or claimed."),
            },
        },
    ]


def _repair_proposal(approval_receipt_id=None):
    """The exact rev07 to rev08 diff, structured so the UI never parses prose."""
    binding = {
        "plan_id": events.PLAN_ID,
        "incident_id": events.FLEET_INC,
        "expected_revision": "rev07",
        "target_revision": "rev08",
        "actions": [
            {"order_id": "O202", "cases": REPAIR_MOVED_CASES,
             "disposition": "TRUCK_2"},
            {"order_id": "O203", "cases": PARTNER_PICKUP_CASES,
             "disposition": "PARTNER_PICKUP"},
        ],
    }
    return {
        "proposal_id": "fixture-PROP-rev08",
        "plan_id": events.PLAN_ID,
        "incident_id": events.FLEET_INC,
        "expected_revision": "rev07",
        "target_revision": "rev08",
        "status": "PROPOSED" if approval_receipt_id is None else "APPROVED",
        "actions": [
            {"order_id": "O202", "agency": "Agency 02",
             "cases": REPAIR_MOVED_CASES, "lot_id": "LTC-4471",
             "from_vehicle": TRUCK_1_ID, "to_vehicle": TRUCK_2_ID,
             "disposition": "TRUCK_2"},
            {"order_id": "O203", "agency": "Agency 03",
             "cases": PARTNER_PICKUP_CASES, "lot_id": "LTC-4471",
             "from_vehicle": TRUCK_1_ID, "to_vehicle": None,
             "disposition": "PARTNER_PICKUP"},
        ],
        # 36 + 22 = 58 of 60. Stated, not left for the client to compute.
        "capacity_arithmetic": {
            "vehicle_id": TRUCK_2_ID,
            "existing_cases": TRUCK_2_BASE_CASES,
            "added_cases": REPAIR_MOVED_CASES,
            "resulting_cases": TRUCK_2_BASE_CASES + REPAIR_MOVED_CASES,
            "capacity_cases": VEHICLE_CAPACITY,
            "statement": "36 + 22 = 58/60",
            "both_orders_would_not_fit": (
                f"{TRUCK_2_BASE_CASES} + {REPAIR_MOVED_CASES} + "
                f"{PARTNER_PICKUP_CASES} = 78 exceeds {VEHICLE_CAPACITY}"),
        },
        "plan_diff_hash": CANONICAL_PLAN_DIFF_HASH,
        # Everything the approval endpoint requires except the client key.
        "approval_payload_template": {
            **copy.deepcopy(binding),
            "plan_diff_hash": CANONICAL_PLAN_DIFF_HASH,
            "idempotency_key": None,
        },
        "approval_endpoint": "POST /api/v1/replay/sessions/{session_id}/approve",
        "idempotency_key_note": "Client-generated. The only field not supplied here.",
        "approval_receipt_id": approval_receipt_id,
        "classification": events.CLASSIFICATION,
    }


def _recovery_proposal():
    """Advisory allocation selected at event 19, before any commitment."""
    return {
        "proposal_id": "fixture-PROP-recovery",
        "incident_id": events.RECALL_INC,
        "status": "PROPOSED",
        "safe_lot_id": "LTC-5090",
        "allocations": [
            {"agency_id": "AGENCY-01", "cases": 18, "status": "PROPOSED"},
            {"agency_id": "AGENCY-02", "cases": 22, "status": "PROPOSED"},
        ],
        "total_proposed_cases": 40,
        "shortfalls": [
            {"agency_id": "AGENCY-03", "shortfall_id": "SF-A03", "cases": 20,
             "status": "PROPOSED"},
        ],
        "mutation_applied": False,
        "commits_at_event": events.RECOVERY_SEQUENCE,
        "basis": "DETERMINISTIC_DERIVATION",
        "classification": events.CLASSIFICATION,
    }


def _custody_graph_at_reconciliation():
    """The reconciled graph, sourced from the fixture that carries it."""
    recovery = load_fixture("recovery")
    return (recovery.get("execution_evidence_as_of") or {}).get("custody_graph")


def enrich_projection(body, cursor, approval_receipt_id=None):
    """Add the frontend surfaces the legacy fixtures never carried."""
    current = body.get("current_day")
    if not isinstance(current, dict):
        return body

    commitments = current.get("commitments") or []
    current["vehicles"] = _vehicle_projection(cursor, commitments)

    # Event 8 proposes the repair; event 9 attaches its receipt; event 10
    # activates. The proposal stays visible after activation as provenance.
    if cursor >= 8:
        current["repair_proposal"] = _repair_proposal(approval_receipt_id)

    # Custody is reconciled at event 18, not first observable at event 20.
    if cursor >= events.CUSTODY_SEQUENCE:
        evidence = body.setdefault("execution_evidence_as_of", {})
        if isinstance(evidence, dict) and not evidence.get("custody_graph"):
            graph = _custody_graph_at_reconciliation()
            if graph:
                evidence["custody_graph"] = graph

    # The advisory proposal is separate from the committed allocation.
    if cursor >= 19:
        current["recovery_proposal"] = _recovery_proposal()

    body["reference_locations"] = locations.reference_locations()
    return body


class ReplaySession:
    """One judge or presenter session. Independent of every other session."""

    def __init__(self, session_id=None):
        self.session_id = session_id or f"fs-replay-{uuid.uuid4()}"
        self.created_at = _now()
        self.cursor = events.INITIAL_CURSOR
        self.mode = IDLE
        self.approval = None
        self.branch = None
        self.branch_events = []
        # Guards every mutation and wakes SSE readers. No busy polling.
        self.cond = threading.Condition()
        self.closed = False
        self._emitted = [
            events.envelope(events.BY_SEQUENCE[sequence],
                            session_id=self.session_id, recorded_at=self.created_at)
            for sequence in range(events.FIRST_SEQUENCE, events.INITIAL_CURSOR + 1)
        ]

    # -- reads ---------------------------------------------------------------

    def feed(self):
        """Committed canonical events. Never contains a future event."""
        with self.cond:
            return copy.deepcopy(self._emitted)

    def history(self):
        """Events 1-4: immutable, read-only, preloaded at creation."""
        with self.cond:
            return copy.deepcopy(self._emitted[:events.INITIAL_CURSOR - 1])

    def state(self):
        with self.cond:
            return {
                "session_id": self.session_id,
                "cursor": self.cursor,
                "mode": self.mode,
                "created_at": self.created_at,
                "operating_timestamp":
                    events.BY_SEQUENCE[self.cursor].effective_at.isoformat(),
                "approval_required": self._gate_is_open_locked(),
                "approved": self.approval is not None,
                "branch": self.branch,
                "classification": events.CLASSIFICATION,
                "synthetic": True,
            }

    def projection(self):
        """Bounded projection at the current cursor, branch-aware."""
        with self.cond:
            if self.branch is not None:
                body = load_fixture(events.BRANCHES[self.branch]["fixture_key"])
                body["authority"] = "ISOLATED"
                body["proof_label"] = events.BRANCHES[self.branch]["label"]
                body["classification"] = events.CLASSIFICATION
                body["reference_locations"] = locations.reference_locations()
                return retime_projection(body)
            cursor = self.cursor
            receipt_id = (self.approval or {}).get("receipt_id")
        return retime_projection(enrich_projection(
            filter_projection(load_fixture(self._fixture_for(cursor)), cursor),
            cursor, receipt_id))

    @staticmethod
    def _fixture_for(cursor):
        """Latest fixture-backed canonical event at or before the cursor."""
        key = None
        for event in events.CANONICAL_EVENTS:
            if event.sequence > cursor:
                break
            if event.fixture_key:
                key = event.fixture_key
        return key or "healthy"

    # -- gate ----------------------------------------------------------------

    def _gate_is_open_locked(self):
        """True when the cursor sits at the boundary before the human gate."""
        return (self.cursor == events.HUMAN_GATE_SEQUENCE - 1
                and self.approval is None)

    def _next_permitted_locked(self):
        """The next sequence autoplay may commit, or None if it must stop."""
        nxt = self.cursor + 1
        if nxt > events.LAST_SEQUENCE:
            return None
        if nxt == events.HUMAN_GATE_SEQUENCE and self.approval is None:
            return None
        if nxt == events.ACTIVATION_SEQUENCE and self.approval is None:
            return None
        return nxt

    # -- writes --------------------------------------------------------------

    def _commit_locked(self, sequence):
        event = events.BY_SEQUENCE[sequence]
        frame = events.envelope(event, session_id=self.session_id,
                                recorded_at=_now())
        self._emitted.append(frame)
        self.cursor = sequence
        return frame

    def advance(self):
        """Commit the next permitted event. FILM_PRESENTER forward control."""
        with self.cond:
            if self.branch is not None:
                raise ReplayError(409, "CANONICAL_ADVANCE_BLOCKED_IN_BRANCH")
            if self.cursor >= events.LAST_SEQUENCE:
                self.mode = COMPLETE
                raise ReplayError(409, "REPLAY_COMPLETE")
            nxt = self._next_permitted_locked()
            if nxt is None:
                self.mode = PAUSED_HUMAN_GATE
                raise ReplayError(409, "HUMAN_APPROVAL_REQUIRED")
            frame = self._commit_locked(nxt)
            if self.cursor >= events.LAST_SEQUENCE:
                self.mode = COMPLETE
            self.cond.notify_all()
            return frame

    def start(self):
        with self.cond:
            if self.mode == COMPLETE:
                raise ReplayError(409, "REPLAY_COMPLETE")
            self.mode = PLAYING
            self.cond.notify_all()
            return self.state_locked()

    def pause(self):
        with self.cond:
            if self.mode == PLAYING:
                self.mode = PAUSED
            self.cond.notify_all()
            return self.state_locked()

    def state_locked(self):
        return {
            "session_id": self.session_id,
            "cursor": self.cursor,
            "mode": self.mode,
            "approval_required": self._gate_is_open_locked(),
            "approved": self.approval is not None,
            "branch": self.branch,
            "classification": events.CLASSIFICATION,
            "synthetic": True,
        }

    def autoplay_step(self):
        """One deterministic tick. Returns the frame, or None when it must stop."""
        with self.cond:
            if self.mode != PLAYING:
                return None
            if self.cursor >= events.LAST_SEQUENCE:
                self.mode = COMPLETE
                self.cond.notify_all()
                return None
            nxt = self._next_permitted_locked()
            if nxt is None:
                self.mode = PAUSED_HUMAN_GATE
                self.cond.notify_all()
                return None
            frame = self._commit_locked(nxt)
            if self.cursor >= events.LAST_SEQUENCE:
                self.mode = COMPLETE
            self.cond.notify_all()
            return frame

    # -- the one human gate --------------------------------------------------

    def approve(self, request):
        """Accept the exact repair binding once.

        Synthetic and disclosed as such. This claims no real authentication, no
        KMS signature, and no human identity.
        """
        if not isinstance(request, dict):
            raise ReplayError(400, "APPROVAL_BINDING_MALFORMED")

        key = request.get("idempotency_key")
        if not isinstance(key, str) or not key:
            raise ReplayError(400, "IDEMPOTENCY_KEY_REQUIRED")

        submitted = {field: request.get(field) for field in BINDING_FIELDS}
        matches = submitted == CANONICAL_BINDING
        # The plan-diff hash is part of the binding, not an optional extra: a
        # missing hash is as unbound as a wrong one, so both are refused.
        if request.get("plan_diff_hash") != CANONICAL_PLAN_DIFF_HASH:
            matches = False

        with self.cond:
            if self.approval is not None:
                prior = self.approval
                # An identical duplicate is idempotent: the original receipt
                # comes back and zero additional events are emitted.
                if prior["idempotency_key"] == key and matches:
                    return {"receipt": copy.deepcopy(prior), "duplicate": True,
                            "state": self.state_locked()}
                if not matches:
                    raise ReplayError(409, "APPROVAL_BINDING_MISMATCH")
                raise ReplayError(409, "APPROVAL_ALREADY_RECORDED")

            if not matches:
                # Zero mutations on an altered binding. The cursor does not move.
                raise ReplayError(409, "APPROVAL_BINDING_MISMATCH")
            if self.cursor != events.HUMAN_GATE_SEQUENCE - 1:
                raise ReplayError(409, "APPROVAL_NOT_PERMITTED_AT_CURSOR")

            receipt = {
                "receipt_id": f"fixture-RCT-approval-{uuid.uuid4().hex[:12]}",
                "idempotency_key": key,
                "plan_diff_hash": CANONICAL_PLAN_DIFF_HASH,
                "actor": dict(events.SYNTHETIC_OPERATOR),
                "recorded_at": _now(),
                "classification": events.CLASSIFICATION,
                "synthetic": True,
                "disclosure": ("Synthetic replay approval. No real "
                               "authentication, KMS signature, or human "
                               "identity is claimed."),
                **copy.deepcopy(CANONICAL_BINDING),
            }
            self.approval = receipt

            # Approval commits event 9 and nothing else. Activation is a
            # separate subsequent commit: autoplay reaches it after the
            # configured interval, and a presenter reaches it with /advance.
            gate = self._commit_locked(events.HUMAN_GATE_SEQUENCE)
            gate["receipt_refs"] = [receipt["receipt_id"]]
            self._emitted[-1]["receipt_refs"] = [receipt["receipt_id"]]
            if self.mode == PAUSED_HUMAN_GATE:
                # Wake the autoplay thread that parked at the gate.
                self.mode = PLAYING
            self.cond.notify_all()
            return {"receipt": copy.deepcopy(receipt), "duplicate": False,
                    "events": [gate], "state": self.state_locked()}

    # -- isolated proof branches --------------------------------------------

    def enter_branch(self, name):
        """Open an isolated proof lens. The canonical cursor does not move."""
        if name not in events.BRANCHES:
            raise ReplayError(404, "UNKNOWN_PROOF_BRANCH")
        with self.cond:
            if self.cursor < events.BRANCH_MIN_SEQUENCE:
                raise ReplayError(409, "PROOF_BRANCH_NOT_AVAILABLE_YET")
            spec = events.BRANCHES[name]
            self.branch = name
            recorded = _now()
            self.branch_events = [
                events.envelope(event, session_id=self.session_id,
                                recorded_at=recorded, authority="ISOLATED",
                                sequence=event.ordinal)
                for event in spec["events"]
            ]
            self.cond.notify_all()
            return {"branch": name, "label": spec["label"],
                    "custody": dict(spec["custody"]),
                    "domain_mutations": spec["domain_mutations"],
                    "evidence_mutations": spec["evidence_mutations"],
                    "events": copy.deepcopy(self.branch_events),
                    "canonical_cursor": self.cursor}

    def exit_branch(self):
        """Return to canonical. Restores the identical pre-branch view."""
        with self.cond:
            self.branch = None
            self.branch_events = []
            self.cond.notify_all()
            return self.state_locked()

    def branch_feed(self):
        with self.cond:
            return copy.deepcopy(self.branch_events)

    def close(self):
        with self.cond:
            self.closed = True
            self.cond.notify_all()


class SessionStore:
    """In-memory registry. Presentation state only; nothing authoritative."""

    def __init__(self):
        self._sessions = {}
        self._lock = threading.Lock()

    def create(self):
        session = ReplaySession()
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id):
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise ReplayError(404, "UNKNOWN_SESSION")
        return session

    def reset(self, session_id):
        """Retire a session and return a brand new one at event 5.

        Reset mints a new opaque id and cannot mutate any other session.
        """
        old = self.get(session_id)
        old.close()
        with self._lock:
            self._sessions.pop(session_id, None)
        return self.create()

    def count(self):
        with self._lock:
            return len(self._sessions)


# -- server-sent events ------------------------------------------------------


def sse_frame(envelope_dict):
    """Render one envelope as an SSE block. The ordinal is the resume id."""
    return (f"id: {envelope_dict['sequence']}\n"
            f"event: replay_event\n"
            f"data: {json.dumps(envelope_dict)}\n\n")


def parse_last_event_id(raw):
    """Decode a canonical resume cursor. Branch ids never resume canonical."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ReplayError(400, "INVALID_LAST_EVENT_ID")
    if value < 0 or value > events.LAST_SEQUENCE:
        raise ReplayError(400, "INVALID_LAST_EVENT_ID")
    return value


# Cadence of the SSE comment heartbeat while a caught-up stream waits. It is a
# deliberate keepalive, not a poll: the wait still returns early on any commit.
KEEPALIVE_SECONDS = 15.0


def stream(session, *, last_event_id=None, max_frames=None, idle_timeout=None,
           keepalive=KEEPALIVE_SECONDS):
    """Yield committed canonical events, resuming strictly after the cursor.

    A caught-up stream stays open indefinitely. It blocks on the session
    condition rather than polling, so it wakes only for a committed event,
    session closure, or the deliberate keepalive.

    `max_frames` and `idle_timeout` are bounded seams for tests, so a test can
    never hang. Neither is used by the server's default stream.
    """
    after = parse_last_event_id(last_event_id) or 0
    sent = 0
    idle_waited = 0.0
    while True:
        with session.cond:
            pending = [f for f in session._emitted if f["sequence"] > after]
            if not pending:
                if session.closed:
                    return
                if max_frames is not None and sent >= max_frames:
                    return
                wait_for = keepalive
                if idle_timeout is not None:
                    wait_for = min(keepalive, max(idle_timeout - idle_waited, 0))
                woke = session.cond.wait(timeout=wait_for)
                if not woke:
                    idle_waited += wait_for
                    # Bounded seam: only a test-supplied idle_timeout ends the
                    # stream. The default path waits forever.
                    if idle_timeout is not None and idle_waited >= idle_timeout:
                        return
                    if session.closed:
                        return
                    yield f": keep-alive {_now()}\n\n"
                    continue
                idle_waited = 0.0
                if session.closed:
                    return
                pending = [f for f in session._emitted if f["sequence"] > after]
                if not pending:
                    continue
            batch = [copy.deepcopy(f) for f in pending]
        for frame in batch:
            yield sse_frame(frame)
            after = frame["sequence"]
            sent += 1
            idle_waited = 0.0
            if max_frames is not None and sent >= max_frames:
                return


def branch_stream(session):
    """Yield the open branch's events on its own ordinal namespace."""
    for frame in session.branch_feed():
        yield sse_frame(frame)
