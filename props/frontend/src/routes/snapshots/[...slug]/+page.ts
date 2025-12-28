import { fetchSnapshotDetail, fetchSnapshotTree } from '$lib/api/client';

export async function load({ params }) {
  const [snapshot, tree] = await Promise.all([fetchSnapshotDetail(params.slug), fetchSnapshotTree(params.slug)]);
  return { snapshot, tree, slug: params.slug };
}
