import { ENV } from '../env';
import type {
  PlanPreviewResponse,
  ExecuteActionRequest,
  ActionReceipt,
  RecallResponse,
  SystemEvidence,
} from './types';

export class FullShelfApiClient {
  private ledgerUrl: string;
  private orchestratorUrl: string;

  constructor() {
    this.ledgerUrl = ENV.PLAN_LEDGER_URL;
    this.orchestratorUrl = ENV.ORCHESTRATOR_URL;
  }

  async getMorningPlanPreview(tenantId: string = ENV.TENANT_ID): Promise<PlanPreviewResponse> {
    const res = await fetch(`${this.ledgerUrl}/api/v1/plans/preview?tenant_id=${tenantId}`);
    if (!res.ok) throw new Error(`Failed to fetch plan preview: ${res.statusText}`);
    return res.json();
  }

  async executeAction(request: ExecuteActionRequest): Promise<ActionReceipt> {
    const res = await fetch(`${this.ledgerUrl}/api/v1/actions/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    if (!res.ok) throw new Error(`Failed to execute action: ${res.statusText}`);
    return res.json();
  }

  async triggerRecall(lotId: string = 'LTC-4471', hazard: string = 'E. coli O157:H7'): Promise<RecallResponse> {
    const res = await fetch(`${this.ledgerUrl}/api/v1/incidents/recall`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lot_id: lotId, hazard }),
    });
    if (!res.ok) throw new Error(`Failed to trigger recall: ${res.statusText}`);
    return res.json();
  }

  async getSystemEvidence(): Promise<SystemEvidence> {
    const res = await fetch(`${this.ledgerUrl}/api/v1/evidence/system`);
    if (!res.ok) throw new Error(`Failed to fetch system evidence: ${res.statusText}`);
    return res.json();
  }
}

export const apiClient = new FullShelfApiClient();
