<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { base } from '$app/paths';
  import { Toaster } from 'svelte-sonner';
  import RunTriggerModal from '$components/RunTriggerModal.svelte';
  import { connected, startFeed } from '$lib/stores/runsFeed';
  import type { Split, ExampleKind } from '$lib/types';
  import type { Snippet } from 'svelte';

  interface Props {
    children: Snippet;
  }
  let { children }: Props = $props();

  interface ModalPrefill {
    definitionId?: string;
    split?: Split;
    kind?: ExampleKind;
  }

  let showRunModal = $state(false);
  let modalPrefill: ModalPrefill | undefined = $state(undefined);

  function handleOpenRunModal(prefill?: ModalPrefill) {
    modalPrefill = prefill;
    showRunModal = true;
  }

  function handleCloseRunModal() {
    showRunModal = false;
    modalPrefill = undefined;
  }

  // Expose modal functions to child routes
  import { setContext } from 'svelte';
  setContext('runModal', { open: handleOpenRunModal });

  // Start WebSocket feed on mount
  onMount(() => {
    startFeed();
  });

  // Navigation items
  const navItems = $derived([
    { href: base || '/', label: 'Overview' },
    { href: `${base}/runs`, label: 'Runs' },
    { href: `${base}/snapshots`, label: 'Ground Truth' },
  ]);

  function isActive(href: string, pathname: string): boolean {
    // Root is exact match, others use startsWith
    if (href === (base || '/')) return pathname === (base || '/');
    return pathname.startsWith(href);
  }
</script>

<Toaster richColors position="top-right" duration={8000} />

<div class="min-h-screen bg-gray-50">
  <!-- Header -->
  <header class="bg-white border-b border-gray-200 px-6 py-3">
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <h1 class="text-xl font-bold">
          <a href="{base}/" class="hover:text-blue-600">Props</a>
        </h1>
        {#if $connected}
          <span class="px-2 py-0.5 text-xs bg-green-100 text-green-700 rounded">live</span>
        {:else}
          <span class="px-2 py-0.5 text-xs bg-orange-100 text-orange-700 rounded">reconnecting...</span>
        {/if}
      </div>
      <nav class="flex gap-1">
        {#each navItems as { href, label }}
          <a
            {href}
            class="px-3 py-1.5 rounded text-sm font-medium transition-colors
              {isActive(href, $page.url.pathname)
              ? 'bg-blue-100 text-blue-700'
              : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'}"
          >
            {label}
          </a>
        {/each}
      </nav>
    </div>
  </header>

  <!-- Main content -->
  <main class="p-6">
    {@render children()}
  </main>
</div>

<RunTriggerModal open={showRunModal} onClose={handleCloseRunModal} prefill={modalPrefill} />
