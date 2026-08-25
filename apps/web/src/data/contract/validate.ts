// =====================================================================
// Full Shelf — runtime validation of the projection transport
// ---------------------------------------------------------------------
// This is a trust boundary: the response is untrusted input even from
// localhost replay. We assert the required contract v2 skeleton and the
// TYPE of every field the normalizer dereferences, then hand back a
// typed RawProjection.
//
// ponytail: hand-written structural checks, no ajv/zod. The contract has
// one shape and one consumer; a schema-validator dependency would be
// ~100x the bytes of the ~40 assertions actually needed. Swap in ajv +
// the real ui_projection.json if the contract grows variants/oneOf.
// =====================================================================

import type { RawProjection } from "./transport";

export class ContractViolation extends Error {
  constructor(public readonly path: string, detail: string) {
    super(`Malformed projection at \`${path}\`: ${detail}`);
    this.name = "ContractViolation";
  }
}

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

function obj(v: unknown, path: string): Record<string, unknown> {
  if (!isObj(v)) throw new ContractViolation(path, `expected object, got ${v === null ? "null" : typeof v}`);
  return v;
}

function arr(v: unknown, path: string): unknown[] {
  if (!Array.isArray(v)) throw new ContractViolation(path, `expected array, got ${v === null ? "null" : typeof v}`);
  return v;
}

function str(v: unknown, path: string): string {
  if (typeof v !== "string") throw new ContractViolation(path, `expected string, got ${v === null ? "null" : typeof v}`);
  return v;
}

function num(v: unknown, path: string): number {
  if (typeof v !== "number" || Number.isNaN(v)) throw new ContractViolation(path, `expected number, got ${v === null ? "null" : typeof v}`);
  return v;
}

/** Present-but-nullable. Absent is a violation; null is legitimate. */
function nullableStr(o: Record<string, unknown>, key: string, path: string): void {
  if (!(key in o)) throw new ContractViolation(`${path}.${key}`, "required field absent");
  const v = o[key];
  if (v !== null && typeof v !== "string") throw new ContractViolation(`${path}.${key}`, `expected string or null, got ${typeof v}`);
}

function nullableNum(o: Record<string, unknown>, key: string, path: string): void {
  if (!(key in o)) throw new ContractViolation(`${path}.${key}`, "required field absent");
  const v = o[key];
  if (v !== null && typeof v !== "number") throw new ContractViolation(`${path}.${key}`, `expected number or null, got ${typeof v}`);
}

const TOP_LEVEL_REQUIRED = [
  "tenant_id",
  "operating_day",
  "authority_scope",
  "verified_principal_subject",
  "classification",
  "projection_boundary",
  "current_day",
  "agent_activity_as_of",
  "execution_evidence_as_of",
  "carry_forward_obligations",
  "recall_intake_as_of",
  "partner_evidence_as_of",
] as const;

/**
 * Validate a decoded JSON body against contract v2 and narrow it to
 * RawProjection. Throws ContractViolation on the first breach.
 */
