import assert from "node:assert/strict";
import test from "node:test";

import {
  createDefaultScenarioSetInput,
  decodeScenarioSetUrlState,
  encodeScenarioSetUrlState,
  normalizeScenarioSetInput,
  scenarioSetInputToRequest,
} from "./scenario_set_state.js";
import { decamelizeObjectKeys } from "./casing.js";

const bootstrap = {
  defaultPropertyId: "location_a_property",
  defaultActorPolicy: "owner_only",
  defaultOwnerResidenceMode: "selected_property",
  defaultRentalUsePolicy: "not_rented",
  defaultLiquidReservePolicy: "none",
  defaultInitialCheckingUsd: 25_000,
  defaultCheckingFloorUsd: 10_000,
  defaultCheckingSaleAmountUsd: 20_000,
  defaultPartnerMonthlyPaymentUsd: 2_435,
  defaultRolloutSamples: 16,
  financeSnapshot: {
    asOfDate: "2026-05-14",
    cashUsd: 26_000,
    wealthfrontSp500Usd: 61_000,
    ibkrVtUsd: 39_000,
    sp500ProxyPortfolioUsd: 100_000,
    concentratedHoldings: [
      {
        holdingId: "private_holding_a",
        label: "Private Holding A",
        units: 500,
        fmvUsdPerUnit: 20,
        valueUsd: 10_000,
        valuationSource: "fixture mark",
      },
    ],
  },
  defaultScenarios: [
    { propertyId: "location_a_property", actorPolicy: "owner_only" },
    { propertyId: "location_b_property", actorPolicy: "owner_plus_partner", label: "Location B shared" },
  ],
  defaultKnobs: {
    holdYears: 5,
    startingPortfolioUsd: 100_000,
    downPaymentPct: 25,
    financingMode: "fixed_30",
    customMortgageRate: 6.5,
    customMortgageTermYears: 30,
    creditScore: 776,
    vacancyPct: 5,
    roomVacancyPct: 5,
    mgmtPct: 8,
    leasingFeePct: 0,
    roomsRentedWhileLiving: 0,
    roomRentMonthlyUsd: 1_800,
    maintenancePct: 1,
    insuranceAnnualUsd: 2_400,
    closingCostBuyPct: 2.5,
    closingCostSellPct: 6.5,
    capGainsExclusionUsd: 250_000,
    depreciableBasisPct: 80,
    marginalTaxRate: 40,
    capGainsRate: 30,
  },
  actorPolicyOptions: [
    { id: "owner_only", label: "Alpha only" },
    { id: "owner_plus_partner", label: "Alpha + Beta" },
  ],
  ownerResidenceModeOptions: [
    { id: "selected_property", label: "Selected" },
    { id: "rental_elsewhere", label: "Elsewhere" },
  ],
  agents: [
    { actorId: "alpha", label: "Alpha", role: "primary_owner" },
    { actorId: "beta", label: "Beta", role: "equity_building_occupant" },
  ],
  rentalUsePolicyOptions: [
    { id: "not_rented", label: "Not rented" },
    { id: "rent_rooms_while_owner_lives_there", label: "Rent rooms" },
    { id: "rent_whole_property", label: "Rent whole property" },
  ],
  liquidReservePolicyOptions: [
    { id: "none", label: "None" },
    { id: "checking_floor_sp500", label: "Sell SP500" },
  ],
  locations: [
    {
      id: "location_a",
      label: "Location A",
      localRegulation: { propertyTaxAnnualPct: 1, localTransferTaxPct: 0, specialAssessmentAnnualUsd: 0 },
    },
    {
      id: "location_b",
      label: "Location B",
      localRegulation: { propertyTaxAnnualPct: 1, localTransferTaxPct: 0, specialAssessmentAnnualUsd: 0 },
    },
  ],
  properties: [
    {
      id: "location_a_property",
      locationId: "location_a",
      address: "Location A Property",
      priceUsd: 998_000,
      hoaMonthlyUsd: 321,
      rentEstimateUsd: 4_200,
      beds: 3,
    },
    {
      id: "location_b_property",
      locationId: "location_b",
      address: "Location B Property",
      priceUsd: 520_000,
      rentEstimateUsd: 3_100,
      beds: 4,
    },
  ],
};

