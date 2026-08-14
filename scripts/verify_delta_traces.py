#!/usr/bin/env python3
"""Read sanitized Cloud Trace span names for delta Model Armor controls."""

from __future__ import annotations

import argparse
import json

import google.auth
from google.auth.transport.requests import AuthorizedSession


PROJECT = "preflight-hackathon"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benign", required=True)
    parser.add_argument("--rejected", action="append", default=[])
    args = parser.parse_args()
    trace_ids = {"benign": args.benign}
    trace_ids.update(
        {f"rejected_{index + 1}": value for index, value in enumerate(args.rejected)}
    )
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    session = AuthorizedSession(credentials)
    evidence = {}
    for label, trace_id in trace_ids.items():
        if len(trace_id) != 32:
            raise SystemExit(f"invalid trace id for {label}")
        response = session.get(
            f"https://cloudtrace.googleapis.com/v1/projects/{PROJECT}/traces/{trace_id}",
            timeout=30,
        )
        response.raise_for_status()
        names = sorted(
            span.get("name", "") for span in response.json().get("spans", [])
        )
        model_spans = [
            name for name in names
            if "generate_content" in name.lower() or "call_llm" in name.lower()
            or "invoke_agent" in name.lower()
        ]
        evidence[label] = {
            "trace_id": trace_id,
            "span_count": len(names),
            "span_names": names,
            "model_spans": model_spans,
        }
        if label == "benign" and not any(
            "generate_content" in name.lower() for name in names
        ):
            raise SystemExit("benign control lacks managed Gemini generation span")
        if label.startswith("rejected_") and model_spans:
            raise SystemExit(f"rejected control unexpectedly contains model span: {label}")
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
