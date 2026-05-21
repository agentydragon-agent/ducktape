import { camelizeObjectKeys, decamelizeObjectKeys } from "./lib/casing.js";
import { getJson, postJson } from "./lib/backend_client.js";
import {
  zBootstrapResponse,
  zMetricFanRequest,
  zMetricFanResponse,
  zRolloutRequest,
  zRolloutResponse,
  zScenarioSetInput,
  zScenarioSetRunResponse,
} from "./lib/api/schema.zod.mjs";

export async function fetchAugurBootstrap({ signal } = {}) {
  return camelizeObjectKeys(zBootstrapResponse.parse(await getJson("/api/bootstrap", signal)));
}

export async function runScenarioSet(scenarioSet, { signal } = {}) {
  const request = zScenarioSetInput.parse(decamelizeObjectKeys(scenarioSet));
  return camelizeObjectKeys(zScenarioSetRunResponse.parse(await postJson("/api/scenario_sets/run", request, signal)));
}

export async function fetchProductMetricFan(metricFanRequest, { signal } = {}) {
  const request = zMetricFanRequest.parse(decamelizeObjectKeys(metricFanRequest));
  return camelizeObjectKeys(
    zMetricFanResponse.parse(await postJson("/api/product/projections/metric_fan", request, signal))
  );
}

export async function fetchProductRollout(rolloutRequest, { signal } = {}) {
  const request = zRolloutRequest.parse(decamelizeObjectKeys(rolloutRequest));
  return camelizeObjectKeys(
    zRolloutResponse.parse(await postJson("/api/product/projections/rollout", request, signal))
  );
}
