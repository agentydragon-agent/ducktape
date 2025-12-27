<script lang="ts">
  // Link component for agent definition IDs
  // - Shows full ID (no truncation)
  // - SPA navigation to /definitions/{id}

  interface Props {
    id: string;
    onclick?: (id: string) => void;
  }

  let { id, onclick }: Props = $props();

  const href = $derived(`/definitions/${id}`);

  function handleClick(event: MouseEvent) {
    event.preventDefault();
    if (onclick) {
      onclick(id);
    } else {
      // Default SPA navigation via history API
      history.pushState({}, '', href);
      window.dispatchEvent(new PopStateEvent('popstate'));
    }
  }
</script>

<a {href} class="text-blue-600 underline hover:text-blue-800" onclick={handleClick}>
  {id}
</a>
