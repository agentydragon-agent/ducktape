<script lang="ts">
  import { splitBadgeClass } from '$lib/colors';
  import type { SnapshotDetailResponse } from '$lib/api/client';

  let { data } = $props();
  const snapshot = $derived(data.snapshot as SnapshotDetailResponse);

  let expandedIssues: Set<string> = $state(new Set());
  let activeTab: 'tps' | 'fps' = $state('tps');

  function toggleIssue(issueId: string) {
    const newSet = new Set(expandedIssues);
    if (newSet.has(issueId)) {
      newSet.delete(issueId);
    } else {
      newSet.add(issueId);
    }
    expandedIssues = newSet;
  }

  function formatFileLocation(file: { path: string; ranges: Array<{ start_line: number; end_line: number }> | null }): string {
    if (!file.ranges || file.ranges.length === 0) {
      return file.path;
    }
    const rangeStrs = file.ranges.map(r =>
      r.start_line === r.end_line ? `${r.start_line}` : `${r.start_line}-${r.end_line}`
    );
    return `${file.path}:${rangeStrs.join(',')}`;
  }
</script>

<div class="bg-white rounded-lg shadow">
  <!-- Header -->
  <div class="px-4 py-3 border-b flex justify-between items-center">
    <div class="flex items-center gap-3">
      <a href="/snapshots" class="text-gray-500 hover:text-gray-700">← Back</a>
      <h2 class="text-xl font-semibold font-mono">{snapshot.slug}</h2>
      <span class="px-2 py-1 text-xs font-medium rounded {splitBadgeClass(snapshot.split)}">
        {snapshot.split}
      </span>
    </div>
  </div>

  <!-- Tabs -->
  <div class="border-b">
    <nav class="flex -mb-px">
      <button
        class="px-4 py-2 font-medium text-sm border-b-2 {activeTab === 'tps' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}"
        onclick={() => activeTab = 'tps'}
      >
        True Positives ({snapshot.true_positives.length})
      </button>
      <button
        class="px-4 py-2 font-medium text-sm border-b-2 {activeTab === 'fps' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}"
        onclick={() => activeTab = 'fps'}
      >
        False Positives ({snapshot.false_positives.length})
      </button>
    </nav>
  </div>

  <!-- Content -->
  <div class="p-4 max-h-[70vh] overflow-y-auto">
    {#if activeTab === 'tps'}
      {#if snapshot.true_positives.length === 0}
        <p class="text-gray-500">No true positives</p>
      {:else}
        <div class="space-y-2">
          {#each snapshot.true_positives as tp}
            <div class="border rounded">
              <button
                class="w-full px-3 py-2 flex justify-between items-center hover:bg-gray-50 text-left"
                onclick={() => toggleIssue(tp.tp_id)}
              >
                <div class="flex items-center gap-2">
                  <span class="text-gray-400">{expandedIssues.has(tp.tp_id) ? '▼' : '▶'}</span>
                  <span class="font-mono text-sm font-medium">{tp.tp_id}</span>
                  <span class="text-xs text-gray-500">({tp.occurrences.length} occ)</span>
                </div>
              </button>

              {#if expandedIssues.has(tp.tp_id)}
                <div class="px-3 pb-3 border-t bg-gray-50">
                  <div class="mt-2">
                    <h4 class="text-xs font-medium text-gray-500 uppercase mb-1">Rationale</h4>
                    <p class="text-sm whitespace-pre-wrap">{tp.rationale}</p>
                  </div>
                  <div class="mt-3">
                    <h4 class="text-xs font-medium text-gray-500 uppercase mb-1">Occurrences</h4>
                    {#each tp.occurrences as occ}
                      <div class="bg-white border rounded p-2 mt-1">
                        <div class="text-xs font-mono text-gray-600">{occ.occurrence_id}</div>
                        <div class="mt-1">
                          {#each occ.files as file}
                            <div class="text-sm font-mono">{formatFileLocation(file)}</div>
                          {/each}
                        </div>
                        {#if occ.note}
                          <div class="mt-1 text-sm text-gray-600 italic">{occ.note}</div>
                        {/if}
                        {#if occ.critic_scopes_expected_to_recall.length > 0}
                          <div class="mt-1 text-xs text-gray-500">
                            Expected recall scopes: {occ.critic_scopes_expected_to_recall.map((f: string[]) => f.join(', ')).join(' | ')}
                          </div>
                        {/if}
                      </div>
                    {/each}
                  </div>
                </div>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    {:else}
      {#if snapshot.false_positives.length === 0}
        <p class="text-gray-500">No false positives</p>
      {:else}
        <div class="space-y-2">
          {#each snapshot.false_positives as fp}
            <div class="border rounded">
              <button
                class="w-full px-3 py-2 flex justify-between items-center hover:bg-gray-50 text-left"
                onclick={() => toggleIssue(fp.fp_id)}
              >
                <div class="flex items-center gap-2">
                  <span class="text-gray-400">{expandedIssues.has(fp.fp_id) ? '▼' : '▶'}</span>
                  <span class="font-mono text-sm font-medium">{fp.fp_id}</span>
                  <span class="text-xs text-gray-500">({fp.occurrences.length} occ)</span>
                </div>
              </button>

              {#if expandedIssues.has(fp.fp_id)}
                <div class="px-3 pb-3 border-t bg-gray-50">
                  <div class="mt-2">
                    <h4 class="text-xs font-medium text-gray-500 uppercase mb-1">Rationale</h4>
                    <p class="text-sm whitespace-pre-wrap">{fp.rationale}</p>
                  </div>
                  <div class="mt-3">
                    <h4 class="text-xs font-medium text-gray-500 uppercase mb-1">Occurrences</h4>
                    {#each fp.occurrences as occ}
                      <div class="bg-white border rounded p-2 mt-1">
                        <div class="text-xs font-mono text-gray-600">{occ.occurrence_id}</div>
                        <div class="mt-1">
                          {#each occ.files as file}
                            <div class="text-sm font-mono">{formatFileLocation(file)}</div>
                          {/each}
                        </div>
                        {#if occ.note}
                          <div class="mt-1 text-sm text-gray-600 italic">{occ.note}</div>
                        {/if}
                        {#if occ.relevant_files.length > 0}
                          <div class="mt-1 text-xs text-gray-500">
                            Relevant: {occ.relevant_files.join(', ')}
                          </div>
                        {/if}
                      </div>
                    {/each}
                  </div>
                </div>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    {/if}
  </div>
</div>
