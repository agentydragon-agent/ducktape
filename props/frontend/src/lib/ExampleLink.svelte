<script lang="ts">
  // Link component for examples
  // Uses native <a> with SvelteKit client-side navigation

  import { formatSnapshotSlug } from './formatters';
  import type { WholeSnapshotExample, SingleFileSetExample } from './api/client';

  type Example = WholeSnapshotExample | SingleFileSetExample;

  interface Props {
    example: Example;
  }

  let { example }: Props = $props();

  const displayText = $derived(
    example.kind === 'whole_snapshot'
      ? `whole@${formatSnapshotSlug(example.snapshot_slug)}`
      : `files@${formatSnapshotSlug(example.snapshot_slug)}/${example.files_hash.slice(0, 6)}`
  );

  const href = $derived.by(() => {
    const params = new URLSearchParams({
      snapshot_slug: example.snapshot_slug,
      example_kind: example.kind,
    });
    if (example.kind === 'file_set') {
      params.set('files_hash', example.files_hash);
    }
    return `/examples?${params.toString()}`;
  });
</script>

<a
  {href}
  class="font-mono text-xs text-blue-600 underline hover:text-blue-800"
  title="{example.snapshot_slug} ({example.kind})"
>
  {displayText}
</a>
