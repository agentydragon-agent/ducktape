import { startThreadViewMarks, stopThreadViewMarks, type ThreadViewEvent } from "./thread_view_timing";

const MARK_PREFIX = "agentplane:thread-view:";
const MAX_BROWSER_ENTRIES = 5_000;
const BROWSER_TYPES = ["layout-shift", "longtask", "long-animation-frame"] as const;

interface BrowserEntry {
  entryType: string;
  startTime: number;
  duration: number;
  value?: number;
  hadRecentInput?: boolean;
}

/** JSON for inspection, not a Chrome DevTools profile. No DOM text or resource URLs. */
export interface ScrollRecording {
  version: 2;
  startedAt: string;
  savedAt: string;
  timeOrigin: number;
  viewport: { width: number; height: number; devicePixelRatio: number };
  dropped: number;
  marks: { name: string; startTime: number; detail: ThreadViewEvent }[];
  browser: BrowserEntry[];
}

interface ActiveRecording {
  startedAt: string;
  startTime: number;
  dropped: number;
  browser: BrowserEntry[];
  observers: PerformanceObserver[];
}

/** The browser owns the mark timeline; this class collects only opt-in browser metrics. */
export class ScrollCapture {
  #recording: ActiveRecording | null = null;

  startRecording(): void {
    if (this.#recording) return;
    const recording = {
      startedAt: new Date().toISOString(),
      startTime: performance.now(),
      dropped: 0,
      browser: [] as BrowserEntry[],
      observers: [] as PerformanceObserver[],
    } satisfies ActiveRecording;
    this.#recording = recording;
    startThreadViewMarks();
    // These entry types are not available via performance.getEntriesByType(). Observe them live.
    if (typeof PerformanceObserver === "undefined") return;
    for (const type of BROWSER_TYPES) {
      if (!PerformanceObserver.supportedEntryTypes?.includes(type)) continue;
      const observer = new PerformanceObserver((list) =>
        list.getEntries().forEach((entry) => this.#addBrowserEntry(recording, entry))
      );
      observer.observe({ type });
      recording.observers.push(observer);
    }
  }

  #addBrowserEntry(recording: ActiveRecording, entry: PerformanceEntry): void {
    if (recording.browser.length >= MAX_BROWSER_ENTRIES) {
      recording.dropped++;
      return;
    }
    const shift = entry as PerformanceEntry & { value?: number; hadRecentInput?: boolean };
    recording.browser.push({
      entryType: entry.entryType,
      startTime: entry.startTime,
      duration: entry.duration,
      ...(entry.entryType === "layout-shift" ? { value: shift.value, hadRecentInput: shift.hadRecentInput } : {}),
    });
  }

  isRecording(): boolean {
    return this.#recording !== null;
  }

  stopRecording(): ScrollRecording | null {
    const recording = this.#recording;
    if (!recording) return null;
    // Collect entries delivered after the last observer callback before disconnecting.
    for (const observer of recording.observers) {
      // Delivery of takeRecords is not automatic; collect the final entries explicitly.
      for (const entry of observer.takeRecords()) this.#addBrowserEntry(recording, entry);
      observer.disconnect();
    }
    this.#recording = null;
    const droppedMarks = stopThreadViewMarks();
    const marks = performance
      .getEntriesByType("mark")
      .filter((entry) => entry.name.startsWith(MARK_PREFIX) && entry.startTime >= recording.startTime)
      .map((entry) => ({
        name: entry.name,
        startTime: entry.startTime,
        detail: (entry as PerformanceMark).detail as ThreadViewEvent,
      }));
    if (!window.__agentplaneThreadViewMarksEnabled) {
      for (const kind of new Set(marks.map(({ name }) => name))) performance.clearMarks(kind);
    }
    return {
      version: 2,
      startedAt: recording.startedAt,
      savedAt: new Date().toISOString(),
      timeOrigin: performance.timeOrigin,
      viewport: { width: window.innerWidth, height: window.innerHeight, devicePixelRatio: window.devicePixelRatio },
      dropped: recording.dropped + droppedMarks,
      marks,
      browser: recording.browser,
    };
  }
}

/** One capture across the page: it survives switching between threads. */
export const scrollCapture: ScrollCapture = new ScrollCapture();

/** On-device diagnostics only: nothing is uploaded. Row keys can contain identifying metadata. */
export function downloadScrollDiagnostics(recording: ScrollRecording): void {
  const url = URL.createObjectURL(new Blob([JSON.stringify(recording, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `agentplane-scroll-diagnostics-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
