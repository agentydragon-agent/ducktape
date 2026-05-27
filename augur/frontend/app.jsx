import React, { useEffect, useMemo, useState } from "react";
import { MantineProvider, NativeSelect } from "@mantine/core";

import { fetchAugurBootstrap, fetchProductMetricFan, fetchProductPortfolio, fetchProductRollout } from "./client.js";
import { fmtNumber, fmtUsd } from "./lib/format.js";

import { MetricFanChart } from "./fan_chart.jsx";
import { TerminalDistributionHistogram } from "./histogram.jsx";
import { TerminalMetricTable } from "./metric_table.jsx";
import { SelectedRolloutEventsPanel, EventKindLegend } from "./events_panel.jsx";
import { ProductScenarioForm } from "./forms.jsx";
import { AugurHeader } from "./header.jsx";
import { RolloutResultsSkeleton, StatCardsSkeleton, ProductProjectionLoading } from "./skeleton.jsx";
import { useVisibleEventKinds, useEventSelection } from "./hooks.js";
import {
  METRIC_OPTIONS,
  productInputDefaults,
  productInputToSearch,
  productInputFromSearch,
  productMetricFanRequest,
} from "./input_helpers.js";
import {
  metricFanRows,
  terminalPercentileValue,
  selectedRolloutMetricRows,
  selectedRolloutEvents,
  visibleMetricOptions,
} from "./data_helpers.js";

function RolloutResultsPanel({
  visibleMetrics,
  selectedMetric,
  onSelectMetric,
  rolloutSummaries,
  selectedSeed,
  onSelectSeed,
  selectedRolloutLoading,
  fanRows,
  percentiles,
  selectedRows,
  selectedEvents,
  selectedSummary,
  visibleEventKinds,
  eventSelection,
  rolloutError,
}) {
  return (
    <section className="augur-panel overflow-hidden" aria-label="Cash projection workspace">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <NativeSelect
          aria-label="Metric to plot"
          value={selectedMetric.value}
          data={visibleMetrics.map((metric) => ({ value: metric.value, label: metric.label }))}
          classNames={{ input: "augur-tabular min-w-[12rem]" }}
          onChange={(event) => onSelectMetric(event.target.value)}
        />
      </div>
      <TerminalDistributionHistogram
        summaries={rolloutSummaries}
        metric={selectedMetric}
        selectedSeed={selectedSeed}
        loadingSeed={selectedRolloutLoading ? selectedSeed : null}
        onSelect={onSelectSeed}
      />
      {fanRows.length > 0 ? (
        <MetricFanChart
          rows={fanRows}
          metric={selectedMetric}
          percentiles={percentiles}
          selectedRows={selectedRows}
          selectedEvents={selectedEvents}
          selectedSeed={selectedSeed}
          selectedFailed={selectedSummary?.failed ?? false}
          visibleEventKinds={visibleEventKinds.visible}
          selectedEventMonthIndex={eventSelection.selectedEventMonthIndex}
          hoveredEventMonthIndex={eventSelection.hoveredEventMonthIndex}
          onSelectEventMonth={eventSelection.onSelectEventMonth}
          onHoverEventMonth={eventSelection.onHoverEventMonth}
        />
      ) : (
        <div className="flex min-h-[22rem] items-center justify-center text-sm augur-muted">Running...</div>
      )}
      {selectedSeed != null && selectedEvents.length > 0 && (
        <EventKindLegend events={selectedEvents} visibility={visibleEventKinds} />
      )}
      {rolloutError && (
        <div className="border-t border-slate-200 p-4 dark:border-slate-700">
          <div className="augur-note-danger">Selected rollout failed to load: {rolloutError}</div>
        </div>
      )}
      {selectedSeed != null && (
        <SelectedRolloutEventsPanel
          events={selectedEvents}
          selectedSummary={selectedSummary}
          loading={selectedRolloutLoading}
          selectedEventMonthIndex={eventSelection.selectedEventMonthIndex}
          hoveredEventMonthIndex={eventSelection.hoveredEventMonthIndex}
          onSelectEventMonth={eventSelection.onSelectEventMonth}
          onHoverEventMonth={eventSelection.onHoverEventMonth}
        />
      )}
      <TerminalMetricTable
        summaries={rolloutSummaries}
        selectedSummary={selectedSummary}
        metrics={visibleMetrics}
        selectedMetric={selectedMetric}
      />
    </section>
  );
}

