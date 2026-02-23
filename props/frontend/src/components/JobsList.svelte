<script lang="ts">
  import { jobs } from "$lib/stores/runsFeed";
  import DefinitionIdLink from "$lib/DefinitionIdLink.svelte";
  import JobIdLink from "$lib/JobIdLink.svelte";

  interface Props {
    onNewRun: () => void;
  }

  let { onNewRun }: Props = $props();
</script>

<div class="bg-white dark:bg-gray-900 rounded-lg shadow dark:shadow-gray-950/30 p-4 mb-4">
  <div class="flex items-center justify-between mb-3">
    <h2 class="text-lg font-semibold">Jobs</h2>
    <button
      type="button"
      onclick={onNewRun}
      class="bg-blue-600 text-white px-4 py-1.5 rounded text-sm hover:bg-blue-700"
    >
      New Run
    </button>
  </div>

  {#if $jobs.length > 0}
    <div class="space-y-2">
      {#each $jobs as job (job.job_id)}
        <div class="text-xs bg-gray-50 dark:bg-gray-800 p-2 rounded">
          <div class="flex gap-4 items-center">
            <JobIdLink id={job.job_id} />
            <span class="font-medium"><DefinitionIdLink id={job.image_digest} /></span>
            <span class="text-gray-500 dark:text-gray-400">{job.example_kind}</span>
            <span
              class={job.status === "running"
                ? "text-blue-600 dark:text-blue-400"
                : job.status === "completed"
                  ? "text-green-600 dark:text-green-400"
                  : "text-red-600 dark:text-red-400"}
            >
              {job.status}
            </span>
            <span class="text-gray-600 dark:text-gray-400">
              {job.completed}/{job.n_samples} done
              {#if job.failed > 0}
                <span class="text-red-500 dark:text-red-400">({job.failed} failed)</span>
              {/if}
            </span>
          </div>
        </div>
      {/each}
    </div>
  {:else}
    <p class="text-sm text-gray-500 dark:text-gray-400">No active jobs</p>
  {/if}
</div>
