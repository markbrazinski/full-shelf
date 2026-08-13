# ADR 004: Regional Model Armor Sanitization for Untrusted External Documents

## Context

External recall notices, supplier bulletins, and partner Webhook payloads are untrusted inputs entering the control plane. They could contain prompt injection, invalid data payloads, or malicious instructions designed to trick Gemini agents into unauthorized actions.

## Decision

1. Untrusted recall notice text passes through Google Cloud Model Armor before
   the ADK/Gemini stage.
2. The exact managed template is
   `projects/preflight-hackathon/locations/us-central1/templates/full-shelf-recall-input-v1`.
3. The orchestrator uses Application Default Credentials for its runtime
   identity and sends the notice in `userPromptData.text` to the regional REST
   operation:

   `POST https://modelarmor.us-central1.rep.googleapis.com/v1/projects/preflight-hackathon/locations/us-central1/templates/full-shelf-recall-input-v1:sanitizeUserPrompt`

4. Only `invocationResult=SUCCESS`, `filterMatchState=NO_MATCH_FOUND`, and a
   nonempty set of successfully executed filters permit processing to advance
   to the next authorized stage.
5. `MATCH_FOUND`, any non-200 response, timeout, malformed response, missing
   filters, or any skipped/failed filter fails closed before Gemini/ADK and
   before ledger invocation.
6. Evidence contains the exact managed resource, operation, sanitized filter
   results, and an application request-correlation identifier. It never
   contains the raw notice, access token, or upstream error body.
7. A template or floor-setting GET and local substring matching are not
   accepted as sanitization.

## Consequences

- Protects LLM reasoning context from adversarial prompt injection attacks.
- Keeps Model Armor calls attributable to the orchestrator runtime identity.
- Makes partial filter execution and managed-service failure explicit refusal
  states rather than fallbacks.
- The WP4 preflight route is judge-key protected and stops at the next-stage
  boundary; it exists to reproduce managed screening without invoking Gemini
  or mutating authoritative state.
