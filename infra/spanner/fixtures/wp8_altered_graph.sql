-- WP8 isolated managed-graph audit fixture.
-- Target only: full-shelf-audit-wp6-20260813 (never full-shelf-main).
-- The zero-case movement/order nodes are topology, not current physical positions.

INSERT INTO Tenants (tenant_id, name, created_at)
VALUES ('wp8-altered-audit', 'WP8 Altered Graph Audit', CURRENT_TIMESTAMP());

INSERT INTO Lots
  (tenant_id, lot_id, code, produce_type, hazard_status, total_cases, created_at)
VALUES
  ('wp8-altered-audit', 'ALT-LOT-9001', 'ALT-LOT-9001', 'Altered Audit Produce', 'RECALLED', 51, CURRENT_TIMESTAMP());

INSERT INTO CustodyNodes
  (tenant_id, node_id, node_type, name, on_hand_cases)
VALUES
  ('wp8-altered-audit', 'ALT-WH', 'WAREHOUSE', 'Alternate Hub', 13),
  ('wp8-altered-audit', 'ALT-MOVE-1', 'OPERATIONAL_MOVEMENT', 'Movement 701/702', 0),
  ('wp8-altered-audit', 'ALT-ORDER-701', 'ORDER', 'Order 701', 0),
  ('wp8-altered-audit', 'ALT-ORDER-702', 'ORDER', 'Order 702', 0),
  ('wp8-altered-audit', 'ALT-AGENCY-77', 'AGENCY', 'Agency 77', 17),
  ('wp8-altered-audit', 'ALT-SITE-77', 'DOWNSTREAM_SITE', 'Site 77', 5),
  ('wp8-altered-audit', 'ALT-AGENCY-88', 'AGENCY', 'Agency 88', 9),
  ('wp8-altered-audit', 'ALT-RESCUE', 'DIRECT_RESCUE', 'Rescue 9', 7);

INSERT INTO CustodyEdges
  (tenant_id, edge_id, source_node_id, target_node_id, lot_id, case_count, is_sub_distribution)
VALUES
  ('wp8-altered-audit', 'ALT-E01', 'ALT-WH', 'ALT-MOVE-1', 'ALT-LOT-9001', 31, FALSE),
  ('wp8-altered-audit', 'ALT-E02', 'ALT-MOVE-1', 'ALT-ORDER-701', 'ALT-LOT-9001', 22, FALSE),
  ('wp8-altered-audit', 'ALT-E03', 'ALT-ORDER-701', 'ALT-AGENCY-77', 'ALT-LOT-9001', 22, FALSE),
  ('wp8-altered-audit', 'ALT-E04', 'ALT-AGENCY-77', 'ALT-SITE-77', 'ALT-LOT-9001', 5, TRUE),
  ('wp8-altered-audit', 'ALT-E05', 'ALT-MOVE-1', 'ALT-ORDER-702', 'ALT-LOT-9001', 9, FALSE),
  ('wp8-altered-audit', 'ALT-E06', 'ALT-ORDER-702', 'ALT-AGENCY-88', 'ALT-LOT-9001', 9, FALSE),
  ('wp8-altered-audit', 'ALT-E07', 'ALT-WH', 'ALT-RESCUE', 'ALT-LOT-9001', 7, FALSE);
