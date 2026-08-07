from typing import List, Tuple
from .models import Vehicle, Order


class CapacityCheckResult:
    def __init__(self, is_feasible: bool, vehicle_id: str, existing_load: int, proposed_load: int, capacity_limit: int, reason: str):
        self.is_feasible = is_feasible
        self.vehicle_id = vehicle_id
        self.existing_load = existing_load
        self.proposed_load = proposed_load
        self.capacity_limit = capacity_limit
        self.reason = reason


def check_vehicle_capacity(vehicle: Vehicle, existing_orders: List[Order], proposed_orders: List[Order]) -> CapacityCheckResult:
    """
    Evaluates truck case capacity limit deterministically.
    
    Example:
      Truck 2 has 36 cases assigned (O204: 15, O205: 21). Max capacity = 60.
      If O202 (22 cases) and O203 (20 cases) are proposed:
      36 + 22 + 20 = 78 cases > 60 case capacity limit.
      Returns CapacityCheckResult(is_feasible=False, ...).
    """
    existing_sum = sum(o.cases for o in existing_orders)
    proposed_sum = sum(o.cases for o in proposed_orders)
    total_load = existing_sum + proposed_sum

    if total_load > vehicle.max_capacity_cases:
        reason = (
            f"Capacity check failed for vehicle {vehicle.vehicle_id} ({vehicle.name}): "
            f"Existing load ({existing_sum} cases) + Proposed load ({proposed_sum} cases) = "
            f"{total_load} cases, which exceeds max capacity limit of {vehicle.max_capacity_cases} cases."
        )
        return CapacityCheckResult(
            is_feasible=False,
            vehicle_id=vehicle.vehicle_id,
            existing_load=existing_sum,
            proposed_load=total_load,
            capacity_limit=vehicle.max_capacity_cases,
            reason=reason,
        )

    return CapacityCheckResult(
        is_feasible=True,
        vehicle_id=vehicle.vehicle_id,
        existing_load=existing_sum,
        proposed_load=total_load,
        capacity_limit=vehicle.max_capacity_cases,
        reason=f"Proposed load of {total_load} cases is within capacity limit of {vehicle.max_capacity_cases} cases.",
    )
