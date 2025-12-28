/**
 * Shared formatting helpers for display.
 * All display-related transformations go here.
 */

import type { RunInfo, CriticTypeConfig } from './api/client';

/**
 * Format a snapshot slug for display.
 * Shows the first path component only (e.g., "ducktape" from "ducktape/2025-01-01").
 */
export function formatSnapshotSlug(slug: string): string {
  return slug.split('/')[0];
}

/**
 * Format a files hash for display (consistent 8 char truncation).
 */
export function formatFilesHash(hash: string): string {
  return hash.slice(0, 8);
}

/**
 * Truncate text with ellipsis.
 */
export function truncateText(text: string, maxLength: number = 100): string {
  return text.length > maxLength ? text.slice(0, maxLength) + '...' : text;
}

/**
 * Format an example for display in compact form.
 * For critic runs: "whole@slug" or "files@slug/hash"
 * For non-critics: "—"
 */
export function formatExample(run: RunInfo): string {
  if (run.type_config.agent_type !== 'critic') return '—';
  const config = run.type_config as CriticTypeConfig;
  const example = config.example;
  const slug = formatSnapshotSlug(example.snapshot_slug);
  if (example.kind === 'whole_snapshot') {
    return `whole@${slug}`;
  }
  return `files@${slug}/${formatFilesHash(example.files_hash)}`;
}
