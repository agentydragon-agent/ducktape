<script lang="ts">
  import { CheckCircle, XCircle } from 'lucide-svelte';
  import type { FileContentResponse, TpInfo, FpInfo } from '../lib/api/client';

  interface Props {
    file: FileContentResponse;
    tps?: TpInfo[];
    fps?: FpInfo[];
  }

  let { file, tps = [], fps = [] }: Props = $props();

  const lines = $derived(file.content.split('\n'));

  // Flatten occurrences that reference this file
  interface OccurrenceMarker {
    kind: 'tp' | 'fp';
    issueId: string;
    occurrenceId: string;
    rationale: string;
    note?: string;
    ranges: Array<{ start_line: number; end_line: number }> | null;
    allFiles: Array<{ path: string; ranges: Array<{ start_line: number; end_line: number }> | null }>;
  }

  const occurrences = $derived<OccurrenceMarker[]>(() => {
    const result: OccurrenceMarker[] = [];

    for (const tp of tps) {
      for (const occ of tp.occurrences) {
        const fileLocation = occ.files.find((f) => f.path === file.path);
        if (fileLocation) {
          result.push({
            kind: 'tp',
            issueId: tp.tp_id,
            occurrenceId: occ.occurrence_id,
            rationale: tp.rationale,
            note: occ.note,
            ranges: fileLocation.ranges,
            allFiles: occ.files,
          });
        }
      }
    }

    for (const fp of fps) {
      for (const occ of fp.occurrences) {
        const fileLocation = occ.files.find((f) => f.path === file.path);
        if (fileLocation) {
          result.push({
            kind: 'fp',
            issueId: fp.fp_id,
            occurrenceId: occ.occurrence_id,
            rationale: fp.rationale,
            note: occ.note,
            ranges: fileLocation.ranges,
            allFiles: occ.files,
          });
        }
      }
    }

    return result;
  });

  // Map line numbers to occurrences (0-based line index)
  const lineToOccurrences = $derived<Map<number, OccurrenceMarker[]>>(() => {
    const map = new Map<number, OccurrenceMarker[]>();

    for (const occ of occurrences) {
      if (!occ.ranges) {
        // Whole file - mark all lines
        for (let i = 0; i < lines.length; i++) {
          const existing = map.get(i) || [];
          map.set(i, [...existing, occ]);
        }
      } else {
        // Specific ranges
        for (const range of occ.ranges) {
          // Convert from 1-based display to 0-based index
          const startIdx = range.start_line;
          const endIdx = range.end_line;
          for (let i = startIdx; i <= endIdx; i++) {
            const existing = map.get(i) || [];
            map.set(i, [...existing, occ]);
          }
        }
      }
    }

    return map;
  });

  let expandedOccurrences = $state<Set<string>>(new Set());

  function toggleOccurrence(id: string) {
    const newSet = new Set(expandedOccurrences);
    if (newSet.has(id)) {
      newSet.delete(id);
    } else {
      newSet.add(id);
    }
    expandedOccurrences = newSet;
  }

  function formatFileLocation(file: {
    path: string;
    ranges: Array<{ start_line: number; end_line: number }> | null;
  }): string {
    if (!file.ranges || file.ranges.length === 0) {
      return file.path;
    }
    const rangeStrs = file.ranges.map((r) =>
      r.start_line === r.end_line ? `${r.start_line + 1}` : `${r.start_line + 1}-${r.end_line + 1}`
    );
    return `${file.path}:${rangeStrs.join(',')}`;
  }
</script>

<div class="border rounded bg-white font-mono text-sm">
  <!-- Header -->
  <div class="px-4 py-2 border-b bg-gray-50 flex items-center gap-2">
    <span class="font-semibold">{file.path}</span>
    <span class="text-gray-500 text-xs">({file.line_count} lines)</span>
  </div>

  <!-- Content -->
  <div class="overflow-auto max-h-[70vh]">
    <table class="w-full">
      <tbody>
        {#each lines as line, idx}
          {@const lineOccs = lineToOccurrences.get(idx) || []}
          {@const hasTP = lineOccs.some((o) => o.kind === 'tp')}
          {@const hasFP = lineOccs.some((o) => o.kind === 'fp')}
          {@const bgClass = hasTP ? 'bg-green-50' : hasFP ? 'bg-red-50' : ''}
          {@const borderClass = hasTP ? 'border-l-4 border-green-500' : hasFP ? 'border-l-4 border-red-500' : ''}

          <tr class="hover:bg-gray-100 {bgClass} {borderClass}">
            <!-- Line number (1-based display) -->
            <td class="px-2 py-0.5 text-right text-gray-400 select-none w-12 border-r align-top">
              <div class="flex items-center justify-end gap-1">
                {#if lineOccs.length > 0}
                  <div class="flex gap-0.5">
                    {#each lineOccs as occ}
                      {#if occ.kind === 'tp'}
                        <CheckCircle size={12} class="text-green-600" />
                      {:else}
                        <XCircle size={12} class="text-red-600" />
                      {/if}
                    {/each}
                  </div>
                {/if}
                <span>{idx + 1}</span>
              </div>
            </td>
            <!-- Line content -->
            <td class="px-4 py-0.5 whitespace-pre align-top">{line}</td>
          </tr>

          <!-- Occurrence details (show after the first line of each occurrence's range) -->
          {#each lineOccs as occ}
            {@const isFirstLine =
              !occ.ranges || occ.ranges.length === 0 ? idx === 0 : occ.ranges.some((r) => r.start_line === idx)}
            {#if isFirstLine}
              {@const occId = `${occ.kind}-${occ.issueId}-${occ.occurrenceId}`}
              {@const isExpanded = expandedOccurrences.has(occId)}
              <tr class={occ.kind === 'tp' ? 'bg-green-50' : 'bg-red-50'}>
                <td colspan="2" class="px-2 py-1">
                  <div class="border-l-4 {occ.kind === 'tp' ? 'border-green-500' : 'border-red-500'} pl-3 text-xs">
                    <button
                      class="flex items-center gap-2 w-full hover:opacity-80"
                      onclick={() => toggleOccurrence(occId)}
                    >
                      <span class="text-gray-400">{isExpanded ? '▼' : '▶'}</span>
                      <span class="font-mono font-medium">
                        {occ.issueId}/{occ.occurrenceId}
                      </span>
                      <span class={occ.kind === 'tp' ? 'text-green-700' : 'text-red-700'}>
                        {occ.kind === 'tp' ? 'TP' : 'FP'}
                      </span>
                    </button>

                    {#if isExpanded}
                      <div class="mt-2 space-y-2 pb-2">
                        <div>
                          <div class="font-medium text-gray-600">Rationale:</div>
                          <div class="text-gray-700 whitespace-pre-wrap">{occ.rationale}</div>
                        </div>

                        {#if occ.note}
                          <div>
                            <div class="font-medium text-gray-600">Note:</div>
                            <div class="text-gray-700 italic">{occ.note}</div>
                          </div>
                        {/if}

                        {#if occ.allFiles.length > 1}
                          <div>
                            <div class="font-medium text-gray-600">All affected files:</div>
                            {#each occ.allFiles as file}
                              <div class="font-mono text-gray-700">
                                {formatFileLocation(file)}
                              </div>
                            {/each}
                          </div>
                        {/if}
                      </div>
                    {/if}
                  </div>
                </td>
              </tr>
            {/if}
          {/each}
        {/each}
      </tbody>
    </table>
  </div>
</div>
