import { camelizeObjectKeys, decamelizeObjectKeys } from "./casing.js";

export const SCENARIO_COLORS = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2"];

const URL_STATE_VERSION = 3;

const DEFAULT_MARKET_REQUEST = {
  marketModelId: "current_market_model",
  rolloutCount: 128,
  horizonMonths: 360,
  seed: 0,
};

const DEFAULT_REPORT_SPEC = {
  metrics: ["net_worth", "liquid_net_worth", "home_equity", "actor_equity", "property_value"],
  percentiles: [5, 25, 50, 75, 95],
  includeMonthlyColumns: true,
  includeSamplePaths: false,
};

const FINANCING_MODE_IDS = new Set(["cash", "fixed_30", "fixed_15", "custom"]);
const PRIVATE_EQUITY_SALE_POLICY_IDS = new Set(["none", "liquid_net_worth_floor"]);

const SCENARIO_INPUT_SECTION_FIELDS = Object.freeze({
  identity: Object.freeze(["scenarioId", "label", "enabled", "color"]),
  propertyAndLocation: Object.freeze(["propertyId"]),
  actorsAndOwnership: Object.freeze(["actorPolicy", "partnerPaymentMonthlyUsd"]),
  timeline: Object.freeze(["holdYears"]),
  financing: Object.freeze([
    "financingMode",
    "downPaymentPct",
    "customMortgageRate",
    "customMortgageTermYears",
    "creditScore",
  ]),
  occupancyAndRental: Object.freeze([
    "ownerResidenceMode",
    "rentalUsePolicy",
    "vacancyPct",
    "managementFeePct",
    "leasingFeePct",
    "roomsRentedWhileLiving",
    "roomRentMonthlyUsd",
    "roomVacancyPct",
  ]),
  propertyAssumptions: Object.freeze(["maintenancePct", "insuranceAnnualUsd", "depreciableBasisPct"]),
  taxAccounting: Object.freeze([
    "closingCostBuyPct",
    "closingCostSellPct",
    "capGainsExclusionUsd",
    "marginalTaxRate",
    "capGainsRate",
  ]),
  initialBalanceSheet: Object.freeze([
    "initialCheckingUsd",
    "startingPortfolioUsd",
    "privateEquityValueUsd",
    "privateEquityUnits",
  ]),
  policies: Object.freeze([
    "liquidReservePolicy",
    "checkingFloorUsd",
    "checkingSaleAmountUsd",
    "privateEquitySalePolicy",
    "privateEquityLiquidNetWorthFloorUsd",
    "privateEquityTenderSaleAmountUsd",
  ]),
});

