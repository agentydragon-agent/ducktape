// Certify the same owner assignment used for diagnostic comparison, from the JS bytes.
import { writeFileSync } from "node:fs";
import path from "node:path";
import { split } from "../translation/testing/split.mjs";

// A certificate process parses and links a whole deployment. Allow for remote
// CI contention during emission and the subsequent check of the written files.
const certificateTimeoutMs = 90_000;

export function certify({ stage, chunkFile, plan, want, providers, nodeRun }) {
  const output = path.join(stage, "certified");
  const spec = path.join(stage, "certificate-spec.json");
  let manifest;
  let entry = plan.entry;
  // Retain the directory of a nested entry and its fixed source modules.
  // Synthetic filenames live beside that entry in the same deployment.
  const deployment = providers.length > 0 && path.dirname(chunkFile) !== ".";
  if (deployment) {
    entry = chunkFile;
    const route = (name) => (name === plan.entry ? entry : path.posix.join(path.dirname(entry), name));
    const modules = Object.fromEntries(Object.entries(plan.modules).map(([name, units]) => [route(name), units]));
    writeFileSync(spec, JSON.stringify({ entry, modules, order: plan.order.map(route), privateEntryBody: true }));
    const fixed = [...new Set(providers)].map((file) => {
      if (path.isAbsolute(file) || file.split("/").some((part) => !part || part === "." || part === ".."))
        throw new Error("invalid fixed provider route: " + file);
      return { path: file, source: path.join(stage, file) };
    });
    manifest = path.join(stage, "deployment.json");
    writeFileSync(
      manifest,
      JSON.stringify({ entry, chunks: [{ path: entry, source: path.join(stage, chunkFile), spec }, ...fixed] })
    );
  } else {
    writeFileSync(spec, JSON.stringify({ ...plan, privateEntryBody: true }));
  }

  const refusals = {};
  for (const mode of deployment ? ["structural"] : ["structural", "default"]) {
    const options = {
      ...(deployment ? { manifest } : { source: path.join(stage, chunkFile), spec }),
      out: output,
      require: "normal-completion",
      structural: mode === "structural",
      ...(deployment ? { deploymentOrigin: "https://corpus.example" } : {}),
      timeoutMs: certificateTimeoutMs,
    };
    const result = split(options);
    const emission =
      result.status === "certified"
        ? { guarantee: result.guarantee, scope: result.scope }
        : { blocker: result.reason, ...(result.reasonCode && { code: result.reasonCode }) };
    if (result.status === "refused") {
      refusals[mode] = emission;
      continue;
    }

    const checked = split({ ...options, checkOutput: true });
    const disk =
      checked.status === "certified"
        ? { guarantee: checked.guarantee, scope: checked.scope }
        : { blocker: checked.reason, ...(checked.reasonCode && { code: checked.reasonCode }) };
    if (checked.status === "refused") return { outcome: "error:disk", mode, emission, disk };
    if (checked.verdict.guarantee !== result.verdict.guarantee || checked.scope !== result.scope)
      return { outcome: "error:disk", mode, emission, disk };

    const originalRun = nodeRun("original", chunkFile, stage);
    const emittedRun = nodeRun("emitted", path.join(output, entry), stage);
    if (want === null) {
      const equivalent =
        !originalRun.failure &&
        !emittedRun.failure &&
        originalRun.code === emittedRun.code &&
        originalRun.stdout === emittedRun.stdout &&
        originalRun.error === emittedRun.error;
      return {
        outcome: equivalent ? "certified" : "error:runtime",
        mode,
        ...(deployment && { origin: "https://corpus.example" }),
        emission,
        disk,
        original: originalRun,
        emitted: emittedRun,
      };
    }
    const matches = (run) => !run.failure && run.code === 0 && run.stdout === want;
    const original = matches(originalRun);
    const emitted = matches(emittedRun);
    return {
      outcome: original && emitted ? "certified" : "error:runtime",
      mode,
      ...(deployment && { origin: "https://corpus.example" }),
      emission,
      disk,
      original,
      emitted,
    };
  }
  return { outcome: "rejected", refusals };
}
