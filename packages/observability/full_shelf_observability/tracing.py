import os
import secrets
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Mapping, Optional, Tuple

from opentelemetry import trace
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    SpanKind,
    TraceFlags,
    set_span_in_context,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "preflight-hackathon")

_tracer = None
_request_trace_id: ContextVar[Optional[str]] = ContextVar(
    "full_shelf_request_trace_id", default=None
)


def get_tracer(service_name: str = "full-shelf"):
    global _tracer
    if _tracer is not None:
        return _tracer

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    try:
        exporter = CloudTraceSpanExporter(project_id=PROJECT_ID)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    except Exception as e:
        print(f"CloudTraceSpanExporter fallback to console: {e}")
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)
    return _tracer


def generate_trace_id() -> str:
    """Return the active request trace, or a valid ID for non-request work."""
    active = _request_trace_id.get()
    if active:
        return active
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        return f"{span_context.trace_id:032x}"
    return secrets.token_hex(16)


def generate_span_id() -> str:
    """Generates a valid 16-character hex W3C span ID."""
    return secrets.token_hex(8)


def build_traceparent(trace_id: str, span_id: str) -> str:
    """Formats a W3C traceparent header string."""
    value = f"00-{trace_id}-{span_id}-01"
    if parse_traceparent(value) is None:
        raise ValueError("INVALID_TRACE_CONTEXT")
    return value


def parse_traceparent(traceparent: str) -> Optional[Tuple[str, str]]:
    """Parses trace_id and span_id from W3C traceparent header."""
    try:
        parts = traceparent.split("-")
        trace_id, span_id = parts[1], parts[2]
        if (
            len(parts) == 4
            and len(trace_id) == 32
            and len(span_id) == 16
            and trace_id != "0" * 32
            and span_id != "0" * 16
        ):
            int(trace_id, 16)
            int(span_id, 16)
            return trace_id.lower(), span_id.lower()
    except Exception:
        pass
    return None


def _remote_parent_context(headers: Mapping[str, str]):
    normalized = {str(key).lower(): str(value) for key, value in headers.items()}
    parsed = parse_traceparent(normalized.get("traceparent", ""))
    sampled = True
    if parsed:
        trace_id, span_id = parsed
    else:
        cloud_header = normalized.get("x-cloud-trace-context", "")
        try:
            trace_hex, remainder = cloud_header.split("/", 1)
            span_decimal, options = remainder.split(";", 1)
            if len(trace_hex) != 32 or trace_hex == "0" * 32:
                return None
            int(trace_hex, 16)
            span_int = int(span_decimal)
            if not 0 < span_int < 2**64:
                return None
            trace_id = trace_hex.lower()
            span_id = f"{span_int:016x}"
            sampled = options == "o=1"
        except (ValueError, TypeError):
            return None

    span_context = SpanContext(
        trace_id=int(trace_id, 16),
        span_id=int(span_id, 16),
        is_remote=True,
        trace_flags=TraceFlags(
            TraceFlags.SAMPLED if sampled else TraceFlags.DEFAULT
        ),
    )
    return set_span_in_context(NonRecordingSpan(span_context))


@contextmanager
def request_trace_span(tracer, headers: Mapping[str, str], span_name: str):
    """Create the real server span and expose its trace ID to request code."""
    parent = _remote_parent_context(headers)
    with tracer.start_as_current_span(
        span_name,
        context=parent,
        kind=SpanKind.SERVER,
    ) as span:
        trace_id = f"{span.get_span_context().trace_id:032x}"
        token = _request_trace_id.set(trace_id)
        try:
            yield trace_id
        finally:
            _request_trace_id.reset(token)
