<script lang="ts">
  import { onMount } from 'svelte';
  import { toast } from 'svelte-sonner';
  import {
    fetchDefinitions,
    fetchActiveRuns,
    fetchJobs,
    triggerValidationRuns,
    type DefinitionInfo,
    type ActiveRunInfo,
    type JobInfo,
  } from '../lib/api/client';

  // State
  let definitions: DefinitionInfo[] = $state([]);
  let activeRuns: ActiveRunInfo[] = $state([]);
  let jobs: JobInfo[] = $state([]);
  let selectedDefinition: string = $state('');
  let exampleKind: 'whole_snapshot' | 'file_set' = $state('whole_snapshot');
  let nSamples: number = $state(5);
  let loading = $state(false);

  // Load critic definitions on mount
  onMount(async () => {
    try {
      const result = await fetchDefinitions('critic');
      definitions = result.definitions;
      if (definitions.length > 0) {
        selectedDefinition = definitions[0].id;
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to load definitions';
      toast.error(message);
    }

    // Poll for status
    pollStatus();
  });

  async function pollStatus() {
    try {
      const [runsResult, jobsResult] = await Promise.all([
        fetchActiveRuns(),
        fetchJobs(),
      ]);
      activeRuns = runsResult.runs;
      jobs = jobsResult.jobs;
    } catch (e) {
      // Log polling errors but don't spam toasts
      console.warn('Status poll failed:', e instanceof Error ? e.message : String(e));
    }
    // Poll every 2 seconds
    setTimeout(pollStatus, 2000);
  }

  async function handleTrigger() {
    if (!selectedDefinition) return;

    loading = true;

    try {
      const result = await triggerValidationRuns({
        definition_id: selectedDefinition,
        example_kind: exampleKind,
        n_samples: nSamples,
        critic_model: 'gpt-5.1-codex-mini',
        grader_model: 'gpt-5.1-codex-mini',
      });
      toast.success(result.message);
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to trigger runs';
      toast.error(message);
    } finally {
      loading = false;
    }
  }
</script>

<div class="bg-white rounded-lg shadow p-4 mb-4">
  <h2 class="text-lg font-semibold mb-3">Trigger Validation Runs</h2>

  <div class="grid grid-cols-4 gap-4 mb-4">
    <!-- Definition selector -->
    <div>
      <label class="block text-sm text-gray-600 mb-1">Critic Definition</label>
      <select
        bind:value={selectedDefinition}
        class="w-full border rounded px-2 py-1 text-sm"
        disabled={loading}
      >
        {#each definitions as def}
          <option value={def.id}>{def.id}</option>
        {/each}
      </select>
    </div>

    <!-- Example kind -->
    <div>
      <label class="block text-sm text-gray-600 mb-1">Example Kind</label>
      <select
        bind:value={exampleKind}
        class="w-full border rounded px-2 py-1 text-sm"
        disabled={loading}
      >
        <option value="whole_snapshot">Whole Snapshot</option>
        <option value="file_set">File Set</option>
      </select>
    </div>

    <!-- Number of samples -->
    <div>
      <label class="block text-sm text-gray-600 mb-1">Samples (1-50)</label>
      <input
        type="number"
        bind:value={nSamples}
        min="1"
        max="50"
        class="w-full border rounded px-2 py-1 text-sm"
        disabled={loading}
      />
    </div>

    <!-- Trigger button -->
    <div class="flex items-end">
      <button
        onclick={handleTrigger}
        disabled={loading || !selectedDefinition}
        class="w-full bg-blue-600 text-white px-4 py-1 rounded text-sm hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
      >
        {loading ? 'Running...' : 'Run Validation'}
      </button>
    </div>
  </div>

  <!-- Jobs -->
  {#if jobs.length > 0}
    <div class="mt-4 border-t pt-3">
      <h3 class="text-sm font-medium text-gray-700 mb-2">Validation Jobs ({jobs.length})</h3>
      <div class="space-y-2">
        {#each jobs as job}
          <div class="text-xs bg-gray-50 p-2 rounded">
            <div class="flex gap-4 items-center">
              <span class="font-mono text-gray-500">{job.job_id.slice(0, 8)}...</span>
              <span class="font-medium">{job.definition_id}</span>
              <span class="text-gray-500">{job.example_kind}</span>
              <span class="{job.status === 'running' ? 'text-blue-600' : job.status === 'completed' ? 'text-green-600' : 'text-red-600'}">
                {job.status}
              </span>
              <span class="text-gray-600">
                {job.completed}/{job.n_samples} done
                {#if job.failed > 0}
                  <span class="text-red-500">({job.failed} failed)</span>
                {/if}
              </span>
            </div>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  <!-- Active runs (individual agents from registry) -->
  {#if activeRuns.length > 0}
    <div class="mt-4 border-t pt-3">
      <h3 class="text-sm font-medium text-gray-700 mb-2">Active Agent Runs ({activeRuns.length})</h3>
      <div class="space-y-1">
        {#each activeRuns as run}
          <div class="text-xs text-gray-600 flex gap-4">
            <span class="font-mono">{run.agent_run_id.slice(0, 8)}...</span>
            <span>{run.definition_id}</span>
            <span class="capitalize {run.status === 'in_progress' ? 'text-blue-600' : ''}">{run.status.replace(/_/g, ' ')}</span>
          </div>
        {/each}
      </div>
    </div>
  {/if}
</div>
