<script lang="ts">
  import { goto } from '$app/navigation';
  import { splitBadgeClass } from '$lib/colors';

  let { data } = $props();

  function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString();
  }
</script>

<div class="bg-white rounded-lg shadow p-4">
  <h2 class="text-xl font-semibold mb-4">Snapshots</h2>

  {#if data.snapshots.length === 0}
    <p class="text-gray-500">No snapshots found</p>
  {:else}
    <div class="overflow-x-auto">
      <table class="min-w-full divide-y divide-gray-200">
        <thead class="bg-gray-50">
          <tr>
            <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Slug</th>
            <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Split</th>
            <th class="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">TPs</th>
            <th class="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">FPs</th>
            <th class="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Created</th>
          </tr>
        </thead>
        <tbody class="bg-white divide-y divide-gray-200">
          {#each data.snapshots as snapshot}
            <tr class="hover:bg-gray-50 cursor-pointer" onclick={() => goto(`/snapshots/${snapshot.slug}`)}>
              <td class="px-4 py-2 font-mono text-sm">{snapshot.slug}</td>
              <td class="px-4 py-2">
                <span class="px-2 py-1 text-xs font-medium rounded {splitBadgeClass(snapshot.split)}">
                  {snapshot.split}
                </span>
              </td>
              <td class="px-4 py-2 text-right text-sm">{snapshot.tp_count}</td>
              <td class="px-4 py-2 text-right text-sm">{snapshot.fp_count}</td>
              <td class="px-4 py-2 text-right text-sm text-gray-500">{formatDate(snapshot.created_at)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
