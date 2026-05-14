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
  defaultPropertyId: "sf_ashton",
  defaultActorPolicy: "owner_only",
  defaultOwnerResidenceMode: "selected_property",
  defaultRentalUsePolicy: "not_rented",
  defaultLiquidReservePolicy: "none",
  defaultInitialCheckingUsd: 25_000,
  defaultCheckingFloorUsd: 10_000,
  defaultCheckingSaleAmountUsd: 20_000,
  defaultPartnerMonthlyPaymentUsd: 2_435,
  defaultRolloutSamples: 16,
  defaultScenarios: [
    { propertyId: "sf_ashton", actorPolicy: "owner_only" },
    { propertyId: "vallejo_calhoun", actorPolicy: "owner_plus_partner", label: "Calhoun St + Partner" },
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
    customCounterfactualRentMonthlyUsd: 4_800,
    counterfactualRentGrowth: 3,
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
  properties: [
    {
      id: "sf_ashton",
      address: "Ashton Ave",
      priceUsd: 998_000,
      hoaMonthlyUsd: 321,
      rentEstimateUsd: 4_200,
      beds: 3,
      location: {
        id: "san_francisco_ca",
        localRegulation: { propertyTaxAnnualPct: 1.18, localTransferTaxPct: 0, specialAssessmentAnnualUsd: 0 },
      },
    },
    {
      id: "vallejo_calhoun",
      address: "Calhoun St",
      priceUsd: 520_000,
      rentEstimateUsd: 3_100,
      beds: 4,
      location: {
        id: "vallejo_ca",
        localRegulation: { propertyTaxAnnualPct: 1.1, localTransferTaxPct: 0, specialAssessmentAnnualUsd: 0 },
      },
    },
  ],
};

