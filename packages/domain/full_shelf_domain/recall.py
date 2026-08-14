import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import httpx

from google.cloud import pubsub_v1, spanner, tasks_v2
from google.api_core.exceptions import AlreadyExists
from full_shelf_observability import build_traceparent, generate_span_id, generate_trace_id
from pydantic import BaseModel, ConfigDict, Field, ValidationError


PROJECT_ID = os.getenv("GCP_PROJECT_ID", "preflight-hackathon")
MODEL_ARMOR_LOCATION = os.getenv("MODEL_ARMOR_LOCATION", "us-central1")
MODEL_ARMOR_TEMPLATE_ID = os.getenv("MODEL_ARMOR_TEMPLATE_ID", "full-shelf-recall-input-v1")
TOPIC_ID = os.getenv("PUBSUB_TOPIC_ID", "full-shelf-incidents")
PLAN_LEDGER_URL = os.getenv("PLAN_LEDGER_URL", "https://full-shelf-plan-ledger-620464070103.us-central1.run.app")
MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-3.5-flash")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "global")

VALID_LIFECYCLE_STATES = [
    "DETECTED",
    "SCOPING",
    "CONTAINMENT_IN_PROGRESS",
    "PARTIALLY_CONTAINED",
    "CONTAINED",
    "CLOSED"
]

SUPPORTED_MODEL_ARMOR_FILTER_ALIASES = {
    "FILTER_VERSION_ALIAS_STABLE",
    "FILTER_VERSION_ALIAS_LATEST",
}


def is_eligible_gemini_model(model_id: str) -> bool:
    """Return true only for a Gemini major/minor identifier at least 3.5."""
    match = re.match(r"^gemini-(\d+)\.(\d+)(?:-|$)", model_id)
    return bool(match and (int(match.group(1)), int(match.group(2))) >= (3, 5))


class RecallExtractionSchema(BaseModel):
    """Strict advisory extraction returned by the load-bearing ADK agent."""

    model_config = ConfigDict(extra="forbid")

    lot_id: str = Field(min_length=1, max_length=64)
    product_name: str = Field(min_length=1, max_length=128)
    hazard: str = Field(min_length=1, max_length=128)
    action_required: str = Field(min_length=1, max_length=128)
    source_anchor: str = Field(min_length=1, max_length=256)


class AdkExtractionFailure(RuntimeError):
    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


def _has_explicit_lot_anchor(notice: str, lot_id: str) -> bool:
    """Distinguish a lot identifier from an unrelated bulletin or document ID."""
    lot_pattern = re.escape(lot_id.strip())
    return bool(
        re.search(
            rf"\blot(?:\s+(?:id|number))?\s*[:#-]?\s*{lot_pattern}(?=\W|$)",
            notice,
            flags=re.IGNORECASE,
        )
    )


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
        version_config = result.get("sanitizationMetadata", {}).get(
            "filterVersionConfig"
        )
        if invocation != "SUCCESS" or match_state not in {"MATCH_FOUND", "NO_MATCH_FOUND"}:
            raise ValueError("MODEL_ARMOR_RESULT_INVALID")
        if not isinstance(filter_results, dict) or not filter_results:
            raise ValueError("MODEL_ARMOR_FILTER_RESULTS_MISSING")
        if not isinstance(version_config, dict):
            raise ValueError("MODEL_ARMOR_FILTER_VERSION_METADATA_MISSING")
        filter_version = version_config.get("filterVersion")
        filter_version_alias = version_config.get("filterVersionAlias")
        if (not isinstance(filter_version, str) or not filter_version
                or filter_version_alias not in SUPPORTED_MODEL_ARMOR_FILTER_ALIASES):
            raise ValueError("MODEL_ARMOR_FILTER_VERSION_UNSUPPORTED")
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
            "filter_version": filter_version,
            "filter_version_alias": filter_version_alias,
            "filter_version_release_date": version_config.get("releaseDate"),
            "filter_version_messages": version_config.get("messageItems", []),
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


