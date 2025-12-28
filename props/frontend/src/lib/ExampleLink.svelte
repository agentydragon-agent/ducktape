<script lang="ts">
  // Link component for examples
  // - For whole_snapshot: displays "whole@{slug}"
  // - For file_set: displays "files@{slug}/{hash}"
  // - Links to /examples?snapshot_slug=...&example_kind=...&files_hash=...

  import { formatSnapshotSlug } from './formatters';
  import type { WholeSnapshotExample, SingleFileSetExample } from './api/client';

  type Example = WholeSnapshotExample | SingleFileSetExample;

  interface Props {
    example: Example;
    onclick?: (example: Example) => void;
  }

  let { example, onclick }: Props = $props();

  const displayText = $derived(
    example.kind === 'whole_snapshot'
      ? `whole@${formatSnapshotSlug(example.snapshot_slug)}`
      : `files@${formatSnapshotSlug(example.snapshot_slug)}/${example.files_hash.slice(0, 6)}`
  );

  const href = $derived(() => {
    const params = new URLSearchParams({
      snapshot_slug: example.snapshot_slug,
      example_kind: example.kind,
    });
    if (example.kind === 'file_set') {
      params.set('files_hash', example.files_hash);
    }
    return `/examples?${params.toString()}`;
  });

  function handleClick(event: MouseEvent) {
    event.preventDefault();
    if (onclick) {
      onclick(example);
    } else {
      // Default SPA navigation via history API
      history.pushState({}, '', href());
      window.dispatchEvent(new PopStateEvent('popstate'));
    }
  }
</script>

<a href={href()} class="font-mono text-xs text-blue-600 underline hover:text-blue-800" title="{example.snapshot_slug} ({example.kind})" onclick={handleClick}>
  {displayText}
</a>
