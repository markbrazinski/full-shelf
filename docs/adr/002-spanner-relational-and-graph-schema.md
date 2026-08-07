# ADR 002: Spanner Relational & Spanner Graph Custody Representation

## Context
Food-bank distribution requires managing relational tables (plans, allocations, orders, vehicles) alongside complex chain-of-custody movements across warehouses, transit vehicles, staging areas, partner agencies, and sub-distributed recipient sites.

## Decision
We utilize Google Cloud Spanner Enterprise, combining relational schemas with Spanner Graph on the same underlying database engine:
1. Relational schema models structured plan revisions, vehicle assignments, order status, and lot inventory.
2. Spanner Graph defines node labels (`Facility`, `Vehicle`, `StagingArea`, `Agency`, `SubSite`, `Recipient`) and edge labels (`TRANSIT_TO`, `DELIVERED_TO`, `SUB_DISTRIBUTED_TO`, `RESCUED_TO`).
3. Custody traversal query reconciles exact physical inventory (96 unique cases of `LOT-RECALL-88` / `LTC-4471`) without double-counting when cases move from Agency 01 to Sub-site 01.

## Consequences
- Single authoritative datastore for operational transactions and graph custody.
- Variable-depth graph traversal enables immediate lineage tracing during recall events.
