import { describe, expect, it } from "vitest";

import type { DeploymentInfo } from "./client";
import type { IndexState } from "./mcp_status_client";
import { deploymentVersions, indexStatusDisplay, settingsTabFromSearch } from "./settings_panel";

function deployment(server: string | null, frontend: string | null): DeploymentInfo {
  const image = (commit: string | null) => ({
    image_tag: commit ? `devel-20260713020000-${commit}` : null,
    source_commit: commit,
    source_commit_url: commit ? `https://github.com/agentydragon/ducktape/commit/${commit}` : null,
  });
  return { server: image(server), frontend: image(frontend) };
}

describe("settingsTabFromSearch", () => {
  it("opens MCP servers by default", () => {
    expect(settingsTabFromSearch("")).toBe("mcp");
  });

  it("restores a linked tab", () => {
    expect(settingsTabFromSearch("?tab=nodes")).toBe("nodes");
    expect(settingsTabFromSearch("?tab=kubernetes")).toBe("kubernetes");
  });

  it("falls back safely for unknown tabs", () => {
    expect(settingsTabFromSearch("?tab=obsolete")).toBe("mcp");
  });
});

describe("deploymentVersions", () => {
  it("collapses matching server and web commits", () => {
    expect(deploymentVersions(deployment("83da566", "83da566"))).toEqual([
      expect.objectContaining({ label: "Deployed", image: expect.objectContaining({ source_commit: "83da566" }) }),
    ]);
  });

  it("exposes rollout skew", () => {
    expect(
      deploymentVersions(deployment("83da566", "bfad4bf")).map(({ label, image }) => [label, image.source_commit])
    ).toEqual([
      ["Server", "83da566"],
      ["Web", "bfad4bf"],
    ]);
  });

  it("omits unavailable metadata", () => {
    expect(deploymentVersions(deployment(null, null))).toEqual([]);
  });
});

describe("indexStatusDisplay", () => {
  const git = (indexed_commit: string | null, remote_commit: string | null): IndexState => ({
    index_type: "git",
    index_id: "ducktape",
    indexed_commit,
    remote_commit,
    remote_seen_at: null,
    branch: "devel",
    indexed_at: null,
    files: 1,
    chunks: 2,
    embedded_chunks: 2,
    pending_chunks: 0,
    superseded_chunks: 0,
  });

  it("distinguishes current, behind, and not-yet-built Git indexes", () => {
    expect(indexStatusDisplay(git("abc", "abc")).label).toBe("Current");
    expect(indexStatusDisplay(git("abc", "def")).label).toBe("Behind");
    expect(indexStatusDisplay(git(null, "def")).label).toBe("Not indexed");
  });

  it("reports pending chat work", () => {
    expect(
      indexStatusDisplay({
        index_type: "chat",
        index_id: "console-chats",
        sessions: 12,
        chunks: 30,
        stale_sessions: 1,
        unindexed_messages: 3,
        lag_seconds: 42,
        last_indexed_at: null,
        embedded_chunks: 27,
        pending_chunks: 3,
        superseded_chunks: 0,
      }).label
    ).toBe("Catching up");
  });
});
