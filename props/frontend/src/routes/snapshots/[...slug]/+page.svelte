<script lang="ts">
  import { page } from '$app/stores';
  import { base } from '$app/paths';
  import { toast } from 'svelte-sonner';
  import { splitBadgeClass } from '$lib/colors';
  import type { SnapshotDetailResponse, FileContentResponse } from '$lib/api/client';
  import { fetchSnapshotFile } from '$lib/api/client';
  import FileTree from '../../../components/FileTree.svelte';
  import FileViewer from '../../../components/FileViewer.svelte';
  import TabButton from '../../../components/TabButton.svelte';
  import Breadcrumb from '../../../components/Breadcrumb.svelte';
  import CopyButton from '../../../components/CopyButton.svelte';
  import { createExpansionState } from '$lib/expansionState.svelte';

  let { data } = $props();
  const snapshot = $derived(data.snapshot as SnapshotDetailResponse);

  const expandedIssues = createExpansionState();
  let activeTab: 'files' | 'tps' | 'fps' = $state('files');
  let selectedFile: FileContentResponse | null = $state(null);
  let loadingFile = $state(false);
  let targetOccurrenceId = $state<string | null>(null);

  // Breadcrumb items for file viewer
  const breadcrumbs = $derived.by(() => {
    if (!selectedFile) return [{ label: snapshot.slug }];

    const parts = selectedFile.path.split('/');
    const items: Array<{ label: string; href?: string }> = [
      { label: snapshot.slug, href: `${base}/snapshots/${data.slug}` },
    ];

    parts.forEach((part, i) => {
      if (i < parts.length - 1) {
        items.push({ label: part });
      } else {
        items.push({ label: part });
      }
    });

    return items;
  });

  function formatFileLocation(file: {
    path: string;
    ranges: Array<{ start_line: number; end_line: number }> | null;
  }): string {
    if (!file.ranges || file.ranges.length === 0) {
      return file.path;
    }
    const rangeStrs = file.ranges.map((r) =>
      r.start_line === r.end_line ? `${r.start_line}` : `${r.start_line}-${r.end_line}`
    );
    return `${file.path}:${rangeStrs.join(',')}`;
  }

  async function handleFileClick(path: string) {
    loadingFile = true;
    try {
      selectedFile = await fetchSnapshotFile(data.slug, path);
    } catch (error) {
      toast.error(`Failed to load file: ${error}`);
    } finally {
      loadingFile = false;
    }
  }

  // Generate URL for occurrence
  function getOccurrenceUrl(issueId: string, occurrenceId: string, filePath?: string): string {
    const path = filePath ? `${base}/snapshots/${data.slug}` : $page.url.pathname;
    const url = new URL(path, $page.url);
    url.hash = `${issueId}/${occurrenceId}`;
    return url.toString();
  }

  // Parse URL fragment and handle deep linking
  $effect(() => {
    const hash = $page.url.hash.slice(1);
    if (hash) {
      const [issueId, occurrenceId] = hash.split('/');
      if (issueId && occurrenceId) {
        targetOccurrenceId = occurrenceId;

        // Find the occurrence and open its file
        for (const tp of snapshot.true_positives) {
          if (tp.tp_id === issueId) {
            const occ = tp.occurrences.find((o) => o.occurrence_id === occurrenceId);
            if (occ && occ.files.length > 0) {
              handleFileClick(occ.files[0].path);
              expandedIssues.expand(issueId);
              activeTab = 'files';

              // Scroll to occurrence after a short delay
              setTimeout(() => {
                const elem = document.getElementById(`${issueId}-${occurrenceId}`);
                elem?.scrollIntoView({ behavior: 'smooth', block: 'center' });
              }, 100);
            }
            break;
          }
        }

        for (const fp of snapshot.false_positives) {
          if (fp.fp_id === issueId) {
            const occ = fp.occurrences.find((o) => o.occurrence_id === occurrenceId);
            if (occ && occ.files.length > 0) {
              handleFileClick(occ.files[0].path);
              expandedIssues.expand(issueId);
              activeTab = 'files';

              setTimeout(() => {
                const elem = document.getElementById(`${issueId}-${occurrenceId}`);
                elem?.scrollIntoView({ behavior: 'smooth', block: 'center' });
              }, 100);
            }
            break;
          }
        }
      }
    }
  });
</script>

