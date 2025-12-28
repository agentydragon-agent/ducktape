<script lang="ts">
  import DefinitionDetail from '$components/DefinitionDetail.svelte';
  import type { DefinitionDetailResponse } from '$lib/api/client';

  let { data } = $props();
  const definition = $derived(data.definition as DefinitionDetailResponse);
</script>

<DefinitionDetail data={definition} />
