<script lang="ts">
  import { onMount } from 'svelte';
  import { Toaster, toast } from 'svelte-sonner';
  import { fetchOverview } from './lib/api';
  import type { OverviewResponse } from './lib/types';
  import DefinitionsTable from './components/stats/DefinitionsTable.svelte';
  import SummaryCards from './components/stats/SummaryCards.svelte';
  import JobsList from './components/JobsList.svelte';
  import RunList from './components/RunList.svelte';
  import RunDetail from './components/RunDetail.svelte';
  import RunsBrowser from './components/RunsBrowser.svelte';
  import DefinitionDetail from './components/DefinitionDetail.svelte';
  import RunTriggerModal from './components/RunTriggerModal.svelte';
  import type { Split, ExampleKind } from './lib/types';

  interface ModalPrefill {
    definitionId?: string;
    split?: Split;
    kind?: ExampleKind;
  }

  // Runs page filters from URL query params
  interface RunsPageFilters {
    definitionId?: string;
    split?: Split;
    kind?: ExampleKind;
  }

  let data: OverviewResponse | null = $state(null);
  let loading = $state(true);
  let selectedRunId: string | null = $state(null);
  let selectedDefinitionId: string | null = $state(null);
  let runsPageFilters: RunsPageFilters | null = $state(null);
  let showRunModal = $state(false);
  let modalPrefill: ModalPrefill | undefined = $state(undefined);

  // Parse URL to extract route state
  function parseUrl(): { runId?: string; definitionId?: string; runsFilters?: RunsPageFilters } {
    const path = window.location.pathname;
    const runMatch = path.match(/^\/runs\/([^/]+)$/);
    const defMatch = path.match(/^\/definitions\/([^/]+)$/);
    const runsListMatch = path === '/runs';

    // Parse query params for /runs page
    let runsFilters: RunsPageFilters | undefined;
    if (runsListMatch) {
      const params = new URLSearchParams(window.location.search);
      runsFilters = {};
      if (params.get('definition')) runsFilters.definitionId = params.get('definition')!;
      if (params.get('split')) runsFilters.split = params.get('split') as Split;
      if (params.get('kind')) runsFilters.kind = params.get('kind') as ExampleKind;
    }

    return {
      runId: runMatch?.[1],
      definitionId: defMatch?.[1],
      runsFilters,
    };
  }

  // Update URL to reflect current state
  function updateUrl() {
    let url = '/';
    if (selectedRunId) {
      url = `/runs/${selectedRunId}`;
    } else if (selectedDefinitionId) {
      url = `/definitions/${selectedDefinitionId}`;
    } else if (runsPageFilters) {
      const params = new URLSearchParams();
      if (runsPageFilters.definitionId) params.set('definition', runsPageFilters.definitionId);
      if (runsPageFilters.split) params.set('split', runsPageFilters.split);
      if (runsPageFilters.kind) params.set('kind', runsPageFilters.kind);
      const qs = params.toString();
      url = qs ? `/runs?${qs}` : '/runs';
    }
    const currentUrl = window.location.pathname + window.location.search;
    if (currentUrl !== url) {
      history.pushState({}, '', url);
    }
  }

  onMount(async () => {
    // Initialize state from URL
    const { runId, definitionId, runsFilters } = parseUrl();
    if (runId) selectedRunId = runId;
    else if (definitionId) selectedDefinitionId = definitionId;
    else if (runsFilters) runsPageFilters = runsFilters;

    // Listen for browser back/forward
    window.addEventListener('popstate', () => {
      const { runId, definitionId, runsFilters } = parseUrl();
      selectedRunId = runId ?? null;
      selectedDefinitionId = definitionId ?? null;
      runsPageFilters = runsFilters ?? null;
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

  function handleGoHome() {
    selectedRunId = null;
    selectedDefinitionId = null;
    runsPageFilters = null;
    updateUrl();
  }

  function handleNavigateToRuns(filters: RunsPageFilters) {
    selectedRunId = null;
    selectedDefinitionId = null;
    runsPageFilters = filters;
    updateUrl();
  }

  function handleCloseRunsPage() {
    runsPageFilters = null;
    updateUrl();
  }

  function handleOpenRunModal(prefill?: ModalPrefill) {
    modalPrefill = prefill;
    showRunModal = true;
  }

  function handleCloseRunModal() {
    showRunModal = false;
    modalPrefill = undefined;
  }
</script>

<Toaster richColors position="top-right" duration={8000} />

<div class="min-h-screen bg-gray-50 p-6">
  <h1 class="text-2xl font-bold mb-4 flex-shrink-0">
    <button type="button" onclick={handleGoHome} class="hover:underline cursor-pointer">
      Props Dashboard
    </button>
  </h1>

  {#if selectedRunId}
    <!-- Run detail view -->
    <RunDetail runId={selectedRunId} onClose={handleCloseDetail} onSelectRun={handleSelectRun} onSelectDefinition={handleSelectDefinition} />
  {:else if selectedDefinitionId}
    <!-- Definition detail view -->
    <DefinitionDetail
      definitionId={selectedDefinitionId}
      onClose={handleClearDefinitionFilter}
      onSelectRun={handleSelectRun}
    />
  {:else if runsPageFilters}
    <!-- Runs list with filters -->
    <RunsBrowser
      onSelectRun={handleSelectRun}
      initialDefinitionId={runsPageFilters.definitionId}
      initialSplit={runsPageFilters.split}
      initialKind={runsPageFilters.kind}
      onClose={handleCloseRunsPage}
      onTriggerRun={(prefill) => handleOpenRunModal(prefill)}
    />
  {:else}
    <!-- Main dashboard -->
    <div>
      <JobsList onNewRun={() => handleOpenRunModal()} />

      <div class="mb-4">
        <RunList onSelectRun={handleSelectRun} />
      </div>

      <div class="mb-4">
        <RunsBrowser onSelectRun={handleSelectRun} />
      </div>

      {#if loading}
        <p class="text-gray-500">Loading...</p>
      {:else if data}
        <SummaryCards {data} onSelectDefinition={handleSelectDefinition} />
        <div class="bg-white rounded-lg shadow">
          <DefinitionsTable
            definitions={data.definitions}
            exampleCounts={data.example_counts}
            onSelectDefinition={handleSelectDefinition}
            onCellClick={handleNavigateToRuns}
          />
        </div>
      {/if}
    </div>
  {/if}
</div>

<RunTriggerModal open={showRunModal} onClose={handleCloseRunModal} prefill={modalPrefill} />
