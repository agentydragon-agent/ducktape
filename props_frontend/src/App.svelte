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

<div class="min-h-screen bg-gray-50 p-6">
  <h1 class="text-2xl font-bold mb-4">Props Dashboard</h1>

  {#if loading}
    <p class="text-gray-500">Loading...</p>
  {:else if error}
    <p class="text-red-600">Error: {error}</p>
  {:else if data}
    <p class="text-gray-600 mb-4">{data.total_definitions} definitions</p>
    <div class="bg-white rounded-lg shadow">
      <DefinitionsTable definitions={data.definitions} />
    </div>
  {/if}
</div>
