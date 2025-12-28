/**
 * Reusable expansion state manager using Svelte 5 runes.
 * Manages a set of expanded item IDs with toggle functionality.
 */
export function createExpansionState() {
  let expanded = $state<Set<string>>(new Set());

  return {
    get expanded() {
      return expanded;
    },
    isExpanded(id: string): boolean {
      return expanded.has(id);
    },
    toggle(id: string) {
      const newSet = new Set(expanded);
      if (newSet.has(id)) {
        newSet.delete(id);
      } else {
        newSet.add(id);
      }
      expanded = newSet;
    },
    expand(id: string) {
      if (!expanded.has(id)) {
        expanded = new Set([...expanded, id]);
      }
    },
    collapse(id: string) {
      if (expanded.has(id)) {
        const newSet = new Set(expanded);
        newSet.delete(id);
        expanded = newSet;
      }
    },
    expandAll(ids: string[]) {
      expanded = new Set(ids);
    },
    collapseAll() {
      expanded = new Set();
    },
  };
}
