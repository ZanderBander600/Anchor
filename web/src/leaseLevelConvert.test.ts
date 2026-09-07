/**
 * D5.5A -- the Lease-Level form/transport boundary.
 *
 * One module converts between what the analyst types and what the wire carries,
 * so this is where a silent unit change, a dropped field or an invented default
 * would live. Every test here is written against that: not "does it convert",
 * but "does it convert *this* value to *that* one, and refuse everything else".
 *
 * The completeness checks are driven off the contracts' own keys rather than
 * hand-written field lists, so a field added to a Lease-Level contract joins
 * them automatically instead of quietly escaping them.
 */

import { describe, expect, it } from 'vitest';
import { FormValidationError, buildAcquisitionTermsRequest } from './convert';
import {
  BLANK_LEASE_LEVEL_FORM_VALUES,
  LEASE_LEVEL_MARKET_FIELD_GROUPS,
  LEASE_LEVEL_OPERATING_FIELD_GROUPS,
  LEASE_LEVEL_PROPERTY_FIELD_GROUPS,
  MARKET_LEASING_EXPENSE_STOP_FIELDS,
  OPTIONAL_MARKET_LEASING_KEYS,
  TERMS_WIRE_IDS,
  buildLeaseLevelFormValues,
  buildLeaseLevelInputsRequest,
  buildLeaseLevelTermsRequest,
  collectBlankScalarIssues,
  wireFieldName,
} from './leaseLevelConvert';
import type {
  LeaseLevelDealFields,
  LeaseLevelFormValues,
  MarketLeasingFormValues,
} from './leaseLevelTypes';
import type { AcquisitionTermsFormValues } from './types';

const TERMS_FORM: AcquisitionTermsFormValues = {
  purchasePrice: '42500000',
  holdPeriod: '7',
  exitCapRate: '6.25',
  ltv: '60',
  interestRate: '5.5',
  amortization: '30',
  acquisitionCostPct: '1.5',
  financingFeePct: '1',
  dispositionCostPct: '1.25',
  annualCapexReserve: '120000',
  ioPeriod: '2',
};

const MARKET_FORM: MarketLeasingFormValues = {
  marketRentPsf: '34.5',
  marketRentGrowth: '3',
  renewalRentPsf: '',
  renewalRentSpread: '-5',
  renewalTermMonths: '60',
  successorEscalationPct: '3',
  renewalDowntimeMonths: '2',
  renewalFreeRentMonths: '1',
  newTermMonths: '84',
  newDowntimeMonths: '9',
  newFreeRentMonths: '4',
  renewalTiPsf: '25',
  newTiPsf: '65',
  leasingCommissionMethod: 'pct_of_total_contractual_base_rent',
  renewalLcPct: '3',
  newLcPct: '6',
  renewalProbability: '70',
  renewalLeaseType: 'nnn',
  renewalRecoveryBasis: '',
  renewalExpenseStopPsf: '',
  newLeaseType: 'modified_gross',
  newRecoveryBasis: 'expense_stop_psf',
  newExpenseStopPsf: '11.25',
};

const FILLED: LeaseLevelFormValues = {
  terms: TERMS_FORM,
  property: { analysisStartDate: '2027-01-01', rentableAreaSf: '62000' },
  operating: {
    otherIncome: '84000',
    otherIncomeGrowth: '2.5',
    creditLossPct: '1.5',
    propertyTaxes: '410000',
    insurance: '62000',
    utilities: '148000',
    repairsMaintenance: '96000',
    otherOperatingExpenses: '54000',
    managementFeePct: '3',
    expenseGrowth: '3',
    recoverableExpenseRatio: '85',
  },
  marketLeasing: MARKET_FORM,
  suites: [],
  leases: [],
};

