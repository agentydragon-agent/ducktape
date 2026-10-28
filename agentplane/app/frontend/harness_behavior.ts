import type { Harness } from "./schema";

interface HarnessBehavior {
  commandsRequireReadySandbox: boolean;
  llmTraceScope: "sandbox" | "session";
}

export function harnessBehavior(harness: Harness | null | undefined): HarnessBehavior {
  switch (harness) {
    case "HARNESS_CENTRAL_SAMPLER":
      return { commandsRequireReadySandbox: false, llmTraceScope: "session" };
    case "HARNESS_CODEX":
    case "HARNESS_CLAUDE":
    case null:
    case undefined:
      return { commandsRequireReadySandbox: true, llmTraceScope: "sandbox" };
  }
}
