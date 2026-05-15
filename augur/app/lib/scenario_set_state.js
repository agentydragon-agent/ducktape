import { camelizeObjectKeys, decamelizeObjectKeys } from "./casing.js";

export const SCENARIO_COLORS = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2"];

const URL_STATE_VERSION = 1;

const DEFAULT_MARKET_REQUEST = {
  marketModelId: "current_market_model",
  rolloutCount: 128,
  horizonMonths: 360,
  randomSeed: 0,
  sharedMarketPaths: true,
};

const DEFAULT_REPORT_SPEC = {
  metrics: ["net_worth", "liquid_net_worth", "home_equity", "actor_equity", "property_value"],
  percentiles: [5, 25, 50, 75, 95],
  includeMonthlyColumns: true,
  includeSamplePaths: true,
};

const FINANCING_MODE_IDS = new Set(["cash", "fixed_30", "fixed_15", "custom"]);
const PRIVATE_EQUITY_SALE_PROCEEDS_IDS = new Set(["cash", "generic_sp500_stock"]);
const PRIVATE_EQUITY_EVENT_TYPE_IDS = new Set([
  "private_equity_sale_request",
  "private_equity_ipo",
  "private_equity_acquisition",
]);
const DEFAULT_PRIVATE_EQUITY_SALE_REQUEST_MONTH = 12;

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

