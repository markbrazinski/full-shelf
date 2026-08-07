/** Environment variable contract for Full Shelf web frontend. */
export const ENV = {
  ORCHESTRATOR_URL: import.meta.env.VITE_ORCHESTRATOR_URL || "http://localhost:8000",
  PLAN_LEDGER_URL: import.meta.env.VITE_PLAN_LEDGER_URL || "http://localhost:8001",
  TENANT_ID: import.meta.env.VITE_TENANT_ID || "east-bay-food-bank",
};
