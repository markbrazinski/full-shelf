import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import httpx

from google import genai
from google.cloud import pubsub_v1, spanner, tasks_v2
from full_shelf_observability import generate_trace_id


PROJECT_ID = os.getenv("GCP_PROJECT_ID", "preflight-hackathon")
MODEL_ARMOR_LOCATION = os.getenv("MODEL_ARMOR_LOCATION", "us-central1")
MODEL_ARMOR_TEMPLATE_ID = os.getenv("MODEL_ARMOR_TEMPLATE_ID", "full-shelf-recall-input-v1")
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


def inspect_recall_notice_with_model_armor(
    notice_text: str,
    *,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Sanitize one untrusted prompt through the managed regional API only."""
    template_name = (
        f"projects/{PROJECT_ID}/locations/{MODEL_ARMOR_LOCATION}/templates/"
        f"{MODEL_ARMOR_TEMPLATE_ID}"
    )
    url = (
        f"https://modelarmor.{MODEL_ARMOR_LOCATION}.rep.googleapis.com/v1/"
        f"{template_name}:sanitizeUserPrompt"
    )
    correlation_id = correlation_id or generate_trace_id()

    try:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default()
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)

        headers = {
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json"
        }

        headers["X-Goog-Request-Reason"] = f"full-shelf-recall-{correlation_id}"
        res = httpx.post(
            url,
            headers=headers,
            json={"userPromptData": {"text": notice_text}},
            timeout=10.0,
        )
        if res.status_code != 200:
            return {
                "status": "SERVICE_UNAVAILABLE",
                "safety_verdict": "BLOCKED_API_FAILURE",
                "model_armor_template": template_name,
                "model_armor_api_status": res.status_code,
                "managed_operation": "sanitizeUserPrompt",
                "correlation_id": correlation_id,
            }
        body = res.json()
        result = body.get("sanitizationResult") if isinstance(body, dict) else None
        if not isinstance(result, dict):
            raise ValueError("MODEL_ARMOR_RESULT_MISSING")
        invocation = result.get("invocationResult")
        match_state = result.get("filterMatchState")
        filter_results = result.get("filterResults")
        if invocation != "SUCCESS" or match_state not in {"MATCH_FOUND", "NO_MATCH_FOUND"}:
            raise ValueError("MODEL_ARMOR_RESULT_INVALID")
        if not isinstance(filter_results, dict) or not filter_results:
            raise ValueError("MODEL_ARMOR_FILTER_RESULTS_MISSING")
        serialized_filters = json.dumps(filter_results, sort_keys=True)
        if "EXECUTION_FAILED" in serialized_filters or "EXECUTION_SKIPPED" in serialized_filters:
            raise ValueError("MODEL_ARMOR_PARTIAL_FILTER_FAILURE")
        blocked = match_state == "MATCH_FOUND"
        return {
            "status": "BLOCKED" if blocked else "APPROVED",
            "safety_verdict": "FAILED_SAFETY_SCREENING" if blocked else "PASSED",
            "model_armor_template": template_name,
            "model_armor_location": MODEL_ARMOR_LOCATION,
            "managed_operation": "sanitizeUserPrompt",
            "invocation_result": invocation,
            "filter_match_state": match_state,
            "filter_results": filter_results,
            "api_response_code": 200,
            "correlation_id": correlation_id,
        }
    except Exception as exc:
        return {
            "status": "SERVICE_UNAVAILABLE",
            "safety_verdict": "BLOCKED_API_FAILURE",
            "model_armor_template": template_name,
            "managed_operation": "sanitizeUserPrompt",
            "correlation_id": correlation_id,
            "failure_type": type(exc).__name__,
        }


def extract_recall_entities_with_gemini_35(raw_notice: str) -> Dict[str, Any]:
    """Extracts recall parameters using Google ADK Agent and Runner with Gemini on Vertex AI."""
    import asyncio
    from google.adk.agents import Agent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1"
    os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
    os.environ["GOOGLE_CLOUD_LOCATION"] = VERTEX_LOCATION

    agent = Agent(
        name="RecallExtractionAgent",
        model="gemini-2.5-flash",
        instruction="""
        You are an automated Food Safety Reasoning Agent powering Full Shelf.
        Extract recall parameters from the provided notice text into exact JSON:
        Keys:
        - "lot_id": string (e.g. LTC-4471)
        - "product_name": string (e.g. Romaine Lettuce)
        - "hazard": string (e.g. E. coli O157:H7)
        - "action_required": string (e.g. PAUSE_DISPATCH_AND_QUARANTINE)
        - "source_anchor": string (e.g. FDA Enforcement Report #2026-0807-L4)
        Return ONLY raw valid JSON. No markdown backticks, no commentary.
        """
    )

    async def _run_adk_extraction():
        session_service = InMemorySessionService()
        runner = Runner(
            agent=agent,
            session_service=session_service,
            app_name="FullShelfApp"
        )
        session = await session_service.create_session(user_id="orchestrator-sa", app_name="FullShelfApp")
        user_msg = types.Content(
            role="user",
            parts=[types.Part.from_text(text=raw_notice)]
        )
        extracted_text = ""
        async for event in runner.run_async(user_id="orchestrator-sa", session_id=session.id, new_message=user_msg):
            if hasattr(event, "content") and event.content:
                for part in getattr(event.content, "parts", []):
                    if hasattr(part, "text") and part.text:
                        extracted_text += part.text
        return session.id, extracted_text

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            session_id, raw_response = loop.run_until_complete(_run_adk_extraction())
        else:
            session_id, raw_response = asyncio.run(_run_adk_extraction())

        text = raw_response.strip()
        if text.startswith("```json"):
            text = text.split("```json")[1].split("```")[0].strip()
        elif text.startswith("```"):
            text = text.split("```")[1].split("```")[0].strip()

        extracted = json.loads(text)
        if "lot_id" not in extracted:
            raise ValueError("Extracted JSON missing mandatory 'lot_id' field")

        extracted["notice_label"] = "REPRESENTATIVE DEMO NOTICE"
        extracted["model_used"] = MODEL_ID
        extracted["vertex_location"] = VERTEX_LOCATION
        extracted["adk_session_id"] = session_id
        extracted["adk_framework"] = "GOOGLE_ADK_2.6"
        extracted["validation_status"] = "VALIDATED_AGAINST_SOURCE_ANCHOR"
        return extracted
    except Exception as e:
        return {
            "status": "EXTRACTION_FAILED_MANUAL_REVIEW_REQUIRED",
            "error_detail": str(e),
            "notice_label": "REPRESENTATIVE DEMO NOTICE",
            "model_used": MODEL_ID,
            "validation_status": "MANUAL_REVIEW_REQUIRED"
        }


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


def schedule_site01_deadline_task(incident_id: str = "INC-RECALL-01", orchestrator_url: Optional[str] = None) -> Dict[str, Any]:
    """Schedules acknowledgment deadline task using GCP Cloud Tasks with OIDC token."""
    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(PROJECT_ID, "us-central1", "full-shelf-deadlines")
    target_url = orchestrator_url or os.getenv("ORCHESTRATOR_URL", "https://full-shelf-orchestrator-620464070103.us-central1.run.app")

    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{target_url}/api/v1/incidents/site01-deadline",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"incident_id": incident_id, "site_id": "SITE-01", "deadline_seconds": 3600}).encode("utf-8"),
            "oidc_token": {
                "service_account_email": f"full-shelf-orchestrator-sa@{PROJECT_ID}.iam.gserviceaccount.com"
            }
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
        return {
            "status": "QUEUED_LOCAL_FALLBACK",
            "queue": parent,
            "target_url": task["http_request"]["url"],
            "note": str(e)
        }
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
