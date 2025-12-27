<script lang="ts">
  import { onMount } from 'svelte';
  import { toast } from 'svelte-sonner';
  import { fetchDefinitionDetail, type DefinitionDetailResponse } from '../lib/api/client';
  import { formatStatsWithCI } from '../lib/format';
  import { formatDistanceToNow } from 'date-fns';
  import RunsBrowser from './RunsBrowser.svelte';
  import type { Split, ExampleKind } from '../lib/types';

  interface Props {
    definitionId: string;
    onClose?: () => void;
    onSelectRun?: (runId: string) => void;
  }
  let { definitionId, onClose, onSelectRun }: Props = $props();

  let data: DefinitionDetailResponse | null = $state(null);
  let loading = $state(true);
  let copied = $state(false);

  const cliCommand = $derived(`props agent-definition fetch ${definitionId} /workspace/my_def/`);

  async function loadData() {
    loading = true;
    try {
      data = await fetchDefinitionDetail(definitionId);
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Unknown error';
      toast.error(message);
    } finally {
      loading = false;
    }
  }

  async function copyCommand() {
    await navigator.clipboard.writeText(cliCommand);
    copied = true;
    setTimeout(() => copied = false, 2000);
  }

  function formatAge(isoDate: string): string {
    return formatDistanceToNow(new Date(isoDate), { addSuffix: true });
  }

  // Column group configs (same as DefinitionsTable)
  const colGroups: { split: Split; kind: ExampleKind; label: string }[] = [
    { split: 'valid', kind: 'whole_snapshot', label: 'Valid Whole' },
    { split: 'valid', kind: 'file_set', label: 'Valid Partial' },
    { split: 'train', kind: 'whole_snapshot', label: 'Train Whole' },
    { split: 'train', kind: 'file_set', label: 'Train Partial' },
  ];

  function getStats(split: Split, kind: ExampleKind) {
    return data?.stats[split]?.[kind];
  }

  function recallClass(value: number | null | undefined): string {
    if (value == null) return 'text-gray-400';
    if (value >= 0.70) return 'text-green-600 font-medium';
    if (value >= 0.40) return 'text-yellow-600';
    return 'text-red-600';
  }

  onMount(() => {
    loadData();
  });
</script>

<div class="space-y-4">
  <!-- Header -->
  <div class="bg-white rounded-lg shadow p-4">
    <div class="flex items-center gap-3 mb-3">
      {#if onClose}
        <button
          type="button"
          class="text-sm text-gray-500 hover:text-gray-700 hover:underline"
          onclick={onClose}
        >
          ← Back
        </button>
      {/if}
      <h2 class="text-lg font-semibold">Definition Detail</h2>
    </div>

    {#if loading}
      <p class="text-gray-500 text-sm">Loading...</p>
    {:else if data}
      <div class="space-y-3">
        <!-- Definition ID and metadata -->
        <div class="flex items-center gap-4 text-sm">
          <span class="font-mono text-blue-600">{data.definition_id}</span>
          <span class="text-gray-400">|</span>
          <span class="text-gray-600">{data.agent_type}</span>
          <span class="text-gray-400">|</span>
          <span class="text-gray-600">{formatAge(data.created_at)}</span>
        </div>

        <!-- CLI command -->
        <div class="flex items-center gap-2">
          <code class="flex-1 bg-gray-100 px-3 py-2 rounded text-sm font-mono text-gray-800 overflow-x-auto">
            {cliCommand}
          </code>
          <button
            type="button"
            class="px-3 py-2 text-sm border rounded hover:bg-gray-50 whitespace-nowrap"
            onclick={copyCommand}
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      </div>
    {/if}
  </div>

  <!-- Stats table -->
  {#if data}
    <div class="bg-white rounded-lg shadow p-4">
      <h3 class="text-sm font-medium text-gray-700 mb-3">Recall by Split/Kind</h3>
      <div class="overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead>
            <tr class="border-b border-gray-300">
              <th class="px-3 py-2 text-left">Split/Kind</th>
              <th class="px-3 py-2 text-right">Recall</th>
              <th class="px-3 py-2 text-right">N</th>
              <th class="px-3 py-2 text-right">Zero</th>
              <th class="px-3 py-2 text-right">Completed</th>
              <th class="px-3 py-2 text-right">Max Turns</th>
            </tr>
          </thead>
          <tbody>
            {#each colGroups as { split, kind, label }}
              {@const stats = getStats(split, kind)}
              <tr class="border-b border-gray-100">
                <td class="px-3 py-2 font-medium">{label}</td>
                {#if stats}
                  <td class="px-3 py-2 text-right {recallClass(stats.recall_stats?.mean)}">
                    {stats.recall_stats ? formatStatsWithCI(stats.recall_stats) : '—'}
                  </td>
                  <td class="px-3 py-2 text-right">
                    {stats.n_examples}/{stats.total_available}
                  </td>
                  <td class="px-3 py-2 text-right text-gray-400">{stats.zero_count}</td>
                  <td class="px-3 py-2 text-right">{stats.status_counts?.completed ?? 0}</td>
                  <td class="px-3 py-2 text-right text-gray-400">{stats.status_counts?.max_turns_exceeded ?? 0}</td>
                {:else}
                  <td class="px-3 py-2 text-right text-gray-300">—</td>
                  <td class="px-3 py-2 text-right text-gray-300">—</td>
                  <td class="px-3 py-2 text-right text-gray-300">—</td>
                  <td class="px-3 py-2 text-right text-gray-300">—</td>
                  <td class="px-3 py-2 text-right text-gray-300">—</td>
                {/if}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}

  <!-- Runs for this definition -->
  <RunsBrowser
    initialDefinitionId={definitionId}
    onSelectRun={onSelectRun}
  />
</div>
