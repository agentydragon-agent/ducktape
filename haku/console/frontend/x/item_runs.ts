import type { Item } from "../client";

export type GroupedItem = Extract<Item, { kind: "tool_call" | "reasoning" }>;

export type ItemRun =
  | { kind: "single"; item: Item }
  | { kind: "tool_reasoning"; items: GroupedItem[]; summary: string };

function summaryFor(items: GroupedItem[]): string {
  const toolCounts = new Map<string, number>();
  let thinkingCount = 0;

  for (const item of items) {
    if (item.kind === "reasoning") {
      thinkingCount += 1;
    } else {
      toolCounts.set(item.tool_name, (toolCounts.get(item.tool_name) ?? 0) + 1);
    }
  }

  const tools = [...toolCounts.entries()]
    .sort((left, right) => right[1] - left[1])
    .map(([toolName, count]) => `${count}x ${toolName}`);
  if (thinkingCount > 0) tools.push(`${thinkingCount} thinking`);
  return tools.join(" · ");
}

export function groupItemRuns(items: Item[]): ItemRun[] {
  const runs: ItemRun[] = [];
  let grouped: GroupedItem[] = [];

  const flush = () => {
    if (grouped.length === 1) {
      runs.push({ kind: "single", item: grouped[0] });
    } else if (grouped.length > 1) {
      runs.push({ kind: "tool_reasoning", items: grouped, summary: summaryFor(grouped) });
    }
    grouped = [];
  };

  for (const item of items) {
    if (item.kind === "tool_call" || item.kind === "reasoning") {
      grouped.push(item);
    } else {
      flush();
      runs.push({ kind: "single", item });
    }
  }
  flush();
  return runs;
}
