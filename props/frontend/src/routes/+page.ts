import { fetchOverview } from '$lib/api/client';

export async function load() {
  const data = await fetchOverview();
  return { overview: data };
}
