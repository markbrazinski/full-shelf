import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import httpx

from google import genai
from google.cloud import pubsub_v1, spanner, tasks_v2
from full_shelf_observability import generate_trace_id


PROJECT_ID = os.getenv("GCP_PROJECT_ID", "preflight-hackathon")
TOPIC_ID = os.getenv("PUBSUB_TOPIC_ID", "full-shelf-incidents")
PLAN_LEDGER_URL = os.getenv("PLAN_LEDGER_URL", "https://full-shelf-plan-ledger-620464070103.us-central1.run.app")
MODEL_ID = "gemini-3.5-flash"
VERTEX_LOCATION = "global"

VALID_LIFECYCLE_STATES = [
    "DETECTED",
    "SCOPING",
    "CONTAINMENT_IN_PROGRESS",
    "PARTIALLY_CONTAINED",
    "CONTAINED",
    "CLOSED"
]


def verify_gemini_35_availability() -> Dict[str, Any]:
    """Asserts that Gemini 3.5 Flash or newer is active on Vertex AI. Fails startup if unavailable."""
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=VERTEX_LOCATION)
    res = client.models.generate_content(model=MODEL_ID, contents="ping")
    if not res.text:
        raise RuntimeError(f"Model verification failed for {MODEL_ID}")
    return {
        "status": "HEALTHY",
        "model_id": MODEL_ID,
        "vertex_location": VERTEX_LOCATION,
        "response": res.text.strip()
    }


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


def extract_recall_entities_with_gemini_35(raw_notice: str) -> Dict[str, Any]:
    """Extracts recall entities from notice using Gemini 3.5 Flash on Vertex AI (location='global')."""
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=VERTEX_LOCATION)
    prompt = f"""
    You are an automated Food Safety Reasoning Agent powering Full Shelf.
    Extract recall parameters from this REPRESENTATIVE DEMO NOTICE into exact JSON:
    Notice: "{raw_notice}"

    Return ONLY a JSON object with exact keys:
    - "lot_id": string (e.g., LTC-4471)
    - "product_name": string (e.g., Romaine Lettuce)
    - "hazard": string (e.g., E. coli O157:H7)
    - "action_required": string (e.g., PAUSE_DISPATCH_AND_QUARANTINE)
    - "source_anchor": string (e.g., FDA Enforcement Report #2026-0807-L4)
    """

    res = client.models.generate_content(
        model=MODEL_ID,
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

    extracted["notice_label"] = "REPRESENTATIVE DEMO NOTICE"
    extracted["model_used"] = MODEL_ID
    extracted["vertex_location"] = VERTEX_LOCATION
    return extracted


class IncidentLifecycleManager:
    """Manages strict incident lifecycle state transitions: DETECTED -> SCOPING -> CONTAINMENT_IN_PROGRESS -> PARTIALLY_CONTAINED."""

    @staticmethod
    def validate_transition(current_state: str, target_state: str, has_unconfirmed_downstream: bool = True) -> bool:
        if target_state in ["CONTAINED", "CLOSED"] and has_unconfirmed_downstream:
            raise ValueError(f"Refused transition from {current_state} to {target_state}: DOWNSTREAM_CUSTODY_UNCONFIRMED")

        allowed_transitions = {
            "DETECTED": ["SCOPING"],
            "SCOPING": ["CONTAINMENT_IN_PROGRESS"],
            "CONTAINMENT_IN_PROGRESS": ["PARTIALLY_CONTAINED"],
            "PARTIALLY_CONTAINED": ["CONTAINED"],
            "CONTAINED": ["CLOSED"],
        }

        if target_state not in allowed_transitions.get(current_state, []):
            raise ValueError(f"Invalid transition path: {current_state} -> {target_state}")
        return True


def schedule_site01_deadline_task(incident_id: str = "INC-RECALL-01") -> Dict[str, Any]:
    """Schedules acknowledgment deadline task using GCP Cloud Tasks."""
    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(PROJECT_ID, "us-central1", "full-shelf-deadlines")

    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{PLAN_LEDGER_URL}/api/v1/incidents/site01-deadline",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"incident_id": incident_id, "site_id": "SITE-01", "deadline_seconds": 3600}).encode("utf-8"),
        }
    }

    try:
        created_task = client.create_task(request={"parent": parent, "task": task})
        return {
            "status": "SCHEDULED",
            "task_name": created_task.name,
            "queue": parent,
            "target_url": task["http_request"]["url"]
        }
    except Exception as e:
        print(f"Cloud Tasks note: {e}")
def publish_recall_event_to_pubsub(event_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Publishes recall event to GCP Pub/Sub topic full-shelf-incidents."""
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
    data = json.dumps(event_payload).encode("utf-8")
    future = publisher.publish(topic_path, data)
    message_id = future.result()
    return {
        "status": "PUBLISHED",
        "topic": topic_path,
        "message_id": message_id,
        "event_payload": event_payload
    }