function normalizePrivateEquityEvents(events, fallback = []) {
  const source = Array.isArray(events) ? events : fallback;
  const usedIds = new Set();
  return source
    .map((event, index) => {
      const fallbackId = `private_equity_event_${index + 1}`;
      const rawId =
        typeof event?.eventId === "string" && /^[a-z0-9][a-z0-9_-]*$/.test(event.eventId) ? event.eventId : fallbackId;
      let eventId = rawId;
      let suffix = 2;
      while (usedIds.has(eventId)) {
        eventId = `${rawId}_${suffix}`;
        suffix += 1;
      }
      usedIds.add(eventId);
      return {
        eventId,
        eventType: PRIVATE_EQUITY_EVENT_TYPE_IDS.has(event?.eventType)
          ? event.eventType
          : "private_equity_sale_request",
        monthIndex: Math.max(0, Math.floor(finiteNumber(event?.monthIndex, DEFAULT_PRIVATE_EQUITY_SALE_REQUEST_MONTH))),
        amountUsd: finiteNumber(event?.amountUsd, 0),
      };
    })
    .filter((event) => event.amountUsd > 0);
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
  return {
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
    privateEquitySaleRequestAmountUsd: finiteNumber(overrides.privateEquitySaleRequestAmountUsd, 0),
    privateEquitySaleRequestMonth: nullableNumber(
      overrides.privateEquitySaleRequestMonth,
      DEFAULT_PRIVATE_EQUITY_SALE_REQUEST_MONTH
    ),
    privateEquitySaleProceedsDestination: PRIVATE_EQUITY_SALE_PROCEEDS_IDS.has(
      overrides.privateEquitySaleProceedsDestination
    )
      ? overrides.privateEquitySaleProceedsDestination
      : "cash",
    privateEquityEvents: normalizePrivateEquityEvents(overrides.privateEquityEvents),
  };
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
  const propertyIds = new Set((bootstrap?.properties ?? []).map((property) => property.id));
  const actorPolicyIds = optionIds(bootstrap?.actorPolicyOptions);
  const ownerResidenceModeIds = optionIds(bootstrap?.ownerResidenceModeOptions);
  const rentalUsePolicyIds = optionIds(bootstrap?.rentalUsePolicyOptions);
  const liquidReservePolicyIds = optionIds(bootstrap?.liquidReservePolicyOptions);
  const defaultScenario = createScenarioInput(bootstrap, { index });
  const privateEquityUnits = finiteNumber(scenario?.privateEquityUnits, defaultScenario.privateEquityUnits);
  const privateEquityValueUsd = privateEquityValueUsdForUnits(bootstrap, privateEquityUnits);
  const scenarioId =
    typeof scenario?.scenarioId === "string" && /^[a-z0-9][a-z0-9_-]*$/.test(scenario.scenarioId)
      ? scenario.scenarioId
      : uniqueScenarioId(existingIds, "scenario");
  existingIds.add(scenarioId);
  return {
    ...defaultScenario,
    scenarioId,
    label: typeof scenario?.label === "string" && scenario.label.trim() ? scenario.label.trim() : defaultScenario.label,
    enabled: Boolean(scenario?.enabled ?? defaultScenario.enabled),
    color: typeof scenario?.color === "string" && scenario.color ? scenario.color : defaultScenario.color,
    propertyId: propertyIds.has(scenario?.propertyId) ? scenario.propertyId : defaultScenario.propertyId,
    actorPolicy: actorPolicyIds.has(scenario?.actorPolicy) ? scenario.actorPolicy : defaultScenario.actorPolicy,
    ownerResidenceMode: ownerResidenceModeIds.has(scenario?.ownerResidenceMode)
      ? scenario.ownerResidenceMode
      : defaultScenario.ownerResidenceMode,
    rentalUsePolicy: rentalUsePolicyIds.has(scenario?.rentalUsePolicy)
      ? scenario.rentalUsePolicy
      : defaultScenario.rentalUsePolicy,
    liquidReservePolicy: liquidReservePolicyIds.has(scenario?.liquidReservePolicy)
      ? scenario.liquidReservePolicy
      : defaultScenario.liquidReservePolicy,
    initialCheckingUsd: finiteNumber(scenario?.initialCheckingUsd, defaultScenario.initialCheckingUsd),
    checkingFloorUsd: finiteNumber(scenario?.checkingFloorUsd, defaultScenario.checkingFloorUsd),
    checkingSaleAmountUsd: positiveNumber(scenario?.checkingSaleAmountUsd, defaultScenario.checkingSaleAmountUsd),
    startingPortfolioUsd: finiteNumber(scenario?.startingPortfolioUsd, defaultScenario.startingPortfolioUsd),
    partnerPaymentMonthlyUsd: finiteNumber(
      scenario?.partnerPaymentMonthlyUsd,
      defaultScenario.partnerPaymentMonthlyUsd
    ),
    holdYears: positiveNumber(scenario?.holdYears, defaultScenario.holdYears),
    financingMode: FINANCING_MODE_IDS.has(scenario?.financingMode)
      ? scenario.financingMode
      : defaultScenario.financingMode,
    downPaymentPct: finiteNumber(scenario?.downPaymentPct, defaultScenario.downPaymentPct),
    customMortgageRate: nullableNumber(scenario?.customMortgageRate, defaultScenario.customMortgageRate),
    customMortgageTermYears: positiveNumber(scenario?.customMortgageTermYears, defaultScenario.customMortgageTermYears),
    creditScore: nullableNumber(scenario?.creditScore, defaultScenario.creditScore),
    vacancyPct: finiteNumber(scenario?.vacancyPct, defaultScenario.vacancyPct),
    managementFeePct: finiteNumber(scenario?.managementFeePct, defaultScenario.managementFeePct),
    leasingFeePct: finiteNumber(scenario?.leasingFeePct, defaultScenario.leasingFeePct),
    roomsRentedWhileLiving: finiteNumber(scenario?.roomsRentedWhileLiving, defaultScenario.roomsRentedWhileLiving),
    roomRentMonthlyUsd: finiteNumber(scenario?.roomRentMonthlyUsd, defaultScenario.roomRentMonthlyUsd),
    roomVacancyPct: finiteNumber(scenario?.roomVacancyPct, defaultScenario.roomVacancyPct),
    maintenancePct: finiteNumber(scenario?.maintenancePct, defaultScenario.maintenancePct),
    insuranceAnnualUsd: finiteNumber(scenario?.insuranceAnnualUsd, defaultScenario.insuranceAnnualUsd),
    closingCostBuyPct: finiteNumber(scenario?.closingCostBuyPct, defaultScenario.closingCostBuyPct),
    closingCostSellPct: finiteNumber(scenario?.closingCostSellPct, defaultScenario.closingCostSellPct),
    capGainsExclusionUsd: finiteNumber(scenario?.capGainsExclusionUsd, defaultScenario.capGainsExclusionUsd),
    depreciableBasisPct: finiteNumber(scenario?.depreciableBasisPct, defaultScenario.depreciableBasisPct),
    marginalTaxRate: finiteNumber(scenario?.marginalTaxRate, defaultScenario.marginalTaxRate),
    capGainsRate: finiteNumber(scenario?.capGainsRate, defaultScenario.capGainsRate),
    privateEquityValueUsd,
    privateEquityUnits,
    privateEquitySaleRequestAmountUsd: finiteNumber(
      scenario?.privateEquitySaleRequestAmountUsd,
      defaultScenario.privateEquitySaleRequestAmountUsd
    ),
    privateEquitySaleRequestMonth: nullableNumber(
      scenario?.privateEquitySaleRequestMonth,
      defaultScenario.privateEquitySaleRequestMonth
    ),
    privateEquitySaleProceedsDestination: PRIVATE_EQUITY_SALE_PROCEEDS_IDS.has(
      scenario?.privateEquitySaleProceedsDestination
    )
      ? scenario.privateEquitySaleProceedsDestination
      : defaultScenario.privateEquitySaleProceedsDestination,
    privateEquityEvents: normalizePrivateEquityEvents(
      scenario?.privateEquityEvents,
      defaultScenario.privateEquityEvents
    ),
  };
}

