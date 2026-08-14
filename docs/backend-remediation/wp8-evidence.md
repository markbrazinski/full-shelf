# WP8 dynamic Spanner Graph evidence

Date: 2026-08-13/14  
Builder status: `WP8 COMPLETE — READY FOR STRATEGY REVIEW`  
Acceptance authority: none. This is builder testimony until a different
auditor independently reproduces it.

## Result

The deployed orchestrator now executes one parameterized variable-depth GQL
shape against the managed `CustodyGraph`. It has no node-table scan or local
graph traversal fallback. An empty result fails with
`GRAPH_TOPOLOGY_NOT_FOUND`; a managed query failure fails with
`AUTHORITATIVE_GRAPH_READ_UNAVAILABLE`.

Evidence classifications:

- Query shape, parameter binding, and no-fallback behavior:
  `STRUCTURALLY_VERIFIED`
- Complete safe suite (118 passed, 0 failed, 18 warnings): `MEASURED`
- Both deployed managed graph executions below: `OBSERVED_LIVE`
- Final WP8 acceptance: `NOT_PROVEN` pending independent reproduction

## Exact build and deployment

- Implementation source:
  `05c2ec6e46c94f4169009115409b37d2dfdb6d33`
- Cloud Build: `c17bc67d-ad33-40a7-9758-5518f6399628`
- Image digest:
  `sha256:472dc8f0d2eb63993b424e47fae23babef11300077345d2fd6ddc6ba7042df71`
- Cloud Run revision: `full-shelf-orchestrator-00037-mpr`, 100% traffic
- Revision source label:
  `full-shelf-source-revision=05c2ec6e46c94f4169009115409b37d2dfdb6d33`

## Reproducible managed query

The application binds both values through the Spanner client `params` and
`param_types` arguments; values are not interpolated into GQL:

```sql
GRAPH CustodyGraph
MATCH (src:Node)-[e:TRANSFERRED_TO
  WHERE e.tenant_id = @tenant_id AND e.lot_id = @lot_id
]->{1,8}(dst:Node)
WHERE src.tenant_id = @tenant_id AND src.node_type = 'WAREHOUSE'
RETURN
  src.node_id AS root_node_id,
  src.node_type AS root_node_type,
  src.name AS root_name,
  src.on_hand_cases AS root_cases,
  dst.node_id AS node_id,
  dst.node_type AS node_type,
  dst.name AS node_name,
  dst.on_hand_cases AS node_cases,
  ARRAY_LENGTH(e) AS path_depth
ORDER BY path_depth, node_id
```

Reproduction uses a judge key read from Secret Manager without printing it:

```bash
audit_key="$(gcloud secrets versions access latest \
  --secret=full-shelf-judge-api-key --project=preflight-hackathon)"
curl -fsS -H "X-Full-Shelf-API-Key: ${audit_key}" \
  'https://full-shelf-orchestrator-620464070103.us-central1.run.app/api/v1/orchestrator/custody/graph?scenario=canonical'
curl -fsS -H "X-Full-Shelf-API-Key: ${audit_key}" \
  'https://full-shelf-orchestrator-620464070103.us-central1.run.app/api/v1/orchestrator/custody/graph?scenario=altered'
```

## Canonical execution

Observed deployed output, sanitized to acceptance fields:

```text
scenario: canonical
lot_id: LTC-4471
unique_current_cases: 96
node_count: 6
max_path_depth: 2
NODE-SITE-01: DOWNSTREAM_SITE, 8 cases, path_depth 2
intermediate_subtotals_readded: false
classification: OBSERVED_LIVE
```

The 96 current cases are the unique managed graph nodes: Warehouse 24,
Truck 2 22, O203 staging 20, Agency 01 10, Site 01 8, and Rescue 12. The O201
historical movement subtotal is not a current-position node and is not added.

## Altered execution

The altered fixture lives only in isolated database
`full-shelf-audit-wp6-20260813`, tenant `wp8-altered-audit`. It uses lot
`ALT-LOT-9001`, orders 701/702, agencies 77/88, different quantities, and four
hops. It does not mutate `full-shelf-main`.

Observed deployed output:

```text
scenario: altered
lot_id: ALT-LOT-9001
unique_current_cases: 51
node_count: 8
max_path_depth: 4
node types: WAREHOUSE, OPERATIONAL_MOVEMENT, ORDER, AGENCY,
            DOWNSTREAM_SITE, DIRECT_RESCUE
classification: OBSERVED_LIVE
```

The 51 result is calculated through the same deployed query path from the
altered managed rows; no canonical quantity or topology is reused.

## Limitations

- This record is builder testimony, not independent acceptance.
- The isolated audit fixture is setup data, not production authority.
- `OBSERVED_LIVE` describes the two executions above only, not future service
  availability.

WP8 COMPLETE — READY FOR STRATEGY REVIEW
