import type { OverviewResponse } from './types';

const API_BASE = '/api';

/** Fetch overview stats from backend */
export async function fetchOverview(): Promise<OverviewResponse> {
  const response = await fetch(`${API_BASE}/stats/overview`);
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }
  return response.json();
}
