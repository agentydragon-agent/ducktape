<script lang="ts">
  import { page } from '$app/stores';
  import { getContext } from 'svelte';
  import RunsBrowser from '$components/RunsBrowser.svelte';
  import type { Split, ExampleKind } from '$lib/types';

  const runModal = getContext<{
    open: (_prefill?: { definitionId?: string; split?: Split; kind?: ExampleKind }) => void;
  }>('runModal');

  // Parse query params
  const definitionId = $derived($page.url.searchParams.get('definition') ?? undefined);
  const split = $derived($page.url.searchParams.get('split') as Split | undefined);
  const kind = $derived($page.url.searchParams.get('kind') as ExampleKind | undefined);

  function handleTriggerRun(prefill: { definitionId: string; split: Split; kind: ExampleKind }) {
    runModal?.open(prefill);
  }
</script>

<RunsBrowser
  initialDefinitionId={definitionId}
  initialSplit={split}
  initialKind={kind}
  onTriggerRun={handleTriggerRun}
/>
