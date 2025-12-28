import { fetchSnapshotDetail } from '$lib/api/client';

export async function load({ params }) {
  const data = await fetchSnapshotDetail(params.slug);
  return { snapshot: data };
}
