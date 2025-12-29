<script lang="ts">
  import { base } from '$app/paths';

  // Link component for critique issue IDs
  // Links to run detail page with anchor to critique issue
  // Uses native <a> with SvelteKit client-side navigation

  interface Props {
    runId: string;
    issueId: string;
    displayText?: string; // Override default issueId display
  }

  let { runId, issueId, displayText }: Props = $props();

  const href = $derived(`${base}/runs/${runId}#critique-${issueId}`);
  const text = $derived(displayText ?? issueId);
</script>

<a
  {href}
  class="font-mono text-blue-600 underline hover:text-blue-800"
  title="View critique issue {issueId} in run {runId}"
>
  {text}
</a>