const SAVED_DEAL: LeaseLevelDealFields = {
  terms: buildAcquisitionTermsRequest(TERMS_FORM),
  property_inputs: { analysis_start_date: '2027-01-01', rentable_area_sf: 62_000 },
  operating_inputs: buildLeaseLevelInputsRequest(FILLED).operating_inputs,
  market_leasing: buildLeaseLevelInputsRequest(FILLED).market_leasing,
  suites: [
    {
      suite_id: '300',
      suite_area_sf: 12_000,
      suite_label: 'Suite 300',
      market_rent_psf: null,
      market_leasing_override: buildLeaseLevelInputsRequest(FILLED).market_leasing,
      initial_vacancy: { strategy: 'market_lease_up', initial_lease_up_months: 8 },
    },
  ],
  leases: [
    {
      lease_id: 'L-100',
      suite_id: '100',
      leased_area_sf: 18_400,
      rent_commencement_date: '2023-06-01',
      lease_expiration_date: '2029-05-31',
      base_rent_psf: 31.25,
      escalation_pct: 0.03,
      escalation_basis: 'lease_anniversary',
      lease_type: 'nnn',
      tenant_name: 'Marlow Provisions',
      lease_start_date: null,
      origin: 'in_place',
      recovery_basis: null,
      expense_stop_psf: null,
    },
  ],
};

// =============================================================================
// 1. The percent convention
// =============================================================================

describe('the percent convention', () => {
  it('divides every rate by 100 exactly once, and leaves currency alone', () => {
    const inputs = buildLeaseLevelInputsRequest(FILLED);

    expect(inputs.operating_inputs.expense_growth).toBeCloseTo(0.03, 12);
    expect(inputs.operating_inputs.recoverable_expense_ratio).toBeCloseTo(0.85, 12);
    expect(inputs.market_leasing.renewal_probability).toBeCloseTo(0.7, 12);
    expect(inputs.market_leasing.new_lc_pct).toBeCloseTo(0.06, 12);

    // Currency, area, months and $/SF are not rates and must pass through.
    expect(inputs.operating_inputs.property_taxes).toBe(410_000);
    expect(inputs.property_inputs.rentable_area_sf).toBe(62_000);
    expect(inputs.market_leasing.new_term_months).toBe(84);
    expect(inputs.market_leasing.market_rent_psf).toBe(34.5);
    expect(inputs.market_leasing.new_ti_psf).toBe(65);
  });

  it('keeps a negative spread negative', () => {
    // A renewal spread below market is a real assumption. Clamping it at zero
    // would be this module overruling the analyst.
    expect(buildLeaseLevelInputsRequest(FILLED).market_leasing.renewal_rent_spread).toBeCloseTo(
      -0.05,
      12,
    );
  });

  it('round-trips a rate through display and back', () => {
    const request = buildLeaseLevelInputsRequest(FILLED);
    const form = buildLeaseLevelFormValues(
      { ...SAVED_DEAL, operating_inputs: request.operating_inputs },
      TERMS_FORM,
    );
    expect(form.operating.recoverableExpenseRatio).toBe('85');
    expect(form.operating.managementFeePct).toBe('3');
  });
});

// =============================================================================
// 2. Nullable vs. required
// =============================================================================

describe('nullable fields', () => {
  it('sends null, not zero, for a blank nullable field', () => {
    // The distinction the contract exists to preserve: "stated as absent" is
    // not "$0.00 per square foot", and the difference changes recoveries.
    const inputs = buildLeaseLevelInputsRequest(FILLED);
    expect(inputs.market_leasing.renewal_rent_psf).toBeNull();
    expect(inputs.market_leasing.renewal_expense_stop_psf).toBeNull();
    expect(inputs.market_leasing.renewal_recovery_basis).toBeNull();
  });

  it('sends the value when one is stated', () => {
    const inputs = buildLeaseLevelInputsRequest(FILLED);
    expect(inputs.market_leasing.new_expense_stop_psf).toBe(11.25);
    expect(inputs.market_leasing.new_recovery_basis).toBe('expense_stop_psf');
  });

  it('always sends the key, even when the value is null', () => {
    // Required-but-nullable. An omitted key and a null value mean different
    // things to the backend contract.
    const marketLeasing = buildLeaseLevelInputsRequest(FILLED).market_leasing;
    for (const key of ['renewal_rent_psf', 'renewal_expense_stop_psf', 'renewal_recovery_basis']) {
      expect(Object.prototype.hasOwnProperty.call(marketLeasing, key)).toBe(true);
    }
  });

  it('OPTIONAL_MARKET_LEASING_KEYS names exactly the keys the builder allows blank', () => {
    // The list is hand-written; this makes it undriftable. A form blank in
    // exactly those keys converts, and a form blank in any other one does not.
    expect(() => buildLeaseLevelInputsRequest(FILLED)).not.toThrow();

    for (const key of Object.keys(MARKET_FORM) as (keyof MarketLeasingFormValues)[]) {
      const blanked: LeaseLevelFormValues = {
        ...FILLED,
        marketLeasing: { ...MARKET_FORM, [key]: '' },
      };
      const isOptional = OPTIONAL_MARKET_LEASING_KEYS.includes(key);
      if (isOptional) {
        expect(() => buildLeaseLevelInputsRequest(blanked), `${key} should be optional`).not.toThrow();
      } else {
        expect(() => buildLeaseLevelInputsRequest(blanked), `${key} should be required`).toThrow(
          FormValidationError,
        );
      }
    }
  });
});

