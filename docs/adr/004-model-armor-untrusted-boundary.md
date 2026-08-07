# ADR 004: Model Armor Floor Setting for Untrusted External Documents

## Context
External recall notices, supplier bulletins, and partner Webhook payloads are untrusted inputs entering the control plane. They could contain prompt injection, invalid data payloads, or malicious instructions designed to trick Gemini agents into unauthorized actions.

## Decision
1. All inbound unstructured documents and text payloads pass through Google Cloud Model Armor before reach the ADK Gemini orchestrator.
2. Model Armor evaluates the payload against configured security floor settings (`projects/preflight-hackathon/locations/us-central1/floorSettings/default`).
3. Payloads flagged with prompt injection or unsafe content generate an immediate security receipt and are quarantined without reaching agent memory or tool execution.

## Consequences
- Protects LLM reasoning context from adversarial prompt injection attacks.
- Provides compliance receipts for input security inspection.
