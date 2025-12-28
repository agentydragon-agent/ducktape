<script lang="ts">
  import '../app.css';
  import { Toaster } from 'svelte-sonner';
  import RunTriggerModal from '$components/RunTriggerModal.svelte';
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
</script>

<Toaster richColors position="top-right" duration={8000} />

<div class="min-h-screen bg-gray-50 p-6">
  <div class="flex justify-between items-center mb-4">
    <h1 class="text-2xl font-bold flex-shrink-0">
      <a href="/" class="hover:underline cursor-pointer">
        Props Dashboard
      </a>
    </h1>
    <nav class="flex gap-4">
      <a
        href="/snapshots"
        class="text-blue-600 hover:text-blue-800 hover:underline"
      >
        Ground Truth
      </a>
    </nav>
  </div>

  {@render children()}
</div>

<RunTriggerModal open={showRunModal} onClose={handleCloseRunModal} prefill={modalPrefill} />
