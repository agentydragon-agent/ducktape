// Re-export types from generated schema
// Run `pnpm generate` with backend running to update
import type { components } from './api/schema';

export type OverviewResponse = components['schemas']['OverviewResponse'];
export type DefinitionRow = components['schemas']['DefinitionRow'];
export type SplitScopeStats = components['schemas']['SplitScopeStats'];
export type StatsWithCI = components['schemas']['StatsWithCI'];
export type Split = components['schemas']['Split'];
export type ExampleKind = components['schemas']['ExampleKind'];
export type AgentRunStatus = components['schemas']['AgentRunStatus'];

// UI-specific types
export interface RunModalPrefill {
  definitionId?: string;
  split?: Split;
  kind?: ExampleKind;
}

export interface RunTrigger {
  definitionId: string;
  split: Split;
  kind: ExampleKind;
}