// =============================================================================
// 3. Dates
// =============================================================================

describe('the analysis start date', () => {
  it('is sent exactly as entered, mid-month included', () => {
    const inputs = buildLeaseLevelInputsRequest({
      ...FILLED,
      property: { ...FILLED.property, analysisStartDate: '2027-03-17' },
    });
    // Snapping to 2027-03-01 would silently underwrite a different month than
    // the analyst chose. `ANALYSIS_START_NOT_MONTH_ALIGNED` is the backend's
    // rule to enforce, by name.
    expect(inputs.property_inputs.analysis_start_date).toBe('2027-03-17');
  });

  it('refuses a value that is not an ISO date, rather than repairing it', () => {
    for (const raw of ['03/17/2027', '2027-3-17', 'March 2027', '2027']) {
      expect(() =>
        buildLeaseLevelInputsRequest({
          ...FILLED,
          property: { ...FILLED.property, analysisStartDate: raw },
        }),
      ).toThrow(FormValidationError);
    }
  });
});

// =============================================================================
// 4. The rent roll passes through untouched
// =============================================================================

describe('the held rent roll', () => {
  it('passes suites and leases through by value, not by re-encoding', () => {
    const values: LeaseLevelFormValues = {
      ...FILLED,
      suites: SAVED_DEAL.suites,
      leases: SAVED_DEAL.leases,
    };
    const inputs = buildLeaseLevelInputsRequest(values);
    expect(inputs.suites).toEqual(SAVED_DEAL.suites);
    expect(inputs.leases).toEqual(SAVED_DEAL.leases);
  });

  it('reopens a saved rent roll unchanged, including a whole override', () => {
    const form = buildLeaseLevelFormValues(SAVED_DEAL, TERMS_FORM);
    expect(form.suites).toEqual(SAVED_DEAL.suites);
    expect(form.leases).toEqual(SAVED_DEAL.leases);
    // All-or-nothing by design: every field of the override survives, or the
    // override is absent. A partial one is not representable.
    expect(form.suites[0].market_leasing_override).toEqual(SAVED_DEAL.market_leasing);
  });

  it('copies the arrays rather than aliasing the response', () => {
    const form = buildLeaseLevelFormValues(SAVED_DEAL, TERMS_FORM);
    expect(form.suites).not.toBe(SAVED_DEAL.suites);
    expect(form.leases).not.toBe(SAVED_DEAL.leases);
  });
});

// =============================================================================
// 5. Completeness, driven off the contracts
// =============================================================================

