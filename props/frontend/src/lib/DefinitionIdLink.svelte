<script lang="ts">
  import { resolve } from "$lib/router";
  import { formatDigest } from "$lib/formatters";

  interface Props {
    id: string;
  }

  let { id }: Props = $props();
</script>

<a href={resolve(`/definitions/${id}`)} class="text-blue-600 underline hover:text-blue-800" title={id}>
  {formatDigest(id)}
</a>
