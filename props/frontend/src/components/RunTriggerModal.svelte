<script lang="ts">
  import { untrack } from "svelte";
  import { toast } from "svelte-sonner";
  import { resolve } from "$lib/router";
  import {
    api,
    fetchDefinitions,
    triggerValidationRuns,
    type DefinitionInfo,
    type Split,
    type ExampleKind,
  } from "../lib/api/client";

  interface Prefill {
    definitionId?: string;
    split?: Split;
    kind?: ExampleKind;
  }

  interface Props {
    open: boolean;
    onClose: () => void;
    prefill?: Prefill;
  }

  let { open, onClose, prefill }: Props = $props();

  type RunMode = "validation" | "optimize" | "improve";
  let mode: RunMode = $state("validation");

  // Shared state
  let loading = $state(false);
  let loadingDefinitions = $state(true);
  let definitions: DefinitionInfo[] = $state([]);
  let resultMessage: string | null = $state(null);
  let resultRunId: string | null = $state(null);

  // Validation form
  let selectedDefinition: string = $state("");
  let selectedSplit: Split = $state("valid");
  let selectedKind: ExampleKind = $state("whole_snapshot");
  let nSamples: number = $state(5);
  let valCriticModel: string = $state("gpt-5.1-codex-mini");
  let valBudgetUsd: number = $state(5.0);

  // Optimize form
  let optTargetMetric: string = $state("whole-repo");
  let optBudgetUsd: number = $state(50.0);
  let optOptimizerModel: string = $state("gpt-5.1");
  let optCriticModel: string = $state("gpt-5.1-codex-mini");
  let optTimeout: number = $state(3600);

  // Improve form
  let impNExamples: number = $state(10);
  let impBudgetUsd: number = $state(50.0);
  let impImprovementModel: string = $state("gpt-5.1");
  let impCriticModel: string = $state("gpt-5.1-codex-mini");
  let impTimeout: number = $state(3600);

  let definitionsFetched = false;

  // Fetch definitions on first open, not on mount
  $effect(() => {
    if (open && !definitionsFetched) {
      definitionsFetched = true;
      untrack(async () => {
        try {
          const result = await fetchDefinitions("critic");
          definitions = result.definitions;
          if (definitions.length > 0 && !selectedDefinition) {
            selectedDefinition = definitions[0].image_digest;
          }
        } catch (e) {
          const message = e instanceof Error ? e.message : "Failed to load definitions";
          toast.error(message);
        } finally {
          loadingDefinitions = false;
        }
      });
    }
  });

  $effect(() => {
    if (prefill) {
      if (prefill.definitionId) selectedDefinition = prefill.definitionId;
      if (prefill.split) selectedSplit = prefill.split;
      if (prefill.kind) selectedKind = prefill.kind;
    }
  });

  function clearResult() {
    resultMessage = null;
    resultRunId = null;
  }

  async function handleValidation() {
    if (!selectedDefinition) return;
    loading = true;
    clearResult();
    try {
      const result = await triggerValidationRuns({
        image_digest: selectedDefinition,
        split: selectedSplit,
        example_kind: selectedKind,
        n_samples: nSamples,
        critic_model: valCriticModel,
        budget_usd: valBudgetUsd,
      });
      resultMessage = `${result.message} (job ${result.job_id.slice(0, 8)})`;
      toast.success(resultMessage);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to trigger validation runs");
    } finally {
      loading = false;
    }
  }

  async function handleOptimize() {
    loading = true;
    clearResult();
    try {
      const { data, error } = await api.POST("/api/runs/optimize", {
        body: {
          target_metric: optTargetMetric as "whole-repo" | "targeted",
          budget_usd: optBudgetUsd,
          optimizer_model: optOptimizerModel,
          critic_model: optCriticModel,
          timeout_seconds: optTimeout,
        },
      });
      if (error) throw new Error((error as { detail?: string }).detail ?? "Failed to launch optimize agent");
      resultRunId = data.agent_run_id;
      resultMessage = `Optimize agent launched`;
      toast.success(resultMessage);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to launch optimize agent");
    } finally {
      loading = false;
    }
  }

  async function handleImprove() {
    loading = true;
    clearResult();
    try {
      const { data, error } = await api.POST("/api/runs/improve", {
        body: {
          n_examples: impNExamples,
          budget_usd: impBudgetUsd,
          improvement_model: impImprovementModel,
          critic_model: impCriticModel,
          timeout_seconds: impTimeout,
        },
      });
      if (error) throw new Error((error as { detail?: string }).detail ?? "Failed to launch improve agent");
      resultRunId = data.agent_run_id;
      resultMessage = `Improve agent launched on ${data.n_examples_selected} examples from ${data.definition_id.slice(0, 16)}`;
      toast.success(resultMessage);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to launch improve agent");
    } finally {
      loading = false;
    }
  }

  async function handleTrigger() {
    if (mode === "validation") await handleValidation();
    else if (mode === "optimize") await handleOptimize();
    else if (mode === "improve") await handleImprove();
  }

  function handleBackdropClick(event: MouseEvent) {
    if (event.target === event.currentTarget) onClose();
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") onClose();
  }

  const inputClass = "w-full border rounded px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500";

  const tabs: { key: RunMode; label: string }[] = [
    { key: "validation", label: "Validation" },
    { key: "optimize", label: "Optimize" },
    { key: "improve", label: "Improve" },
  ];
