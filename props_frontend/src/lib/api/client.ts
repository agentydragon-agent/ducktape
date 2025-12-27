import createClient from 'openapi-fetch';
import type { paths, components } from './schema';

// Create typed API client
// Run `pnpm generate` with backend running to regenerate types
export const api = createClient<paths>({ baseUrl: '' });

// Re-export generated types
export type DefinitionInfo = components['schemas']['DefinitionInfo'];
export type ActiveRunInfo = components['schemas']['ActiveRunInfo'];
export type ValidationRunRequest = components['schemas']['ValidationRunRequest'];
export type ValidationRunResponse = components['schemas']['ValidationRunResponse'];
export type AgentRunDetail = components['schemas']['AgentRunDetail'];
export type EventInfo = components['schemas']['EventInfo'];
export type EventsResponse = components['schemas']['EventsResponse'];
export type AgentRunStatus = components['schemas']['AgentRunStatus'];
export type JobInfo = components['schemas']['JobInfo'];
export type JobsResponse = components['schemas']['JobsResponse'];
export type AgentType = components['schemas']['AgentType'];
export type RunInfo = components['schemas']['RunInfo'];
export type RunsListResponse = components['schemas']['RunsListResponse'];

// Enum value arrays for UI dropdowns (must match schema definitions)
export const AGENT_RUN_STATUS_VALUES: AgentRunStatus[] = [
  'in_progress',
  'completed',
  'max_turns_exceeded',
  'context_length_exceeded',
  'reported_failure',
];

export const AGENT_TYPE_VALUES: AgentType[] = [
  'critic',
  'grader',
  'prompt_optimizer',
  'clustering',
  'improvement',
  'freeform',
];

// Extract error message from API error response
function extractErrorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === 'object') {
    // FastAPI HTTPException format: { detail: string }
    if ('detail' in error && typeof (error as { detail: unknown }).detail === 'string') {
      return (error as { detail: string }).detail;
    }
    // Generic message field
    if ('message' in error && typeof (error as { message: unknown }).message === 'string') {
      return (error as { message: string }).message;
    }
  }
  return fallback;
}

// Convenience wrapper for overview endpoint
export async function fetchOverview() {
  const { data, error } = await api.GET('/api/stats/overview');
  if (error) throw new Error(extractErrorMessage(error, 'Failed to fetch overview'));
  return data;
}

// Fetch all definitions
export async function fetchDefinitions(agentType?: AgentType) {
  const { data, error } = await api.GET('/api/stats/definitions', {
    params: { query: agentType ? { agent_type: agentType } : {} },
  });
  if (error) throw new Error(extractErrorMessage(error, 'Failed to fetch definitions'));
  return data;
}

// Fetch active runs
export async function fetchActiveRuns() {
  const { data, error } = await api.GET('/api/runs/active');
  if (error) throw new Error(extractErrorMessage(error, 'Failed to fetch active runs'));
  return data;
}

// Trigger validation runs
export async function triggerValidationRuns(request: ValidationRunRequest) {
  const { data, error } = await api.POST('/api/runs/validation', {
    body: request,
  });
  if (error) throw new Error(extractErrorMessage(error, 'Failed to trigger validation runs'));
  return data;
}

// Fetch validation jobs
export async function fetchJobs() {
  const { data, error } = await api.GET('/api/runs/jobs');
  if (error) throw new Error(extractErrorMessage(error, 'Failed to fetch jobs'));
  return data;
}

// Fetch run details
export async function fetchRun(runId: string) {
  const { data, error } = await api.GET('/api/runs/{run_id}', {
    params: { path: { run_id: runId } },
  });
  if (error) throw new Error(extractErrorMessage(error, 'Failed to fetch run'));
  return data;
}

// Fetch run events
export async function fetchRunEvents(runId: string, offset = 0, limit = 100) {
  const { data, error } = await api.GET('/api/runs/{run_id}/events', {
    params: { path: { run_id: runId }, query: { offset, limit } },
  });
  if (error) throw new Error(extractErrorMessage(error, 'Failed to fetch events'));
  return data;
}

// Fetch all runs with filters and pagination
export interface RunsFilters {
  status?: AgentRunStatus;
  definition_id?: string;
  agent_type?: AgentType;
  offset?: number;
  limit?: number;
}

export async function fetchRuns(filters?: RunsFilters) {
  const { data, error } = await api.GET('/api/runs', {
    params: { query: filters ?? {} },
  });
  if (error) throw new Error(extractErrorMessage(error, 'Failed to fetch runs'));
  return data;
}
