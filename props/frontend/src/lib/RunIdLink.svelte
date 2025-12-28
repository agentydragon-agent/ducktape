<script lang="ts">
  // Link component for agent run IDs (UUIDs)
  // - Truncates with CSS ellipsis if space constrained
  // - Monospace font
  // - SPA navigation to /runs/{id}

  interface Props {
    id: string;
    onclick?: (id: string) => void;
  }

  let { id, onclick }: Props = $props();

  const href = $derived(`/runs/${id}`);

  function handleClick(event: MouseEvent) {
    event.preventDefault();
    if (onclick) {
      onclick(id);
    } else {
      history.pushState({}, '', href);
      window.dispatchEvent(new PopStateEvent('popstate'));
    }
  }
</script>

<a {href} class="font-mono text-blue-600 underline hover:text-blue-800 truncate" title={id} onclick={handleClick}>
  {id}
</a>
