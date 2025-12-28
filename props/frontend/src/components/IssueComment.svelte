<script lang="ts">
  import { CheckCircle, XCircle, Link, HelpCircle } from 'lucide-svelte';
  import type { GradingEdgeInfo } from '../lib/api/client';

  interface Props {
    kind: 'tp' | 'fp' | 'critique';
    issueId: string;
    rationale: string;
    note?: string;
    allFiles?: Array<{ path: string; ranges: Array<{ start_line: number; end_line: number }> | null }>;
    expanded?: boolean;
    onToggle?: () => void;
    gradingEdges?: GradingEdgeInfo[]; // For critique issues - show what they matched
    credit?: number; // For grading edge targets
  }

  let {
    kind,
    issueId,
    rationale,
    note,
    allFiles = [],
    expanded = false,
    onToggle,
    gradingEdges = [],
    credit,
  }: Props = $props();

  // Visual styling based on kind
  const styling = $derived(() => {
    switch (kind) {
      case 'tp':
        return {
          bg: 'bg-green-50',
          border: 'border-green-200',
          headerBg: 'bg-green-100',
          icon: CheckCircle,
          iconColor: 'text-green-600',
          label: 'TP',
          labelColor: 'text-green-700',
        };
      case 'fp':
        return {
          bg: 'bg-red-50',
          border: 'border-red-200',
          headerBg: 'bg-red-100',
          icon: XCircle,
          iconColor: 'text-red-600',
          label: 'FP',
          labelColor: 'text-red-700',
        };
      case 'critique': {
        // Color based on grading if available
        const hasTPMatch = gradingEdges.some((e) => e.target.kind === 'tp' && e.target.credit > 0);
        const hasFPMatch = gradingEdges.some((e) => e.target.kind === 'fp' && e.target.credit > 0);
        const isNovel = gradingEdges.some((e) => e.target.kind === 'none');

        if (hasTPMatch) {
          return {
            bg: 'bg-blue-50',
            border: 'border-blue-200',
            headerBg: 'bg-blue-100',
            icon: Link,
            iconColor: 'text-blue-600',
            label: 'Critique (TP)',
            labelColor: 'text-blue-700',
          };
        } else if (hasFPMatch) {
          return {
            bg: 'bg-orange-50',
            border: 'border-orange-200',
            headerBg: 'bg-orange-100',
            icon: Link,
            iconColor: 'text-orange-600',
            label: 'Critique (FP)',
            labelColor: 'text-orange-700',
          };
        } else if (isNovel) {
          return {
            bg: 'bg-gray-50',
            border: 'border-gray-200',
            headerBg: 'bg-gray-100',
            icon: HelpCircle,
            iconColor: 'text-gray-600',
            label: 'Critique (Novel)',
            labelColor: 'text-gray-700',
          };
        } else {
          return {
            bg: 'bg-blue-50',
            border: 'border-blue-200',
            headerBg: 'bg-blue-100',
            icon: Link,
            iconColor: 'text-blue-600',
            label: 'Critique',
            labelColor: 'text-blue-700',
          };
        }
    }
  });

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

<div class="border-l-4 {styling.border} {styling.bg} rounded-r shadow-sm my-2">
  <!-- Header -->
  <button
    class="w-full px-3 py-2 {styling.headerBg} flex items-center gap-2 hover:opacity-80 transition-opacity"
    onclick={onToggle}
    type="button"
  >
    <svelte:component this={styling.icon} size={16} class={styling.iconColor} />
    <span class="font-mono text-sm font-medium">{issueId}</span>
    <span class="text-xs {styling.labelColor} font-medium">{styling.label}</span>
    {#if credit !== undefined}
      <span class="text-xs text-gray-500">(+{credit.toFixed(2)})</span>
    {/if}
    <span class="ml-auto text-gray-400 text-xs">{expanded ? '▼' : '▶'}</span>
  </button>

  <!-- Content (expanded) -->
  {#if expanded}
    <div class="px-3 py-2 space-y-2 text-sm">
      <div>
        <div class="text-xs font-medium text-gray-600 mb-1">Rationale:</div>
        <div class="text-gray-800 whitespace-pre-wrap">{rationale}</div>
      </div>

      {#if note}
        <div>
          <div class="text-xs font-medium text-gray-600 mb-1">Note:</div>
          <div class="text-gray-700 italic">{note}</div>
        </div>
      {/if}

      {#if allFiles.length > 1}
        <div>
          <div class="text-xs font-medium text-gray-600 mb-1">All affected files:</div>
          {#each allFiles as file}
            <div class="font-mono text-xs text-gray-700">
              {formatFileLocation(file)}
            </div>
          {/each}
        </div>
      {/if}

      {#if kind === 'critique' && gradingEdges.length > 0}
        <div>
          <div class="text-xs font-medium text-gray-600 mb-1">Grading:</div>
          <div class="space-y-1">
            {#each gradingEdges as edge}
              {@const target = edge.target}
              {@const edgeCredit = target.kind === 'tp' || target.kind === 'fp' ? target.credit : 0}
              {#if edgeCredit > 0 || target.kind === 'none'}
                <div
                  class="text-xs p-1.5 rounded border {target.kind === 'tp'
                    ? 'bg-green-50 border-green-200'
                    : target.kind === 'fp'
                      ? 'bg-red-50 border-red-200'
                      : 'bg-gray-50 border-gray-200'}"
                >
                  <div class="flex items-center gap-2">
                    {#if target.kind === 'tp'}
                      <CheckCircle size={12} class="text-green-600" />
                      <span class="font-mono text-green-700">{target.tp_id}/{target.occurrence_id}</span>
                      <span class="text-green-600 font-medium">(+{edgeCredit.toFixed(2)})</span>
                    {:else if target.kind === 'fp'}
                      <XCircle size={12} class="text-red-600" />
                      <span class="font-mono text-red-700">{target.fp_id}/{target.occurrence_id}</span>
                      <span class="text-red-600 font-medium">(+{edgeCredit.toFixed(2)})</span>
                    {:else}
                      <HelpCircle size={12} class="text-gray-600" />
                      <span class="text-gray-600">Novel finding (no match)</span>
                    {/if}
                  </div>
                  {#if edge.rationale}
                    <div class="text-gray-600 mt-1">{edge.rationale}</div>
                  {/if}
                </div>
              {/if}
            {/each}
          </div>
        </div>
      {/if}
    </div>
  {/if}
</div>
