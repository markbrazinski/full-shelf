# WP9 event-backed SSE evidence

Date: 2026-08-13/14  
Builder status: `WP9 COMPLETE — READY FOR STRATEGY REVIEW`  
Acceptance authority: none. This is builder testimony until a different
auditor independently reproduces it.

## Result

`/api/v1/projections/stream` is now a durable live tail of committed Spanner
`Receipts`, ordered by `(timestamp, receipt_id)`. The connection stays open,
polls for later commits, emits keep-alives, stops on disconnect, and emits a
truthfully classified terminal error rather than silently treating a managed
read failure as an empty stream.

It does not read `/api/v1/projections/demo-beats` or any static demo array.

Evidence classifications:

- Cursor encoding, ordered query, disconnect, error, and no-duplicate tests:
  `STRUCTURALLY_VERIFIED`
- Complete safe suite (123 passed, 0 failed, 18 warnings): `MEASURED`
- Deployed live commit and reconnect observations: `OBSERVED_LIVE`
- Final WP9 acceptance: `NOT_PROVEN` pending independent reproduction

## Exact build and deployment

- Implementation source:
  `1a3ace8062a88faf93c8c8c8966c8569b48422e5`
- Cloud Build: `fe41b4c9-5768-4fe2-aab0-95186c15b8ed`
- Image digest:
  `sha256:6694df648962ae629114f30e8f63644afb7e7cd7194fba3bf714305b63d5838f`
- Cloud Run revision: `full-shelf-orchestrator-00038-s85`, 100% traffic
- Revision source label:
  `full-shelf-source-revision=1a3ace8062a88faf93c8c8c8966c8569b48422e5`

## Durable cursor contract

Each event ID has version `r1` and URL-safe base64 JSON containing the
authoritative UTC commit timestamp and receipt ID. Resume queries use:

```sql
AND (
  timestamp > @cursor_timestamp
  OR (timestamp = @cursor_timestamp AND receipt_id > @cursor_receipt_id)
)
ORDER BY timestamp ASC, receipt_id ASC
```

Malformed or legacy ambiguous cursors fail HTTP 400 before streaming. A valid
`Last-Event-ID` resumes strictly after the named event.

## Same-connection live observation

One deployed connection remained open after reaching the prior tail. The
deployed orchestrator then made decision
`site01-d69b9328ebc03ee3673070eeced6ae5c`; its managed Cloud Task callback
committed receipt `RCT-B98C0B3C40844BDCB1084F9B` at
`2026-08-14T02:33:46.068180Z`.

Without reconnecting, that already-open stream emitted at
`2026-08-14T02:33:46.418720Z`:

```text
event: projection_update
event_id: r1.WyIyMDI2LTA4LTE0VDAyOjMzOjQ2LjA2ODE4MCswMDowMCIsIlJDVC1COThDMEIzQzQwODQ0QkRDQjEwODRGOUIiXQ
receipt_id: RCT-B98C0B3C40844BDCB1084F9B
action_id: CMD-SITE01-site01-d69b9328ebc03ee3673070eeced6ae5c
status: SUCCESS
classification: OBSERVED_LIVE
```

## Disconnect/reconnect observation

A new connection supplied the exact event ID above as `Last-Event-ID`. It did
not emit `RCT-B98C0B3C40844BDCB1084F9B` again. A second deployed decision,
`site01-da1def577ef276b08d97957ab9599c68`, committed authoritative receipt
`RCT-208D1843F053D04DD4612FB7` at `2026-08-14T02:34:16.640968Z`.

The reconnected stream emitted exactly that next event:

```text
event: projection_update
event_id: r1.WyIyMDI2LTA4LTE0VDAyOjM0OjE2LjY0MDk2OCswMDowMCIsIlJDVC0yMDhEMTg0M0YwNTNEMDRERDQ2MTJGQjciXQ
receipt_id: RCT-208D1843F053D04DD4612FB7
action_id: CMD-SITE01-site01-da1def577ef276b08d97957ab9599c68
status: SUCCESS
classification: OBSERVED_LIVE
```

Direct Spanner queries independently returned both receipt IDs, action IDs,
success statuses, commit timestamps, and two mutations each.

## Reproduction outline

1. Connect with `curl -sS -N` to `/api/v1/projections/stream`.
2. Allow the stream to reach its tail and remain connected.
3. Commit one authorized ledger action through the deployed orchestrator.
4. Observe its receipt on the same connection.
5. Disconnect and reconnect with that exact event ID in `Last-Event-ID`.
6. Commit another authorized action and confirm only the next receipt appears.
7. Query `Receipts` directly by both action IDs.

## Limitations

- This is builder testimony, not independent acceptance.
- The two fresh receipts used the already-authorized Site 01 acknowledgment
  hold path; they did not change the locked terminal truth.
- `OBSERVED_LIVE` applies to these executions and does not promise future
  service availability.

WP9 COMPLETE — READY FOR STRATEGY REVIEW
