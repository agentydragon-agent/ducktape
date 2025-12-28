import { fetchExampleDetail, type ExampleKind } from '$lib/api/client';

export async function load({ url }) {
  const snapshotSlug = url.searchParams.get('snapshot_slug') ?? '';
  const exampleKind = (url.searchParams.get('example_kind') ?? 'whole_snapshot') as ExampleKind;
  const filesHash = url.searchParams.get('files_hash');

  if (!snapshotSlug) {
    return { example: null, error: 'Missing snapshot_slug parameter' };
  }

  const data = await fetchExampleDetail(snapshotSlug, exampleKind, filesHash);
  return { example: data };
}
