import pytest
from full_shelf_domain.models import Vehicle, Order
from full_shelf_domain.capacity import check_vehicle_capacity


def test_truck_capacity_feasible_reroute():
    """Truck 2 initial load = 36 cases (O204: 15, O205: 21). Capacity = 60. Adding O202 (22 cases) = 58 <= 60 (FEASIBLE)."""
    truck2 = Vehicle(vehicle_id="TRUCK-02", name="Refrigerated Truck 2", max_capacity_cases=60)
    existing_orders = [
        Order(order_id="O204", destination_agency_id="AGENCY-04", destination_agency_name="Agency 04", cases=15, lot_id="LTC-5090"),
        Order(order_id="O205", destination_agency_id="AGENCY-05", destination_agency_name="Agency 05", cases=21, lot_id="LTC-5090"),
    ]
    reroute_order_202 = [
        Order(order_id="O202", destination_agency_id="AGENCY-02", destination_agency_name="Agency 02", cases=22, lot_id="LTC-4471"),
    ]

    res = check_vehicle_capacity(truck2, existing_orders, reroute_order_202)
    assert res.is_feasible is True
    assert res.proposed_load == 58


def test_truck_capacity_infeasible_both_orders():
    """Truck 2 initial load = 36 cases. Proposing O202 (22 cases) + O203 (20 cases) = 78 > 60 (INFEASIBLE)."""
    truck2 = Vehicle(vehicle_id="TRUCK-02", name="Refrigerated Truck 2", max_capacity_cases=60)
    existing_orders = [
        Order(order_id="O204", destination_agency_id="AGENCY-04", destination_agency_name="Agency 04", cases=15, lot_id="LTC-5090"),
        Order(order_id="O205", destination_agency_id="AGENCY-05", destination_agency_name="Agency 05", cases=21, lot_id="LTC-5090"),
    ]
    both_orders = [
        Order(order_id="O202", destination_agency_id="AGENCY-02", destination_agency_name="Agency 02", cases=22, lot_id="LTC-4471"),
        Order(order_id="O203", destination_agency_id="AGENCY-03", destination_agency_name="Agency 03", cases=20, lot_id="LTC-4471"),
    ]

    res = check_vehicle_capacity(truck2, existing_orders, both_orders)
    assert res.is_feasible is False
    assert res.proposed_load == 78
    assert "exceeds max capacity limit of 60 cases" in res.reason
