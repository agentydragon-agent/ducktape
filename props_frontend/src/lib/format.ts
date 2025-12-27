/**
 * Formatting utilities for stats display.
 */
import type { StatsWithCI } from './types';

// Intl.NumberFormat for locale-aware percentage formatting
const pctFormatter = new Intl.NumberFormat(undefined, {
  style: 'percent',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

const pctFormatterWhole = new Intl.NumberFormat(undefined, {
  style: 'percent',
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

/**
 * Format a 0.0-1.0 value as percentage string using Intl.NumberFormat.
 */
export function formatPct(value: number, decimals = 1): string {
  return decimals === 0 ? pctFormatterWhole.format(value) : pctFormatter.format(value);
}

/**
 * Format StatsWithCI as "mean ± margin" where margin is half the CI width.
 * Example: "45.2% ± 3.1%" or "45.2% (n=10)" if no CI
 */
export function formatStatsWithCI(stats: StatsWithCI, options?: { showN?: boolean }): string {
  const mean = formatPct(stats.mean);

  if (stats.lcb95 != null && stats.ucb95 != null) {
    // Margin is half the CI width (symmetric around mean)
    const margin = (stats.ucb95 - stats.lcb95) / 2;
    return `${mean} ± ${formatPct(margin)}`;
  }

  if (options?.showN) {
    return `${mean} (n=${stats.n})`;
  }

  return mean;
}

/**
 * Format StatsWithCI compactly for table cells.
 * Example: "45.2% ± 3%"
 */
export function formatStatsCompact(stats: StatsWithCI): string {
  const mean = formatPct(stats.mean);

  if (stats.lcb95 != null && stats.ucb95 != null) {
    const margin = (stats.ucb95 - stats.lcb95) / 2;
    return `${mean} ± ${formatPct(margin, 0)}`;
  }

  return mean;
}
