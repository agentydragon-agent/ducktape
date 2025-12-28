<script lang="ts">
  import {
    ChevronRight,
    ChevronDown,
    Folder,
    FolderOpen,
    File,
    FileText,
    FileCode,
    FileJson,
    Settings,
  } from 'lucide-svelte';
  import type { FileTreeNode } from '../lib/api/client';

  interface Props {
    nodes: FileTreeNode[];
    onFileClick: (_: string) => void;
    selectedPath?: string;
  }

  let { nodes, onFileClick, selectedPath }: Props = $props();

  let expanded = $state<Set<string>>(new Set());

  function toggleExpand(path: string) {
    const newSet = new Set(expanded);
    if (newSet.has(path)) {
      newSet.delete(path);
    } else {
      newSet.add(path);
    }
    expanded = newSet;
  }
</script>

{#snippet treeNode(node: FileTreeNode, depth: number)}
  {@const isExpanded = expanded.has(node.path)}
  {@const isSelected = selectedPath === node.path}
  {@const indent = depth * 16}
  {@const ext = node.name.split('.').pop()?.toLowerCase()}

  <div
    class="flex items-center gap-1 px-2 py-1 hover:bg-gray-100 cursor-pointer text-sm {isSelected ? 'bg-blue-100' : ''}"
    style="padding-left: {indent + 8}px"
    onclick={() => {
      if (node.is_dir) {
        toggleExpand(node.path);
      } else {
        onFileClick(node.path);
      }
    }}
  >
    {#if node.is_dir}
      <span class="text-gray-400">
        {#if isExpanded}
          <ChevronDown size={16} />
        {:else}
          <ChevronRight size={16} />
        {/if}
      </span>
      <span class="text-blue-500">
        {#if isExpanded}
          <FolderOpen size={16} />
        {:else}
          <Folder size={16} />
        {/if}
      </span>
    {:else}
      <span class="text-gray-400">
        {#if ext === 'json' || ext === 'yaml' || ext === 'yml'}
          <FileJson size={16} />
        {:else if ext === 'js' || ext === 'ts' || ext === 'jsx' || ext === 'tsx' || ext === 'py' || ext === 'rb' || ext === 'java' || ext === 'c' || ext === 'cpp' || ext === 'go' || ext === 'rs'}
          <FileCode size={16} />
        {:else if ext === 'md' || ext === 'txt'}
          <FileText size={16} />
        {:else if ext === 'config' || ext === 'conf' || ext === 'cfg'}
          <Settings size={16} />
        {:else}
          <File size={16} />
        {/if}
      </span>
    {/if}
    <span class="flex-1 font-mono">{node.name}</span>
    {#if node.tp_count > 0 || node.fp_count > 0}
      <div class="flex items-center gap-1 text-xs">
        {#if node.tp_count > 0}
          <span class="px-1.5 py-0.5 bg-green-100 text-green-700 rounded font-medium">
            {node.tp_count} TP
          </span>
        {/if}
        {#if node.fp_count > 0}
          <span class="px-1.5 py-0.5 bg-red-100 text-red-700 rounded font-medium">
            {node.fp_count} FP
          </span>
        {/if}
      </div>
    {/if}
  </div>

  {#if node.is_dir && isExpanded && node.children}
    {#each node.children as child}
      {@render treeNode(child, depth + 1)}
    {/each}
  {/if}
{/snippet}

<div class="border rounded bg-white">
  {#each nodes as node}
    {@render treeNode(node, 0)}
  {/each}
</div>