function finiteNumber(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function nullableNumber(value, fallback = null) {
  if (value === null || value === undefined || value === "") return fallback;
  return finiteNumber(value, fallback);
}

function positiveNumber(value, fallback) {
  const number = finiteNumber(value, fallback);
  return number > 0 ? number : fallback;
}

function nullableInteger(value, fallback = null) {
  if (value === null || value === undefined || value === "") return fallback;
  const number = Number(value);
  return Number.isInteger(number) ? number : fallback;
}

function optionIds(options) {
  return new Set((options ?? []).map((option) => option.id));
}

function defaultOption(options, fallback) {
  return options?.[0]?.id ?? fallback;
}

function propertyById(bootstrap, propertyId) {
  return bootstrap?.properties?.find((property) => property.id === propertyId) ?? bootstrap?.properties?.[0] ?? null;
}

function defaultPropertyId(bootstrap) {
  return bootstrap?.defaultPropertyId ?? bootstrap?.properties?.[0]?.id ?? null;
}

function defaultConcentratedHolding(bootstrap) {
  return bootstrap?.financeSnapshot?.concentratedHoldings?.[0] ?? null;
}

function holdingValueUsd(holding) {
  return finiteNumber(holding?.valueUsd, finiteNumber(holding?.units, 0) * finiteNumber(holding?.fmvUsdPerUnit, 0));
}

function hasOwnField(value, field) {
  return Object.prototype.hasOwnProperty.call(value ?? {}, field);
}

function scenarioInputSectionsFromFlatFields(fields, { includeMissing }) {
  const source = fields ?? {};
  return Object.fromEntries(
    Object.entries(SCENARIO_INPUT_SECTION_FIELDS).map(([section, fieldNames]) => [
      section,
      Object.fromEntries(
        fieldNames.flatMap((fieldName) =>
          includeMissing || hasOwnField(source, fieldName) ? [[fieldName, source[fieldName]]] : []
        )
      ),
    ])
  );
}

export function scenarioInputFromFlatFields(fields) {
  return scenarioInputSectionsFromFlatFields(fields, { includeMissing: true });
}

function nonEmptyObject(value) {
  return Boolean(value && typeof value === "object" && Object.keys(value).length > 0);
}

export function scenarioResultDataModes(scenarioResult) {
  const modes = [];
  if (nonEmptyObject(scenarioResult?.metricFanColumns) || nonEmptyObject(scenarioResult?.terminalColumns)) {
    modes.push("distribution");
  }
  if (nonEmptyObject(scenarioResult?.monthlyColumns)) {
    modes.push("trajectory");
  }
  return modes;
}

export function scenarioResultSupportsMode(scenarioResult, mode) {
  return scenarioResultDataModes(scenarioResult).includes(mode);
}

export function privateEquityCurrentUnitPriceUsd(bootstrap) {
  const holding = defaultConcentratedHolding(bootstrap);
  const fmv = finiteNumber(holding?.fmvUsdPerUnit, NaN);
  if (Number.isFinite(fmv)) return fmv;
  const units = finiteNumber(holding?.units, 0);
  return units > 0 ? holdingValueUsd(holding) / units : 0;
}

export function privateEquityValueUsdForUnits(bootstrap, units) {
  return Math.max(0, finiteNumber(units, 0)) * privateEquityCurrentUnitPriceUsd(bootstrap);
}

function scenarioIdFromIndex(index) {
  return `scenario_${index + 1}`;
}

function scenarioFromFields(fields) {
  return scenarioInputFromFlatFields(fields);
}

export function scenarioInputView(scenario) {
  return Object.fromEntries(
    Object.entries(SCENARIO_INPUT_SECTION_FIELDS).flatMap(([section, fieldNames]) =>
      fieldNames.map((fieldName) => [fieldName, scenario?.[section]?.[fieldName] ?? scenario?.[fieldName]])
    )
  );
}

export function patchScenarioInput(scenario, patch) {
  const next = {
    ...scenario,
  };
  for (const section of Object.keys(SCENARIO_INPUT_SECTION_FIELDS)) {
    next[section] = { ...(scenario?.[section] ?? {}) };
  }
  const sections = scenarioInputSectionsFromFlatFields(patch, { includeMissing: false });
  for (const [section, values] of Object.entries(sections)) {
    Object.assign(next[section], values);
  }
  return next;
}

export function patchScenarioInputSection(scenario, section, patch) {
  if (!Object.hasOwn(SCENARIO_INPUT_SECTION_FIELDS, section)) {
    throw new Error(`Unknown Augur scenario input section: ${section}`);
  }
  return {
    ...scenario,
    [section]: {
      ...(scenario?.[section] ?? {}),
      ...(patch ?? {}),
    },
  };
}

export function uniqueScenarioId(existingScenarioIds, base = "scenario") {
  const existing = new Set(existingScenarioIds);
  let index = 1;
  let candidate = `${base}_${index}`;
  while (existing.has(candidate)) {
    index += 1;
    candidate = `${base}_${index}`;
  }
  return candidate;
}

export function createScenarioInput(bootstrap, overrides = {}) {
  const index = finiteNumber(overrides.index, 0);
  const fallbackPropertyId = defaultPropertyId(bootstrap);
  const propertyId = overrides.propertyId ?? fallbackPropertyId;
  const property = propertyById(bootstrap, propertyId);
  const defaultKnobs = bootstrap?.defaultKnobs ?? {};
  const holding = defaultConcentratedHolding(bootstrap);
  const privateEquityUnits = finiteNumber(overrides.privateEquityUnits, holding?.units ?? 0);
  return scenarioFromFields({
    scenarioId: overrides.scenarioId ?? scenarioIdFromIndex(index),
    label: overrides.label ?? (property?.address ? `${property.address}` : `Scenario ${index + 1}`),
    enabled: overrides.enabled ?? true,
    color: overrides.color ?? SCENARIO_COLORS[index % SCENARIO_COLORS.length],
    propertyId,
    actorPolicy:
      overrides.actorPolicy ??
      bootstrap?.defaultActorPolicy ??
      defaultOption(bootstrap?.actorPolicyOptions, "owner_only"),
    ownerResidenceMode:
      overrides.ownerResidenceMode ??
      bootstrap?.defaultOwnerResidenceMode ??
      defaultOption(bootstrap?.ownerResidenceModeOptions, "selected_property"),
    rentalUsePolicy:
      overrides.rentalUsePolicy ??
      bootstrap?.defaultRentalUsePolicy ??
      defaultOption(bootstrap?.rentalUsePolicyOptions, "not_rented"),
    liquidReservePolicy:
      overrides.liquidReservePolicy ??
      bootstrap?.defaultLiquidReservePolicy ??
      defaultOption(bootstrap?.liquidReservePolicyOptions, "none"),
    initialCheckingUsd: finiteNumber(overrides.initialCheckingUsd, bootstrap?.defaultInitialCheckingUsd ?? 25_000),
    checkingFloorUsd: finiteNumber(overrides.checkingFloorUsd, bootstrap?.defaultCheckingFloorUsd ?? 10_000),
    checkingSaleAmountUsd: positiveNumber(
      overrides.checkingSaleAmountUsd,
      bootstrap?.defaultCheckingSaleAmountUsd ?? 20_000
    ),
    startingPortfolioUsd: finiteNumber(
      overrides.startingPortfolioUsd,
      defaultKnobs.startingPortfolioUsd ?? bootstrap?.financeSnapshot?.sp500ProxyPortfolioUsd ?? 0
    ),
    partnerPaymentMonthlyUsd: finiteNumber(
      overrides.partnerPaymentMonthlyUsd,
      bootstrap?.defaultPartnerMonthlyPaymentUsd ?? 0
    ),
    holdYears: positiveNumber(overrides.holdYears, defaultKnobs.holdYears ?? 5),
    financingMode: FINANCING_MODE_IDS.has(overrides.financingMode)
      ? overrides.financingMode
      : (defaultKnobs.financingMode ?? "fixed_30"),
    downPaymentPct: finiteNumber(overrides.downPaymentPct, defaultKnobs.downPaymentPct ?? 25),
    customMortgageRate: nullableNumber(overrides.customMortgageRate, defaultKnobs.customMortgageRate ?? null),
    customMortgageTermYears: positiveNumber(
      overrides.customMortgageTermYears,
      defaultKnobs.customMortgageTermYears ?? 30
    ),
    creditScore: nullableNumber(overrides.creditScore, defaultKnobs.creditScore ?? null),
    vacancyPct: finiteNumber(overrides.vacancyPct, defaultKnobs.vacancyPct ?? 0),
    managementFeePct: finiteNumber(overrides.managementFeePct, defaultKnobs.mgmtPct ?? 0),
    leasingFeePct: finiteNumber(overrides.leasingFeePct, defaultKnobs.leasingFeePct ?? 0),
    roomsRentedWhileLiving: finiteNumber(overrides.roomsRentedWhileLiving, defaultKnobs.roomsRentedWhileLiving ?? 0),
    roomRentMonthlyUsd: finiteNumber(overrides.roomRentMonthlyUsd, defaultKnobs.roomRentMonthlyUsd ?? 0),
    roomVacancyPct: finiteNumber(overrides.roomVacancyPct, defaultKnobs.roomVacancyPct ?? 0),
    maintenancePct: finiteNumber(overrides.maintenancePct, defaultKnobs.maintenancePct ?? 1),
    insuranceAnnualUsd: finiteNumber(overrides.insuranceAnnualUsd, defaultKnobs.insuranceAnnualUsd ?? 0),
    closingCostBuyPct: finiteNumber(overrides.closingCostBuyPct, defaultKnobs.closingCostBuyPct ?? 0),
    closingCostSellPct: finiteNumber(overrides.closingCostSellPct, defaultKnobs.closingCostSellPct ?? 0),
    capGainsExclusionUsd: finiteNumber(overrides.capGainsExclusionUsd, defaultKnobs.capGainsExclusionUsd ?? 0),
    depreciableBasisPct: finiteNumber(overrides.depreciableBasisPct, defaultKnobs.depreciableBasisPct ?? 0),
    marginalTaxRate: finiteNumber(overrides.marginalTaxRate, defaultKnobs.marginalTaxRate ?? 0),
    capGainsRate: finiteNumber(overrides.capGainsRate, defaultKnobs.capGainsRate ?? 0),
    privateEquityValueUsd: privateEquityValueUsdForUnits(bootstrap, privateEquityUnits),
    privateEquityUnits,
    privateEquitySalePolicy: PRIVATE_EQUITY_SALE_POLICY_IDS.has(overrides.privateEquitySalePolicy)
      ? overrides.privateEquitySalePolicy
      : "none",
    privateEquityLiquidNetWorthFloorUsd: finiteNumber(overrides.privateEquityLiquidNetWorthFloorUsd, 0),
    privateEquityTenderSaleAmountUsd: positiveNumber(overrides.privateEquityTenderSaleAmountUsd, 50_000),
  });
}

export function createDefaultScenarioSetInput(bootstrap) {
  const defaultScenarioSpecs =
    Array.isArray(bootstrap?.defaultScenarios) && bootstrap.defaultScenarios.length > 0
      ? bootstrap.defaultScenarios
      : [{ propertyId: defaultPropertyId(bootstrap), actorPolicy: bootstrap?.defaultActorPolicy }];
  const scenarios = defaultScenarioSpecs.map((spec, index) =>
    createScenarioInput(bootstrap, {
      index,
      propertyId: spec.propertyId,
      actorPolicy: spec.actorPolicy,
      label: spec.label,
    })
  );
  return {
    title: "Augur futures comparison",
    marketRequest: {
      ...DEFAULT_MARKET_REQUEST,
      rolloutCount: bootstrap?.defaultRolloutSamples ?? DEFAULT_MARKET_REQUEST.rolloutCount,
    },
    reportSpec: DEFAULT_REPORT_SPEC,
    scenarios,
  };
}

function normalizeScenarioInput(scenario, bootstrap, index, existingIds) {
  const sourceScenario = scenarioInputView(scenario);
  const propertyIds = new Set((bootstrap?.properties ?? []).map((property) => property.id));
  const actorPolicyIds = optionIds(bootstrap?.actorPolicyOptions);
  const ownerResidenceModeIds = optionIds(bootstrap?.ownerResidenceModeOptions);
  const rentalUsePolicyIds = optionIds(bootstrap?.rentalUsePolicyOptions);
  const liquidReservePolicyIds = optionIds(bootstrap?.liquidReservePolicyOptions);
  const defaultScenario = createScenarioInput(bootstrap, { index });
  const defaultView = scenarioInputView(defaultScenario);
  const privateEquityUnits = finiteNumber(sourceScenario.privateEquityUnits, defaultView.privateEquityUnits);
  const privateEquityValueUsd = privateEquityValueUsdForUnits(bootstrap, privateEquityUnits);
  const scenarioId =
    typeof sourceScenario.scenarioId === "string" && /^[a-z0-9][a-z0-9_-]*$/.test(sourceScenario.scenarioId)
      ? sourceScenario.scenarioId
      : uniqueScenarioId(existingIds, "scenario");
  existingIds.add(scenarioId);
  return scenarioFromFields({
    ...defaultView,
    scenarioId,
    label:
      typeof sourceScenario.label === "string" && sourceScenario.label.trim()
        ? sourceScenario.label.trim()
        : defaultView.label,
    enabled: Boolean(sourceScenario.enabled ?? defaultView.enabled),
    color: typeof sourceScenario.color === "string" && sourceScenario.color ? sourceScenario.color : defaultView.color,
    propertyId: propertyIds.has(sourceScenario.propertyId) ? sourceScenario.propertyId : defaultView.propertyId,
    actorPolicy: actorPolicyIds.has(sourceScenario.actorPolicy) ? sourceScenario.actorPolicy : defaultView.actorPolicy,
    ownerResidenceMode: ownerResidenceModeIds.has(sourceScenario.ownerResidenceMode)
      ? sourceScenario.ownerResidenceMode
      : defaultView.ownerResidenceMode,
    rentalUsePolicy: rentalUsePolicyIds.has(sourceScenario.rentalUsePolicy)
      ? sourceScenario.rentalUsePolicy
      : defaultView.rentalUsePolicy,
    liquidReservePolicy: liquidReservePolicyIds.has(sourceScenario.liquidReservePolicy)
      ? sourceScenario.liquidReservePolicy
      : defaultView.liquidReservePolicy,
    initialCheckingUsd: finiteNumber(sourceScenario.initialCheckingUsd, defaultView.initialCheckingUsd),
    checkingFloorUsd: finiteNumber(sourceScenario.checkingFloorUsd, defaultView.checkingFloorUsd),
    checkingSaleAmountUsd: positiveNumber(sourceScenario.checkingSaleAmountUsd, defaultView.checkingSaleAmountUsd),
    startingPortfolioUsd: finiteNumber(sourceScenario.startingPortfolioUsd, defaultView.startingPortfolioUsd),
    partnerPaymentMonthlyUsd: finiteNumber(
      sourceScenario.partnerPaymentMonthlyUsd,
      defaultView.partnerPaymentMonthlyUsd
    ),
    holdYears: positiveNumber(sourceScenario.holdYears, defaultView.holdYears),
    financingMode: FINANCING_MODE_IDS.has(sourceScenario.financingMode)
      ? sourceScenario.financingMode
      : defaultView.financingMode,
    downPaymentPct: finiteNumber(sourceScenario.downPaymentPct, defaultView.downPaymentPct),
    customMortgageRate: nullableNumber(sourceScenario.customMortgageRate, defaultView.customMortgageRate),
    customMortgageTermYears: positiveNumber(
      sourceScenario.customMortgageTermYears,
      defaultView.customMortgageTermYears
    ),
    creditScore: nullableNumber(sourceScenario.creditScore, defaultView.creditScore),
    vacancyPct: finiteNumber(sourceScenario.vacancyPct, defaultView.vacancyPct),
    managementFeePct: finiteNumber(sourceScenario.managementFeePct, defaultView.managementFeePct),
    leasingFeePct: finiteNumber(sourceScenario.leasingFeePct, defaultView.leasingFeePct),
    roomsRentedWhileLiving: finiteNumber(sourceScenario.roomsRentedWhileLiving, defaultView.roomsRentedWhileLiving),
    roomRentMonthlyUsd: finiteNumber(sourceScenario.roomRentMonthlyUsd, defaultView.roomRentMonthlyUsd),
    roomVacancyPct: finiteNumber(sourceScenario.roomVacancyPct, defaultView.roomVacancyPct),
    maintenancePct: finiteNumber(sourceScenario.maintenancePct, defaultView.maintenancePct),
    insuranceAnnualUsd: finiteNumber(sourceScenario.insuranceAnnualUsd, defaultView.insuranceAnnualUsd),
    closingCostBuyPct: finiteNumber(sourceScenario.closingCostBuyPct, defaultView.closingCostBuyPct),
    closingCostSellPct: finiteNumber(sourceScenario.closingCostSellPct, defaultView.closingCostSellPct),
    capGainsExclusionUsd: finiteNumber(sourceScenario.capGainsExclusionUsd, defaultView.capGainsExclusionUsd),
    depreciableBasisPct: finiteNumber(sourceScenario.depreciableBasisPct, defaultView.depreciableBasisPct),
    marginalTaxRate: finiteNumber(sourceScenario.marginalTaxRate, defaultView.marginalTaxRate),
    capGainsRate: finiteNumber(sourceScenario.capGainsRate, defaultView.capGainsRate),
    privateEquityValueUsd,
    privateEquityUnits,
    privateEquitySalePolicy: PRIVATE_EQUITY_SALE_POLICY_IDS.has(sourceScenario.privateEquitySalePolicy)
      ? sourceScenario.privateEquitySalePolicy
      : defaultView.privateEquitySalePolicy,
    privateEquityLiquidNetWorthFloorUsd: finiteNumber(
      sourceScenario.privateEquityLiquidNetWorthFloorUsd,
      defaultView.privateEquityLiquidNetWorthFloorUsd
    ),
    privateEquityTenderSaleAmountUsd: positiveNumber(
      sourceScenario.privateEquityTenderSaleAmountUsd,
      defaultView.privateEquityTenderSaleAmountUsd
    ),
  });
}

export function normalizeScenarioSetInput(input, bootstrap) {
  const fallback = createDefaultScenarioSetInput(bootstrap);
  const existingIds = new Set();
  const scenariosSource =
    Array.isArray(input?.scenarios) && input.scenarios.length > 0 ? input.scenarios : fallback.scenarios;
  const scenarios = scenariosSource.map((scenario, index) =>
    normalizeScenarioInput(scenario, bootstrap, index, existingIds)
  );
  const horizonMonths = Math.max(
    1,
    ...scenarios.map((scenario) => Math.ceil(scenarioInputView(scenario).holdYears * 12))
  );
  return {
    title: typeof input?.title === "string" && input.title.trim() ? input.title.trim() : fallback.title,
    marketRequest: {
      ...fallback.marketRequest,
      ...(input?.marketRequest && typeof input.marketRequest === "object" ? input.marketRequest : {}),
      horizonMonths,
      rolloutCount: positiveNumber(input?.marketRequest?.rolloutCount, fallback.marketRequest.rolloutCount),
      seed: nullableInteger(input?.marketRequest?.seed, fallback.marketRequest.seed),
    },
    reportSpec: normalizeReportSpec(input?.reportSpec, fallback.reportSpec),
    scenarios,
  };
}

function normalizeReportSpec(reportSpec, fallback) {
  const source = reportSpec && typeof reportSpec === "object" ? reportSpec : {};
  return {
    ...fallback,
    ...source,
    includeMonthlyColumns: Boolean(source.includeMonthlyColumns ?? fallback.includeMonthlyColumns),
    includeSamplePaths: false,
  };
}

function agentsByRole(bootstrap) {
  const agents = bootstrap?.agents ?? [];
  const primary = agents.find((a) => a.role === "primary_owner");
  const partner = agents.find((a) => a.role === "equity_building_occupant") ?? null;
  return { primary, partner };
}

function occupancyModeForScenario(scenario) {
  const view = scenarioInputView(scenario);
  if (view.ownerResidenceMode === "other_owned_property") {
    return "owner_lives_in_other_owned_property";
  }
  if (view.ownerResidenceMode === "rental_elsewhere") {
    return "owner_rents_elsewhere";
  }
  if (view.rentalUsePolicy === "rent_whole_property") {
    return "no_owner_occupancy";
  }
  return "owner_lives_in_property";
}

function rentalModeForScenario(scenario) {
  const view = scenarioInputView(scenario);
  if (view.rentalUsePolicy === "rent_rooms_while_owner_lives_there") {
    return "rent_rooms_while_owner_lives_there";
  }
  if (view.rentalUsePolicy === "rent_whole_property") {
    return "rent_whole_property";
  }
  return "not_rented";
}

function scenarioPolicies(scenario, bootstrap) {
  const view = scenarioInputView(scenario);
  const { primary, partner } = agentsByRole(bootstrap);
  const policies = [];
  if (view.actorPolicy === "owner_plus_partner" && partner) {
    policies.push({
      policyId: "partner_equity_accrual",
      policyType: "partner_equity_accrual",
      actorId: partner.actorId,
      enabled: view.enabled,
      baseMonthlyPaymentUsd: view.partnerPaymentMonthlyUsd,
    });
  }
  if (view.liquidReservePolicy === "checking_floor_sp500") {
    policies.push({
      policyId: "checking_floor",
      policyType: "checking_floor_sell_public_stock",
      actorId: primary.actorId,
      enabled: true,
      floorUsd: view.checkingFloorUsd,
      saleAmountUsd: view.checkingSaleAmountUsd,
    });
  }
  if (view.privateEquitySalePolicy === "liquid_net_worth_floor") {
    policies.push({
      policyId: "private_equity_liquid_floor_sale",
      policyType: "private_equity_sale",
      actorId: primary.actorId,
      enabled: true,
      proceedsDestination: "generic_sp500_stock",
      saleRule: {
        saleRuleType: "liquid_net_worth_floor",
        minLiquidNetWorthUsd: view.privateEquityLiquidNetWorthFloorUsd,
        saleAmountUsd: view.privateEquityTenderSaleAmountUsd,
      },
    });
  }
  return policies;
}

function scenarioActors(scenario, bootstrap) {
  const view = scenarioInputView(scenario);
  const { primary, partner } = agentsByRole(bootstrap);
  const actors = [
    {
      actorId: primary.actorId,
      label: primary.label,
      role: primary.role,
    },
  ];
  if (view.actorPolicy === "owner_plus_partner" && partner) {
    actors.push({
      actorId: partner.actorId,
      label: partner.label,
      role: partner.role,
    });
  }
  return actors;
}

function scenarioEvents(scenario, property, bootstrap) {
  const view = scenarioInputView(scenario);
  const { primary } = agentsByRole(bootstrap);
  const downPaymentPct = view.downPaymentPct;
  const loanAmountUsd = Math.max(0, (property?.priceUsd ?? 0) * (1 - downPaymentPct / 100));
  const events = [
    {
      eventId: "purchase",
      eventType: "property_purchase",
      monthIndex: 0,
      actorId: primary.actorId,
      propertyId: view.propertyId,
      amountUsd: property?.priceUsd ?? 0,
      description: "Property purchase at scenario start.",
      hoaMonthlyUsd: property?.hoaMonthlyUsd ?? 0,
    },
    {
      eventId: "mortgage",
      eventType: "mortgage_origination",
      monthIndex: 0,
      actorId: primary.actorId,
      propertyId: view.propertyId,
      amountUsd: loanAmountUsd,
      description: "Mortgage originated at scenario start.",
    },
  ];
  return events;
}

function scenarioBalanceSheet(scenario, bootstrap) {
  const view = scenarioInputView(scenario);
  const { primary } = agentsByRole(bootstrap);
  const privateEquityUnits = Math.max(0, finiteNumber(view.privateEquityUnits, 0));
  const privateEquityValueUsd = privateEquityValueUsdForUnits(bootstrap, privateEquityUnits);
  const assets = [
    {
      assetId: "sp500",
      assetType: "generic_sp500_stock",
      ownerActorId: primary.actorId,
      valueUsd: view.startingPortfolioUsd,
      costBasisUsd: view.startingPortfolioUsd,
    },
  ];
  if (privateEquityValueUsd > 0 || privateEquityUnits > 0) {
    assets.push({
      assetId: "private_equity_private",
      assetType: "private_equity",
      ownerActorId: primary.actorId,
      valueUsd: privateEquityValueUsd,
      units: privateEquityUnits,
      costBasisUsd: 0,
    });
  }
  return {
    accounts: [
      {
        accountId: "checking",
        accountType: "checking",
        ownerActorId: primary.actorId,
        balanceUsd: view.initialCheckingUsd,
      },
    ],
    assets,
    liabilities: [],
  };
}

function scenarioToBackendScenario(scenario, bootstrap) {
  const view = scenarioInputView(scenario);
  const property = propertyById(bootstrap, view.propertyId);
  const holdMonths = Math.ceil(view.holdYears * 12);
  const rentalMode = rentalModeForScenario(scenario);
  const rentEstimate = finiteNumber(property?.rentEstimateUsd, 0);
  const beds = Math.max(1, finiteNumber(property?.beds, 1));
  return {
    scenarioId: view.scenarioId,
    label: view.label,
    enabled: view.enabled,
    color: view.color,
    actors: scenarioActors(scenario, bootstrap),
    events: scenarioEvents(scenario, property, bootstrap),
    policies: scenarioPolicies(scenario, bootstrap),
    propertySelection: {
      propertyId: view.propertyId,
    },
    financing: {
      financingMode: view.financingMode,
      downPaymentPct: view.downPaymentPct,
      mortgageRatePct: view.customMortgageRate,
      mortgageTermYears: view.customMortgageTermYears,
      creditScore: view.creditScore,
    },
    occupancyPlan: {
      occupancyMode: occupancyModeForScenario(scenario),
      ownerResidencePropertyId: view.ownerResidenceMode === "selected_property" ? view.propertyId : null,
      startMonth: 0,
      endMonth: view.rentalUsePolicy === "rent_whole_property" ? 0 : holdMonths,
    },
    rentalPlan: {
      rentalMode,
      startMonth: rentalMode === "not_rented" ? null : 0,
      endMonth: rentalMode === "not_rented" ? null : holdMonths,
      monthlyRentUsd: rentalMode === "rent_whole_property" ? rentEstimate : null,
      roomsRented:
        rentalMode === "rent_rooms_while_owner_lives_there"
          ? Math.min(Math.max(0, view.roomsRentedWhileLiving), Math.max(0, beds - 1))
          : 0,
      roomRentMonthlyUsd: rentalMode === "rent_rooms_while_owner_lives_there" ? view.roomRentMonthlyUsd : null,
      vacancyPct: view.vacancyPct,
      roomVacancyPct: view.roomVacancyPct,
      managementFeePct: view.managementFeePct,
      leasingFeePct: view.leasingFeePct,
    },
    taxProfile: {
      marginalTaxRate: view.marginalTaxRate,
      capGainsRate: view.capGainsRate,
      capGainsExclusionUsd: view.capGainsExclusionUsd,
    },
    transactionCosts: {
      closingCostBuyPct: view.closingCostBuyPct,
      closingCostSellPct: view.closingCostSellPct,
    },
    propertyAssumptions: {
      insuranceAnnualUsd: view.insuranceAnnualUsd,
      maintenancePct: view.maintenancePct,
      depreciableBasisPct: view.depreciableBasisPct,
    },
    initialBalanceSheet: scenarioBalanceSheet(scenario, bootstrap),
  };
}

export function scenarioSetInputToRequest(input, bootstrap) {
  const normalized = normalizeScenarioSetInput(input, bootstrap);
  return {
    scenarioSetId: "augur_futures_explorer",
    title: normalized.title,
    marketRequest: normalized.marketRequest,
    reportSpec: normalized.reportSpec,
    scenarios: normalized.scenarios.map((scenario) => scenarioToBackendScenario(scenario, bootstrap)),
  };
}

function serializableScenario(scenario) {
  const view = scenarioInputView(scenario);
  return {
    identity: {
      scenarioId: view.scenarioId,
      label: view.label,
      enabled: view.enabled,
      color: view.color,
    },
    propertyAndLocation: {
      propertyId: view.propertyId,
    },
    actorsAndOwnership: {
      actorPolicy: view.actorPolicy,
      partnerPaymentMonthlyUsd: view.partnerPaymentMonthlyUsd,
    },
    timeline: {
      holdYears: view.holdYears,
    },
    financing: {
      financingMode: view.financingMode,
      downPaymentPct: view.downPaymentPct,
      ...(view.financingMode === "custom"
        ? {
            customMortgageRate: view.customMortgageRate,
            customMortgageTermYears: view.customMortgageTermYears,
          }
        : {}),
      creditScore: view.creditScore,
    },
    occupancyAndRental: {
      ownerResidenceMode: view.ownerResidenceMode,
      rentalUsePolicy: view.rentalUsePolicy,
      vacancyPct: view.vacancyPct,
      managementFeePct: view.managementFeePct,
      leasingFeePct: view.leasingFeePct,
      roomsRentedWhileLiving: view.roomsRentedWhileLiving,
      roomRentMonthlyUsd: view.roomRentMonthlyUsd,
      roomVacancyPct: view.roomVacancyPct,
    },
    propertyAssumptions: {
      maintenancePct: view.maintenancePct,
      insuranceAnnualUsd: view.insuranceAnnualUsd,
      depreciableBasisPct: view.depreciableBasisPct,
    },
    taxAccounting: {
      closingCostBuyPct: view.closingCostBuyPct,
      closingCostSellPct: view.closingCostSellPct,
      capGainsExclusionUsd: view.capGainsExclusionUsd,
      marginalTaxRate: view.marginalTaxRate,
      capGainsRate: view.capGainsRate,
    },
    initialBalanceSheet: {
      initialCheckingUsd: view.initialCheckingUsd,
      startingPortfolioUsd: view.startingPortfolioUsd,
      privateEquityUnits: view.privateEquityUnits,
    },
    policies: {
      liquidReservePolicy: view.liquidReservePolicy,
      checkingFloorUsd: view.checkingFloorUsd,
      checkingSaleAmountUsd: view.checkingSaleAmountUsd,
      privateEquitySalePolicy: view.privateEquitySalePolicy,
      privateEquityLiquidNetWorthFloorUsd: view.privateEquityLiquidNetWorthFloorUsd,
      privateEquityTenderSaleAmountUsd: view.privateEquityTenderSaleAmountUsd,
    },
  };
}

function serializableScenarioSetInput(input) {
  return {
    title: input.title,
    marketRequest: input.marketRequest,
    reportSpec: input.reportSpec,
    scenarios: (input.scenarios ?? []).map(serializableScenario),
  };
}

function bytesToBase64Url(bytes) {
  if (typeof Buffer !== "undefined") {
    return Buffer.from(bytes).toString("base64").replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
  }
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function base64UrlToBytes(value) {
  const base64 = value
    .replaceAll("-", "+")
    .replaceAll("_", "/")
    .padEnd(Math.ceil(value.length / 4) * 4, "=");
  if (typeof Buffer !== "undefined") {
    return Uint8Array.from(Buffer.from(base64, "base64"));
  }
  const binary = atob(base64);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

export function encodeScenarioSetUrlState(input) {
  const payload = {
    version: URL_STATE_VERSION,
    scenario_set_input: decamelizeObjectKeys(serializableScenarioSetInput(input)),
  };
  return bytesToBase64Url(new TextEncoder().encode(JSON.stringify(payload)));
}

export function decodeScenarioSetUrlState(value) {
  if (!value) return null;
  const payload = JSON.parse(new TextDecoder().decode(base64UrlToBytes(value)));
  if (payload?.version !== URL_STATE_VERSION) {
    throw new Error(`Unsupported augur scenario URL state version: ${payload?.version ?? "<missing>"}`);
  }
  if (!payload.scenario_set_input || typeof payload.scenario_set_input !== "object") {
    throw new Error("Augur scenario URL state is missing scenario_set_input");
  }
  return camelizeObjectKeys(payload.scenario_set_input);
}

export function scenarioSetInputFromUrlSearch(search) {
  const params = new URLSearchParams(search);
  return decodeScenarioSetUrlState(params.get("state"));
}

export function searchWithScenarioSetInput(search, input) {
  const params = new URLSearchParams(search);
  params.set("state", encodeScenarioSetUrlState(input));
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}
