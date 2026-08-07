import os
import random
from typing import Optional, Dict, Tuple

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "preflight-hackathon")

_tracer = None


def get_tracer(service_name: str = "full-shelf"):
    global _tracer
    if _tracer is not None:
        return _tracer

    provider = TracerProvider()
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
    """Generates a valid 32-character hex W3C trace ID."""
    return f"{random.getrandbits(128):032x}"


def generate_span_id() -> str:
    """Generates a valid 16-character hex W3C span ID."""
    return f"{random.getrandbits(64):016x}"


def build_traceparent(trace_id: str, span_id: str) -> str:
    """Formats a W3C traceparent header string."""
    return f"00-{trace_id}-{span_id}-01"


def parse_traceparent(traceparent: str) -> Optional[Tuple[str, str]]:
    """Parses trace_id and span_id from W3C traceparent header."""
    try:
        parts = traceparent.split("-")
        if len(parts) == 4:
            return parts[1], parts[2]
    except Exception:
        pass
    return None