<div class="bg-white rounded-lg shadow">
  <!-- Header -->
  <div class="px-4 py-3 border-b flex justify-between items-center">
    <div class="flex items-center gap-3">
      <a href="{base}/snapshots" class="text-gray-500 hover:text-gray-700">← Back</a>
      <h2 class="text-xl font-semibold font-mono">{snapshot.slug}</h2>
      <span class="px-2 py-1 text-xs font-medium rounded {splitBadgeClass(snapshot.split)}">
        {snapshot.split}
      </span>
    </div>
  </div>

  <!-- Tabs -->
  <div class="border-b">
    <nav class="flex -mb-px">
      <TabButton active={activeTab === 'files'} onclick={() => (activeTab = 'files')}>Files</TabButton>
      <TabButton active={activeTab === 'tps'} onclick={() => (activeTab = 'tps')}>
        True Positives ({snapshot.true_positives.length})
      </TabButton>
      <TabButton active={activeTab === 'fps'} onclick={() => (activeTab = 'fps')}>
        False Positives ({snapshot.false_positives.length})
      </TabButton>
    </nav>
  </div>

  <!-- Content -->
  <div class="p-4">
    {#if activeTab === 'files'}
      <div class="grid grid-cols-2 gap-4">
        <!-- File Tree -->
        <div class="overflow-y-auto max-h-[70vh]">
          <h3 class="text-sm font-medium mb-2">File Browser</h3>
          <FileTree nodes={data.tree.tree} onFileClick={handleFileClick} selectedPath={selectedFile?.path} />
        </div>

        <!-- File Viewer -->
        <div class="overflow-y-auto max-h-[70vh]">
          {#if loadingFile}
            <div class="flex items-center justify-center h-full text-gray-500">Loading...</div>
          {:else if selectedFile}
            <div class="mb-3">
              <Breadcrumb items={breadcrumbs} />
            </div>
            <FileViewer
              file={selectedFile}
              tps={snapshot.true_positives}
              fps={snapshot.false_positives}
              snapshotSlug={snapshot.slug}
              {targetOccurrenceId}
            />
          {:else}
            <div class="flex items-center justify-center h-full text-gray-500">Select a file to view</div>
          {/if}
        </div>
      </div>
    {:else if activeTab === 'tps'}
      <div class="max-h-[70vh] overflow-y-auto">
        {#if snapshot.true_positives.length === 0}
          <p class="text-gray-500">No true positives</p>
        {:else}
          <div class="space-y-2">
            {#each snapshot.true_positives as tp}
              <div class="border rounded">
                <button
                  class="w-full px-3 py-2 flex justify-between items-center hover:bg-gray-50 text-left"
                  onclick={() => expandedIssues.toggle(tp.tp_id)}
                >
                  <div class="flex items-center gap-2">
                    <span class="text-gray-400">{expandedIssues.isExpanded(tp.tp_id) ? '▼' : '▶'}</span>
                    <span class="font-mono text-sm font-medium">{tp.tp_id}</span>
                    <span class="text-xs text-gray-500">({tp.occurrences.length} occ)</span>
                  </div>
                </button>

                {#if expandedIssues.isExpanded(tp.tp_id)}
                  <div class="px-3 pb-3 border-t bg-gray-50">
                    <div class="mt-2">
                      <h4 class="text-xs font-medium text-gray-500 uppercase mb-1">Rationale</h4>
                      <p class="text-sm whitespace-pre-wrap">{tp.rationale}</p>
                    </div>
                    <div class="mt-3">
                      <h4 class="text-xs font-medium text-gray-500 uppercase mb-1">Occurrences</h4>
                      {#each tp.occurrences as occ}
                        <div
                          id="{tp.tp_id}-{occ.occurrence_id}"
                          class="bg-white border rounded p-2 mt-1 {targetOccurrenceId === occ.occurrence_id
                            ? 'ring-2 ring-blue-500'
                            : ''}"
                        >
                          <div class="flex items-center justify-between">
                            <div class="text-xs font-mono text-gray-600">{occ.occurrence_id}</div>
                            <CopyButton
                              text={getOccurrenceUrl(tp.tp_id, occ.occurrence_id, occ.files[0]?.path)}
                              label="Copy URL"
                            />
                          </div>
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
                              Expected recall scopes: {occ.critic_scopes_expected_to_recall
                                .map((f: string[]) => f.join(', '))
                                .join(' | ')}
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
      </div>
    {:else}
      <div class="max-h-[70vh] overflow-y-auto">
        {#if snapshot.false_positives.length === 0}
          <p class="text-gray-500">No false positives</p>
        {:else}
          <div class="space-y-2">
            {#each snapshot.false_positives as fp}
              <div class="border rounded">
                <button
                  class="w-full px-3 py-2 flex justify-between items-center hover:bg-gray-50 text-left"
                  onclick={() => expandedIssues.toggle(fp.fp_id)}
                >
                  <div class="flex items-center gap-2">
                    <span class="text-gray-400">{expandedIssues.isExpanded(fp.fp_id) ? '▼' : '▶'}</span>
                    <span class="font-mono text-sm font-medium">{fp.fp_id}</span>
                    <span class="text-xs text-gray-500">({fp.occurrences.length} occ)</span>
                  </div>
                </button>

                {#if expandedIssues.isExpanded(fp.fp_id)}
                  <div class="px-3 pb-3 border-t bg-gray-50">
                    <div class="mt-2">
                      <h4 class="text-xs font-medium text-gray-500 uppercase mb-1">Rationale</h4>
                      <p class="text-sm whitespace-pre-wrap">{fp.rationale}</p>
                    </div>
                    <div class="mt-3">
                      <h4 class="text-xs font-medium text-gray-500 uppercase mb-1">Occurrences</h4>
                      {#each fp.occurrences as occ}
                        <div
                          id="{fp.fp_id}-{occ.occurrence_id}"
                          class="bg-white border rounded p-2 mt-1 {targetOccurrenceId === occ.occurrence_id
                            ? 'ring-2 ring-blue-500'
                            : ''}"
                        >
                          <div class="flex items-center justify-between">
                            <div class="text-xs font-mono text-gray-600">{occ.occurrence_id}</div>
                            <CopyButton
                              text={getOccurrenceUrl(fp.fp_id, occ.occurrence_id, occ.files[0]?.path)}
                              label="Copy URL"
                            />
                          </div>
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
      </div>
    {/if}
  </div>
</div>
