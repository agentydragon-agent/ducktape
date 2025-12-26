<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchOverview } from './lib/api';
  import type { OverviewResponse } from './lib/types';
  import DefinitionsTable from './components/stats/DefinitionsTable.svelte';

  let data: OverviewResponse | null = $state(null);
  let error: string | null = $state(null);
  let loading = $state(true);

  onMount(async () => {
    try {
      data = await fetchOverview();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Unknown error';
    } finally {
      loading = false;
    }
  });
</script>

<h1>Props Dashboard</h1>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p style="color: red;">Error: {error}</p>
{:else if data}
  <p>
    {data.total_definitions} definitions
  </p>
  <DefinitionsTable definitions={data.definitions} />
{/if}
