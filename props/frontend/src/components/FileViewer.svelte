<script lang="ts">
  import type { FileContentResponse } from '../lib/api/client';

  interface Props {
    file: FileContentResponse;
  }

  let { file }: Props = $props();

  const lines = $derived(file.content.split('\n'));
</script>

<div class="border rounded bg-white font-mono text-sm">
  <!-- Header -->
  <div class="px-4 py-2 border-b bg-gray-50 flex items-center gap-2">
    <span class="font-semibold">{file.path}</span>
    <span class="text-gray-500 text-xs">({file.line_count} lines)</span>
  </div>

  <!-- Content -->
  <div class="overflow-auto max-h-[70vh]">
    <table class="w-full">
      <tbody>
        {#each lines as line, idx}
          <tr class="hover:bg-gray-50">
            <!-- Line number (1-based display) -->
            <td class="px-2 py-0.5 text-right text-gray-400 select-none w-12 border-r">
              {idx + 1}
            </td>
            <!-- Line content -->
            <td class="px-4 py-0.5 whitespace-pre">{line}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>
