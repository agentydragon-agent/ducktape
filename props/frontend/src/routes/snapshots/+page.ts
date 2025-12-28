import { fetchSnapshots } from '$lib/api/client';

export async function load() {
  const data = await fetchSnapshots();
  return { snapshots: data.snapshots };
}
