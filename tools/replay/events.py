"""Canonical event graph for the Full Shelf deterministic runtime controller.

Frozen data plus an envelope builder. No I/O, no session state, no Google service
of any kind. The 25 canonical events and the two isolated proof branches come
from docs/strategy/GOLDEN_DEMO_EVENT_CONTRACT.md sections 5 and 6.

Scenario time is America/Los_Angeles. 2026-08-14 is -07:00. The committed
fixtures under fixtures/ were generated with UTC wall-clock stamps, so events map
to a fixture by canonical (hour, minute) rather than by comparing ISO strings.
That deliberate seam is documented in the delivery report.

Everything emitted here is SYNTHETIC_TEST.
"""

import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

SCENARIO_TZ = ZoneInfo("America/Los_Angeles")
SCENARIO_ID = "full-shelf-friday-2026-08-14"
SCHEMA_VERSION = "full-shelf.demo-event.v2"
TENANT = "east-bay-food-bank"
OPERATING_DAY = "2026-08-14"
PLAN_ID = "PLAN-2026-08-14"
FLEET_INC = "INC-2210"
RECALL_INC = "INC-2231"
CLASSIFICATION = "SYNTHETIC_TEST"

# The single interactive human gate, and the first event it unlocks.
HUMAN_GATE_SEQUENCE = 9
ACTIVATION_SEQUENCE = 10
# Session cursor at creation. Events 1-4 preload as immutable history.
INITIAL_CURSOR = 5
# Proof branches begin from the canonical terminal state, never before it.
BRANCH_MIN_SEQUENCE = 22


def T(hh, mm):
    """Scenario wall-clock time on the canonical operating day."""
    return datetime(2026, 8, 14, hh, mm, tzinfo=SCENARIO_TZ)


class CanonicalEvent:
    """One immutable entry in the section 5 event set."""

    __slots__ = ("sequence", "event_id", "event_type", "effective_at",
                 "trigger_class", "actor", "incident_id", "activity",
                 "fixture_key", "receipt_refs")

    def __init__(self, sequence, event_id, event_type, effective_at,
                 trigger_class, actor, incident_id, activity,
                 fixture_key=None, receipt_refs=()):
        self.sequence = sequence
        self.event_id = event_id
        self.event_type = event_type
        self.effective_at = effective_at
        self.trigger_class = trigger_class
        self.actor = actor
        self.incident_id = incident_id
        self.activity = activity
        self.fixture_key = fixture_key
        self.receipt_refs = tuple(receipt_refs)


def _a(severity, headline, detail, action_required=False):
    return {"severity": severity, "headline": headline, "detail": detail,
            "action_required": action_required}


def _actor(kind, ident):
    return {"kind": kind, "id": ident}


SYSTEM = _actor("SYSTEM", "full-shelf.orchestrator")
LEDGER = _actor("SYSTEM", "full-shelf.plan-ledger")
SCHEDULER = _actor("SYSTEM", "full-shelf.scheduler")
POLICY = _actor("SYSTEM", "full-shelf.deterministic-policy")
PROJECTION = _actor("SYSTEM", "full-shelf.projection")
TELEMATICS = _actor("EXTERNAL", "fixture-fleet-telematics")
REGULATOR = _actor("EXTERNAL", "fixture-regulatory-feed")
ARMOR = _actor("SYSTEM", "full-shelf.model-armor")
PARTNER = _actor("EXTERNAL", "fixture-partner-callback")
# Disclosed synthetic principal. Replay never claims a real human identity.
SYNTHETIC_OPERATOR = _actor("HUMAN", "fixture-synthetic-operations-director")

AGENT_INCIDENT_LEAD = _actor("AGENT", "full-shelf.incident-lead.v1")
AGENT_EXTRACTION = _actor("AGENT", "full-shelf.recall-intake-extraction.v2")
AGENT_CUSTODY = _actor("AGENT", "full-shelf.network-custody.v2")
AGENT_FULFILLMENT = _actor("AGENT", "full-shelf.fulfillment-planning-recovery.v2")
AGENT_PARTNER_OPS = _actor("AGENT", "full-shelf.partner-operations.v2")


