<script lang="ts">
  import { CheckCircle, XCircle, Link, HelpCircle } from 'lucide-svelte';
  import type { GradingEdgeInfo } from '../lib/api/client';
  import { issueColors } from '../lib/colors';
  import { formatFileLocation } from '../lib/formatters';

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
  const styling = $derived.by(() => {
    switch (kind) {
      case 'tp': {
        const colors = issueColors.tp;
        return {
          ...colors,
          icon: CheckCircle,
          iconColor: colors.text,
          label: 'TP',
          labelColor: colors.textDark,
        };
      }
      case 'fp': {
        const colors = issueColors.fp;
        return {
          ...colors,
          icon: XCircle,
          iconColor: colors.text,
          label: 'FP',
          labelColor: colors.textDark,
        };
      }
      case 'critique': {
        // Color based on grading if available
        const hasTPMatch = gradingEdges.some((e) => e.target.kind === 'tp' && e.target.credit > 0);
        const hasFPMatch = gradingEdges.some((e) => e.target.kind === 'fp' && e.target.credit > 0);
        const isNovel = gradingEdges.some((e) => e.target.kind === 'none');

        if (hasTPMatch) {
          const colors = issueColors.critique;
          return {
            ...colors,
            icon: Link,
            iconColor: colors.text,
            label: 'Critique (TP)',
            labelColor: colors.textDark,
          };
        } else if (hasFPMatch) {
          const colors = issueColors.critiqueFp;
          return {
            ...colors,
            icon: Link,
            iconColor: colors.text,
            label: 'Critique (FP)',
            labelColor: colors.textDark,
          };
        } else if (isNovel) {
          const colors = issueColors.novel;
          return {
            ...colors,
            icon: HelpCircle,
            iconColor: colors.text,
            label: 'Critique (Novel)',
            labelColor: colors.textDark,
          };
        } else {
          const colors = issueColors.critique;
          return {
            ...colors,
            icon: Link,
            iconColor: colors.text,
            label: 'Critique',
            labelColor: colors.textDark,
          };
        }
      }
    }
  });
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
                {@const targetStyling =
                  target.kind === 'tp'
                    ? {
                        bg: 'bg-green-50',
                        border: 'border-green-200',
                        icon: CheckCircle,
                        iconColor: 'text-green-600',
                        textColor: 'text-green-700',
                        creditColor: 'text-green-600',
                        label: `${target.tp_id}/${target.occurrence_id}`,
                      }
                    : target.kind === 'fp'
                      ? {
                          bg: 'bg-red-50',
                          border: 'border-red-200',
                          icon: XCircle,
                          iconColor: 'text-red-600',
                          textColor: 'text-red-700',
                          creditColor: 'text-red-600',
                          label: `${target.fp_id}/${target.occurrence_id}`,
                        }
                      : {
                          bg: 'bg-gray-50',
                          border: 'border-gray-200',
                          icon: HelpCircle,
                          iconColor: 'text-gray-600',
                          textColor: 'text-gray-600',
                          creditColor: '',
                          label: 'Novel finding (no match)',
                        }}
                <div class="text-xs p-1.5 rounded border {targetStyling.bg} {targetStyling.border}">
                  <div class="flex items-center gap-2">
                    <svelte:component this={targetStyling.icon} size={12} class={targetStyling.iconColor} />
                    <span class="font-mono {targetStyling.textColor}">{targetStyling.label}</span>
                    {#if edgeCredit > 0}
                      <span class="{targetStyling.creditColor} font-medium">(+{edgeCredit.toFixed(2)})</span>
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
