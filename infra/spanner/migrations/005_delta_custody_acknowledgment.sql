-- Add authoritative downstream acknowledgment state used by the generalized
-- recall policy. Existing historical rows remain nullable; every operating
-- plan created by this candidate supplies an explicit value.
ALTER TABLE CustodyNodes ADD COLUMN acknowledgment_status STRING(32);

CREATE OR REPLACE PROPERTY GRAPH CustodyGraph
  NODE TABLES (
    CustodyNodes
      KEY (tenant_id, node_id)
      LABEL Node
      PROPERTIES (tenant_id, node_id, node_type, name, on_hand_cases, acknowledgment_status)
  )
  EDGE TABLES (
    CustodyEdges
      KEY (tenant_id, edge_id)
      SOURCE KEY (tenant_id, source_node_id) REFERENCES CustodyNodes (tenant_id, node_id)
      DESTINATION KEY (tenant_id, target_node_id) REFERENCES CustodyNodes (tenant_id, node_id)
      LABEL TRANSFERRED_TO
      PROPERTIES (tenant_id, edge_id, lot_id, case_count, is_sub_distribution)
  );