export function validateProjection(body: unknown): RawProjection {
  const root = obj(body, "$");

  for (const key of TOP_LEVEL_REQUIRED) {
    if (!(key in root)) throw new ContractViolation(`$.${key}`, "required field absent");
  }

  str(root.tenant_id, "$.tenant_id");
  str(root.operating_day, "$.operating_day");
  str(root.classification, "$.classification");
  str(root.authority_scope, "$.authority_scope");
  str(root.verified_principal_subject, "$.verified_principal_subject");
  arr(root.partner_evidence_as_of, "$.partner_evidence_as_of").forEach((entry, i) => {
    const p = `$.partner_evidence_as_of[${i}]`;
    const o = obj(entry, p);
    for (const key of [
      "source_event_id", "event_type", "incident_id", "authoritative_partner_id",
      "source_occurred_at", "received_at", "committed_at", "original_response",
      "decision",
    ]) str(o[key], `${p}.${key}`);
    const principal = obj(o.callback_principal, `${p}.callback_principal`);
    for (const key of ["subject", "email", "audience", "issuer", "provenance"])
      str(principal[key], `${p}.callback_principal.${key}`);
    arr(o.policy_reasons, `${p}.policy_reasons`).forEach((reason, j) =>
      str(reason, `${p}.policy_reasons[${j}]`));
    obj(o.claim_verification, `${p}.claim_verification`);
    obj(o.before_after, `${p}.before_after`);
    obj(o.agent, `${p}.agent`);
    obj(o.custody, `${p}.custody`);
    if (o.receipt !== null) {
      const receipt = obj(o.receipt, `${p}.receipt`);
      str(receipt.receipt_id, `${p}.receipt.receipt_id`);
      str(receipt.status, `${p}.receipt.status`);
      num(receipt.domain_mutations_applied, `${p}.receipt.domain_mutations_applied`);
      num(receipt.evidence_mutations_applied, `${p}.receipt.evidence_mutations_applied`);
    }
  });

  // ---- projection_boundary: the as_of contract the whole UI hangs on ----
  const pb = obj(root.projection_boundary, "$.projection_boundary");
  str(pb.as_of, "$.projection_boundary.as_of");
  str(pb.mode, "$.projection_boundary.mode");
  arr(pb.omitted_fields, "$.projection_boundary.omitted_fields").forEach((f, i) => {
    const o = obj(f, `$.projection_boundary.omitted_fields[${i}]`);
    str(o.field, `$.projection_boundary.omitted_fields[${i}].field`);
    str(o.reason, `$.projection_boundary.omitted_fields[${i}].reason`);
  });

  // ---- current_day ----
  const cd = obj(root.current_day, "$.current_day");
  str(cd.plan_id, "$.current_day.plan_id");
  nullableStr(cd, "active_plan_revision", "$.current_day");

  arr(cd.plan_revisions, "$.current_day.plan_revisions").forEach((r, i) => {
    const o = obj(r, `$.current_day.plan_revisions[${i}]`);
    str(o.plan_id, `$.current_day.plan_revisions[${i}].plan_id`);
    str(o.revision, `$.current_day.plan_revisions[${i}].revision`);
    str(o.status, `$.current_day.plan_revisions[${i}].status`);
  });

  arr(cd.commitments, "$.current_day.commitments").forEach((c, i) => {
    const p = `$.current_day.commitments[${i}]`;
    const o = obj(c, p);
    str(o.revision, `${p}.revision`);
    str(o.order_id, `${p}.order_id`);
    nullableStr(o, "agency", p);
    nullableNum(o, "cases", p);
    nullableStr(o, "lot_id", p);
    nullableStr(o, "vehicle", p);
    nullableStr(o, "status", p);
  });

  arr(cd.approvals, "$.current_day.approvals").forEach((a, i) => {
    const p = `$.current_day.approvals[${i}]`;
    const o = obj(a, p);
    str(o.approval_id, `${p}.approval_id`);
    str(o.verified_at, `${p}.verified_at`);
    str(o.state, `${p}.state`);
    str(o.approver_identity_class, `${p}.approver_identity_class`);
    nullableStr(o, "plan_id", p);
    nullableStr(o, "source_revision", p);
    nullableStr(o, "proposed_revision", p);
    nullableStr(o, "plan_diff_hash", p);
    nullableStr(o, "kms_key_version", p);
    // A signature must never reach the browser. Fail loudly if one appears.
    if ("kms_signature" in o || "signature" in o) {
      throw new ContractViolation(p, "signature material must never be transported");
    }
    arr(o.plan_diff, `${p}.plan_diff`).forEach((d, j) => {
      const dp = `${p}.plan_diff[${j}]`;
      const dd = obj(d, dp);
      str(dd.change_type, `${dp}.change_type`);
      nullableStr(dd, "order_id", dp);
      nullableNum(dd, "cases", dp);
      nullableStr(dd, "target_vehicle", dp);
    });
  });

  arr(cd.incidents, "$.current_day.incidents").forEach((inc, i) => {
    const p = `$.current_day.incidents[${i}]`;
    const o = obj(inc, p);
    str(o.incident_id, `${p}.incident_id`);
    str(o.status, `${p}.status`);
    str(o.terminal_state, `${p}.terminal_state`);
    nullableStr(o, "incident_type", p);
    nullableStr(o, "affected_lot_id", p);
    if (o.model_armor_screening !== null) {
      const ma = obj(o.model_armor_screening, `${p}.model_armor_screening`);
      str(ma.result, `${p}.model_armor_screening.result`);
    }
    if (o.refusal !== null) {
      const rf = obj(o.refusal, `${p}.refusal`);
      str(rf.decision, `${p}.refusal.decision`);
      num(rf.mutations_applied, `${p}.refusal.mutations_applied`);
      str(rf.receipt_id, `${p}.refusal.receipt_id`);
      str(rf.committed_at, `${p}.refusal.committed_at`);
    }
  });

  const rec = obj(cd.recovery, "$.current_day.recovery");
  arr(rec.allocations, "$.current_day.recovery.allocations");
  arr(rec.shortfalls, "$.current_day.recovery.shortfalls");
  if (rec.explanation !== null) {
    const e = obj(rec.explanation, "$.current_day.recovery.explanation");
    const p = "$.current_day.recovery.explanation";
    str(e.basis, `${p}.basis`);
    str(e.statement, `${p}.statement`);
    num(e.cases_requested, `${p}.cases_requested`);
    num(e.cases_allocated, `${p}.cases_allocated`);
    num(e.cases_short, `${p}.cases_short`);
    num(e.agencies_allocated, `${p}.agencies_allocated`);
    num(e.agencies_short, `${p}.agencies_short`);
    nullableStr(e, "persisted_agent_rationale", p);
  }

  if (cd.dispatch !== null && cd.dispatch !== undefined) {
    const d = obj(cd.dispatch, "$.current_day.dispatch");
    nullableStr(d, "plan_id", "$.current_day.dispatch");
    nullableStr(d, "revision", "$.current_day.dispatch");
    arr(d.vehicles, "$.current_day.dispatch.vehicles").forEach((v, i) => {
      const p = `$.current_day.dispatch.vehicles[${i}]`;
      const o = obj(v, p);
      str(o.vehicle_id, `${p}.vehicle_id`);
      num(o.stop_count, `${p}.stop_count`);
      nullableStr(o, "name", p);
      // Capacity is legitimately unknown at rev07 — null must survive.
      nullableNum(o, "capacity_cases", p);
      nullableNum(o, "assigned_cases", p);
      nullableNum(o, "remaining_cases", p);
      arr(o.stops, `${p}.stops`).forEach((s, j) => {
        const sp = `${p}.stops[${j}]`;
        const so = obj(s, sp);
        str(so.order_id, `${sp}.order_id`);
        str(so.assignment_type, `${sp}.assignment_type`);
        nullableNum(so, "cases", sp);
      });
      // No coordinate, bearing, or position may ride on a vehicle.
      for (const banned of ["lat", "lng", "latitude", "longitude", "heading", "bearing", "last_reported_at", "current_position"]) {
        if (banned in o) throw new ContractViolation(p, `positional field \`${banned}\` is not part of the contract`);
      }
    });
    arr(d.partner_pickups, "$.current_day.dispatch.partner_pickups").forEach((pp, i) => {
      const p = `$.current_day.dispatch.partner_pickups[${i}]`;
      const o = obj(pp, p);
      str(o.order_id, `${p}.order_id`);
      str(o.assignment_type, `${p}.assignment_type`);
      nullableNum(o, "cases", p);
    });
  }

  // ---- agent_activity_as_of: null before its first safe boundary ----
  if (root.agent_activity_as_of !== null) {
    const aa = obj(root.agent_activity_as_of, "$.agent_activity_as_of");
    str(aa.topology, "$.agent_activity_as_of.topology");
    str(aa.committed_at, "$.agent_activity_as_of.committed_at");
    arr(aa.delegation_trace, "$.agent_activity_as_of.delegation_trace");
    arr(aa.governed_sequence, "$.agent_activity_as_of.governed_sequence");
    arr(aa.agents, "$.agent_activity_as_of.agents").forEach((a, i) => {
      const p = `$.agent_activity_as_of.agents[${i}]`;
      const o = obj(a, p);
      str(o.agent_id, `${p}.agent_id`);
      str(o.display_name, `${p}.display_name`);
      str(o.role, `${p}.role`);
      const state = str(o.state, `${p}.state`);
      // Running/Waiting are unsupported by a synchronous runtime.
      if (state === "RUNNING" || state === "WAITING") {
        throw new ContractViolation(`${p}.state`, `unsupported transient state \`${state}\``);
      }
      arr(o.declared_tools, `${p}.declared_tools`);
      arr(o.tool_invocations, `${p}.tool_invocations`);
    });
  }

  // ---- execution_evidence_as_of ----
  const ee = obj(root.execution_evidence_as_of, "$.execution_evidence_as_of");
  num(ee.receipts_committed, "$.execution_evidence_as_of.receipts_committed");
  arr(ee.history, "$.execution_evidence_as_of.history").forEach((h, i) => {
    const p = `$.execution_evidence_as_of.history[${i}]`;
    const o = obj(h, p);
    str(o.receipt_id, `${p}.receipt_id`);
    str(o.action_id, `${p}.action_id`);
    str(o.action_type, `${p}.action_type`);
    str(o.status, `${p}.status`);
    str(o.committed_at, `${p}.committed_at`);
    nullableNum(o, "mutations_applied", p);
  });
  if (ee.custody_graph !== null) {
    const cg = obj(ee.custody_graph, "$.execution_evidence_as_of.custody_graph");
    const p = "$.execution_evidence_as_of.custody_graph";
    num(cg.unique_current_cases, `${p}.unique_current_cases`);
    num(cg.confirmed_cases, `${p}.confirmed_cases`);
    num(cg.unconfirmed_cases, `${p}.unconfirmed_cases`);
    num(cg.node_count, `${p}.node_count`);
    str(cg.lot_id, `${p}.lot_id`);
    arr(cg.edges, `${p}.edges`);
    arr(cg.current_positions, `${p}.current_positions`).forEach((n, i) => {
      const np = `${p}.current_positions[${i}]`;
      const no = obj(n, np);
      str(no.node_id, `${np}.node_id`);
      str(no.name, `${np}.name`);
      str(no.acknowledgment_status, `${np}.acknowledgment_status`);
      num(no.on_hand_cases, `${np}.on_hand_cases`);
    });
  }

  // ---- recall_intake_as_of: null before the notice is received ----
  if (root.recall_intake_as_of !== null) {
    const ri = obj(root.recall_intake_as_of, "$.recall_intake_as_of");
    str(ri.incident_id, "$.recall_intake_as_of.incident_id");
    arr(ri.steps, "$.recall_intake_as_of.steps").forEach((s, i) => {
      const p = `$.recall_intake_as_of.steps[${i}]`;
      const o = obj(s, p);
      str(o.step, `${p}.step`);
      str(o.state, `${p}.state`);
    });
  }

  arr(root.carry_forward_obligations, "$.carry_forward_obligations").forEach((c, i) => {
    const p = `$.carry_forward_obligations[${i}]`;
    const o = obj(c, p);
    str(o.kind, `${p}.kind`);
    str(o.reference_id, `${p}.reference_id`);
  });

  if (root.next_day_draft !== undefined && root.next_day_draft !== null) {
    const nd = obj(root.next_day_draft, "$.next_day_draft");
    str(nd.plan_id, "$.next_day_draft.plan_id");
    str(nd.revision, "$.next_day_draft.revision");
    str(nd.status, "$.next_day_draft.status");
    if (typeof nd.approval_required !== "boolean") {
      throw new ContractViolation("$.next_day_draft.approval_required", "expected boolean");
    }
  }

  return body as RawProjection;
}
