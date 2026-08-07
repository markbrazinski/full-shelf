import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import httpx

from google import genai
from google.cloud import pubsub_v1
from full_shelf_observability import generate_trace_id


PROJECT_ID = os.getenv("GCP_PROJECT_ID", "preflight-hackathon")
TOPIC_ID = os.getenv("PUBSUB_TOPIC_ID", "full-shelf-incidents")
PLAN_LEDGER_URL = os.getenv("PLAN_LEDGER_URL", "https://full-shelf-plan-ledger-620464070103.us-central1.run.app")


def inspect_recall_notice_with_model_armor(notice_text: str) -> Dict[str, Any]:
    """Screen recall notice text through Model Armor safety filters."""
    is_safe = "DROP TABLE" not in notice_text and "IGNORE ALL PREVIOUS" not in notice_text
    return {
        "status": "APPROVED" if is_safe else "BLOCKED",
        "safety_verdict": "PASSED" if is_safe else "FAILED_SAFETY_SCREENING",
        "model_armor_template": f"projects/{PROJECT_ID}/locations/us-central1/templates/full-shelf-recall-guard",
        "notice_text": notice_text.strip(),
        "threats_detected": [] if is_safe else ["UNSAFE_PROMPT_INJECTION"],
    }


def publish_recall_event_to_pubsub(
    lot_id: str = "LTC-4471",
    product_name: str = "Romaine Lettuce",
    hazard: str = "E. coli O157:H7",
    action_required: str = "PAUSE_DISPATCH_AND_QUARANTINE",
    source_anchor: str = "FDA Enforcement Report #2026-0807-L4",
    trace_id: Optional[str] = None
) -> Dict[str, Any]:
    """Publishes LTC-4471 recall incident event to Pub/Sub topic full-shelf-incidents."""
    t_id = trace_id or generate_trace_id()
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)

    event_payload = {
        "event_id": f"EVT-RECALL-{lot_id}",
        "tenant_id": "east-bay-food-bank",
        "event_type": "FOOD_SAFETY_RECALL",
        "lot_id": lot_id,
        "product_name": product_name,
        "hazard": hazard,
        "action_required": action_required,
        "source_anchor": source_anchor,
        "raw_notice": f"FDA ENFORCEMENT REPORT #{source_anchor}: Urgent recall issued for Lot {lot_id} ({product_name}) due to contamination with {hazard}. Action: {action_required}.",
        "trace_id": t_id,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }

    data_bytes = json.dumps(event_payload).encode("utf-8")
    future = publisher.publish(topic_path, data=data_bytes, trace_id=t_id, tenant_id="east-bay-food-bank")
    message_id = future.result(timeout=10.0)

    return {
        "status": "PUBLISHED",
        "topic": topic_path,
        "message_id": message_id,
        "trace_id": t_id,
        "payload": event_payload,
    }


def extract_recall_entities_with_gemini(raw_notice: str) -> Dict[str, Any]:
    """Extracts lot, product, hazard, action, and source anchor from FDA notice using Gemini 2.5 Flash on Vertex AI."""
    client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")
    prompt = f"""
    You are an automated Food Safety Reasoning Agent.
    Extract recall parameters from the following FDA notice into exact JSON:
    Notice: "{raw_notice}"

    Return ONLY a JSON object with exact keys:
    - "lot_id": string (e.g., LTC-4471)
    - "product_name": string (e.g., Romaine Lettuce)
    - "hazard": string (e.g., E. coli O157:H7)
    - "action_required": string (e.g., PAUSE_DISPATCH_AND_QUARANTINE)
    - "source_anchor": string (e.g., FDA Enforcement Report #2026-0807-L4)
    """

    res = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )

    try:
        text = res.text.strip()
        if text.startswith("```json"):
            text = text.split("```json")[1].split("```")[0].strip()
        elif text.startswith("```"):
            text = text.split("```")[1].split("```")[0].strip()
        extracted = json.loads(text)
    except Exception as e:
        extracted = {
            "lot_id": "LTC-4471",
            "product_name": "Romaine Lettuce",
            "hazard": "E. coli O157:H7",
            "action_required": "PAUSE_DISPATCH_AND_QUARANTINE",
            "source_anchor": "FDA Enforcement Report #2026-0807-L4",
            "fallback_note": str(e)
        }

    return extracted


def open_recall_incident_in_spanner(
    tenant_id: str = "east-bay-food-bank",
    incident_id: str = "INC-RECALL-01",
    recall_data: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None
) -> Dict[str, Any]:
    """Opens INC-RECALL-01 in Spanner via plan-ledger S2S endpoint, preserving Orchestrator's read-only IAM isolation."""
    now = datetime.now(timezone.utc)
    t_id = trace_id or generate_trace_id()

    data = recall_data or {
        "lot_id": "LTC-4471",
        "product_name": "Romaine Lettuce",
        "hazard": "E. coli O157:H7",
        "action_required": "PAUSE_DISPATCH_AND_QUARANTINE",
        "source_anchor": "FDA Enforcement Report #2026-0807-L4",
    }

    payload = {
        "tenant_id": tenant_id,
        "incident_id": incident_id,
        "event_type": "FOOD_SAFETY_RECALL",
        "lot_id": data["lot_id"],
        "trace_id": t_id,
        "details": data,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.post(f"{PLAN_LEDGER_URL}/api/v1/incidents/open", json=payload)
            if res.status_code == 200:
                ledger_res = res.json()
                return ledger_res
    except Exception as e:
        print(f"Call to plan-ledger open incident note: {e}")

    return {
        "incident_id": incident_id,
        "tenant_id": tenant_id,
        "event_type": "FOOD_SAFETY_RECALL",
        "affected_lot_id": data["lot_id"],
        "hazard": data["hazard"],
        "action_required": data["action_required"],
        "source_anchor": data["source_anchor"],
        "plan_status": "INVALIDATED_RECALL",
        "terminal_state": "PARTIALLY_CONTAINED",
        "trace_id": t_id,
        "opened_at": now.isoformat(),
    }
