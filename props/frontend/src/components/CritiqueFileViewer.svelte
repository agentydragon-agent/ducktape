<script lang="ts">
  import 'highlight.js/styles/github.css';
  import type { FileContentResponse, TpInfo, FpInfo, GradingEdgeInfo } from '../lib/api/client';
  import IssueComment from './IssueComment.svelte';
  import { detectLanguage } from '../lib/fileTypes';
  import { highlightLines } from '../lib/highlighting';

  interface CritiqueIssue {
    id: string;
    rationale: string;
    note?: string;
    ranges: Array<{ start_line: number; end_line: number }> | null;
    allFiles: Array<{ path: string; ranges: Array<{ start_line: number; end_line: number }> | null }>;
  }

  interface Props {
    file: FileContentResponse;
    tps: TpInfo[];
    fps: FpInfo[];
    critiqueIssues: CritiqueIssue[];
    gradingEdges: GradingEdgeInfo[];
  }

  let { file, tps, fps, critiqueIssues, gradingEdges }: Props = $props();

  const lines = $derived(file.content.split('\n'));
  const language = $derived(detectLanguage(file.path));
  const highlightedLines = $derived(highlightLines(lines, language));

  // Unified issue marker interface
  interface IssueMarker {
    kind: 'tp' | 'fp' | 'critique';
    issueId: string;
    occurrenceId?: string;
    rationale: string;
    note?: string;
    ranges: Array<{ start_line: number; end_line: number }> | null;
    allFiles: Array<{ path: string; ranges: Array<{ start_line: number; end_line: number }> | null }>;
    gradingEdges?: GradingEdgeInfo[];
  }

  // Combine all issues (TPs, FPs, and critique issues) that reference this file
  const allIssues = $derived<IssueMarker[]>(() => {
    const result: IssueMarker[] = [];

    // Add TPs
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

    // Add FPs
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

    // Add critique issues
    for (const issue of critiqueIssues) {
      const fileLocation = issue.allFiles.find((f) => f.path === file.path);
      if (fileLocation) {
        // Find grading edges for this critique issue
        const edges = gradingEdges.filter((e) => e.critique_issue_id === issue.id);
        result.push({
          kind: 'critique',
          issueId: issue.id,
          rationale: issue.rationale,
          note: issue.note,
          ranges: fileLocation.ranges,
          allFiles: issue.allFiles,
          gradingEdges: edges,
        });
      }
    }

    return result;
  });

  // Map line numbers to issues (0-based line index)
  const lineToIssues = $derived<Map<number, IssueMarker[]>>(() => {
    const map = new Map<number, IssueMarker[]>();

    for (const issue of allIssues) {
      if (!issue.ranges) {
        // Whole file - mark all lines
        for (let i = 0; i < lines.length; i++) {
          const existing = map.get(i) || [];
          map.set(i, [...existing, issue]);
        }
      } else {
        // Specific ranges
        for (const range of issue.ranges) {
          const startIdx = range.start_line;
          const endIdx = range.end_line;
          for (let i = startIdx; i <= endIdx; i++) {
            const existing = map.get(i) || [];
            map.set(i, [...existing, issue]);
          }
        }
      }
    }

    return map;
  });

  let expandedIssues = $state<Set<string>>(new Set());

  function toggleIssue(id: string) {
    const newSet = new Set(expandedIssues);
    if (newSet.has(id)) {
      newSet.delete(id);
    } else {
      newSet.add(id);
    }
    expandedIssues = newSet;
  }

  function getIssueKey(issue: IssueMarker): string {
    return issue.occurrenceId
      ? `${issue.kind}-${issue.issueId}-${issue.occurrenceId}`
      : `${issue.kind}-${issue.issueId}`;
  }
</script>

<div class="border rounded bg-white font-mono text-sm">
  <!-- Header -->
  <div class="px-4 py-2 border-b bg-gray-50 flex items-center gap-2">
    <span class="font-semibold">{file.path}</span>
    <span class="text-gray-500 text-xs">({file.line_count} lines)</span>
    <span class="text-gray-500 text-xs ml-auto">
      {allIssues.filter((i) => i.kind === 'critique').length} critique,
      {allIssues.filter((i) => i.kind === 'tp').length} TPs,
      {allIssues.filter((i) => i.kind === 'fp').length} FPs
    </span>
  </div>

  <!-- Content -->
  <div class="overflow-auto max-h-[70vh]">
    <table class="w-full">
      <tbody>
        {#each lines as line, idx}
          {@const lineIssues = lineToIssues.get(idx) || []}
          {@const hasTP = lineIssues.some((i) => i.kind === 'tp')}
          {@const hasFP = lineIssues.some((i) => i.kind === 'fp')}
          {@const hasCritique = lineIssues.some((i) => i.kind === 'critique')}
          {@const bgClass = hasTP ? 'bg-green-50' : hasFP ? 'bg-red-50' : hasCritique ? 'bg-blue-50' : ''}
          {@const borderClass = hasTP
            ? 'border-l-4 border-green-500'
            : hasFP
              ? 'border-l-4 border-red-500'
              : hasCritique
                ? 'border-l-4 border-blue-500'
                : ''}

          <tr class="hover:bg-gray-100 {bgClass} {borderClass}">
            <!-- Line number (1-based display) -->
            <td class="px-2 py-0.5 text-right text-gray-400 select-none w-12 border-r align-top">
              <span>{idx + 1}</span>
            </td>
            <!-- Line content -->
            <td class="px-4 py-0.5 whitespace-pre align-top">
              {@html highlightedLines[idx] || line}
            </td>
          </tr>

          <!-- Issue comment cards (show after the first line of each issue's range) -->
          {#each lineIssues as issue}
            {@const isFirstLine =
              !issue.ranges || issue.ranges.length === 0 ? idx === 0 : issue.ranges.some((r) => r.start_line === idx)}
            {#if isFirstLine}
              {@const issueKey = getIssueKey(issue)}
              {@const isExpanded = expandedIssues.has(issueKey)}
              <tr>
                <td colspan="2" class="px-4 py-1">
                  <IssueComment
                    kind={issue.kind}
                    issueId={issue.occurrenceId ? `${issue.issueId}/${issue.occurrenceId}` : issue.issueId}
                    rationale={issue.rationale}
                    note={issue.note}
                    allFiles={issue.allFiles}
                    expanded={isExpanded}
                    onToggle={() => toggleIssue(issueKey)}
                    gradingEdges={issue.gradingEdges}
                  />
                </td>
              </tr>
            {/if}
          {/each}
        {/each}
      </tbody>
    </table>
  </div>
</div>