</script>

{#if open}
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div
    class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
    role="dialog"
    aria-modal="true"
    aria-labelledby="modal-title"
    tabindex="-1"
    onclick={handleBackdropClick}
    onkeydown={handleKeydown}
  >
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="bg-white rounded-lg shadow-xl p-6 w-full max-w-md max-h-[90vh] overflow-y-auto"
      role="document"
      onclick={(e) => e.stopPropagation()}
      onkeydown={() => {}}
    >
      <h2 id="modal-title" class="text-lg font-semibold mb-3">Launch Agent</h2>

      <!-- Mode tabs -->
      <div class="flex border-b border-gray-200 mb-4">
        {#each tabs as tab (tab.key)}
          <button
            type="button"
            class="px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors
              {mode === tab.key
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}"
            onclick={() => {
              mode = tab.key;
              clearResult();
            }}
          >
            {tab.label}
          </button>
        {/each}
      </div>

      {#if loadingDefinitions && mode === "validation"}
        <p class="text-gray-500">Loading definitions...</p>
      {:else}
        <div class="space-y-3">
          {#if mode === "validation"}
            <!-- Validation form -->
            <div>
              <label for="m-def" class="block text-sm font-medium text-gray-700 mb-1">Critic Definition</label>
              <select id="m-def" bind:value={selectedDefinition} class={inputClass} disabled={loading}>
                {#each definitions as def (def.image_digest)}
                  <option value={def.image_digest}>{def.image_digest}</option>
                {/each}
              </select>
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label for="m-split" class="block text-sm font-medium text-gray-700 mb-1">Split</label>
                <select id="m-split" bind:value={selectedSplit} class={inputClass} disabled={loading}>
                  <option value="train">Train</option>
                  <option value="valid">Validation</option>
                </select>
              </div>
              <div>
                <label for="m-kind" class="block text-sm font-medium text-gray-700 mb-1">Example Kind</label>
                <select id="m-kind" bind:value={selectedKind} class={inputClass} disabled={loading}>
                  <option value="whole_snapshot">Whole Snapshot</option>
                  <option value="file_set">File Set</option>
                </select>
              </div>
            </div>
            <div>
              <label for="m-model" class="block text-sm font-medium text-gray-700 mb-1">Critic Model</label>
              <input id="m-model" type="text" bind:value={valCriticModel} class={inputClass} disabled={loading} />
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label for="m-budget" class="block text-sm font-medium text-gray-700 mb-1">Budget / critic ($)</label>
                <input
                  id="m-budget"
                  type="number"
                  bind:value={valBudgetUsd}
                  min="0.01"
                  step="0.5"
                  class={inputClass}
                  disabled={loading}
                />
              </div>
              <div>
                <label for="m-n" class="block text-sm font-medium text-gray-700 mb-1">Samples (1-50)</label>
                <input
                  id="m-n"
                  type="number"
                  bind:value={nSamples}
                  min="1"
                  max="50"
                  class={inputClass}
                  disabled={loading}
                />
              </div>
            </div>
          {:else if mode === "optimize"}
            <!-- Optimize form -->
            <div>
              <label for="o-metric" class="block text-sm font-medium text-gray-700 mb-1">Target Metric</label>
              <select id="o-metric" bind:value={optTargetMetric} class={inputClass} disabled={loading}>
                <option value="whole-repo">Whole Repo (full-snapshot validation only)</option>
                <option value="targeted">Targeted (includes per-file validation)</option>
              </select>
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label for="o-optmodel" class="block text-sm font-medium text-gray-700 mb-1">Optimizer Model</label>
                <input
                  id="o-optmodel"
                  type="text"
                  bind:value={optOptimizerModel}
                  class={inputClass}
                  disabled={loading}
                />
              </div>
              <div>
                <label for="o-critmodel" class="block text-sm font-medium text-gray-700 mb-1">Critic Model</label>
                <input id="o-critmodel" type="text" bind:value={optCriticModel} class={inputClass} disabled={loading} />
              </div>
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label for="o-budget" class="block text-sm font-medium text-gray-700 mb-1">Budget ($)</label>
                <input
                  id="o-budget"
                  type="number"
                  bind:value={optBudgetUsd}
                  min="1"
                  step="5"
                  class={inputClass}
                  disabled={loading}
                />
              </div>
              <div>
                <label for="o-timeout" class="block text-sm font-medium text-gray-700 mb-1">Timeout (s)</label>
                <input
                  id="o-timeout"
                  type="number"
                  bind:value={optTimeout}
                  min="60"
                  step="300"
                  class={inputClass}
                  disabled={loading}
                />
              </div>
            </div>
          {:else if mode === "improve"}
            <!-- Improve form -->
            <p class="text-xs text-gray-500 mb-2">
              Auto-selects the best definition (by validation LCB) and top Pareto training examples.
            </p>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label for="i-impmodel" class="block text-sm font-medium text-gray-700 mb-1">Improvement Model</label>
                <input
                  id="i-impmodel"
                  type="text"
                  bind:value={impImprovementModel}
                  class={inputClass}
                  disabled={loading}
                />
              </div>
              <div>
                <label for="i-critmodel" class="block text-sm font-medium text-gray-700 mb-1">Critic Model</label>
                <input id="i-critmodel" type="text" bind:value={impCriticModel} class={inputClass} disabled={loading} />
              </div>
            </div>
            <div class="grid grid-cols-3 gap-3">
              <div>
                <label for="i-n" class="block text-sm font-medium text-gray-700 mb-1">Examples</label>
                <input
                  id="i-n"
                  type="number"
                  bind:value={impNExamples}
                  min="1"
                  max="100"
                  class={inputClass}
                  disabled={loading}
                />
              </div>
              <div>
                <label for="i-budget" class="block text-sm font-medium text-gray-700 mb-1">Budget ($)</label>
                <input
                  id="i-budget"
                  type="number"
                  bind:value={impBudgetUsd}
                  min="1"
                  step="5"
                  class={inputClass}
                  disabled={loading}
                />
              </div>
              <div>
                <label for="i-timeout" class="block text-sm font-medium text-gray-700 mb-1">Timeout (s)</label>
                <input
                  id="i-timeout"
                  type="number"
                  bind:value={impTimeout}
                  min="60"
                  step="300"
                  class={inputClass}
                  disabled={loading}
                />
              </div>
            </div>
          {/if}
        </div>

        <!-- Result message -->
        {#if resultMessage}
          <div class="mt-3 text-sm text-green-700 bg-green-50 p-2 rounded">
            {resultMessage}
            {#if resultRunId}
              — <a href={resolve(`/runs/${resultRunId}`)} class="underline font-medium" onclick={onClose}>view run</a>
            {/if}
          </div>
        {/if}

        <!-- Buttons -->
        <div class="flex justify-end gap-3 mt-4">
          <button
            type="button"
            onclick={onClose}
            disabled={loading}
            class="px-4 py-2 text-sm border border-gray-300 text-gray-700 bg-white rounded hover:bg-gray-50 disabled:opacity-50"
          >
            {resultMessage ? "Close" : "Cancel"}
          </button>
          <button
            type="button"
            onclick={handleTrigger}
            disabled={loading || (mode === "validation" && (!selectedDefinition || valBudgetUsd <= 0))}
            class="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            {loading ? "Launching..." : mode === "validation" ? "Run" : mode === "optimize" ? "Optimize" : "Improve"}
          </button>
        </div>
      {/if}
    </div>
  </div>
{/if}