export function normalizeScenarioSetInput(input, bootstrap) {
  const fallback = createDefaultScenarioSetInput(bootstrap);
  const existingIds = new Set();
  const scenariosSource =
    Array.isArray(input?.scenarios) && input.scenarios.length > 0 ? input.scenarios : fallback.scenarios;
  const scenarios = scenariosSource.map((scenario, index) =>
    normalizeScenarioInput(scenario, bootstrap, index, existingIds)
  );
  const horizonMonths = Math.max(1, ...scenarios.map((scenario) => Math.ceil(scenario.holdYears * 12)));
  return {
    title: typeof input?.title === "string" && input.title.trim() ? input.title.trim() : fallback.title,
    marketRequest: {
      ...fallback.marketRequest,
      ...(input?.marketRequest && typeof input.marketRequest === "object" ? input.marketRequest : {}),
      horizonMonths,
      rolloutCount: positiveNumber(input?.marketRequest?.rolloutCount, fallback.marketRequest.rolloutCount),
      randomSeed: nullableInteger(input?.marketRequest?.randomSeed, fallback.marketRequest.randomSeed),
      sharedMarketPaths: Boolean(input?.marketRequest?.sharedMarketPaths ?? fallback.marketRequest.sharedMarketPaths),
    },
    reportSpec: {
      ...fallback.reportSpec,
      ...(input?.reportSpec && typeof input.reportSpec === "object" ? input.reportSpec : {}),
    },
    scenarios,
  };
}

function agentsByRole(bootstrap) {
  const agents = bootstrap?.agents ?? [];
  const primary = agents.find((a) => a.role === "primary_owner");
  const partner = agents.find((a) => a.role === "equity_building_occupant") ?? null;
  return { primary, partner };
}

function occupancyModeForScenario(scenario) {
  if (scenario.ownerResidenceMode === "other_owned_property") {
    return "owner_lives_in_other_owned_property";
  }
  if (scenario.ownerResidenceMode === "rental_elsewhere") {
    return "owner_rents_elsewhere";
  }
  if (scenario.rentalUsePolicy === "rent_whole_property") {
    return "no_owner_occupancy";
  }
  return "owner_lives_in_property";
}

function rentalModeForScenario(scenario) {
  if (scenario.rentalUsePolicy === "rent_rooms_while_owner_lives_there") {
    return "rent_rooms_while_owner_lives_there";
  }
  if (scenario.rentalUsePolicy === "rent_whole_property") {
    return "rent_whole_property";
  }
  return "not_rented";
}

function scenarioPolicies(scenario, bootstrap) {
  const { primary, partner } = agentsByRole(bootstrap);
  const policies = [];
  if (scenario.actorPolicy === "owner_plus_partner" && partner) {
    policies.push({
      policyId: "partner_equity_accrual",
      policyType: "partner_equity_accrual",
      actorId: partner.actorId,
      enabled: scenario.enabled,
      baseMonthlyPaymentUsd: scenario.partnerPaymentMonthlyUsd,
    });
  }
  if (scenario.liquidReservePolicy === "checking_floor_sp500") {
    policies.push({
      policyId: "checking_floor",
      policyType: "checking_floor_sell_public_stock",
      actorId: primary.actorId,
      enabled: true,
      floorUsd: scenario.checkingFloorUsd,
      saleAmountUsd: scenario.checkingSaleAmountUsd,
    });
  }
  if (
    scenario.privateEquitySaleRequestAmountUsd > 0 ||
    (scenario.privateEquityEvents ?? []).some((event) => event.amountUsd > 0)
  ) {
    policies.push({
      policyId: "private_equity_sale",
      policyType: "private_equity_sale",
      actorId: primary.actorId,
      enabled: true,
      proceedsDestination: scenario.privateEquitySaleProceedsDestination,
      saleRule: {
        saleRuleType: "manual_requests_only",
      },
    });
  }
  return policies;
}

