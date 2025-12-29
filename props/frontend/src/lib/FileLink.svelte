<script lang="ts">
  import { base } from '$app/paths';

  // Link component for files in snapshots
  // Links to snapshot detail page with file query parameter
  // Uses native <a> with SvelteKit client-side navigation

  interface Props {
    snapshotSlug: string;
    filePath: string;
    displayText?: string; // Override default filePath display
  }

  let { snapshotSlug, filePath, displayText }: Props = $props();

  const href = $derived(`${base}/snapshots/${snapshotSlug}?file=${encodeURIComponent(filePath)}`);
  const text = $derived(displayText ?? filePath);
</script>

<a
  {href}
  class="font-mono text-xs text-blue-600 underline hover:text-blue-800"
  title="View {filePath} in {snapshotSlug}"
>
  {text}
</a>
