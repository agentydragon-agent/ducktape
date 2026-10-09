// Browser-test-only collector for thread-view User Timing marks. Unlike the full
// history probe, this does not read layout or run work on every animation frame.
(() => {
  // Installed before the app starts. Production does not set this flag.
  window.__agentplaneThreadViewMarksEnabled = true;
  const historyEvents = [];
  const historyErrors = [];
  const onHistoryMarks = (entries) => {
    for (const entry of entries) {
      if (!entry.name.startsWith("agentplane:thread-view:")) continue;
      const event = entry.detail;
      historyEvents.push({ at: entry.startTime, event });
      if (historyEvents.length > 2000) historyEvents.shift();
      if (event.kind === "measure" && event.first && historyErrors.length < 20_000) {
        historyErrors.push({ error: event.measured - event.estimate, remembered: event.remembered });
      }
      // Browser tests already retain the relevant decisions. Avoid accumulating a second,
      // unbounded copy in the browser's performance timeline.
      performance.clearMarks(entry.name);
    }
  };
  const historyObserver = new PerformanceObserver((list) => onHistoryMarks(list.getEntries()));
  historyObserver.observe({ type: "mark", buffered: true });
  const flushHistory = () => onHistoryMarks(historyObserver.takeRecords());
  window.__threadViewTiming = {
    events: () => {
      flushHistory();
      return historyEvents;
    },
    estimateErrors: () => {
      flushHistory();
      return historyErrors;
    },
  };
})();
