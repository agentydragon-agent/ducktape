<script lang="ts">
  import ExampleDetail from '$components/ExampleDetail.svelte';
  import type { ExampleDetailResponse } from '$lib/api/client';

  let { data } = $props();
  const example = $derived(data.example as ExampleDetailResponse | null);
</script>

{#if data.error}
  <p class="text-gray-500">{data.error}</p>
{:else if example}
  <ExampleDetail data={example} />
{:else}
  <p class="text-gray-500">Loading...</p>
{/if}