function ProductProjectionWorkspace({ bootstrap }) {
  const [input, setInput] = useState(() => productInputFromSearch(window.location.search, bootstrap));
  const [selectedMetricValue, setSelectedMetricValue] = useState("net_worth_usd");
  const [result, setResult] = useState(null);
  const [runError, setRunError] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [portfolioError, setPortfolioError] = useState(null);
  const [selectedSeed, setSelectedSeed] = useState(null);
  const [rolloutDetails, setRolloutDetails] = useState(() => new Map());
  const [rolloutError, setRolloutError] = useState(null);
  const eventSelection = useEventSelection();
  const visibleEventKinds = useVisibleEventKinds();
  const visibleMetrics = useMemo(() => visibleMetricOptions(input), [input]);
  const selectedMetric =
    visibleMetrics.find((metric) => metric.value === selectedMetricValue) ?? visibleMetrics[0] ?? METRIC_OPTIONS[0];
  const request = useMemo(
    () => productMetricFanRequest(input, bootstrap, selectedMetric),
    [input, bootstrap, selectedMetric]
  );
  const scenarioCacheKey = useMemo(() => JSON.stringify(request.scenario), [request.scenario]);
  const fanRows = useMemo(() => metricFanRows(result), [result]);
  const rolloutSummaries = result?.rolloutSummaries ?? [];
  const selectedSummary = useMemo(
    () => rolloutSummaries.find((summary) => Number(summary.seed) === selectedSeed) ?? null,
    [rolloutSummaries, selectedSeed]
  );
  const selectedDetailKey = selectedSeed == null ? null : `${scenarioCacheKey}|${selectedSeed}`;
  const selectedDetail = selectedDetailKey ? rolloutDetails.get(selectedDetailKey) : null;
  const selectedRows = useMemo(
    () => selectedRolloutMetricRows(selectedDetail, selectedMetric),
    [selectedDetail, selectedMetric]
  );
  const selectedEvents = useMemo(() => selectedRolloutEvents(selectedDetail), [selectedDetail]);
  const failedCount = result?.failedCount ?? null;
  const terminalP50 = terminalPercentileValue(result, 50);
  const updateInput = (patch) => setInput((previous) => ({ ...previous, ...patch }));
  const selectedRolloutLoading = selectedSeed != null && result != null && !selectedDetail && !rolloutError;

  useEffect(() => {
    const search = productInputToSearch(input, bootstrap);
    const newUrl = `${window.location.pathname}${search ? "?" + search : ""}${window.location.hash}`;
    if (newUrl !== window.location.pathname + window.location.search + window.location.hash) {
      window.history.replaceState(null, "", newUrl);
    }
  }, [input, bootstrap]);

  useEffect(() => {
    const controller = new AbortController();
    fetchProductPortfolio({ signal: controller.signal })
      .then((payload) => {
        setPortfolio(payload);
        setPortfolioError(null);
      })
      .catch((error) => {
        if (error?.name === "AbortError") return;
        setPortfolio(null);
        setPortfolioError(error?.message || String(error));
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setResult(null);
    const handle = setTimeout(() => {
      fetchProductMetricFan(request, { signal: controller.signal })
        .then((payload) => {
          setResult(payload);
          setRunError(null);
        })
        .catch((error) => {
          if (error?.name === "AbortError") return;
          setResult(null);
          setRunError(error?.message || String(error));
        });
    }, 120);
    return () => {
      clearTimeout(handle);
      controller.abort();
    };
  }, [request]);

  useEffect(() => {
    if (selectedSeed == null || !result?.rolloutSummaries) return;
    if (!result.rolloutSummaries.some((summary) => Number(summary.seed) === selectedSeed)) {
      setSelectedSeed(null);
    }
  }, [result, selectedSeed]);

  useEffect(() => {
    eventSelection.clear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDetailKey]);

  useEffect(() => {
    if (selectedSeed == null || result == null || selectedDetailKey == null) return;
    if (rolloutDetails.has(selectedDetailKey)) return;
    const controller = new AbortController();
    setRolloutError(null);
    fetchProductRollout({ scenario: request.scenario, seed: selectedSeed }, { signal: controller.signal })
      .then((payload) => {
        setRolloutDetails((previous) => {
          const next = new Map(previous);
          next.set(selectedDetailKey, payload);
          return next;
        });
      })
      .catch((error) => {
        if (error?.name === "AbortError") return;
        setRolloutError(error?.message || String(error));
      });
    return () => controller.abort();
  }, [request.scenario, result, rolloutDetails, selectedDetailKey, selectedSeed]);

  return (
    <div
      data-augur-surface="product"
      className="min-h-screen bg-slate-100 text-slate-800 dark:bg-slate-950 dark:text-slate-100"
    >
      <AugurHeader
        rightSlot={<span className="whitespace-nowrap">{fmtNumber(request.rolloutSeeds.length)} rollouts</span>}
      />

      <main className="px-4 py-6 sm:px-6 lg:px-8">
        <section className="grid min-w-0 gap-5 xl:grid-cols-[34rem_minmax(0,1fr)]">
          <ProductScenarioForm
            input={input}
            bootstrap={bootstrap}
            portfolio={portfolio}
            portfolioError={portfolioError}
            onChange={updateInput}
            onReset={() => setInput(productInputDefaults(bootstrap))}
          />

          <div className="min-w-0 space-y-5">
            {runError && <div className="augur-note-danger p-4 text-sm">Product projection failed: {runError}</div>}

            {result ? (
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="augur-card p-4">
                  <div className="augur-eyebrow">Median terminal {selectedMetric.label.toLowerCase()}</div>
                  <div className="mt-2 text-2xl font-semibold augur-tabular">{fmtUsd(terminalP50)}</div>
                </div>
                <div className="augur-card p-4">
                  <div className="augur-eyebrow">Failed rollouts</div>
                  <div className="mt-2 text-2xl font-semibold augur-tabular">
                    {fmtNumber(failedCount)} / {fmtNumber(request.rolloutSeeds.length)}
                  </div>
                </div>
                <div className="augur-card p-4">
                  <div className="augur-eyebrow">Exogenous model</div>
                  <div className="mt-2 text-sm font-semibold augur-tabular">{result.exogenousModelId}</div>
                </div>
              </div>
            ) : (
              <StatCardsSkeleton />
            )}

            {result ? (
              <RolloutResultsPanel
                visibleMetrics={visibleMetrics}
                selectedMetric={selectedMetric}
                onSelectMetric={setSelectedMetricValue}
                rolloutSummaries={rolloutSummaries}
                selectedSeed={selectedSeed}
                onSelectSeed={setSelectedSeed}
                selectedRolloutLoading={selectedRolloutLoading}
                fanRows={fanRows}
                percentiles={request.percentiles}
                selectedRows={selectedRows}
                selectedEvents={selectedEvents}
                selectedSummary={selectedSummary}
                visibleEventKinds={visibleEventKinds}
                eventSelection={eventSelection}
                rolloutError={rolloutError}
              />
            ) : (
              <RolloutResultsSkeleton />
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

function ProductProjectionAppShell() {
  const [bootstrap, setBootstrap] = useState(null);
  const [bootstrapError, setBootstrapError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchAugurBootstrap({ signal: controller.signal })
      .then((payload) => {
        setBootstrap(payload);
        setBootstrapError(null);
      })
      .catch((error) => {
        if (error?.name === "AbortError") return;
        setBootstrap(null);
        setBootstrapError(error?.message || String(error));
      });
    return () => controller.abort();
  }, []);

  if (!bootstrap) return <ProductProjectionLoading error={bootstrapError} />;

  return <ProductProjectionWorkspace bootstrap={bootstrap} />;
}

export default function AugurApp() {
  return (
    <MantineProvider defaultColorScheme="auto">
      <ProductProjectionAppShell />
    </MantineProvider>
  );
}
