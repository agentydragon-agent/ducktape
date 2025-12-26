/** Split enum values from backend */
export type Split = 'train' | 'valid' | 'test';

/** ExampleKind enum values from backend */
export type ExampleKind = 'whole_snapshot' | 'file_set';

/** AgentRunStatus enum values from backend */
export type AgentRunStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'max_turns_exceeded'
  | 'context_length_exceeded'
  | 'reported_failure'
  | 'budget_exceeded';

/** Stats for a single (split, example_kind) combination */
export interface SplitScopeStats {
  recall_pct: number | null;
  lcb_pct: number | null;
  n_examples: number;
  zero_count: number;
  status_counts: Record<AgentRunStatus, number>;
  total_available: number;
}

/** Nested stats: split -> example_kind -> stats */
export type SplitStats = Partial<Record<Split, Partial<Record<ExampleKind, SplitScopeStats>>>>;

/** Single row in the definitions leaderboard */
export interface DefinitionRow {
  definition_id: string;
  created_at: string;
  stats: SplitStats;
}

/** Main overview response */
export interface OverviewResponse {
  definitions: DefinitionRow[];
  example_counts: Partial<Record<Split, Partial<Record<ExampleKind, number>>>>;
  total_definitions: number;
}
