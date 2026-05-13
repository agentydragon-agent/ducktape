import { camelizeObjectKeys, decamelizeObjectKeys } from "./lib/casing.js";
import { getJson, postJson } from "./lib/backend_client.js";

export async function fetchAugurBootstrap({ signal } = {}) {
  return camelizeObjectKeys(await getJson("/api/bootstrap", signal));
}

export async function runScenarioSet(scenarioSet, { signal } = {}) {
  return camelizeObjectKeys(await postJson("/api/scenario_sets/run", decamelizeObjectKeys(scenarioSet), signal));
}
