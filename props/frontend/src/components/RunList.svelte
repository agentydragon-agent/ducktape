<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { fetchActiveRuns, type ActiveRunInfo } from '../lib/api/client';
  import { getStatusColor, formatStatus } from '../lib/status';
  import DefinitionIdLink from '../lib/DefinitionIdLink.svelte';

  // State
  let runs: ActiveRunInfo[] = $state([]);
  let loading = $state(true);
  let pollInterval: ReturnType<typeof setInterval> | null = null;

  // Load runs
  async function loadRuns() {
    try {
      const result = await fetchActiveRuns();
      runs = result.runs;
    } catch (e) {
      console.warn('Failed to load runs:', e instanceof Error ? e.message : String(e));
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    loadRuns();
    // Poll every 2 seconds
    pollInterval = setInterval(loadRuns, 2000);
  });

  onDestroy(() => {
    if (pollInterval) clearInterval(pollInterval);
  });
</script>

<div class="bg-white rounded-lg shadow p-4">
  <h2 class="text-lg font-semibold mb-3">Active Runs</h2>

  {#if loading}
    <p class="text-gray-500 text-sm">Loading...</p>
  {:else if runs.length === 0}
    <p class="text-gray-500 text-sm">No active runs</p>
  {:else}
    <div class="space-y-2">
      {#each runs as run}
        <a
          href="/runs/{run.agent_run_id}"
          class="block w-full text-left p-3 rounded border hover:bg-gray-50 transition-colors"
        >
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-3">
              <span class="font-mono text-blue-600 truncate" title={run.agent_run_id}>{run.agent_run_id}</span>
              <DefinitionIdLink id={run.definition_id} />
            </div>
            <div class="flex items-center gap-2">
              <span class="text-xs text-gray-500">{run.model}</span>
              <span class="px-2 py-0.5 rounded text-xs font-medium capitalize {getStatusColor(run.status)}">
                {formatStatus(run.status)}
              </span>
            </div>
          </div>
        </a>
      {/each}
    </div>
  {/if}
</div>
