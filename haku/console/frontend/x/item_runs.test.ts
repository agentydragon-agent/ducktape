import { describe, expect, it } from "vitest";

import type { Item } from "../client";
import { groupItemRuns } from "./item_runs";

const provenance = { kind: "authored" as const };

function tool(opened_seq: number, tool_name: string): Item {
  return {
    kind: "tool_call",
    opened_seq,
    closed_seq: opened_seq + 1,
    status: "complete",
    provenance,
    call_id: `call-${opened_seq}`,
    tool_name,
    arguments: {},
    content: "",
    structured: null,
    outcome: null,
  };
}

function thinking(opened_seq: number): Item {
  return {
    kind: "reasoning",
    opened_seq,
    closed_seq: opened_seq + 1,
    status: "complete",
    provenance,
    text: "",
    disclosure: "withheld",
  };
}

function prompt(opened_seq: number): Item {
  return {
    kind: "prompt",
    opened_seq,
    closed_seq: opened_seq + 1,
    status: "complete",
    provenance,
    text: "prompt",
    origin: "spa",
  };
}

function message(opened_seq: number): Item {
  return {
    kind: "message",
    opened_seq,
    closed_seq: opened_seq + 1,
    status: "complete",
    provenance,
    text: "message",
    backend_item_id: null,
  };
}

describe("groupItemRuns", () => {
  it("returns no runs for an empty list", () => {
    expect(groupItemRuns([])).toEqual([]);
  });

  it("splits runs at prompts and messages", () => {
    const items = [
      tool(1, "first"),
      tool(2, "first"),
      prompt(3),
      thinking(4),
      thinking(5),
      message(6),
      tool(7, "last"),
    ];

    expect(groupItemRuns(items)).toEqual([
      { kind: "tool_reasoning", items: [items[0], items[1]], summary: "2x first" },
      { kind: "single", item: items[2] },
      { kind: "tool_reasoning", items: [items[3], items[4]], summary: "2 thinking" },
      { kind: "single", item: items[5] },
      { kind: "single", item: items[6] },
    ]);
  });

  it("aggregates tools by descending count and puts thinking last", () => {
    const runs = groupItemRuns([
      tool(1, "get_tool_call"),
      thinking(2),
      tool(3, "commandExecution"),
      tool(4, "get_tool_call"),
      thinking(5),
      tool(6, "commandExecution"),
      tool(7, "commandExecution"),
    ]);

    expect(runs).toHaveLength(1);
    expect(runs[0]).toMatchObject({
      kind: "tool_reasoning",
      summary: "3x commandExecution · 2x get_tool_call · 2 thinking",
    });
  });

  it("passes a run of one item through directly", () => {
    const item = thinking(1);

    expect(groupItemRuns([item])).toEqual([{ kind: "single", item }]);
  });
});
