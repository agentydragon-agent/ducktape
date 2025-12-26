import createClient from 'openapi-fetch';
import type { paths } from './schema';

// Create typed API client
// Run `pnpm generate` with backend running to regenerate types
export const api = createClient<paths>({ baseUrl: '' });

// Convenience wrapper for overview endpoint
export async function fetchOverview() {
  const { data, error } = await api.GET('/api/stats/overview');
  if (error) throw new Error('Failed to fetch overview');
  return data;
}