function scenarioActors(scenario, bootstrap) {
  const { primary, partner } = agentsByRole(bootstrap);
  const actors = [
    {
      actorId: primary.actorId,
      label: primary.label,
      role: primary.role,
    },
  ];
  if (scenario.actorPolicy === "owner_plus_partner" && partner) {
    actors.push({
      actorId: partner.actorId,
      label: partner.label,
      role: partner.role,
    });
  }
  return actors;
}

function scenarioEvents(scenario, property, bootstrap) {
  const { primary } = agentsByRole(bootstrap);
  const downPaymentPct = scenario.downPaymentPct;
  const loanAmountUsd = Math.max(0, (property?.priceUsd ?? 0) * (1 - downPaymentPct / 100));
  const events = [
    {
      eventId: "purchase",
      eventType: "property_purchase",
      monthIndex: 0,
      actorId: primary.actorId,
      propertyId: scenario.propertyId,
      amountUsd: property?.priceUsd ?? 0,
      description: "Property purchase at scenario start.",
      hoaMonthlyUsd: property?.hoaMonthlyUsd ?? 0,
    },
    {
      eventId: "mortgage",
      eventType: "mortgage_origination",
      monthIndex: 0,
      actorId: primary.actorId,
      propertyId: scenario.propertyId,
      amountUsd: loanAmountUsd,
      description: "Mortgage originated at scenario start.",
    },
  ];
  if (scenario.privateEquitySaleRequestAmountUsd > 0) {
    events.push({
      eventId: "private_equity_sale_request",
      eventType: "private_equity_sale_request",
      monthIndex: Math.max(
        0,
        Math.floor(nullableNumber(scenario.privateEquitySaleRequestMonth, DEFAULT_PRIVATE_EQUITY_SALE_REQUEST_MONTH))
      ),
      actorId: primary.actorId,
      amountUsd: scenario.privateEquitySaleRequestAmountUsd,
      description: "Requested private-equity sale.",
    });
  }
  for (const privateEquityEvent of scenario.privateEquityEvents ?? []) {
    if (privateEquityEvent.amountUsd <= 0) continue;
    events.push({
      eventId: privateEquityEvent.eventId,
      eventType: privateEquityEvent.eventType,
      monthIndex: Math.max(0, Math.floor(privateEquityEvent.monthIndex)),
      actorId: primary.actorId,
      amountUsd: privateEquityEvent.amountUsd,
      description: "Scheduled liquidity sale request.",
    });
  }
  return events;
}

function scenarioBalanceSheet(scenario, bootstrap) {
  const { primary } = agentsByRole(bootstrap);
  const privateEquityUnits = Math.max(0, finiteNumber(scenario.privateEquityUnits, 0));
  const privateEquityValueUsd = privateEquityValueUsdForUnits(bootstrap, privateEquityUnits);
  const assets = [
    {
      assetId: "sp500",
      assetType: "generic_sp500_stock",
      ownerActorId: primary.actorId,
      valueUsd: scenario.startingPortfolioUsd,
      costBasisUsd: scenario.startingPortfolioUsd,
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
        balanceUsd: scenario.initialCheckingUsd,
      },
    ],
    assets,
    liabilities: [],
  };
}

