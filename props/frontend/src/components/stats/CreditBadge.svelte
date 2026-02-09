<script lang="ts">
  interface Props {
    meanCredit: number;
    nRuns: number;
  }

  let { meanCredit, nRuns }: Props = $props();

  const colorClass = $derived(
    meanCredit >= 0.7
      ? "bg-green-100 text-green-700 border-green-300"
      : meanCredit >= 0.4
        ? "bg-yellow-100 text-yellow-700 border-yellow-300"
        : "bg-red-100 text-red-700 border-red-300"
  );
</script>

<span
  class="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs font-medium rounded border {colorClass}"
  title="Mean credit: {(meanCredit * 100).toFixed(1)}% ({nRuns} runs)"
>
  {(meanCredit * 100).toFixed(0)}%
  <span class="text-gray-400">({nRuns})</span>
</span>
