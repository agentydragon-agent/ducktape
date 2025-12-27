<script lang="ts">
  import { onMount } from 'svelte';
  import { Toaster, toast } from 'svelte-sonner';
  import { fetchOverview } from './lib/api';
  import type { OverviewResponse } from './lib/types';
  import DefinitionsTable from './components/stats/DefinitionsTable.svelte';
  import ValidationRunTrigger from './components/ValidationRunTrigger.svelte';
  import RunList from './components/RunList.svelte';
  import RunDetail from './components/RunDetail.svelte';
  import RunsBrowser from './components/RunsBrowser.svelte';

  let data: OverviewResponse | null = $state(null);
  let loading = $state(true);
  let selectedRunId: string | null = $state(null);
  let selectedDefinitionId: string | null = $state(null);

  // Parse URL to extract route state
  function parseUrl(): { runId?: string; definitionId?: string } {
    const path = window.location.pathname;
    const runMatch = path.match(/^\/runs\/([^/]+)$/);
    const defMatch = path.match(/^\/definitions\/([^/]+)\/runs$/);
    return {
      runId: runMatch?.[1],
      definitionId: defMatch?.[1],
    };
  }

  // Update URL to reflect current state
  function updateUrl() {
    let path = '/';
    if (selectedRunId) {
      path = `/runs/${selectedRunId}`;
    } else if (selectedDefinitionId) {
      path = `/definitions/${selectedDefinitionId}/runs`;
    }
    if (window.location.pathname !== path) {
      history.pushState({}, '', path);
    }
  }

  onMount(async () => {
    // Initialize state from URL
    const { runId, definitionId } = parseUrl();
    if (runId) selectedRunId = runId;
    else if (definitionId) selectedDefinitionId = definitionId;

    // Listen for browser back/forward
    window.addEventListener('popstate', () => {
      const { runId, definitionId } = parseUrl();
      selectedRunId = runId ?? null;
      selectedDefinitionId = definitionId ?? null;
    });

    // Fetch overview data
    try {
      data = await fetchOverview();
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Unknown error';
      toast.error(message);
    } finally {
      loading = false;
    }
  });

  function handleSelectRun(runId: string) {
    selectedRunId = runId;
    updateUrl();
  }

  function handleCloseDetail() {
    selectedRunId = null;
    updateUrl();
  }

  function handleSelectDefinition(definitionId: string) {
    selectedDefinitionId = definitionId;
    updateUrl();
  }

  function handleClearDefinitionFilter() {
    selectedDefinitionId = null;
    updateUrl();
  }
</script>

<Toaster richColors position="top-right" />

<div class="h-screen bg-gray-50 p-6 flex flex-col overflow-hidden">
  <h1 class="text-2xl font-bold mb-4 flex-shrink-0">Props Dashboard</h1>

  {#if selectedRunId}
    <!-- Run detail view -->
    <div class="flex-1 min-h-0">
      <RunDetail runId={selectedRunId} onClose={handleCloseDetail} />
    </div>
  {:else if selectedDefinitionId}
    <!-- Definition runs view -->
    <div class="flex-1 overflow-y-auto min-h-0">
      <RunsBrowser
        initialDefinitionId={selectedDefinitionId}
        onSelectRun={handleSelectRun}
        onClearDefinitionFilter={handleClearDefinitionFilter}
      />
    </div>
  {:else}
    <!-- Main dashboard -->
    <div class="flex-1 overflow-y-auto min-h-0">
      <ValidationRunTrigger />

      <div class="mb-4">
        <RunList onSelectRun={handleSelectRun} />
      </div>

      <div class="mb-4">
        <RunsBrowser onSelectRun={handleSelectRun} />
      </div>

      {#if loading}
        <p class="text-gray-500">Loading...</p>
      {:else if data}
        <p class="text-gray-600 mb-4">{data.total_definitions} definitions</p>
        <div class="bg-white rounded-lg shadow">
          <DefinitionsTable definitions={data.definitions} onSelectDefinition={handleSelectDefinition} />
        </div>
      {/if}
    </div>
  {/if}
</div>