function scenarioToBackendScenario(scenario, bootstrap) {
  const property = propertyById(bootstrap, scenario.propertyId);
  const holdMonths = Math.ceil(scenario.holdYears * 12);
  const rentalMode = rentalModeForScenario(scenario);
  const rentEstimate = finiteNumber(property?.rentEstimateUsd, 0);
  const beds = Math.max(1, finiteNumber(property?.beds, 1));
  return {
    scenarioId: scenario.scenarioId,
    label: scenario.label,
    enabled: scenario.enabled,
    color: scenario.color,
    actors: scenarioActors(scenario, bootstrap),
    events: scenarioEvents(scenario, property, bootstrap),
    policies: scenarioPolicies(scenario, bootstrap),
    propertySelection: {
      propertyId: scenario.propertyId,
    },
    financing: {
      financingMode: scenario.financingMode,
      downPaymentPct: scenario.downPaymentPct,
      mortgageRatePct: scenario.customMortgageRate,
      mortgageTermYears: scenario.customMortgageTermYears,
      creditScore: scenario.creditScore,
    },
    occupancyPlan: {
      occupancyMode: occupancyModeForScenario(scenario),
      ownerResidencePropertyId: scenario.ownerResidenceMode === "selected_property" ? scenario.propertyId : null,
      startMonth: 0,
      endMonth: scenario.rentalUsePolicy === "rent_whole_property" ? 0 : holdMonths,
    },
    rentalPlan: {
      rentalMode,
      startMonth: rentalMode === "not_rented" ? null : 0,
      endMonth: rentalMode === "not_rented" ? null : holdMonths,
      monthlyRentUsd: rentalMode === "rent_whole_property" ? rentEstimate : null,
      roomsRented:
        rentalMode === "rent_rooms_while_owner_lives_there"
          ? Math.min(Math.max(0, scenario.roomsRentedWhileLiving), Math.max(0, beds - 1))
          : 0,
      roomRentMonthlyUsd: rentalMode === "rent_rooms_while_owner_lives_there" ? scenario.roomRentMonthlyUsd : null,
      vacancyPct: scenario.vacancyPct,
      roomVacancyPct: scenario.roomVacancyPct,
      managementFeePct: scenario.managementFeePct,
      leasingFeePct: scenario.leasingFeePct,
    },
    taxProfile: {
      marginalTaxRate: scenario.marginalTaxRate,
      capGainsRate: scenario.capGainsRate,
      capGainsExclusionUsd: scenario.capGainsExclusionUsd,
    },
    transactionCosts: {
      closingCostBuyPct: scenario.closingCostBuyPct,
      closingCostSellPct: scenario.closingCostSellPct,
    },
    propertyAssumptions: {
      insuranceAnnualUsd: scenario.insuranceAnnualUsd,
      maintenancePct: scenario.maintenancePct,
      depreciableBasisPct: scenario.depreciableBasisPct,
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
  return {
    scenarioId: scenario.scenarioId,
    label: scenario.label,
    enabled: scenario.enabled,
    color: scenario.color,
    propertyId: scenario.propertyId,
    actorPolicy: scenario.actorPolicy,
    ownerResidenceMode: scenario.ownerResidenceMode,
    rentalUsePolicy: scenario.rentalUsePolicy,
    liquidReservePolicy: scenario.liquidReservePolicy,
    initialCheckingUsd: scenario.initialCheckingUsd,
    checkingFloorUsd: scenario.checkingFloorUsd,
    checkingSaleAmountUsd: scenario.checkingSaleAmountUsd,
    startingPortfolioUsd: scenario.startingPortfolioUsd,
    partnerPaymentMonthlyUsd: scenario.partnerPaymentMonthlyUsd,
    holdYears: scenario.holdYears,
    financingMode: scenario.financingMode,
    downPaymentPct: scenario.downPaymentPct,
    customMortgageRate: scenario.customMortgageRate,
    customMortgageTermYears: scenario.customMortgageTermYears,
    creditScore: scenario.creditScore,
    vacancyPct: scenario.vacancyPct,
    managementFeePct: scenario.managementFeePct,
    leasingFeePct: scenario.leasingFeePct,
    roomsRentedWhileLiving: scenario.roomsRentedWhileLiving,
    roomRentMonthlyUsd: scenario.roomRentMonthlyUsd,
    roomVacancyPct: scenario.roomVacancyPct,
    maintenancePct: scenario.maintenancePct,
    insuranceAnnualUsd: scenario.insuranceAnnualUsd,
    closingCostBuyPct: scenario.closingCostBuyPct,
    closingCostSellPct: scenario.closingCostSellPct,
    capGainsExclusionUsd: scenario.capGainsExclusionUsd,
    depreciableBasisPct: scenario.depreciableBasisPct,
    marginalTaxRate: scenario.marginalTaxRate,
    capGainsRate: scenario.capGainsRate,
    privateEquityUnits: scenario.privateEquityUnits,
    privateEquitySaleRequestAmountUsd: scenario.privateEquitySaleRequestAmountUsd,
    privateEquitySaleRequestMonth: scenario.privateEquitySaleRequestMonth,
    privateEquitySaleProceedsDestination: scenario.privateEquitySaleProceedsDestination,
    privateEquityEvents: scenario.privateEquityEvents,
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
