<script lang="ts">
  import type { GradingEdgeInfo, MissedOccurrenceInfo } from '../lib/api/client';

  interface Props {
    edges: GradingEdgeInfo[];
    missedOccurrences?: MissedOccurrenceInfo[];
    totalCredit?: number;
    recallDenominator?: number;
    defaultOpen?: boolean;
  }

  let { edges, missedOccurrences = [], totalCredit, recallDenominator, defaultOpen = false }: Props = $props();

  const creditSummary = $derived(
    totalCredit != null && recallDenominator != null
      ? `${totalCredit.toFixed(1)}/${recallDenominator} recall`
      : null
  );

  // Filter and sort edges - in complete bipartite graph, most edges have zero credit
  // Only show non-zero credit edges prominently, collapse zeros
  const nonZeroTpEdges = $derived(
    edges
      .filter(e => e.target.kind === 'tp' && e.target.credit > 0)
      .sort((a, b) => {
        // Sort by credit descending
        const aCredit = a.target.kind === 'tp' ? a.target.credit : 0;
        const bCredit = b.target.kind === 'tp' ? b.target.credit : 0;
        return bCredit - aCredit;
      })
  );

  const zeroTpEdges = $derived(
    edges.filter(e => e.target.kind === 'tp' && e.target.credit === 0)
  );

  const fpEdges = $derived(edges.filter(e => e.target.kind === 'fp'));
  const unmatchedEdges = $derived(edges.filter(e => e.target.kind === 'none'));

  let showZeroEdges = $state(false);
</script>

{#if edges.length > 0 || missedOccurrences.length > 0}
  <details open={defaultOpen}>
    <summary class="cursor-pointer text-gray-500 hover:text-gray-700 text-xs">
      Grading ({nonZeroTpEdges.length} matches, {zeroTpEdges.length} non-matches)
      {#if creditSummary}
        <span class="text-gray-400">— {creditSummary}</span>
      {/if}
    </summary>
    <div class="mt-2 space-y-2">
      <!-- Matched TPs (non-zero credit) -->
      {#if nonZeroTpEdges.length > 0}
        <div class="text-xs font-medium text-green-600 mb-1">Matches ({nonZeroTpEdges.length}):</div>
        {#each nonZeroTpEdges as edge}
          {@const target = edge.target}
          <div class="p-2 rounded border text-xs bg-green-50 border-green-200">
            <div class="flex items-center gap-2 mb-1">
              <span class="font-mono font-medium">{edge.critique_issue_id}</span>
              <span class="text-gray-400">→</span>
              {#if target.kind === 'tp'}
                <span class="text-green-600">{target.tp_id}/{target.occurrence_id}</span>
                <span class="text-green-600 font-medium">(+{target.credit.toFixed(2)})</span>
              {/if}
            </div>
            <div class="text-gray-600">{edge.rationale}</div>
          </div>
        {/each}
      {/if}

      <!-- Zero-credit TP edges (collapsed by default) -->
      {#if zeroTpEdges.length > 0}
        <div class="mt-3 pt-2 border-t border-gray-200">
          <button
            type="button"
            onclick={() => showZeroEdges = !showZeroEdges}
            class="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
          >
            <span>{showZeroEdges ? '▼' : '▶'}</span>
            <span>Non-matches ({zeroTpEdges.length})</span>
          </button>
          {#if showZeroEdges}
            <div class="mt-2 space-y-1">
              {#each zeroTpEdges as edge}
                {@const target = edge.target}
                <div class="p-2 rounded border text-xs bg-gray-50 border-gray-200">
                  <div class="flex items-center gap-2 mb-1">
                    <span class="font-mono text-gray-500">{edge.critique_issue_id}</span>
                    <span class="text-gray-400">→</span>
                    {#if target.kind === 'tp'}
                      <span class="text-gray-500">{target.tp_id}/{target.occurrence_id}</span>
                      <span class="text-gray-400">(0.00)</span>
                    {/if}
                  </div>
                  <div class="text-gray-500 text-[11px]">{edge.rationale}</div>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      {/if}

      <!-- Matched FPs -->
      {#if fpEdges.length > 0}
        <div class="mt-3 pt-2 border-t border-gray-200">
          <div class="text-xs font-medium text-red-600 mb-1">Matched FPs ({fpEdges.length}):</div>
          {#each fpEdges as edge}
            {@const target = edge.target}
            <div class="p-2 rounded border text-xs bg-red-50 border-red-200">
              <div class="flex items-center gap-2 mb-1">
                <span class="font-mono font-medium">{edge.critique_issue_id}</span>
                <span class="text-gray-400">→</span>
                {#if target.kind === 'fp'}
                  <span class="text-red-600">{target.fp_id}/{target.occurrence_id}</span>
                {/if}
              </div>
              <div class="text-gray-600">{edge.rationale}</div>
            </div>
          {/each}
        </div>
      {/if}

      <!-- Novel Findings (novel findings) -->
      {#if unmatchedEdges.length > 0}
        <div class="mt-3 pt-2 border-t border-gray-200">
          <div class="text-xs font-medium text-gray-500 mb-1">Novel Findings ({unmatchedEdges.length}):</div>
          {#each unmatchedEdges as edge}
            <div class="p-2 rounded border text-xs bg-gray-50 border-gray-200">
              <div class="flex items-center gap-2 mb-1">
                <span class="font-mono font-medium">{edge.critique_issue_id}</span>
              </div>
              <div class="text-gray-600">{edge.rationale}</div>
            </div>
          {/each}
        </div>
      {/if}

      <!-- Missed occurrences -->
      {#if missedOccurrences.length > 0}
        <div class="mt-3 pt-2 border-t border-gray-200">
          <div class="text-xs font-medium text-red-600 mb-1">Missed ({missedOccurrences.length}):</div>
          {#each missedOccurrences as missed}
            <div class="p-2 rounded border text-xs bg-red-50 border-red-200">
              <div class="flex items-center gap-2">
                <span class="font-mono font-medium text-red-700">{missed.tp_id}/{missed.occurrence_id}</span>
              </div>
              <div class="text-gray-600 mt-1">{missed.tp_rationale}</div>
              {#if missed.occ_note}
                <div class="text-gray-500 italic mt-1">{missed.occ_note}</div>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    </div>
  </details>
{/if}
