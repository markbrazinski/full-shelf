# ADR 009: Accept the public Cloud Run health boundary

## Status

Accepted on 2026-08-14 as an acceptance-contract amendment.

## Context

The deployed orchestrator serves `GET /` without authentication as HTTP 200.
At the public Cloud Run boundary, `GET /healthz` does not reach the container;
Google returns HTTP 404. The application still contains and exhaustively
classifies `/healthz`, but that fact is structural evidence rather than an
observed-live public health response.

## Decision

1. `GET /` is Full Shelf's sole externally reachable public health endpoint.
   Its unauthenticated deployed acceptance expectation is HTTP 200.
2. The deployed public-boundary expectation for `GET /healthz` is the
   Google-generated HTTP 404. It is not an observed-live application health
   endpoint.
3. The application route-authentication matrix remains exhaustive. Its
   `/healthz` classification and default-deny behavior are unchanged.
4. No replacement health path, gateway, third service, runtime revision, IAM
   change, or authentication exception is introduced by this decision.

## Evidence classification

- The deployed unauthenticated `GET /` HTTP 200 is `OBSERVED_LIVE`.
- The deployed Google-generated `GET /healthz` HTTP 404 is `OBSERVED_LIVE`
  platform-boundary behavior.
- The application `/healthz` handler and its explicit route classification are
  `STRUCTURALLY_VERIFIED`; they are not an observed-live public health
  capability.

## Consequences

The final independent audit uses `/` for the public health control and expects
the platform-boundary 404 for `/healthz`. Sensitive-route identity controls,
the private ledger, the two-service topology, deterministic mutation boundary,
canonical state, and reserved final-audit authority remain unchanged. This
decision does not constitute backend acceptance; that authority remains with
the independent auditor.