describe('completeness', () => {
  it('gives every scalar form field a label, exactly once', () => {
    const configured = [
      ...LEASE_LEVEL_PROPERTY_FIELD_GROUPS.flatMap((group) => group.fields.map((f) => f.key)),
      ...LEASE_LEVEL_OPERATING_FIELD_GROUPS.flatMap((group) => group.fields.map((f) => f.key)),
      ...LEASE_LEVEL_MARKET_FIELD_GROUPS.flatMap((group) => group.fields.map((f) => f.key)),
      ...MARKET_LEASING_EXPENSE_STOP_FIELDS.map((f) => f.key),
    ];
    expect(new Set(configured).size, 'a field is configured twice').toBe(configured.length);

    // The five enum fields are selects and are rendered by the workspace
    // directly; `analysisStartDate` is a date control. Everything else must be
    // in a group, or it is a field nobody can see.
    const rendered = new Set<string>([
      ...configured,
      'analysisStartDate',
      'leasingCommissionMethod',
      'renewalLeaseType',
      'renewalRecoveryBasis',
      'newLeaseType',
      'newRecoveryBasis',
    ]);
    for (const group of ['property', 'operating', 'marketLeasing'] as const) {
      for (const key of Object.keys(BLANK_LEASE_LEVEL_FORM_VALUES[group])) {
        expect(rendered.has(key), `${group}.${key} is not rendered anywhere`).toBe(true);
      }
    }
  });

  it('maps every terms form key to a wire id the request builder emits', () => {
    const request = buildLeaseLevelTermsRequest(TERMS_FORM);
    for (const [formKey, wireId] of Object.entries(TERMS_WIRE_IDS)) {
      expect(
        Object.prototype.hasOwnProperty.call(request, wireId),
        `${formKey} maps to ${wireId}, which the request does not carry`,
      ).toBe(true);
    }
    expect(Object.keys(TERMS_WIRE_IDS).length).toBe(Object.keys(request).length);
  });

  it('derives every wire field name from its form key', () => {
    const inputs = buildLeaseLevelInputsRequest(FILLED);
    for (const [group, object] of [
      ['property', inputs.property_inputs],
      ['operating', inputs.operating_inputs],
      ['marketLeasing', inputs.market_leasing],
    ] as const) {
      for (const key of Object.keys(BLANK_LEASE_LEVEL_FORM_VALUES[group])) {
        expect(
          Object.prototype.hasOwnProperty.call(object, wireFieldName(key)),
          `${group}.${key} -> ${wireFieldName(key)} is not a field on the request`,
        ).toBe(true);
      }
    }
  });
});

// =============================================================================
// 6. Blank collection
// =============================================================================

describe('collectBlankScalarIssues', () => {
  it('reports nothing for a complete form', () => {
    expect(collectBlankScalarIssues(FILLED)).toEqual({ leaseIssues: [], termsIssues: [] });
  });

  it('reports every blank field at once, not the first', () => {
    const { leaseIssues, termsIssues } = collectBlankScalarIssues(BLANK_LEASE_LEVEL_FORM_VALUES);
    expect(termsIssues.length).toBe(11);
    // 2 property + 11 operating + 23 market, less the 5 optional market fields.
    expect(leaseIssues.length).toBe(2 + 11 + (23 - 5));
  });

  it('anchors each blank to the path the backend would use', () => {
    const { leaseIssues } = collectBlankScalarIssues({
      ...FILLED,
      operating: { ...FILLED.operating, recoverableExpenseRatio: '' },
    });
    expect(leaseIssues).toEqual([
      {
        code: 'MALFORMED_FIELD',
        path: 'operating_inputs.recoverable_expense_ratio',
        message: 'is required',
        severity: 'error',
      },
    ]);
  });

  it('treats whitespace as blank', () => {
    const { termsIssues } = collectBlankScalarIssues({
      ...FILLED,
      terms: { ...TERMS_FORM, purchasePrice: '   ' },
    });
    expect(termsIssues).toEqual([
      { field_id: 'purchase_price', category: 'MISSING_FIELD_ID', message: 'is required' },
    ]);
  });
});

// =============================================================================
// 7. Mutation kills
//
// Each mutant is the specific wrong behaviour a reviewer would worry about,
// applied to real values and shown to be caught -- not asserted impossible.
// =============================================================================

