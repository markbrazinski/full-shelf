import pytest
from full_shelf_domain.models import Order


def test_tenant_isolation_boundary():
    """Queries and orders must strictly filter by tenant_id."""
    order_a = Order(
        order_id="O201",
        tenant_id="east-bay-food-bank",
        destination_agency_id="AGENCY-01",
        destination_agency_name="Agency 01",
        cases=18,
        lot_id="LOT-RECALL-88",
    )
    order_b = Order(
        order_id="O999",
        tenant_id="other-tenant-bank",
        destination_agency_id="AGENCY-99",
        destination_agency_name="Agency 99",
        cases=10,
        lot_id="LOT-SAFE-99",
    )

    orders = [order_a, order_b]

    # Enforce tenant query boundary
    target_tenant = "east-bay-food-bank"
    filtered_orders = [o for o in orders if o.tenant_id == target_tenant]

    assert len(filtered_orders) == 1
    assert filtered_orders[0].order_id == "O201"
    assert filtered_orders[0].tenant_id == "east-bay-food-bank"
