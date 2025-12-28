<script lang="ts">
  import type { FileTreeNode } from '../lib/api/client';

  interface Props {
    nodes: FileTreeNode[];
    onFileClick: (path: string) => void;
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

  function getFileIcon(name: string, isDir: boolean): string {
    if (isDir) return '📁';

    // Simple file type icons
    const ext = name.split('.').pop()?.toLowerCase();
    switch (ext) {
      case 'js':
      case 'ts':
      case 'jsx':
      case 'tsx':
        return '📜';
      case 'py':
        return '🐍';
      case 'md':
        return '📝';
      case 'json':
      case 'yaml':
      case 'yml':
        return '⚙️';
      case 'html':
      case 'css':
        return '🎨';
      default:
        return '📄';
    }
  }

  function TreeNode(node: FileTreeNode, depth: number = 0) {
    const isExpanded = expanded.has(node.path);
    const isSelected = selectedPath === node.path;
    const indent = depth * 16;

    return (
      <>
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
            <span class="text-gray-400">{isExpanded ? '▼' : '▶'}</span>
          {/if}
          <span>{getFileIcon(node.name, node.is_dir)}</span>
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
            {@render TreeNode(child, depth + 1)}
          {/each}
        {/if}
      </>
    );
  }
</script>

<div class="border rounded bg-white">
  {#each nodes as node}
    {@render TreeNode(node, 0)}
  {/each}
</div>
