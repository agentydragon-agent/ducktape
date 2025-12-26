<script lang="ts">
  import { DataTable } from '@careswitch/svelte-data-table';
  import type { DefinitionRow, SplitScopeStats, Split, ExampleKind } from '../../lib/types';
  import { formatDistanceToNow } from 'date-fns';

  interface Props {
    definitions: DefinitionRow[];
  }

  let { definitions }: Props = $props();

  function getStats(def: DefinitionRow, split: Split, kind: ExampleKind): SplitScopeStats | undefined {
    return def.stats[split]?.[kind];
  }

  function formatPct(value: number | null | undefined): string {
    if (value == null) return '—';
    return `${value.toFixed(1)}%`;
  }

  function formatCount(n: number, total: number): string {
    return `${n}/${total}`;
  }

  function formatAge(isoDate: string): string {
    return formatDistanceToNow(new Date(isoDate), { addSuffix: false });
  }

  // Column group configs
  const colGroups: { split: Split; kind: ExampleKind; label: string }[] = [
    { split: 'valid', kind: 'whole_snapshot', label: 'Valid Whole' },
    { split: 'valid', kind: 'file_set', label: 'Valid Partial' },
    { split: 'train', kind: 'whole_snapshot', label: 'Train Whole' },
    { split: 'train', kind: 'file_set', label: 'Train Partial' },
  ];

  // Create DataTable with sortable columns
  const table = $derived(new DataTable({
    data: definitions,
    columns: [
      { id: 'definition_id', key: 'definition_id', name: 'Definition', sortable: true },
      { id: 'created_at', key: 'created_at', name: 'Age', sortable: true },
      // Generate columns for each split/kind combo
      ...colGroups.flatMap(({ split, kind, label }) => [
        {
          id: `${split}_${kind}_recall`,
          key: 'stats' as keyof DefinitionRow,
          name: `${label} Recall`,
          sortable: true,
          getValue: (row: DefinitionRow) => getStats(row, split, kind)?.recall_pct ?? -1,
        },
      ]),
    ],
    initialSort: 'valid_whole_snapshot_recall',
    initialSortDirection: 'desc',
  }));

  function getSortIndicator(columnId: string): string {
    const state = table.getSortState(columnId);
    if (state === 'asc') return ' ↑';
    if (state === 'desc') return ' ↓';
    return '';
  }

  function recallClass(pct: number | null | undefined): string {
    if (pct == null) return 'text-gray-400';
    if (pct >= 70) return 'text-green-600 font-medium';
    if (pct >= 40) return 'text-yellow-600';
    return 'text-red-600';
  }

</script>

<div class="overflow-x-auto">
  <table class="min-w-full text-sm">
    <thead>
      <tr class="border-b border-gray-300">
        <th
          class="px-3 py-2 text-left cursor-pointer hover:bg-gray-100"
          onclick={() => table.toggleSort('definition_id')}
        >
          Definition{getSortIndicator('definition_id')}
        </th>
        <th
          class="px-3 py-2 text-right cursor-pointer hover:bg-gray-100"
          onclick={() => table.toggleSort('created_at')}
        >
          Age{getSortIndicator('created_at')}
        </th>
        {#each colGroups as { split, kind, label }}
          {@const colId = `${split}_${kind}_recall`}
          <th
            colspan="6"
            class="px-3 py-2 text-center border-l border-gray-200 cursor-pointer hover:bg-gray-100"
            onclick={() => table.toggleSort(colId)}
          >
            {label}{getSortIndicator(colId)}
          </th>
        {/each}
      </tr>
      <tr class="border-b border-gray-200 text-xs text-gray-500">
        <th></th>
        <th></th>
        {#each colGroups as _}
          <th class="px-2 py-1 text-right">Recall</th>
          <th class="px-2 py-1 text-right">LCB</th>
          <th class="px-2 py-1 text-right">N</th>
          <th class="px-2 py-1 text-right">Z</th>
          <th class="px-2 py-1 text-right">✓</th>
          <th class="px-2 py-1 text-right">S</th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each table.rows as def (def.definition_id)}
        <tr class="border-b border-gray-100 hover:bg-gray-50">
          <td class="px-3 py-2 font-mono text-xs">
            {def.definition_id}
          </td>
          <td class="px-3 py-2 text-right text-gray-600">
            {formatAge(def.created_at)}
          </td>
          {#each colGroups as { split, kind }}
            {@const stats = getStats(def, split, kind)}
            {#if stats}
              <td class="px-2 py-2 text-right {recallClass(stats.recall_pct)}">{formatPct(stats.recall_pct)}</td>
              <td class="px-2 py-2 text-right text-gray-400">{formatPct(stats.lcb_pct)}</td>
              <td class="px-2 py-2 text-right">{formatCount(stats.n_examples, stats.total_available)}</td>
              <td class="px-2 py-2 text-right text-gray-400">{stats.zero_count}</td>
              <td class="px-2 py-2 text-right">{stats.status_counts.completed ?? 0}</td>
              <td class="px-2 py-2 text-right text-gray-400">{stats.status_counts.max_turns_exceeded ?? 0}</td>
            {:else}
              <td class="px-2 py-2 text-right text-gray-300">—</td>
              <td class="px-2 py-2 text-right text-gray-300">—</td>
              <td class="px-2 py-2 text-right text-gray-300">—</td>
              <td class="px-2 py-2 text-right text-gray-300">—</td>
              <td class="px-2 py-2 text-right text-gray-300">—</td>
              <td class="px-2 py-2 text-right text-gray-300">—</td>
            {/if}
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
</div>
