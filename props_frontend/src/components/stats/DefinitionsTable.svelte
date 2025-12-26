<script lang="ts">
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

  function recallClass(pct: number | null | undefined): string {
    if (pct == null) return 'dim';
    if (pct >= 70) return 'recall-high';
    if (pct >= 40) return 'recall-mid';
    return 'recall-low';
  }

  function shortId(id: string): string {
    return id.length > 12 ? id.slice(0, 12) : id;
  }

  function formatAge(isoDate: string): string {
    return formatDistanceToNow(new Date(isoDate), { addSuffix: false });
  }

  // Column configs for DRY rendering
  const columns: { split: Split; kind: ExampleKind; label: string; cssClass: string }[] = [
    { split: 'valid', kind: 'whole_snapshot', label: 'Valid Whole', cssClass: 'col-group-valid' },
    { split: 'train', kind: 'whole_snapshot', label: 'Train Whole', cssClass: 'col-group-train-w' },
    { split: 'train', kind: 'file_set', label: 'Train Partial', cssClass: 'col-group-train-p' },
  ];
</script>

<table>
  <thead>
    <tr>
      <th rowspan="2">Definition</th>
      <th rowspan="2">Age</th>
      {#each columns as col}
        <th colspan="6" class="col-group {col.cssClass}">{col.label}</th>
      {/each}
    </tr>
    <tr>
      {#each columns as _}
        <th class="num">Recall</th>
        <th class="num">LCB</th>
        <th class="num">N</th>
        <th class="num">Z</th>
        <th class="num">✓</th>
        <th class="num">S</th>
      {/each}
    </tr>
  </thead>
  <tbody>
    {#each definitions as def}
      <tr>
        <td title={def.definition_id}>{shortId(def.definition_id)}</td>
        <td class="num">{formatAge(def.created_at)}</td>
        {#each columns as col}
          {@const stats = getStats(def, col.split, col.kind)}
          {#if stats}
            <td class="num {recallClass(stats.recall_pct)}">{formatPct(stats.recall_pct)}</td>
            <td class="num dim">{formatPct(stats.lcb_pct)}</td>
            <td class="num">{formatCount(stats.n_examples, stats.total_available)}</td>
            <td class="num dim">{stats.zero_count}</td>
            <td class="num">{stats.status_counts.completed ?? 0}</td>
            <td class="num dim">{stats.status_counts.max_turns_exceeded ?? 0}</td>
          {:else}
            <td class="num dim">—</td>
            <td class="num dim">—</td>
            <td class="num dim">—</td>
            <td class="num dim">—</td>
            <td class="num dim">—</td>
            <td class="num dim">—</td>
          {/if}
        {/each}
      </tr>
    {/each}
  </tbody>
</table>
