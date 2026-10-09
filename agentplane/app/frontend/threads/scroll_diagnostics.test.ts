// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { markThreadViewEvent } from "./thread_view_timing";
import { ScrollCapture } from "./scroll_diagnostics";

describe("ScrollCapture User Timing", () => {
  const marks: Array<{ name: string; startTime: number; detail: unknown }> = [];
  const mark = vi.fn((name: string, options: { detail: unknown }) => {
    marks.push({ name, startTime: marks.length + 1, detail: options.detail });
  });
  beforeEach(() => {
    marks.length = 0;
    vi.stubGlobal("performance", {
      now: () => 0,
      timeOrigin: 1234,
      mark,
      clearMarks: vi.fn(),
      getEntriesByType: () => marks,
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    mark.mockClear();
  });

  it("does not emit marks until the reader opts in", () => {
    const trace = new ScrollCapture();
    markThreadViewEvent({ kind: "load-older" });
    expect(mark).not.toHaveBeenCalled();
    trace.startRecording();
    markThreadViewEvent({ kind: "input", source: "wheel", direction: "up", scrollTop: 200 });
    markThreadViewEvent({ kind: "virtual-size", before: 2000, after: 1000, sync: false, following: false });
    const capture = trace.stopRecording();
    expect(capture?.marks.map((entry) => entry.name)).toEqual([
      "agentplane:thread-view:input",
      "agentplane:thread-view:virtual-size",
    ]);
    expect(capture?.version).toBe(2);
    expect(capture?.timeOrigin).toBe(1234);
    markThreadViewEvent({ kind: "load-older" });
    expect(mark).toHaveBeenCalledTimes(2);
  });

  it("drops excess marks rather than growing the native timeline indefinitely", () => {
    const trace = new ScrollCapture();
    trace.startRecording();
    for (let i = 0; i < 20_005; i++) markThreadViewEvent({ kind: "load-older" });
    expect(trace.stopRecording()?.dropped).toBe(5);
    expect(mark).toHaveBeenCalledTimes(20_000);
  });
});