describe('mutation kills', () => {
  it('M17: a rate sent at percent scale is caught', () => {
    const inputs = buildLeaseLevelInputsRequest(FILLED);
    // The mutant is `parseNumber` where `parsePercent` belongs: 70 instead of
    // 0.7. Every rate is asserted below its own plausible percent value.
    for (const rate of [
      inputs.operating_inputs.expense_growth,
      inputs.operating_inputs.management_fee_pct,
      inputs.operating_inputs.credit_loss_pct,
      inputs.operating_inputs.recoverable_expense_ratio,
      inputs.market_leasing.renewal_probability,
      inputs.market_leasing.market_rent_growth,
      inputs.market_leasing.new_lc_pct,
      inputs.market_leasing.renewal_lc_pct,
      inputs.market_leasing.successor_escalation_pct,
    ]) {
      expect(Math.abs(rate)).toBeLessThanOrEqual(1);
    }
  });

  it('M18: a currency field divided by 100 is caught', () => {
    const inputs = buildLeaseLevelInputsRequest(FILLED);
    // The inverse mutant: `parsePercent` where `parseNumber` belongs.
    expect(inputs.operating_inputs.other_income).toBe(84_000);
    expect(inputs.market_leasing.new_ti_psf).toBe(65);
    expect(inputs.market_leasing.market_rent_psf).toBe(34.5);
  });

  it('M19: a blank nullable field defaulted to zero is caught', () => {
    const inputs = buildLeaseLevelInputsRequest(FILLED);
    expect(inputs.market_leasing.renewal_rent_psf).not.toBe(0);
    expect(inputs.market_leasing.renewal_expense_stop_psf).not.toBe(0);
    expect(inputs.market_leasing.renewal_rent_psf).toBeNull();
  });

  it('M20: a blank required field defaulted rather than refused is caught', () => {
    for (const key of ['marketRentPsf', 'renewalProbability', 'newTermMonths'] as const) {
      expect(() =>
        buildLeaseLevelInputsRequest({
          ...FILLED,
          marketLeasing: { ...MARKET_FORM, [key]: '' },
        }),
      ).toThrow(FormValidationError);
    }
  });

  it('M21: an unselected enum defaulted to its first option is caught', () => {
    expect(BLANK_LEASE_LEVEL_FORM_VALUES.marketLeasing.renewalLeaseType).toBe('');
    expect(BLANK_LEASE_LEVEL_FORM_VALUES.marketLeasing.newLeaseType).toBe('');
    expect(BLANK_LEASE_LEVEL_FORM_VALUES.marketLeasing.leasingCommissionMethod).toBe('');
    expect(() =>
      buildLeaseLevelInputsRequest({
        ...FILLED,
        marketLeasing: { ...MARKET_FORM, renewalLeaseType: '' },
      }),
    ).toThrow(FormValidationError);
  });

  it('M22: an unrecognised enum token accepted is caught', () => {
    expect(() =>
      buildLeaseLevelInputsRequest({
        ...FILLED,
        marketLeasing: { ...MARKET_FORM, newLeaseType: 'triple_net' },
      }),
    ).toThrow(FormValidationError);
  });

  it('M23: a date snapped to the first of the month is caught', () => {
    expect(
      buildLeaseLevelInputsRequest({
        ...FILLED,
        property: { ...FILLED.property, analysisStartDate: '2027-03-17' },
      }).property_inputs.analysis_start_date,
    ).not.toBe('2027-03-01');
  });

  it('M24: a suite dropped or reordered on the way out is caught', () => {
    const suites = [
      { ...SAVED_DEAL.suites[0], suite_id: 'A' },
      { ...SAVED_DEAL.suites[0], suite_id: 'B' },
      { ...SAVED_DEAL.suites[0], suite_id: 'C' },
    ];
    const inputs = buildLeaseLevelInputsRequest({ ...FILLED, suites });
    expect(inputs.suites.map((suite) => suite.suite_id)).toEqual(['A', 'B', 'C']);
  });

  it('M25: an override flattened into the property default is caught', () => {
    const form = buildLeaseLevelFormValues(SAVED_DEAL, TERMS_FORM);
    const mutatedDefault = { ...FILLED, marketLeasing: { ...MARKET_FORM, marketRentPsf: '99' } };
    const inputs = buildLeaseLevelInputsRequest({ ...mutatedDefault, suites: form.suites });
    expect(inputs.market_leasing.market_rent_psf).toBe(99);
    expect(inputs.suites[0].market_leasing_override?.market_rent_psf).toBe(34.5);
  });

  it('M26: the blank form seeded with an economic value is caught', () => {
    for (const group of ['terms', 'property', 'operating', 'marketLeasing'] as const) {
      for (const [key, value] of Object.entries(BLANK_LEASE_LEVEL_FORM_VALUES[group])) {
        expect(value, `${group}.${key} is seeded with ${String(value)}`).toBe('');
      }
    }
    expect(BLANK_LEASE_LEVEL_FORM_VALUES.suites).toEqual([]);
    expect(BLANK_LEASE_LEVEL_FORM_VALUES.leases).toEqual([]);
  });
});