def extract_recall_entities_with_gemini_35(
    raw_notice: str,
    *,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run schema-bound recall extraction through a real Google ADK Runner."""
    import asyncio
    from importlib.metadata import version

    from google.adk.agents import Agent
    from google.adk.planners import BuiltInPlanner
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    correlation_id = correlation_id or generate_trace_id()
    execution: Dict[str, Any] = {
        "adk_session_id": None,
        "adk_run_id": None,
        "adk_event_id": None,
    }
    adk_version = version("google-adk")

    if not is_eligible_gemini_model(MODEL_ID):
        return {
            "status": "MANUAL_REVIEW_REQUIRED",
            "reason_code": "INELIGIBLE_MODEL_CONFIGURATION",
            "model_used": MODEL_ID,
            "vertex_location": VERTEX_LOCATION,
            "adk_framework": f"google-adk/{adk_version}",
            "correlation_id": correlation_id,
            "downstream_allowed": False,
            **execution,
        }

    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1"
    os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
    os.environ["GOOGLE_CLOUD_LOCATION"] = VERTEX_LOCATION

    agent = Agent(
        name="RecallExtractionAgent",
        model=MODEL_ID,
        output_schema=RecallExtractionSchema,
        planner=BuiltInPlanner(
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        generate_content_config=types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=512,
        ),
        instruction="""
        Extract the requested fields only from the supplied recall notice.
        Every value must be explicitly supported by text in that notice.
        Do not infer missing values, use remembered examples, or invent a
        canonical scenario. Return the configured structured response only.
        """
    )

    async def _run_adk_extraction():
        session_service = InMemorySessionService()
        runner = Runner(
            agent=agent,
            session_service=session_service,
            app_name="FullShelfApp"
        )
        session = await session_service.create_session(
            user_id="orchestrator-workload",
            app_name="FullShelfApp",
        )
        execution["adk_session_id"] = session.id
        user_msg = types.Content(
            role="user",
            parts=[types.Part.from_text(text=raw_notice)]
        )
        final_texts = []
        usage = None
        async for event in runner.run_async(
            user_id="orchestrator-workload",
            session_id=session.id,
            new_message=user_msg,
        ):
            if event.invocation_id:
                if execution["adk_run_id"] not in {None, event.invocation_id}:
                    raise AdkExtractionFailure("MULTIPLE_ADK_RUN_IDENTIFIERS")
                execution["adk_run_id"] = event.invocation_id
            if event.error_code:
                raise AdkExtractionFailure("ADK_MODEL_ERROR")
            if event.author != agent.name or not event.is_final_response():
                continue
            finish_reason = getattr(event.finish_reason, "name", event.finish_reason)
            if finish_reason not in {None, "STOP"}:
                raise AdkExtractionFailure("ADK_RESPONSE_INCOMPLETE")
            text = "".join(
                part.text or ""
                for part in (event.content.parts if event.content else [])
            ).strip()
            if text:
                final_texts.append(text)
                execution["adk_event_id"] = event.id
                usage = event.usage_metadata
        if not execution["adk_run_id"]:
            raise AdkExtractionFailure("ADK_RUN_IDENTIFIER_MISSING")
        if len(final_texts) != 1:
            raise AdkExtractionFailure("ADK_FINAL_RESPONSE_COUNT_INVALID")
        return final_texts[0], usage

    try:
        raw_response, usage = asyncio.run(_run_adk_extraction())
        extracted = RecallExtractionSchema.model_validate_json(raw_response)
        normalized_notice = raw_notice.casefold()
        for field_name in RecallExtractionSchema.model_fields:
            value = getattr(extracted, field_name)
            if value.casefold() not in normalized_notice:
                raise AdkExtractionFailure("SOURCE_ANCHOR_VALIDATION_FAILED")
        if not _has_explicit_lot_anchor(raw_notice, extracted.lot_id):
            raise AdkExtractionFailure("LOT_ANCHOR_VALIDATION_FAILED")

        result = {
            **extracted.model_dump(),
            "status": "EXTRACTION_VALIDATED",
            "model_used": MODEL_ID,
            "vertex_location": VERTEX_LOCATION,
            "adk_framework": f"google-adk/{adk_version}",
            "adk_session_backend": "InMemorySessionService",
            "validation_status": "SCHEMA_AND_SOURCE_ANCHORS_VALIDATED",
            "correlation_id": correlation_id,
            "downstream_allowed": True,
            **execution,
        }
        if usage:
            result["token_usage"] = {
                "prompt_tokens": usage.prompt_token_count,
                "output_tokens": usage.candidates_token_count,
                "total_tokens": usage.total_token_count,
            }
        return result
    except ValidationError:
        reason_code = "INVALID_STRUCTURED_OUTPUT"
    except AdkExtractionFailure as exc:
        reason_code = exc.reason_code
    except Exception:
        reason_code = "ADK_INVOCATION_FAILED"

    return {
            "status": "MANUAL_REVIEW_REQUIRED",
            "reason_code": reason_code,
            "model_used": MODEL_ID,
            "vertex_location": VERTEX_LOCATION,
            "adk_framework": f"google-adk/{adk_version}",
            "adk_session_backend": "InMemorySessionService",
            "validation_status": "MANUAL_REVIEW_REQUIRED",
            "correlation_id": correlation_id,
            "downstream_allowed": False,
            **execution,
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


def schedule_site01_deadline_task(
    *,
    tenant_id: str,
    incident_id: str,
    hold_incident_id: str,
    coordinator_id: str,
    lot_id: str,
    site_id: str,
    unconfirmed_cases: int,
    task_id: str,
    event_idempotency_key: Optional[str] = None,
    orchestrator_url: Optional[str] = None,
    oidc_audience: Optional[str] = None,
    delivery_service_account: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create one real, explicitly audience-bound Site 01 deadline task."""
    if not all((tenant_id, incident_id, hold_incident_id, coordinator_id,
                lot_id, site_id)) or unconfirmed_cases <= 0:
        raise ValueError("TASK_AUTHORITY_SCOPE_REQUIRED")
    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(PROJECT_ID, "us-central1", "full-shelf-deadlines")
    target_url = orchestrator_url or os.getenv("ORCHESTRATOR_URL", "https://full-shelf-orchestrator-620464070103.us-central1.run.app")
    audience = oidc_audience or os.getenv("MANAGED_CALLBACK_AUDIENCE", "")
    service_account = delivery_service_account or os.getenv("MANAGED_CALLBACK_SERVICE_ACCOUNT_EMAIL", "")
    if not audience or not service_account:
        raise ValueError("TASK_OIDC_CONFIGURATION_REQUIRED")
    correlation_trace_id = trace_id or generate_trace_id()
    task_name = client.task_path(PROJECT_ID, "us-central1", "full-shelf-deadlines", task_id)

    task = {
        "name": task_name,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{target_url}/api/v1/incidents/site01-deadline",
            "headers": {
                "Content-Type": "application/json",
                "traceparent": build_traceparent(correlation_trace_id, generate_span_id()),
            },
            "body": json.dumps({
                "incident_id": incident_id,
                "hold_incident_id": hold_incident_id,
                "coordinator_id": coordinator_id,
                "lot_id": lot_id,
                "site_id": site_id,
                "unconfirmed_cases": unconfirmed_cases,
                "tenant_id": tenant_id,
                "task_decision_id": task_id,
                "event_idempotency_key": event_idempotency_key or task_id,
                "correlation_trace_id": correlation_trace_id,
            }).encode("utf-8"),
            "oidc_token": {
                "service_account_email": service_account,
                "audience": audience,
            }
        }
    }

    try:
        created_task = client.create_task(request={"parent": parent, "task": task})
        created_task_name = created_task.name
        status = "SCHEDULED"
    except AlreadyExists:
        # The deterministic task name makes Pub/Sub redelivery safe. Cloud Tasks
        # retains de-duplicated names after execution, so an existing name is the
        # authoritative indication that the same escalation was already scheduled.
        created_task_name = task_name
        status = "ALREADY_SCHEDULED"
    return {
        "status": status,
        "task_name": created_task_name,
        "queue": parent,
        "target_url": task["http_request"]["url"],
        "oidc_audience": audience,
        "delivery_service_account": service_account,
        "correlation_trace_id": correlation_trace_id,
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
