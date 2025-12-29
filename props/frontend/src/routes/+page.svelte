<script lang="ts">
  import { getContext } from 'svelte';
  import { goto } from '$app/navigation';
  import type { RunModalPrefill } from '$lib/types';
  import DefinitionsTable from '$components/stats/DefinitionsTable.svelte';
  import SummaryCards from '$components/stats/SummaryCards.svelte';
  import JobsList from '$components/JobsList.svelte';
  import RunList from '$components/RunList.svelte';

  let { data } = $props();

  const runModal = getContext<{
    open: (_?: RunModalPrefill) => void;
  }>('runModal');

  function handleNavigateToRuns(filters: RunModalPrefill) {
    const params = new URLSearchParams();
    if (filters.definitionId) params.set('definition', filters.definitionId);
    if (filters.split) params.set('split', filters.split);
    if (filters.kind) params.set('kind', filters.kind);
    const qs = params.toString();
    goto(qs ? `/runs?${qs}` : '/runs');
  }
</script>

<div>
  <JobsList onNewRun={() => runModal?.open()} />

  <div class="mb-4">
    <RunList />
  </div>

  <SummaryCards data={data.overview} />
  <div class="bg-white rounded-lg shadow">
    <DefinitionsTable
      definitions={data.overview.definitions}
      exampleCounts={data.overview.example_counts}
      onCellClick={handleNavigateToRuns}
    />
  </div>
</div>
