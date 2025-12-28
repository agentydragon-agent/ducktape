<script lang="ts">
  import { page } from '$app/stores';
  import RunDetail from '$components/RunDetail.svelte';

  const runId = $derived($page.params.runId ?? '');
</script>

{#if runId}
  <RunDetail {runId} />
{:else}
  <p class="text-gray-500">Invalid run ID</p>
{/if}
