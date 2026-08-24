import { describe, expect, it } from "vitest";

import type { ChatLaunchOption } from "./client";
import {
  conversationLaunchOptions,
  defaultLaunchKey,
  launchKey,
  shouldShowLaunchSelector,
} from "./conversation_launch";

const haku = {
  agent_id: "00000000-0000-4000-8000-000000000001",
  agent_display_name: "Haku",
  runtime: "claude_code",
  runtime_display_name: "Claude Code",
  is_default: true,
} satisfies ChatLaunchOption;

const coder = {
  agent_id: "00000000-0000-4000-8000-000000000002",
  agent_display_name: "public-coder-agent",
  runtime: "codex_app_server",
  runtime_display_name: "Codex",
  is_default: false,
} satisfies ChatLaunchOption;

describe("conversation launch choices", () => {
  it("tolerates an older API replica with no launch catalog", () => {
    expect(conversationLaunchOptions({})).toEqual([]);
    expect(defaultLaunchKey(conversationLaunchOptions({}))).toBeNull();
  });

  it("chooses the declared default rather than relying on catalog order", () => {
    expect(defaultLaunchKey([coder, haku])).toBe(launchKey(haku));
  });

  it("falls back to the first choice when no option is marked default", () => {
    expect(
      defaultLaunchKey([
        { ...coder, is_default: false },
        { ...haku, is_default: false },
      ])
    ).toBe(launchKey(coder));
  });

  it("only needs a selector when multiple launches are available", () => {
    expect(shouldShowLaunchSelector([])).toBe(false);
    expect(shouldShowLaunchSelector([coder])).toBe(false);
    expect(shouldShowLaunchSelector([haku, coder])).toBe(true);
  });
});
