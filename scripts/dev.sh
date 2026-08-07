#!/usr/bin/env bash
set -e

echo "Starting Full Shelf Plan Ledger Service on port 8001..."
uvicorn apps.plan_ledger.src.main:app --host 0.0.0.0 --port 8001 &
LEDGER_PID=$!

echo "Starting Full Shelf ADK Orchestrator Service on port 8000..."
uvicorn apps.orchestrator.src.main:app --host 0.0.0.0 --port 8000 &
ORCH_PID=$!

echo "Full Shelf Services Running!"
echo "  - Plan Ledger API: http://localhost:8001"
echo "  - Orchestrator API: http://localhost:8000"

trap "kill $LEDGER_PID $ORCH_PID" EXIT
wait
