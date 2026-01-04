import { fetchSnapshotDetail, fetchSnapshotTree } from '$lib/api/client';

export async function load({ params, url }: { params: { slug: string }; url: URL }) {
  // Parse the slug: either "snapshot-name" or "snapshot-name/issueId/occurrenceId"
  const parts = params.slug.split('/');
  const slug = parts[0];
  const issueId = parts.length >= 3 ? parts[1] : undefined;
  const occurrenceId = parts.length >= 3 ? parts[2] : undefined;
  const fileToShow = url.searchParams.get('file') || undefined;

  const [snapshot, tree] = await Promise.all([fetchSnapshotDetail(slug), fetchSnapshotTree(slug)]);
  return { snapshot, tree, slug, issueId, occurrenceId, fileToShow };
}
