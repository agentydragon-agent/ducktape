// Re-export types from generated schema
// Run `pnpm generate` with backend running to update
import type { components } from './api/schema';

export type OverviewResponse = components['schemas']['OverviewResponse'];
export type DefinitionRow = components['schemas']['DefinitionRow'];
export type SplitScopeStats = components['schemas']['SplitScopeStats'];
export type Split = components['schemas']['Split'];
export type ExampleKind = components['schemas']['ExampleKind'];
export type AgentRunStatus = components['schemas']['AgentRunStatus'];