# Section 5, in order. fixture_key names the committed projection fixture whose
# bounded state this event establishes; None means the event changes no
# projection surface of its own.
CANONICAL_EVENTS = (
    CanonicalEvent(
        1, "FS-E001-PLAN-GENERATION-TRIGGERED", "PLAN_GENERATION_TRIGGERED",
        T(5, 30), "AUTONOMOUS_SCHEDULED", SCHEDULER, None,
        _a("INFO", "Morning plan generation triggered",
           "Candidate generation begins from current constraints.")),
    CanonicalEvent(
        2, "FS-E002-REV07-PROPOSED", "REV07_PROPOSED",
        T(5, 30), "AUTONOMOUS_CHAINED", AGENT_FULFILLMENT, None,
        _a("INFO", "rev07 proposed",
           "Deterministically feasible candidate for five stops and 96 cases.")),
    CanonicalEvent(
        3, "FS-E003-REV07-APPROVED", "REV07_APPROVED",
        T(6, 45), "HUMAN_GATE", SYNTHETIC_OPERATOR, None,
        _a("SUCCESS", "rev07 approved",
           "Exact rev07 candidate approved and bound.")),
    CanonicalEvent(
        4, "FS-E004-REV07-ACTIVATED", "REV07_ACTIVATED",
        T(7, 30), "AUTONOMOUS_CHAINED", LEDGER, None,
        _a("SUCCESS", "rev07 active",
           "Five commitments and manifests are authoritative."),
        receipt_refs=("fixture-RCT-plan:rev07",)),
    CanonicalEvent(
        5, "FS-E005-DAY-OPENED", "DAY_OPENED",
        T(8, 5), "AUTONOMOUS_SCHEDULED", PROJECTION, None,
        _a("INFO", "Friday opened",
           "Five stops, 96 cases, Truck 2 at 36/60."),
        fixture_key="healthy"),
    CanonicalEvent(
        6, "FS-E006-REFRIGERATION-FAILURE-RECEIVED", "REFRIGERATION_FAILURE_RECEIVED",
        T(8, 20), "EXTERNAL_EVENT", TELEMATICS, FLEET_INC,
        _a("CRITICAL", "Truck 1 refrigeration failure",
           "Cold-chain capability unavailable. Not inferred from GPS.",
           action_required=True),
        fixture_key="truckfail",
        receipt_refs=("fixture-RCT-status:SCOPING",)),
    CanonicalEvent(
        7, "FS-E007-FLEET-INCIDENT-SCOPED", "FLEET_INCIDENT_SCOPED",
        T(8, 20), "AUTONOMOUS_CHAINED", AGENT_INCIDENT_LEAD, FLEET_INC,
        _a("ATTENTION", "Incident scoped",
           "Cold-chain loss affects commitments O202 and O203.")),
    CanonicalEvent(
        8, "FS-E008-REV08-REPAIR-PROPOSED", "REV08_REPAIR_PROPOSED",
        T(8, 21), "AUTONOMOUS_CHAINED", AGENT_FULFILLMENT, FLEET_INC,
        _a("ATTENTION", "Repair proposed",
           "O202 (22 cases) to Truck 2; O203 (20 cases) to refrigerated "
           "partner pickup. rev07 remains authoritative.",
           action_required=True),
        fixture_key="review"),
    CanonicalEvent(
        9, "FS-E009-REV08-REPAIR-APPROVED", "REV08_REPAIR_APPROVED",
        T(8, 24), "HUMAN_GATE", SYNTHETIC_OPERATOR, FLEET_INC,
        _a("SUCCESS", "Repair approved",
           "One click approves the exact diff once.")),
    CanonicalEvent(
        10, "FS-E010-REV08-ACTIVATED", "REV08_ACTIVATED",
        T(8, 24), "AUTONOMOUS_CHAINED", LEDGER, FLEET_INC,
        _a("SUCCESS", "rev08 active",
           "Truck 2 at 58/60; O203 partner pickup; INC-2210 resolved."),
        fixture_key="rev08",
        receipt_refs=("fixture-RCT-plan:rev08",)),
    CanonicalEvent(
        11, "FS-E011-RECALL-NOTICE-RECEIVED", "RECALL_NOTICE_RECEIVED",
        T(9, 36), "EXTERNAL_EVENT", REGULATOR, RECALL_INC,
        _a("CRITICAL", "Recall notice received",
           "Representative FDA-format notice for lot LTC-4471.",
           action_required=True),
        fixture_key="recall_received",
        receipt_refs=("fixture-RCT-status:SCOPING",)),
    CanonicalEvent(
        12, "FS-E012-MODEL-ARMOR-PASSED", "MODEL_ARMOR_PASSED",
        T(9, 36), "AUTONOMOUS_CHAINED", ARMOR, RECALL_INC,
        _a("INFO", "Safety screening passed",
           "A pass is not factual sufficiency. Model Armor is not an agent.")),
    CanonicalEvent(
        13, "FS-E013-RECALL-SCOPE-EXTRACTED", "RECALL_SCOPE_EXTRACTED",
        T(10, 4), "AUTONOMOUS_CHAINED", AGENT_EXTRACTION, RECALL_INC,
        _a("ATTENTION", "Recall scope extracted",
           "Lot LTC-4471, E. coli O157:H7. Source-anchored; no invented custody."),
        fixture_key="processing"),
    CanonicalEvent(
        14, "FS-E014-RECALL-RESPONSE-SCOPED", "RECALL_RESPONSE_SCOPED",
        T(10, 4), "AUTONOMOUS_CHAINED", AGENT_INCIDENT_LEAD, RECALL_INC,
        _a("ATTENTION", "Recall response scoped",
           "Governed recall-response playbook selected. INC-2231 scoping.")),
    CanonicalEvent(
        15, "FS-E015-MOVEMENT-BARRIER-ACTIVATED", "MOVEMENT_BARRIER_ACTIVATED",
        T(10, 5), "AUTONOMOUS_CHAINED", POLICY, RECALL_INC,
        _a("CRITICAL", "Movement barrier active",
           "Further movement of LTC-4471 is barred. East Bay Distribution Annex acknowledgment opened."),
        fixture_key="custody",
        receipt_refs=("fixture-RCT-movement-barrier",)),
    CanonicalEvent(
        16, "FS-E016-CONTAINMENT-IN-PROGRESS", "CONTAINMENT_IN_PROGRESS",
        T(10, 6), "AUTONOMOUS_CHAINED", LEDGER, RECALL_INC,
        _a("ATTENTION", "Containment in progress",
           "INC-2231 advances after barrier activation."),
        receipt_refs=("fixture-RCT-status:CONTAINMENT_IN_PROGRESS",)),
    CanonicalEvent(
        17, "FS-E017-REV08-INVALIDATED", "REV08_INVALIDATED",
        T(10, 7), "AUTONOMOUS_CHAINED", POLICY, RECALL_INC,
        _a("CRITICAL", "rev08 invalidated",
           "Active plan is unsafe for the recalled lot. No rev09 is invented."),
        receipt_refs=("fixture-RCT-plan:invalidate",)),
    CanonicalEvent(
        18, "FS-E018-CUSTODY-RECONCILED", "CUSTODY_RECONCILED",
        T(10, 10), "AUTONOMOUS_CHAINED", AGENT_CUSTODY, RECALL_INC,
        _a("ATTENTION", "Custody reconciled",
           "96 unique, 88 confirmed, 8 unconfirmed at East Bay Distribution Annex. No double count.")),
    CanonicalEvent(
        19, "FS-E019-SAFE-RECOVERY-PROPOSED", "SAFE_RECOVERY_PROPOSED",
        T(10, 10), "AUTONOMOUS_CHAINED", AGENT_FULFILLMENT, RECALL_INC,
        _a("ATTENTION", "Safe recovery proposed",
           "18 cases to Berkeley Community Pantry, 22 to Alameda Family Pantry. East Oakland Community Pantry short 20.")),
    CanonicalEvent(
        20, "FS-E020-SAFE-RECOVERY-COMMITTED", "SAFE_RECOVERY_COMMITTED",
        T(10, 10), "AUTONOMOUS_CHAINED", POLICY, RECALL_INC,
        _a("SUCCESS", "Safe recovery committed",
           "Exactly 40 safe replacements. East Oakland Community Pantry shortfall SF-A03 is 20."),
        fixture_key="recovery",
        receipt_refs=("fixture-RCT-safe-recovery",)),
    CanonicalEvent(
        21, "FS-E021-CLOSURE-REFUSED", "CLOSURE_REFUSED",
        T(10, 12), "AUTONOMOUS_CHAINED", POLICY, RECALL_INC,
        _a("REFUSAL", "Closure refused",
           "Eight cases remain unconfirmed. False containment refused with "
           "zero prohibited domain mutations.")),
    CanonicalEvent(
        22, "FS-E022-PARTIALLY-CONTAINED", "PARTIALLY_CONTAINED",
        T(10, 13), "AUTONOMOUS_CHAINED", LEDGER, RECALL_INC,
        _a("ATTENTION", "Partially contained",
           "Terminal canonical Friday state. Custody remains 88/96."),
        fixture_key="refusal"),
    CanonicalEvent(
        23, "FS-E023-DAY-OUTCOME-PUBLISHED", "DAY_OUTCOME_PUBLISHED",
        T(16, 30), "AUTONOMOUS_SCHEDULED", PROJECTION, RECALL_INC,
        _a("INFO", "Friday outcome published",
           "88/96 confirmed, 40 recovered, 20 short, East Bay Distribution Annex open."),
        fixture_key="outcome"),
    CanonicalEvent(
        24, "FS-E024-SATURDAY-DRAFT-PROPOSED", "SATURDAY_DRAFT_PROPOSED",
        T(17, 0), "AUTONOMOUS_SCHEDULED", AGENT_FULFILLMENT, RECALL_INC,
        _a("ATTENTION", "Saturday draft proposed",
           "Saturday rev01 stored DRAFT_WITH_CONSTRAINTS. No activation control."),
        fixture_key="tomorrow"),
    CanonicalEvent(
        25, "FS-E025-OBLIGATIONS-CARRIED-FORWARD", "OBLIGATIONS_CARRIED_FORWARD",
        T(17, 0), "AUTONOMOUS_CHAINED", PROJECTION, RECALL_INC,
        _a("ATTENTION", "Obligations carried forward",
           "LTC-4471 barrier, East Oakland Community Pantry short 20, East Bay Distribution Annex acknowledgment, "
           "and the unresolved incident.")),
)

