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
import threading
import uuid
from datetime import datetime, timezone

import events

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

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
                return body
            cursor = self.cursor
        return filter_projection(load_fixture(self._fixture_for(cursor)), cursor)

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
        submitted_hash = request.get("plan_diff_hash")
        if submitted_hash is not None and submitted_hash != CANONICAL_PLAN_DIFF_HASH:
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

            gate = self._commit_locked(events.HUMAN_GATE_SEQUENCE)
            gate["receipt_refs"] = [receipt["receipt_id"]]
            # Approval automatically resumes progression to activation.
            activation = self._commit_locked(events.ACTIVATION_SEQUENCE)
            if self.mode == PAUSED_HUMAN_GATE:
                self.mode = PLAYING
            self.cond.notify_all()
            return {"receipt": copy.deepcopy(receipt), "duplicate": False,
                    "events": [gate, activation], "state": self.state_locked()}

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


def stream(session, *, last_event_id=None, max_frames=None, timeout=None):
    """Yield committed canonical events, resuming strictly after the cursor.

    Blocks on the session condition rather than polling, so a waiting stream
    costs nothing until an event actually commits.
    """
    after = parse_last_event_id(last_event_id) or 0
    sent = 0
    while True:
        with session.cond:
            pending = [f for f in session._emitted if f["sequence"] > after]
            if not pending:
                if session.closed:
                    return
                if max_frames is not None and sent >= max_frames:
                    return
                if not session.cond.wait(timeout=timeout if timeout is not None else 0.25):
                    if timeout is not None:
                        return
                    if max_frames is None:
                        return
                    continue
                pending = [f for f in session._emitted if f["sequence"] > after]
            batch = [copy.deepcopy(f) for f in pending]
        for frame in batch:
            yield sse_frame(frame)
            after = frame["sequence"]
            sent += 1
            if max_frames is not None and sent >= max_frames:
                return


def branch_stream(session):
    """Yield the open branch's events on its own ordinal namespace."""
    for frame in session.branch_feed():
        yield sse_frame(frame)
