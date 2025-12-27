<script lang="ts">
  import { onMount } from 'svelte';
  import { toast } from 'svelte-sonner';
  import { DataTable } from '@careswitch/svelte-data-table';
  import { formatDistanceToNow } from 'date-fns';
  import {
    fetchRuns,
    type RunInfo,
    type AgentRunStatus,
    type AgentType,
    type RunsFilters,
    type Split,
    type ExampleKind,
    AGENT_RUN_STATUS_VALUES,
    AGENT_TYPE_VALUES,
  } from '../lib/api/client';
  import RunIdLink from '../lib/RunIdLink.svelte';
  import DefinitionIdLink from '../lib/DefinitionIdLink.svelte';
  import { formatExample } from '../lib/formatters';

  interface TriggerPrefill {
    definitionId: string;
    split: Split;
    kind: ExampleKind;
  }

  // Props
  interface Props {
    onSelectRun?: (runId: string) => void;
    initialDefinitionId?: string;
    initialSplit?: Split;
    initialKind?: ExampleKind;
    onClose?: () => void;
    onTriggerRun?: (prefill: TriggerPrefill) => void;
  }
  let { onSelectRun, initialDefinitionId, initialSplit, initialKind, onClose, onTriggerRun }: Props = $props();

  // State
  let runs: RunInfo[] = $state([]);
  let totalCount = $state(0);
  let loading = $state(true);
  let offset = $state(0);
  const limit = 50;

  // Filters
  let statusFilter: AgentRunStatus | '' = $state('');
  let agentTypeFilter: AgentType | '' = $state('');


  // Status badge colors (same as RunList)
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

  function formatStatus(status: AgentRunStatus): string {
    return status.replace(/_/g, ' ');
  }

  function formatAge(isoDate: string): string {
    return formatDistanceToNow(new Date(isoDate), { addSuffix: true });
  }

  // Build filters object
  function buildFilters(): RunsFilters {
    const filters: RunsFilters = { offset, limit };
    if (statusFilter) filters.status = statusFilter;
    if (agentTypeFilter) filters.agent_type = agentTypeFilter;
    if (initialDefinitionId) filters.definition_id = initialDefinitionId;
    if (initialSplit) filters.split = initialSplit;
    if (initialKind) filters.example_kind = initialKind;
    return filters;
  }

  // Load runs
  async function loadRuns() {
    loading = true;
    try {
      const result = await fetchRuns(buildFilters());
      runs = result?.runs ?? [];
      totalCount = result?.total_count ?? 0;
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Unknown error';
      toast.error(message);
      runs = [];
      totalCount = 0;
    } finally {
      loading = false;
    }
  }

  // Reset offset when filters change
  function handleFilterChange() {
    offset = 0;
    loadRuns();
  }

  // Pagination
  function nextPage() {
    if (offset + limit < totalCount) {
      offset += limit;
      loadRuns();
    }
  }

  function prevPage() {
    if (offset > 0) {
      offset = Math.max(0, offset - limit);
      loadRuns();
    }
  }

  // DataTable for sorting
  const table = $derived(new DataTable({
    data: runs,
    columns: [
      { id: 'agent_run_id', key: 'agent_run_id', name: 'ID', sortable: true },
      { id: 'definition_id', key: 'definition_id', name: 'Definition', sortable: true },
      { id: 'split', key: 'split', name: 'Split', sortable: true },
      { id: 'model', key: 'model', name: 'Model', sortable: true },
      { id: 'status', key: 'status', name: 'Status', sortable: true },
      { id: 'created_at', key: 'created_at', name: 'Created', sortable: true },
    ],
    initialSort: 'created_at',
    initialSortDirection: 'desc',
  }));

  function getSortIndicator(columnId: string): string {
    const state = table.getSortState(columnId);
    if (state === 'asc') return ' ↑';
    if (state === 'desc') return ' ↓';
    return '';
  }

  function handleRowClick(runId: string) {
    if (onSelectRun) {
      onSelectRun(runId);
    }
  }

  onMount(() => {
    loadRuns();
  });

  // Pagination info
  const pageStart = $derived(totalCount === 0 ? 0 : offset + 1);
  const pageEnd = $derived(Math.min(offset + limit, totalCount));
