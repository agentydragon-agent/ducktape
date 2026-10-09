// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { markThreadViewEvent } from "./thread_view_timing";
import { downloadScrollDiagnostics, ScrollCapture } from "./scroll_diagnostics";

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
    expect(capture?.marks).toEqual([
      {
        name: "agentplane:thread-view:input",
        startTime: 1,
        detail: { kind: "input", source: "wheel", direction: "up", scrollTop: 200 },
      },
      {
        name: "agentplane:thread-view:virtual-size",
        startTime: 2,
        detail: { kind: "virtual-size", before: 2000, after: 1000, sync: false, following: false },
      },
    ]);
    expect(capture?.version).toBe(2);
    expect(capture?.timeOrigin).toBe(1234);
    markThreadViewEvent({ kind: "load-older" });
    expect(mark).toHaveBeenCalledTimes(2);
  });

  it("downloads the recorded marks as local JSON and cleans up its temporary link", async () => {
    const trace = new ScrollCapture();
    trace.startRecording();
    markThreadViewEvent({ kind: "marker" });
    const recording = trace.stopRecording();
    expect(recording).not.toBeNull();
    if (!recording) throw new Error("Missing recording");

    let savedBlob: Blob | undefined;
    const createObjectURL = vi.fn((blob: Blob) => {
      savedBlob = blob;
      return "blob:scroll-recording";
    });
    const revokeObjectURL = vi.fn();
    const NativeURL = URL;
    vi.stubGlobal(
      "URL",
      class extends NativeURL {
        static createObjectURL = createObjectURL;
        static revokeObjectURL = revokeObjectURL;
      }
    );
    const clickLink = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement
    ) {
      expect(this.download).toMatch(/^agentplane-scroll-diagnostics-.*\.json$/);
      expect(this.href).toBe("blob:scroll-recording");
    });
    try {
      downloadScrollDiagnostics(recording);
      expect(clickLink).toHaveBeenCalledOnce();
      expect(createObjectURL).toHaveBeenCalledOnce();
      expect(savedBlob?.type).toBe("application/json");
      expect(savedBlob).toBeDefined();
      if (!savedBlob) throw new Error("Missing download blob");
      expect(JSON.parse(await savedBlob.text())).toMatchObject({
        version: 2,
        marks: [{ name: "agentplane:thread-view:marker", detail: { kind: "marker" } }],
      });
      expect(document.querySelector('a[href="blob:scroll-recording"]')).toBeNull();
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:scroll-recording");
    } finally {
      clickLink.mockRestore();
    }
  });

  it("drops excess marks rather than growing the native timeline indefinitely", () => {
    const trace = new ScrollCapture();
    trace.startRecording();
    for (let i = 0; i < 20_005; i++) markThreadViewEvent({ kind: "load-older" });
    expect(trace.stopRecording()?.dropped).toBe(5);
    expect(mark).toHaveBeenCalledTimes(20_000);
  });
});