BY_SEQUENCE = {event.sequence: event for event in CANONICAL_EVENTS}
FIRST_SEQUENCE = CANONICAL_EVENTS[0].sequence
LAST_SEQUENCE = CANONICAL_EVENTS[-1].sequence


class BranchEvent:
    """One entry in a section 6 isolated proof branch."""

    __slots__ = ("ordinal", "event_id", "event_type", "effective_at",
                 "actor", "activity", "validation")

    def __init__(self, ordinal, event_id, event_type, effective_at, actor,
                 activity, validation):
        self.ordinal = ordinal
        self.event_id = event_id
        self.event_type = event_type
        self.effective_at = effective_at
        self.actor = actor
        self.activity = activity
        self.validation = validation


_ACCEPTED = {"status": "ACCEPTED", "reasons": []}

# Section 6.1 and 6.2. Both branches begin from canonical event 22 and neither
# advances the canonical cursor.
BRANCHES = {
    "vague": {
        "fixture_key": "partner_vague",
        "label": "ISOLATED SELECTED PROOF",
        "custody": {"unique": 96, "confirmed": 88, "unconfirmed": 8},
        "domain_mutations": 0,
        "evidence_mutations": 1,
        "events": (
            BranchEvent("b1", "FS-PV1-PARTNER-CALLBACK-RECEIVED",
                        "PARTNER_CALLBACK_RECEIVED", T(10, 15), PARTNER,
                        _a("INFO", "Partner callback received",
                           "Authenticated partner callback accepted in an "
                           "isolated authority."), _ACCEPTED),
            BranchEvent("b2", "FS-PV2-MODEL-ARMOR-PASSED", "MODEL_ARMOR_PASSED",
                        T(10, 15), ARMOR,
                        _a("INFO", "Safety screening passed",
                           "No factual sufficiency implied."), _ACCEPTED),
            BranchEvent("b3", "FS-PV3-PARTNER-EVIDENCE-PROPOSED",
                        "PARTNER_EVIDENCE_PROPOSED", T(10, 16), AGENT_PARTNER_OPS,
                        _a("ATTENTION", "Partner evidence proposed",
                           "Intent understood, but lot, quantity, location, and "
                           "qualifying disposition remain unsupported."), _ACCEPTED),
            BranchEvent("b4", "FS-PV4-PARTNER-EVIDENCE-DENIED",
                        "PARTNER_EVIDENCE_DENIED", T(10, 16), POLICY,
                        _a("REFUSAL", "Partner evidence denied",
                           "DENIED. Domain mutations 0, evidence mutations 1. "
                           "Custody remains 88/96 and the WorkItem stays open."),
                        {"status": "DENIED",
                         "reasons": ["INSUFFICIENT_PARTNER_EVIDENCE"]}),
        ),
    },
    "complete": {
        "fixture_key": "partner_complete",
        "label": "ISOLATED SELECTED PROOF",
        "custody": {"unique": 96, "confirmed": 96, "unconfirmed": 0},
        "domain_mutations": 2,
        "evidence_mutations": 1,
        "events": (
            BranchEvent("b1", "FS-PC1-PARTNER-CALLBACK-RECEIVED",
                        "PARTNER_CALLBACK_RECEIVED", T(10, 18), PARTNER,
                        _a("INFO", "Partner callback received",
                           "Authenticated partner callback accepted in an "
                           "isolated authority."), _ACCEPTED),
            BranchEvent("b2", "FS-PC2-MODEL-ARMOR-PASSED", "MODEL_ARMOR_PASSED",
                        T(10, 18), ARMOR,
                        _a("INFO", "Safety screening passed",
                           "No factual sufficiency implied."), _ACCEPTED),
            BranchEvent("b3", "FS-PC3-PARTNER-EVIDENCE-PROPOSED",
                        "PARTNER_EVIDENCE_PROPOSED", T(10, 19), AGENT_PARTNER_OPS,
                        _a("ATTENTION", "Partner evidence proposed",
                           "Literal lot, quantity, location, disposition, and "
                           "confirmation time support the open obligation."), _ACCEPTED),
            BranchEvent("b4", "FS-PC4-PARTNER-EVIDENCE-APPLIED",
                        "PARTNER_EVIDENCE_APPLIED", T(10, 19), POLICY,
                        _a("SUCCESS", "Partner evidence applied in isolation",
                           "APPLIED in isolated authority. Domain mutations 2, "
                           "evidence mutations 1. Branch custody 96/96. Canonical "
                           "Friday history remains 88/96."),
                        {"status": "ACCEPTED", "reasons": []}),
        ),
    },
}