</script>

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
    <h2 class="text-lg font-semibold">
      {#if initialDefinitionId}
        Runs for <span class="font-mono text-blue-600">{initialDefinitionId}</span>
        {#if initialSplit}<span class="text-gray-500">/ {initialSplit}</span>{/if}
        {#if initialKind}<span class="text-gray-500">/ {initialKind}</span>{/if}
      {:else}
        All Runs
      {/if}
    </h2>
    <div class="flex-1"></div>
    {#if onTriggerRun && initialDefinitionId && initialSplit && initialKind}
      <button
        type="button"
        class="px-3 py-1 text-sm bg-blue-500 text-white rounded hover:bg-blue-600"
        onclick={() => onTriggerRun({ definitionId: initialDefinitionId!, split: initialSplit!, kind: initialKind! })}
      >
        + New Run
      </button>
    {/if}
  </div>

  <!-- Filters -->
  <div class="flex gap-4 mb-4">
    <div>
      <label for="runs-status-filter" class="block text-xs text-gray-500 mb-1">Status</label>
      <select
        id="runs-status-filter"
        class="border rounded px-2 py-1 text-sm"
        bind:value={statusFilter}
        onchange={handleFilterChange}
      >
        <option value="">All</option>
        {#each AGENT_RUN_STATUS_VALUES as status}
          <option value={status}>{formatStatus(status)}</option>
        {/each}
      </select>
    </div>
    <div>
      <label for="runs-agent-type-filter" class="block text-xs text-gray-500 mb-1">Agent Type</label>
      <select
        id="runs-agent-type-filter"
        class="border rounded px-2 py-1 text-sm"
        bind:value={agentTypeFilter}
        onchange={handleFilterChange}
      >
        <option value="">All</option>
        {#each AGENT_TYPE_VALUES as type}
          <option value={type}>{type}</option>
        {/each}
      </select>
    </div>
    <div class="flex-1"></div>
    <div class="self-end text-sm text-gray-600">
      {pageStart}–{pageEnd} of {totalCount}
    </div>
  </div>

  {#if loading}
    <p class="text-gray-500 text-sm">Loading...</p>
  {:else if runs.length === 0}
    <p class="text-gray-500 text-sm">No runs found</p>
  {:else}
    <div class="overflow-x-auto">
      <table class="min-w-full text-sm">
        <thead>
          <tr class="border-b border-gray-300">
            <th
              class="px-3 py-2 text-left cursor-pointer hover:bg-gray-100"
              onclick={() => table.toggleSort('agent_run_id')}
            >
              ID{getSortIndicator('agent_run_id')}
            </th>
            <th
              class="px-3 py-2 text-left cursor-pointer hover:bg-gray-100"
              onclick={() => table.toggleSort('definition_id')}
            >
              Definition{getSortIndicator('definition_id')}
            </th>
            <th
              class="px-3 py-2 text-left cursor-pointer hover:bg-gray-100"
              onclick={() => table.toggleSort('split')}
            >
              Split{getSortIndicator('split')}
            </th>
            <th class="px-3 py-2 text-left">
              Example
            </th>
            <th
              class="px-3 py-2 text-left cursor-pointer hover:bg-gray-100"
              onclick={() => table.toggleSort('model')}
            >
              Model{getSortIndicator('model')}
            </th>
            <th
              class="px-3 py-2 text-left cursor-pointer hover:bg-gray-100"
              onclick={() => table.toggleSort('status')}
            >
              Status{getSortIndicator('status')}
            </th>
            <th
              class="px-3 py-2 text-left cursor-pointer hover:bg-gray-100"
              onclick={() => table.toggleSort('created_at')}
            >
              Created{getSortIndicator('created_at')}
            </th>
          </tr>
        </thead>
        <tbody>
          {#each table.rows as run (run.agent_run_id)}
            <tr
              class="border-b border-gray-100 hover:bg-gray-50 cursor-pointer"
              onclick={() => handleRowClick(run.agent_run_id)}
            >
              <td class="px-3 py-2 text-xs">
                <RunIdLink id={run.agent_run_id} />
              </td>
              <td class="px-3 py-2 text-xs">
                <DefinitionIdLink id={run.definition_id} />
              </td>
              <td class="px-3 py-2 text-xs text-gray-500">
                {run.split ?? '—'}
              </td>
              <td class="px-3 py-2 text-xs text-gray-500 font-mono">
                {formatExample(run)}
              </td>
              <td class="px-3 py-2 text-xs text-gray-500">
                {run.model}
              </td>
              <td class="px-3 py-2">
                <span class="px-2 py-0.5 rounded text-xs font-medium capitalize {getStatusColor(run.status)}">
                  {formatStatus(run.status)}
                </span>
              </td>
              <td class="px-3 py-2 text-gray-600 text-xs">
                {formatAge(run.created_at)}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    <div class="flex justify-between items-center mt-4">
      <button
        type="button"
        class="px-3 py-1 text-sm border rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
        onclick={prevPage}
        disabled={offset === 0}
      >
        ← Previous
      </button>
      <button
        type="button"
        class="px-3 py-1 text-sm border rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
        onclick={nextPage}
        disabled={offset + limit >= totalCount}
      >
        Next →
      </button>
    </div>
  {/if}
</div>