test("default input creates comparable generic location scenarios", () => {
  const input = createDefaultScenarioSetInput(bootstrap);

  assert.equal(input.scenarios.length, 2);
  assert.equal(input.scenarios[0].propertyId, "location_a_property");
  assert.equal(input.scenarios[0].initialCheckingUsd, 25_000);
  assert.equal(input.scenarios[0].startingPortfolioUsd, 100_000);
  assert.equal(input.scenarios[0].privateEquityValueUsd, 10_000);
  assert.equal(input.scenarios[0].privateEquityUnits, 500);
  assert.equal(input.scenarios[1].propertyId, "location_b_property");
  assert.equal(input.scenarios[1].actorPolicy, "owner_plus_partner");
  assert.equal(input.marketRequest.randomSeed, 0);
});

test("scenario set request is canonical backend input after decamelizing", () => {
  const input = normalizeScenarioSetInput(createDefaultScenarioSetInput(bootstrap), bootstrap);
  input.scenarios[0] = {
    ...input.scenarios[0],
    liquidReservePolicy: "checking_floor_sp500",
    rentalUsePolicy: "rent_rooms_while_owner_lives_there",
    financingMode: "custom",
    downPaymentPct: 42,
    customMortgageRate: 7.25,
    customMortgageTermYears: 18,
    creditScore: 701,
    vacancyPct: 12,
    managementFeePct: 9.5,
    leasingFeePct: 50,
    roomsRentedWhileLiving: 2,
    roomRentMonthlyUsd: 1_650,
    roomVacancyPct: 11,
    maintenancePct: 1.4,
    insuranceAnnualUsd: 3_200,
    closingCostBuyPct: 3.1,
    closingCostSellPct: 5.9,
    capGainsExclusionUsd: 500_000,
    depreciableBasisPct: 75,
    marginalTaxRate: 37,
    capGainsRate: 28,
    privateEquityValueUsd: 123_000,
    privateEquityUnits: 456,
  };
  const request = scenarioSetInputToRequest(input, bootstrap);
  const backendRequest = decamelizeObjectKeys(request);
  const firstScenario = backendRequest.scenarios[0];
  const purchaseEvent = firstScenario.events.find((event) => event.event_type === "property_purchase");
  const mortgageEvent = firstScenario.events.find((event) => event.event_type === "mortgage_origination");

  assert.equal(backendRequest.scenario_set_id, "augur_futures_explorer");
  assert.deepEqual(firstScenario.property_selection, { property_id: "location_a_property" });
  assert.equal(firstScenario.tax_regimes, undefined);
  assert.equal(firstScenario.financing.financing_mode, "custom");
  assert.equal(firstScenario.financing.down_payment_pct, 42);
  assert.equal(firstScenario.financing.mortgage_rate_pct, 7.25);
  assert.equal(firstScenario.financing.mortgage_term_years, 18);
  assert.equal(firstScenario.financing.credit_score, 701);
  assert.equal(firstScenario.policies[0].policy_type, "checking_floor_sell_public_stock");
  assert.equal(firstScenario.policies[0].floor_usd, 10_000);
  assert.equal(firstScenario.policies[0].sale_amount_usd, 20_000);
  assert.equal(
    firstScenario.policies.find((policy) => policy.policy_type === "private_equity_sale"),
    undefined
  );
  assert.equal(firstScenario.rental_plan.rental_mode, "rent_rooms_while_owner_lives_there");
  assert.equal(firstScenario.rental_plan.rooms_rented, 2);
  assert.equal(firstScenario.rental_plan.room_rent_monthly_usd, 1_650);
  assert.equal(firstScenario.rental_plan.vacancy_pct, 12);
  assert.equal(firstScenario.rental_plan.room_vacancy_pct, 11);
  assert.equal(firstScenario.rental_plan.management_fee_pct, 9.5);
  assert.equal(firstScenario.rental_plan.leasing_fee_pct, 50);
  assert.equal(purchaseEvent.hoa_monthly_usd, 321);
  assert.deepEqual(firstScenario.tax_profile, {
    marginal_tax_rate: 37,
    cap_gains_rate: 28,
    cap_gains_exclusion_usd: 500_000,
  });
  assert.deepEqual(firstScenario.transaction_costs, {
    closing_cost_buy_pct: 3.1,
    closing_cost_sell_pct: 5.9,
  });
  assert.deepEqual(firstScenario.property_assumptions, {
    insurance_annual_usd: 3_200,
    maintenance_pct: 1.4,
    depreciable_basis_pct: 75,
  });
  assert.ok(Math.abs(mortgageEvent.amount_usd - 578_840) < 1e-6);
  assert.equal(
    firstScenario.events.find((event) => event.event_type.startsWith("private_equity_")),
    undefined
  );
  assert.deepEqual(
    firstScenario.initial_balance_sheet.assets.find((asset) => asset.asset_type === "private_equity"),
    {
      asset_id: "private_equity_private",
      asset_type: "private_equity",
      owner_actor_id: "alpha",
      value_usd: 9_120,
      units: 456,
      cost_basis_usd: 0,
    }
  );
  assert.equal(backendRequest.scenarios[1].policies[0].policy_type, "partner_equity_accrual");
  assert.equal(backendRequest.scenarios[1].policies[0].actor_id, "beta");
  assert.equal(backendRequest.scenarios[1].policies[0].base_monthly_payment_usd, 2_435);
});