test("default input creates comparable SF and Vallejo scenarios", () => {
  const input = createDefaultScenarioSetInput(bootstrap);

  assert.equal(input.scenarios.length, 2);
  assert.equal(input.scenarios[0].propertyId, "sf_ashton");
  assert.equal(input.scenarios[1].propertyId, "vallejo_calhoun");
  assert.equal(input.scenarios[1].actorPolicy, "owner_plus_partner");
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
    customCounterfactualRentMonthlyUsd: 5_100,
    counterfactualRentGrowth: 4.2,
    privateEquityValueUsd: 123_000,
    privateEquityUnits: 456,
    privateEquitySaleRequestAmountUsd: 25_000,
    privateEquitySaleRequestMonth: 18,
    privateEquitySaleProceedsDestination: "generic_sp500_stock",
    privateEquityEvents: [
      {
        eventId: "private_equity_followup_sale",
        eventType: "private_equity_sale_request",
        monthIndex: 30,
        amountUsd: 40_000,
      },
      { eventId: "private_equity_ipo_request", eventType: "private_equity_ipo", monthIndex: 60, amountUsd: 125_000 },
    ],
  };
  const request = scenarioSetInputToRequest(input, bootstrap);
  const backendRequest = decamelizeObjectKeys(request);
  const sfScenario = backendRequest.scenarios[0];
  const purchaseEvent = sfScenario.events.find((event) => event.event_type === "property_purchase");
  const mortgageEvent = sfScenario.events.find((event) => event.event_type === "mortgage_origination");
  const saleRequestEvent = sfScenario.events.find((event) => event.event_type === "private_equity_sale_request");
  const ipoEvent = sfScenario.events.find((event) => event.event_id === "private_equity_ipo_request");
  const salePolicy = sfScenario.policies.find((policy) => policy.policy_type === "private_equity_sale");

  assert.equal(backendRequest.scenario_set_id, "house_futures_explorer");
  assert.deepEqual(sfScenario.property_selection, { property_id: "sf_ashton" });
  assert.equal(sfScenario.tax_regimes, undefined);
  assert.equal(sfScenario.financing.financing_mode, "custom");
  assert.equal(sfScenario.financing.down_payment_pct, 42);
  assert.equal(sfScenario.financing.mortgage_rate_pct, 7.25);
  assert.equal(sfScenario.financing.mortgage_term_years, 18);
  assert.equal(sfScenario.financing.credit_score, 701);
  assert.equal(sfScenario.policies[0].policy_type, "checking_floor_sell_public_stock");
  assert.equal(sfScenario.policies[0].floor_usd, 10_000);
  assert.equal(sfScenario.policies[0].sale_amount_usd, 20_000);
  assert.equal(salePolicy.policy_id, "private_equity_sale");
  assert.equal(salePolicy.actor_id, "alpha");
  assert.equal(salePolicy.proceeds_destination, "generic_sp500_stock");
  assert.deepEqual(salePolicy.sale_rule, { sale_rule_type: "manual_requests_only" });
  assert.equal(sfScenario.rental_plan.rental_mode, "rent_rooms_while_owner_lives_there");
  assert.equal(sfScenario.rental_plan.rooms_rented, 2);
  assert.equal(sfScenario.rental_plan.room_rent_monthly_usd, 1_650);
  assert.equal(sfScenario.rental_plan.vacancy_pct, 12);
  assert.equal(sfScenario.rental_plan.room_vacancy_pct, 11);
  assert.equal(sfScenario.rental_plan.management_fee_pct, 9.5);
  assert.equal(sfScenario.rental_plan.leasing_fee_pct, 50);
  assert.equal(purchaseEvent.hoa_monthly_usd, 321);
  assert.deepEqual(sfScenario.tax_profile, {
    marginal_tax_rate: 37,
    cap_gains_rate: 28,
    cap_gains_exclusion_usd: 500_000,
  });
  assert.deepEqual(sfScenario.transaction_costs, {
    closing_cost_buy_pct: 3.1,
    closing_cost_sell_pct: 5.9,
  });
  assert.deepEqual(sfScenario.property_assumptions, {
    insurance_annual_usd: 3_200,
    maintenance_pct: 1.4,
    depreciable_basis_pct: 75,
  });
  assert.ok(Math.abs(mortgageEvent.amount_usd - 578_840) < 1e-6);
  assert.equal(saleRequestEvent.event_id, "private_equity_sale_request");
  assert.equal(saleRequestEvent.month_index, 18);
  assert.equal(saleRequestEvent.amount_usd, 25_000);
  assert.equal(ipoEvent.event_type, "private_equity_ipo");
  assert.equal(ipoEvent.month_index, 60);
  assert.equal(ipoEvent.amount_usd, 125_000);
  assert.deepEqual(
    sfScenario.initial_balance_sheet.assets.find((asset) => asset.asset_type === "private_equity"),
    {
      asset_id: "private_equity_private",
      asset_type: "private_equity",
      owner_actor_id: "alpha",
      value_usd: 123_000,
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
  assert.equal(decoded.scenarios[0].propertyId, "sf_ashton");
});

test("URL state round-trips rich scenario controls in camelCase", () => {
  const input = normalizeScenarioSetInput(createDefaultScenarioSetInput(bootstrap), bootstrap);
  input.scenarios[0] = {
    ...input.scenarios[0],
    financingMode: "custom",
    downPaymentPct: 35,
    marginalTaxRate: 39,
    vacancyPct: 7,
    customCounterfactualRentMonthlyUsd: 5_300,
    privateEquityValueUsd: 987_000,
    privateEquityUnits: 1_234,
    privateEquitySaleRequestAmountUsd: 250_000,
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

  assert.equal(decoded.scenarios[0].financingMode, "custom");
  assert.equal(decoded.scenarios[0].downPaymentPct, 35);
  assert.equal(decoded.scenarios[0].marginalTaxRate, 39);
  assert.equal(decoded.scenarios[0].vacancyPct, 7);
  assert.equal(decoded.scenarios[0].customCounterfactualRentMonthlyUsd, 5_300);
  assert.equal(decoded.scenarios[0].privateEquityValueUsd, 987_000);
  assert.equal(decoded.scenarios[0].privateEquityUnits, 1_234);
  assert.equal(decoded.scenarios[0].privateEquitySaleRequestAmountUsd, 250_000);
  assert.equal(decoded.scenarios[0].privateEquitySaleRequestMonth, 24);
  assert.equal(decoded.scenarios[0].privateEquitySaleProceedsDestination, "generic_sp500_stock");
  assert.deepEqual(decoded.scenarios[0].privateEquityEvents, [
    {
      eventId: "private_equity_followup_sale",
      eventType: "private_equity_sale_request",
      monthIndex: 48,
      amountUsd: 75_000,
    },
  ]);
});

test("scheduled private equity sale requests normalize into backend events", () => {
  const input = normalizeScenarioSetInput(createDefaultScenarioSetInput(bootstrap), bootstrap);
  input.scenarios[0] = {
    ...input.scenarios[0],
    privateEquitySaleRequestAmountUsd: 75_000,
    privateEquityEvents: [
      { eventId: "bad id", eventType: "bad_event_type", monthIndex: "24", amountUsd: 25_000 },
      { eventId: "bad id", eventType: "private_equity_acquisition", monthIndex: 36, amountUsd: 50_000 },
      { eventId: "zero_sale", eventType: "private_equity_sale_request", monthIndex: 48, amountUsd: 0 },
    ],
  };

  const backendRequest = decamelizeObjectKeys(scenarioSetInputToRequest(input, bootstrap));
  const privateEquityEvents = backendRequest.scenarios[0].events.filter((event) =>
    event.event_type.startsWith("private_equity_")
  );

  assert.deepEqual(
    privateEquityEvents.map((event) => [event.event_id, event.event_type, event.month_index, event.amount_usd]),
    [
      ["private_equity_sale_request", "private_equity_sale_request", 12, 75_000],
      ["private_equity_event_1", "private_equity_sale_request", 24, 25_000],
      ["private_equity_event_2", "private_equity_acquisition", 36, 50_000],
    ]
  );
});
