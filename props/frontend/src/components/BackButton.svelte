<script lang="ts">
  import { base } from '$app/paths';

  interface Props {
    href?: string;
    label?: string;
    class?: string;
  }

  let { href = `${base}/`, label = '← Back', class: className }: Props = $props();
</script>

<a {href} class={className || 'text-sm text-gray-500 hover:text-gray-700 hover:underline'}>
  {label}
</a>
