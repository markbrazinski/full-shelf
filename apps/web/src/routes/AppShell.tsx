import React, { useEffect, useState } from 'react';
import { apiClient } from '../api/client';
import type { PlanPreviewResponse, SystemEvidence } from '../api/types';

export const AppShell: React.FC = () => {
  const [plan, setPlan] = useState<PlanPreviewResponse | null>(null);
  const [evidence, setEvidence] = useState<SystemEvidence | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    async function loadData() {
      try {
        const p = await apiClient.getMorningPlanPreview();
        const e = await apiClient.getSystemEvidence();
        setPlan(p);
        setEvidence(e);
      } catch (err) {
        console.error('Failed to load initial control plane state:', err);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  return (
    <div style={{ fontFamily: 'sans-serif', padding: '24px', backgroundColor: '#0f172a', color: '#f8fafc', minHeight: '100vh' }}>
      <header style={{ borderBottom: '1px solid #334155', paddingBottom: '16px', marginBottom: '24px' }}>
        <h1 style={{ margin: 0, fontSize: '24px', fontWeight: 'bold' }}>Full Shelf — Control Plane Shell</h1>
        <p style={{ margin: '4px 0 0 0', color: '#94a3b8' }}>Food-bank fulfillment control plane reserved for UI integration</p>
      </header>

      {loading ? (
        <p>Connecting to Full Shelf control plane services...</p>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
          <section style={{ backgroundColor: '#1e293b', padding: '16px', borderRadius: '8px' }}>
            <h2>Morning Plan Active Revision ({plan?.active_plan_revision})</h2>
            <p>Tenant: {plan?.tenant_id}</p>
            <h3>Truck Assignments</h3>
            <ul>
              {plan?.trucks.map((t) => (
                <li key={t.vehicle_id}>
                  {t.name}: {t.assigned_cases} / {t.capacity} cases
                </li>
              ))}
            </ul>
          </section>

          <section style={{ backgroundColor: '#1e293b', padding: '16px', borderRadius: '8px' }}>
            <h2>System Evidence & Security</h2>
            <p>Project: {evidence?.gcp_project_id}</p>
            <p>Region: {evidence?.region}</p>
            <p>Spanner Database: {evidence?.spanner_database}</p>
            <p>Recorded Receipts: {evidence?.total_receipts_recorded}</p>
          </section>
        </div>
      )}
    </div>
  );
};
