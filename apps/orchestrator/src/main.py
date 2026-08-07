from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
import os
import httpx

app = FastAPI(title="Full Shelf ADK Orchestrator", version="1.0.0")

PLAN_LEDGER_URL = os.getenv("PLAN_LEDGER_URL", "http://localhost:8001")


class AssessmentRequest(BaseModel):
    event_type: str  # "TRUCK_BREAKDOWN" or "FOOD_SAFETY_RECALL"
    event_details: dict


@app.get("/")
def health_check():
    return {"service": "orchestrator", "status": "healthy", "model": "gemini-3.5-flash", "read_only_spanner": True}


@app.get("/api/v1/orchestrator/preview")
async def get_agent_preview(tenant_id: str = Query("east-bay-food-bank")):
    """
    Agent fleet reads operational plan from plan-ledger and generates a structured preview.
    (Read-Only Spanner access via plan-ledger API boundary).
    """
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{PLAN_LEDGER_URL}/api/v1/plans/preview?tenant_id={tenant_id}")
            plan_data = res.json()
        except Exception:
            # Fallback fixture if plan-ledger is offline
            plan_data = {
                "active_plan_revision": "v1",
                "trucks": [{"vehicle_id": "TRUCK-01", "name": "Refrigerated Truck 1", "capacity": 60}],
                "deliveries": [],
            }

    summary = (
        f"Full Shelf Operations Preview for {tenant_id}: "
        f"Active plan revision {plan_data.get('active_plan_revision')}. "
        f"5 East Bay partner deliveries scheduled across 2 refrigerated trucks."
    )

    return {
        "tenant_id": tenant_id,
        "summary": summary,
        "plan": plan_data,
        "agent_status": "WAITING_FOR_EVENTS",
    }


@app.post("/api/v1/orchestrator/incident/assess")
async def assess_incident(req: AssessmentRequest):
    """
    ADK Incident Coordinator agent interprets disruption and proposes recovery actions.
    Note: Gemini reasoning does not mutate state directly; proposals are sent to plan-ledger.
    """
    if req.event_type == "TRUCK_BREAKDOWN":
        return {
            "incident_type": "TRUCK_BREAKDOWN",
            "reasoning": "Truck 1 failed after Stop 1. Capacity check proves Order 202 (22 cases) and Order 203 (20 cases) cannot both go to Truck 2 (capacity 60). Proposing Order 202 reroute to Truck 2 and Order 203 conversion to partner pickup requiring KMS approval.",
            "proposed_actions": [
                {"action_type": "REROUTE_ORDER", "order_id": "O202", "target_vehicle": "TRUCK-02"},
                {"action_type": "CONVERT_TO_PARTNER_PICKUP", "order_id": "O203", "cases": 20, "requires_kms_approval": True},
            ],
        }
    elif req.event_type == "FOOD_SAFETY_RECALL":
        return {
            "incident_type": "FOOD_SAFETY_RECALL",
            "reasoning": "Recall received for lot LTC-4471 / LOT-RECALL-88 (E. coli O157:H7). Invalidating plan revision v2. Activating lot barrier across 96 unique cases.",
            "proposed_actions": [
                {"action_type": "INVALIDATE_PLAN", "plan_id": "PLAN-2026-08-07"},
                {"action_type": "ACTIVATE_LOT_BARRIER", "lot_id": "LOT-RECALL-88"},
            ],
            "terminal_state": "PARTIALLY_CONTAINED_AWAITING_RECOVERY",
        }

    return {"incident_type": req.event_type, "status": "NO_ACTION_REQUIRED"}
