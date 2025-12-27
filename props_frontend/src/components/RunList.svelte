<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { toast } from 'svelte-sonner';
  import { fetchActiveRuns, type ActiveRunInfo, type AgentRunStatus } from '../lib/api/client';
  import RunIdLink from '../lib/RunIdLink.svelte';
  import DefinitionIdLink from '../lib/DefinitionIdLink.svelte';

  // Props
  interface Props {
    onSelectRun?: (runId: string) => void;
  }
  let { onSelectRun }: Props = $props();

  // State
  let runs: ActiveRunInfo[] = $state([]);
  let loading = $state(true);
  let pollInterval: ReturnType<typeof setInterval> | null = null;

  // Status badge colors
  function getStatusColor(status: AgentRunStatus): string {
    switch (status) {
      case 'in_progress':
        return 'bg-blue-100 text-blue-800';
      case 'completed':
        return 'bg-green-100 text-green-800';
      case 'max_turns_exceeded':
      case 'context_length_exceeded':
        return 'bg-yellow-100 text-yellow-800';
      case 'reported_failure':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  }

  // Format status for display
  function formatStatus(status: AgentRunStatus): string {
    return status.replace(/_/g, ' ');
  }

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

  function handleClick(runId: string) {
    if (onSelectRun) {
      onSelectRun(runId);
    }
  }
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
        <button
          type="button"
          onclick={() => handleClick(run.agent_run_id)}
          class="w-full text-left p-3 rounded border hover:bg-gray-50 transition-colors"
        >
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-3">
              <RunIdLink id={run.agent_run_id} />
              <DefinitionIdLink id={run.definition_id} />
            </div>
            <div class="flex items-center gap-2">
              <span class="text-xs text-gray-500">{run.model}</span>
              <span class="px-2 py-0.5 rounded text-xs font-medium capitalize {getStatusColor(run.status)}">
                {formatStatus(run.status)}
              </span>
            </div>
          </div>
        </button>
      {/each}
    </div>
  {/if}
</div>
