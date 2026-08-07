# ADR 005: Two-Incident Day Coordinator & Truthful Unresolved Terminal State

## Context
A daily fulfillment plan may experience multiple cascading real-world disruptions (e.g., Truck 1 breakdown followed by a food-safety recall for lot `LTC-4471`). The system must not prematurely mark an incident or day coordinator as `RESOLVED` while physical inventory state or downstream partner acknowledgments remain unconfirmed.

## Decision
1. A day-level coordinator tracks daily fulfillment state and links child incidents:
   - `INC-TRUCK`: Truck breakdown (resolved via approved pickup conversion).
   - `INC-RECALL`: Food safety recall for lot `LTC-4471`.
2. When Agency 01 has sub-distributed 8 cases to Site 01, and an acknowledgment request is issued to Site 01 via Cloud Tasks callback, the incident cannot be marked `RESOLVED`.
3. The system explicitly evaluates and publishes the terminal state as `PARTIALLY_CONTAINED`.
4. The day coordinator remains active and subscribed to Pub/Sub events until all downstream acknowledgments are recorded or explicitly escalated.

## Consequences
- Honest operational reporting: prevents false declaration of safety or containment.
- Clear separation between service status (4/5 agencies supplied, 1 shortfall) and safety containment status (partially contained, 8 cases pending acknowledgment).