# Cursor gates for projection filtering. A field is removed outright until the
# canonical event that establishes it has committed.
REV08_SEQUENCE = 10
RECALL_SEQUENCE = 11
CUSTODY_SEQUENCE = 18
RECOVERY_SEQUENCE = 20
TERMINAL_SEQUENCE = 22
SATURDAY_SEQUENCE = 24


def plan_diff_hash(binding):
    """Deterministic hash over the bound repair diff."""
    canonical = json.dumps(binding, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def envelope(event, *, session_id, recorded_at, authority="CANONICAL",
             sequence=None, validation=None, payload=None,
             projection_delta=None, receipt_refs=None, source_refs=()):
    """Build a section 3 event envelope."""
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "scenario_id": SCENARIO_ID,
        "session_id": session_id,
        "sequence": sequence if sequence is not None else event.sequence,
        "effective_at": event.effective_at.isoformat(),
        "recorded_at": recorded_at,
        "trigger_class": getattr(event, "trigger_class", "ISOLATED_PROOF"),
        "authority": authority,
        "actor": dict(event.actor),
        "correlation": {
            "tenant_id": TENANT,
            "operating_day": OPERATING_DAY,
            "plan_id": PLAN_ID,
            "incident_id": getattr(event, "incident_id", None),
            "source_event_id": None,
            "agent_run_id": None,
        },
        # Identifiers only. Raw partner and recall source text never crosses SSE.
        "source_refs": list(source_refs),
        "payload": dict(payload or {}),
        "validation": dict(validation or getattr(event, "validation", None)
                           or _ACCEPTED),
        "receipt_refs": list(receipt_refs if receipt_refs is not None
                             else getattr(event, "receipt_refs", ())),
        "projection_delta": dict(projection_delta or {}),
        "activity_entry": dict(event.activity),
        "evidence_classification": CLASSIFICATION,
    }
