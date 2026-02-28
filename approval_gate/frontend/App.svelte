<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "./api.ts";
  import { getMcpClient } from "./mcp.ts";
  import ActionList from "./ActionList.svelte";
  import ActionDetail from "./ActionDetail.svelte";
  import type { Action } from "./types.ts";

  const actionMatch = window.location.hash.match(/^#\/actions\/([^/]+)\/?$/);
  const actionId: string | null = actionMatch ? actionMatch[1] : null;

  let pending = $state<Action[]>([]);
  let recent = $state<Action[]>([]);
  let action = $state<Action | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function loadList(): Promise<void> {
    [pending, recent] = await Promise.all([api.listActions("pending"), api.listActions(undefined, 20)]);
  }

  onMount(async () => {
    if (actionId) {
      try {
        const mcp = await getMcpClient();
        await mcp.subscribeAction<Action>(`resource://actions/${actionId}`, (a) => {
          action = a;
          loading = false;
          error = null;
        });
        if (loading) {
          error = "Failed to read action resource";
          loading = false;
        }
      } catch (err) {
        error = String(err);
        loading = false;
      }
    } else {
      try {
        await loadList();
      } catch (e) {
        error = String(e);
      } finally {
        loading = false;
      }
      const mcp = await getMcpClient();
      mcp.onListChanged(() => {
        loadList();
      });
    }
  });
</script>

{#if loading}
  <header><h1>Approval Gate</h1></header>
  <main><p>Loading…</p></main>
{:else if error}
  <header><h1>Approval Gate</h1></header>
  <main><p class="error">Failed to load: {error}</p></main>
{:else if actionId !== null}
  {#if action}
    <ActionDetail {action} />
  {:else}
    <header><h1>Approval Gate</h1></header>
    <main><p class="error">Action not found.</p></main>
  {/if}
{:else}
  <ActionList {pending} {recent} />
{/if}
