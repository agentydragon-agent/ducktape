<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { toast } from 'svelte-sonner';
  import {
    fetchRun,
    fetchRunEvents,
    type AgentRunDetail,
    type EventInfo,
    type AgentRunStatus,
  } from '../lib/api/client';

  // Props
  interface Props {
    runId: string;
    onClose?: () => void;
  }
  let { runId, onClose }: Props = $props();

  // State
  let run: AgentRunDetail | null = $state(null);
  let events: EventInfo[] = $state([]);
  let loading = $state(true);
  let pollInterval: ReturnType<typeof setInterval> | null = null;

  // Status badge colors
  function getStatusColor(status: AgentRunStatus): string {
    switch (status) {
      case 'in_progress':
        return 'bg-blue-100 text-blue-800';
      case 'completed':
        return 'bg-green-100 text-green-800';
      case 'max_turns_exceeded':
      case 'context_length_exceeded':
        return 'bg-yellow-100 text-yellow-800';
      case 'reported_failure':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  }

  function formatStatus(status: AgentRunStatus): string {
    return status.replace(/_/g, ' ');
  }

  // Get agent type from type_config
  function getAgentType(run: AgentRunDetail): string {
    return run.type_config.agent_type;
  }

  // Load run data
  async function loadData() {
    try {
      const [runResult, eventsResult] = await Promise.all([
        fetchRun(runId),
        fetchRunEvents(runId, 0, 500),
      ]);
      run = runResult;
      events = eventsResult.events;
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to load run';
      toast.error(message);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    loadData();
    // Poll while in progress
    pollInterval = setInterval(() => {
      if (run?.status === 'in_progress') {
        loadData();
      }
    }, 1000);
  });

  onDestroy(() => {
    if (pollInterval) clearInterval(pollInterval);
  });

  // Render event content based on type
  function renderEventContent(event: EventInfo): { label: string; content: string; style: string } {
    const payload = event.payload;

    switch (payload.type) {
      case 'user_text':
        return { label: 'User', content: payload.text, style: 'bg-blue-50 border-blue-200' };
      case 'assistant_text':
        return { label: 'Assistant', content: payload.text, style: 'bg-green-50 border-green-200' };
      case 'tool_call':
        const argsPreview = payload.args_json ? payload.args_json.slice(0, 100) + (payload.args_json.length > 100 ? '...' : '') : '';
        return { label: `Tool: ${payload.name}`, content: argsPreview, style: 'bg-purple-50 border-purple-200' };
      case 'function_call_output':
        const resultText = payload.result.content.map((c: any) => c.text || '[non-text]').join('\n');
        const preview = resultText.slice(0, 200) + (resultText.length > 200 ? '...' : '');
        return { label: 'Tool Output', content: preview, style: 'bg-gray-50 border-gray-200' };
      case 'reasoning':
        const summaryText = payload.summary?.map((s: any) => s.text).join('\n') || '[thinking]';
        return { label: 'Reasoning', content: summaryText, style: 'bg-yellow-50 border-yellow-200' };
      case 'api_request':
        return { label: 'API Request', content: `Phase ${payload.phase_number}, model: ${payload.model}`, style: 'bg-indigo-50 border-indigo-200' };
      case 'response':
        const usage = payload.usage;
        return { label: 'Response', content: `${usage.total_tokens || 0} tokens (${usage.input_tokens || 0} in, ${usage.output_tokens || 0} out)`, style: 'bg-indigo-50 border-indigo-200' };
      default:
        return { label: event.event_type, content: JSON.stringify(payload).slice(0, 100), style: 'bg-gray-50 border-gray-200' };
    }
  }
</script>

<div class="bg-white rounded-lg shadow h-full flex flex-col">
  <!-- Header -->
  <div class="p-4 border-b flex items-center justify-between">
    <div class="flex items-center gap-4">
      {#if onClose}
        <button
          type="button"
          onclick={onClose}
          class="text-gray-500 hover:text-gray-700"
        >
          &larr; Back
        </button>
      {/if}
      <h2 class="text-lg font-semibold">Run Details</h2>
    </div>
    {#if run}
      <span class="px-2 py-1 rounded text-sm font-medium capitalize {getStatusColor(run.status)}">
        {formatStatus(run.status)}
      </span>
    {/if}
  </div>

  {#if loading}
    <div class="p-4">
      <p class="text-gray-500">Loading...</p>
    </div>
  {:else if run}
    <!-- Run info -->
    <div class="p-4 border-b bg-gray-50">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        <div>
          <span class="text-gray-500">ID:</span>
          <span class="font-mono ml-1">{run.agent_run_id.slice(0, 12)}...</span>
        </div>
        <div>
          <span class="text-gray-500">Type:</span>
          <span class="ml-1 capitalize">{getAgentType(run)}</span>
        </div>
        <div>
          <span class="text-gray-500">Definition:</span>
          <span class="ml-1">{run.definition_id}</span>
        </div>
        <div>
          <span class="text-gray-500">Model:</span>
          <span class="ml-1">{run.model}</span>
        </div>
        <div>
          <span class="text-gray-500">Events:</span>
          <span class="ml-1">{run.event_count}</span>
        </div>
        {#if run.parent_agent_run_id}
          <div>
            <span class="text-gray-500">Parent:</span>
            <span class="font-mono ml-1">{run.parent_agent_run_id.slice(0, 8)}...</span>
          </div>
        {/if}
        {#if run.completion_summary}
          <div class="col-span-2">
            <span class="text-gray-500">Summary:</span>
            <span class="ml-1">{run.completion_summary}</span>
          </div>
        {/if}
      </div>
    </div>

    <!-- Events timeline -->
    <div class="p-4 flex-1 flex flex-col min-h-0">
      <h3 class="text-md font-medium mb-3 flex-shrink-0">Events ({events.length})</h3>
      {#if events.length === 0}
        <p class="text-gray-500 text-sm">No events yet</p>
      {:else}
        <div class="space-y-2 flex-1 overflow-y-auto">
          {#each events as event}
            {@const rendered = renderEventContent(event)}
            <div class="p-2 rounded border {rendered.style}">
              <div class="flex items-center justify-between mb-1">
                <span class="text-xs font-medium">{rendered.label}</span>
                <span class="text-xs text-gray-400">#{event.sequence_num}</span>
              </div>
              <pre class="text-xs whitespace-pre-wrap break-words font-mono">{rendered.content}</pre>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  {:else}
    <div class="p-4">
      <p class="text-red-500">Failed to load run</p>
    </div>
  {/if}
</div>