test("URL state round-trips only input state", () => {
  const input = createDefaultScenarioSetInput(bootstrap);
  const polluted = {
    ...input,
    scenarioResults: [{ scenarioId: "scenario_1", summary: { netWorthUsd: 123 } }],
    scenarios: input.scenarios.map((scenario) => ({ ...scenario, backendResult: { shouldNotPersist: true } })),
  };
  const encoded = encodeScenarioSetUrlState(polluted);
  const decoded = decodeScenarioSetUrlState(encoded);

  assert.deepEqual(decoded.scenarioResults, undefined);
  assert.deepEqual(decoded.scenarios[0].backendResult, undefined);
  assert.equal(decoded.scenarios[0].propertyId, "location_a_property");
});

test("URL state round-trips rich scenario controls in camelCase", () => {
  const input = normalizeScenarioSetInput(createDefaultScenarioSetInput(bootstrap), bootstrap);
  input.scenarios[0] = {
    ...input.scenarios[0],
    financingMode: "custom",
    downPaymentPct: 35,
    marginalTaxRate: 39,
    vacancyPct: 7,
    privateEquityValueUsd: 987_000,
    privateEquityUnits: 1_234,
  };

  const decoded = decodeScenarioSetUrlState(encodeScenarioSetUrlState(input));

  assert.equal(decoded.scenarios[0].financingMode, "custom");
  assert.equal(decoded.scenarios[0].downPaymentPct, 35);
  assert.equal(decoded.scenarios[0].marginalTaxRate, 39);
  assert.equal(decoded.scenarios[0].vacancyPct, 7);
  assert.equal(decoded.scenarios[0].privateEquityValueUsd, undefined);
  assert.equal(decoded.scenarios[0].privateEquityUnits, 1_234);
  assert.equal(normalizeScenarioSetInput(decoded, bootstrap).scenarios[0].privateEquityValueUsd, 24_680);
});

test("URL state normalizes missing trajectory seed to deterministic default", () => {
  const input = createDefaultScenarioSetInput(bootstrap);
  const decoded = decodeScenarioSetUrlState(encodeScenarioSetUrlState(input));
  decoded.marketRequest.randomSeed = null;

  const normalized = normalizeScenarioSetInput(decoded, bootstrap);

  assert.equal(normalized.marketRequest.randomSeed, 0);
});

test("browser scenario state does not emit manual private equity sale requests", () => {
  const input = normalizeScenarioSetInput(createDefaultScenarioSetInput(bootstrap), bootstrap);
  input.scenarios[0] = {
    ...input.scenarios[0],
    privateEquitySaleRequestAmountUsd: 75_000,
    privateEquitySaleRequestMonth: 24,
    privateEquitySaleProceedsDestination: "generic_sp500_stock",
    privateEquityEvents: [
      {
        eventId: "private_equity_followup_sale",
        eventType: "private_equity_sale_request",
        monthIndex: 48,
        amountUsd: 75_000,
      },
    ],
  };

  const decoded = decodeScenarioSetUrlState(encodeScenarioSetUrlState(input));
  const backendRequest = decamelizeObjectKeys(scenarioSetInputToRequest(input, bootstrap));

  assert.equal(decoded.scenarios[0].privateEquitySaleRequestAmountUsd, undefined);
  assert.equal(decoded.scenarios[0].privateEquitySaleRequestMonth, undefined);
  assert.equal(decoded.scenarios[0].privateEquitySaleProceedsDestination, undefined);
  assert.equal(decoded.scenarios[0].privateEquityEvents, undefined);
  assert.deepEqual(
    backendRequest.scenarios[0].events.filter((event) => event.event_type.startsWith("private_equity_")),
    []
  );
  assert.equal(
    backendRequest.scenarios[0].policies.find((policy) => policy.policy_type === "private_equity_sale"),
    undefined
  );
});
