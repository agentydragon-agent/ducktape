<script lang="ts">
  import 'highlight.js/styles/github.css';
  import { CheckCircle, XCircle } from 'lucide-svelte';
  import type { FileContentResponse, TpInfo, FpInfo } from '../lib/api/client';
  import IssueComment from './IssueComment.svelte';
  import { detectLanguage } from '../lib/fileTypes';
  import { highlightLines } from '../lib/highlighting';

  interface Props {
    file: FileContentResponse;
    tps?: TpInfo[];
    fps?: FpInfo[];
    snapshotSlug?: string;
    targetOccurrenceId?: string | null;
  }

  let { file, tps = [], fps = [], snapshotSlug, targetOccurrenceId = null }: Props = $props();

  const lines = $derived(file.content.split('\n'));
  const language = $derived(detectLanguage(file.path));
  const highlightedLines = $derived(highlightLines(lines, language));

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

  const occurrences = $derived.by<OccurrenceMarker[]>(() => {
    const result: OccurrenceMarker[] = [];

    for (const tp of tps) {
      for (const occ of tp.occurrences) {
        const fileLocation = occ.files.find((f: { path: string }) => f.path === file.path);
        if (fileLocation) {
          result.push({
            kind: 'tp',
            issueId: tp.tp_id,
            occurrenceId: occ.occurrence_id,
            rationale: tp.rationale,
            note: occ.note ?? undefined,
            ranges: fileLocation.ranges,
            allFiles: occ.files,
          });
        }
      }
    }

    for (const fp of fps) {
      for (const occ of fp.occurrences) {
        const fileLocation = occ.files.find((f: { path: string }) => f.path === file.path);
        if (fileLocation) {
          result.push({
            kind: 'fp',
            issueId: fp.fp_id,
            occurrenceId: occ.occurrence_id,
            rationale: fp.rationale,
            note: occ.note ?? undefined,
            ranges: fileLocation.ranges,
            allFiles: occ.files,
          });
        }
      }
    }

    return result;
  });

  // Map line numbers to occurrences (0-based line index)
  const lineToOccurrences = $derived.by<Map<number, OccurrenceMarker[]>>(() => {
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

  function getOccurrenceUrl(issueId: string, occurrenceId: string): string | undefined {
    if (!snapshotSlug) return undefined;
    const origin = typeof window !== 'undefined' ? window.location.origin : '';
    return `${origin}/snapshots/${snapshotSlug}#${issueId}/${occurrenceId}`;
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
            <td class="px-4 py-0.5 whitespace-pre align-top">
              {@html highlightedLines[idx] || line}
            </td>
          </tr>

          <!-- Issue comment cards (show after the first line of each occurrence's range) -->
          {#each lineOccs as occ}
            {@const isFirstLine =
              !occ.ranges || occ.ranges.length === 0 ? idx === 0 : occ.ranges.some((r) => r.start_line === idx)}
            {#if isFirstLine}
              {@const occId = `${occ.kind}-${occ.issueId}-${occ.occurrenceId}`}
              {@const isExpanded = expandedOccurrences.has(occId)}
              {@const isTargeted = targetOccurrenceId === occ.occurrenceId}
              <tr>
                <td colspan="2" class="px-4 py-1">
                  <div id="{occ.issueId}-{occ.occurrenceId}" class={isTargeted ? 'ring-2 ring-blue-500 rounded' : ''}>
                    <IssueComment
                      kind={occ.kind}
                      issueId="{occ.issueId}/{occ.occurrenceId}"
                      rationale={occ.rationale}
                      note={occ.note}
                      allFiles={occ.allFiles}
                      expanded={isExpanded}
                      onToggle={() => toggleOccurrence(occId)}
                      copyUrl={getOccurrenceUrl(occ.issueId, occ.occurrenceId)}
                    />
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
