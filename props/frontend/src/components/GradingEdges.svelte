<script lang="ts">
  import type { GradingEdgeInfo, MissedOccurrenceInfo } from '../lib/api/client';

  interface Props {
    edges: GradingEdgeInfo[];
    missedOccurrences?: MissedOccurrenceInfo[];
    totalCredit?: number;
    nCatchable?: number;
    defaultOpen?: boolean;
  }

  let { edges, missedOccurrences = [], totalCredit, nCatchable, defaultOpen = false }: Props = $props();

  const creditSummary = $derived(
    totalCredit != null && nCatchable != null ? `${totalCredit.toFixed(1)}/${nCatchable} credit` : null
  );

  // Group edges by type
  const tpEdges = $derived(edges.filter(e => e.target.kind === 'tp'));
  const fpEdges = $derived(edges.filter(e => e.target.kind === 'fp'));
  const unmatchedEdges = $derived(edges.filter(e => e.target.kind === 'none'));
</script>

{#if edges.length > 0 || missedOccurrences.length > 0}
  <details open={defaultOpen}>
    <summary class="cursor-pointer text-gray-500 hover:text-gray-700 text-xs">
      Grading Edges ({edges.length})
      {#if creditSummary}
        <span class="text-gray-400">— {creditSummary}</span>
      {/if}
    </summary>
    <div class="mt-2 space-y-2">
      <!-- Matched TPs -->
      {#if tpEdges.length > 0}
        <div class="text-xs font-medium text-green-600 mb-1">Matched TPs ({tpEdges.length}):</div>
        {#each tpEdges as edge}
          {@const target = edge.target}
          <div class="p-2 rounded border text-xs bg-green-50 border-green-200">
            <div class="flex items-center gap-2 mb-1">
              <span class="font-mono font-medium">{edge.critique_issue_id}</span>
              <span class="text-gray-400">→</span>
              {#if target.kind === 'tp'}
                <span class="text-green-600">{target.tp_id}/{target.occurrence_id}</span>
                <span class="text-green-600 font-medium">(+{target.credit.toFixed(2)} credit)</span>
              {/if}
            </div>
            <div class="text-gray-600">{edge.rationale}</div>
          </div>
        {/each}
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

      <!-- Unmatched (novel findings) -->
      {#if unmatchedEdges.length > 0}
        <div class="mt-3 pt-2 border-t border-gray-200">
          <div class="text-xs font-medium text-gray-500 mb-1">Unmatched ({unmatchedEdges.length}):</div>
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

      <!-- Missed catchable occurrences -->
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
