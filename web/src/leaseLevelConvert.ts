/**
 * D5.5A -- Lease-Level form <-> transport conversion and field configuration.
 *
 * The Lease-Level counterpart of `convert.ts`, reusing its primitives rather
 * than restating them: `parseNumber`, `parsePercent`, `parseWholeNumber` and
 * `formatDisplayNumber` are imported, so a percentage means exactly what it
 * already means everywhere else in Anchor -- percent-scale in the input,
 * decimal on the wire, one conversion in each direction.
 *
 * **No financial arithmetic.** Percent scaling and numeric string parsing are
 * serialization at the transport boundary, and are the same two operations
 * `buildAcquisitionTermsRequest` has always performed. Nothing here derives a
 * rent, a period, an escalation or a total.
 *
 * **No fabricated assumptions.** The blank state is empty across the board.
 * A contract *default* (the backend applies `credit_loss_pct = 0.0` when the
 * key is absent) is not the same thing as an analyst assumption, and prefilling
 * one here would put a number in front of the analyst that they never chose but
 * would be held to.
 */

import { FormValidationError, parseNumber, parsePercent, parseWholeNumber } from './convert';
import type {
  LeaseLevelDealFields,
  LeaseLevelFormValues,
  LeaseLevelInputsRequest,
  LeaseLevelIssue,
  EscalationBasis,
  InitialVacancyAssumptionsRequest,
  InitialVacancyStrategy,
  InitialVacancyFormValues,
  LeaseFormValues,
  LeaseRequest,
  SuiteRequest,
  SuiteRowFormValues,
  LeaseLevelOperatingFormValues,
  LeaseLevelOperatingInputsRequest,
  LeaseLevelPropertyFormValues,
  LeaseLevelPropertyInputsRequest,
  LeaseType,
  LeasingCommissionMethod,
  MarketLeasingAssumptionsRequest,
  MarketLeasingFormValues,
  RecoveryBasis,
} from './leaseLevelTypes';
import type {
  AcquisitionTermsFormValues,
  AcquisitionTermsRequest,
  ValidationIssue,
} from './types';
import {
  BLANK_TERMS_FORM_VALUES,
  buildAcquisitionTermsRequest,
  formatDisplayNumber,
} from './convert';

// =============================================================================
// Field configuration
//
// Same `{ key, label, prefix?, suffix? }` shape as `TERMS_FIELD_GROUPS` and
// `DETAILED_OPERATING_FIELD_GROUPS`, so `AssumptionFieldGrid` renders these
// with no change, and label/unit stay defined in exactly one place.
// =============================================================================

export interface LeaseLevelFieldConfig<Key extends string> {
  key: Key;
  label: string;
  prefix?: string;
  suffix?: string;
}

export interface LeaseLevelFieldGroup<Key extends string> {
  title: string;
  fields: LeaseLevelFieldConfig<Key>[];
}

export const LEASE_LEVEL_PROPERTY_FIELD_GROUPS: LeaseLevelFieldGroup<
  keyof LeaseLevelPropertyFormValues
>[] = [
  {
    title: 'Property',
    fields: [
      { key: 'rentableAreaSf', label: 'Rentable Area', suffix: 'SF' },
      // `analysisStartDate` is deliberately absent: it is a date, and the
      // scalar grid renders numeric inputs. The workspace gives it a real date
      // control of its own rather than bending the shared grid around one field.
    ],
  },
];

export const LEASE_LEVEL_OPERATING_FIELD_GROUPS: LeaseLevelFieldGroup<
  keyof LeaseLevelOperatingFormValues
>[] = [
  {
    title: 'Other Income & Credit Loss',
    fields: [
      { key: 'otherIncome', label: 'Other Income', prefix: '$' },
      { key: 'otherIncomeGrowth', label: 'Other Income Growth', suffix: '%' },
      { key: 'creditLossPct', label: 'Credit Loss', suffix: '%' },
    ],
  },
  {
    title: 'Property Expenses',
    fields: [
      { key: 'propertyTaxes', label: 'Property Taxes', prefix: '$' },
      { key: 'insurance', label: 'Insurance', prefix: '$' },
      { key: 'utilities', label: 'Utilities', prefix: '$' },
      { key: 'repairsMaintenance', label: 'Repairs & Maintenance', prefix: '$' },
      { key: 'otherOperatingExpenses', label: 'Other Operating Expenses', prefix: '$' },
    ],
  },
  {
    title: 'Fees, Growth & Recoverability',
    fields: [
      { key: 'managementFeePct', label: 'Management Fee', suffix: '%' },
      { key: 'expenseGrowth', label: 'Expense Growth', suffix: '%' },
      { key: 'recoverableExpenseRatio', label: 'Recoverable Expense Ratio', suffix: '%' },
    ],
  },
];

/** The twenty-three property-default market-leasing assumptions, grouped by the
 * decision each one belongs to.
 *
 * Grouped, not reordered arbitrarily: the sections follow the contract's own
 * structure -- the market, then a renewal, then a new tenant, then the leasing
 * capital both share. Twenty-three inputs in one unbroken column is a wall
 * nobody reads carefully, and these are exactly the assumptions that most
 * reward reading carefully.
 *
 * D5.5E renamed the visible labels only. Human Pass #1 found "Successor
 * Escalation" and "Branch" unreadable to anyone who had not read the engine;
 * every wire key, enum and contract name below is untouched.
 *
 * The three enum fields and the two nullable expense stops live in
 * `MARKET_LEASING_STRUCTURE_FIELDS` below, since they are selects rather than
 * numeric inputs. */
export const LEASE_LEVEL_MARKET_FIELD_GROUPS: LeaseLevelFieldGroup<
  keyof MarketLeasingFormValues
>[] = [
  {
    title: 'Market Rent',
    fields: [
      { key: 'marketRentPsf', label: 'Market Rent', prefix: '$', suffix: '/SF' },
      { key: 'marketRentGrowth', label: 'Market Rent Growth', suffix: '%' },
    ],
  },
  {
    title: 'Renewal',
    fields: [
      { key: 'renewalProbability', label: 'Renewal Probability', suffix: '%' },
      {
        key: 'renewalRentPsf',
        label: 'Renewal Rent (as of analysis start)',
        prefix: '$',
        suffix: '/SF',
      },
      { key: 'renewalRentSpread', label: 'Renewal Rent Spread', suffix: '%' },
      { key: 'renewalTermMonths', label: 'Renewal Term', suffix: 'mo' },
      { key: 'renewalDowntimeMonths', label: 'Renewal Downtime', suffix: 'mo' },
      { key: 'renewalFreeRentMonths', label: 'Renewal Free Rent', suffix: 'mo' },
    ],
  },
  {
    title: 'New Tenant',
    fields: [
      { key: 'newTermMonths', label: 'New Tenant Term', suffix: 'mo' },
      { key: 'newDowntimeMonths', label: 'New Tenant Downtime', suffix: 'mo' },
      { key: 'newFreeRentMonths', label: 'New Tenant Free Rent', suffix: 'mo' },
    ],
  },
  {
    title: 'Leasing Capital',
    fields: [
      { key: 'renewalTiPsf', label: 'Renewal TI', prefix: '$', suffix: '/SF' },
      { key: 'newTiPsf', label: 'New Tenant TI', prefix: '$', suffix: '/SF' },
      { key: 'renewalLcPct', label: 'Renewal LC', suffix: '%' },
      { key: 'newLcPct', label: 'New Tenant LC', suffix: '%' },
    ],
  },
  {
    title: 'Future Lease Escalation',
    fields: [
      { key: 'successorEscalationPct', label: 'Future Lease Rent Escalation', suffix: '%' },
    ],
  },
];

/** The expense stops, which are numeric but belong beside their lease-structure
 * selects rather than in a numeric group of their own. */
export const MARKET_LEASING_EXPENSE_STOP_FIELDS: LeaseLevelFieldConfig<
  keyof MarketLeasingFormValues
>[] = [
  { key: 'renewalExpenseStopPsf', label: 'Renewal Expense Stop', prefix: '$', suffix: '/SF' },
  { key: 'newExpenseStopPsf', label: 'New Tenant Expense Stop', prefix: '$', suffix: '/SF' },
];

/** The wire `field_id` each `AcquisitionTerms` form key validates as.
 *
 * `terms` is validated by the shared `validate_acquisition_terms`, which raises
 * the Quick/Detailed `InputIssue` shape keyed by a flat snake_case `field_id` --
 * not the Lease-Level `path`. Anchoring those messages to their inputs needs
 * this one translation.
 *
 * Typed as a total `Record` over the form keys, so the compiler refuses a
 * missing entry; `test_terms_wire_ids_match_the_request_builder` proves each
 * value is a key the request builder actually emits, so a wrong entry cannot
 * survive either.
 */
export const TERMS_WIRE_IDS: Record<keyof AcquisitionTermsFormValues, string> = {
  purchasePrice: 'purchase_price',
  holdPeriod: 'hold_period',
  exitCapRate: 'exit_cap_rate',
  ltv: 'ltv',
  interestRate: 'interest_rate',
  amortization: 'amortization',
  acquisitionCostPct: 'acquisition_cost_pct',
  financingFeePct: 'financing_fee_pct',
  dispositionCostPct: 'disposition_cost_pct',
  annualCapexReserve: 'annual_capex_reserve',
  ioPeriod: 'io_period',
};

// =============================================================================
// Select options
//
// Wire token in `value`, human label in `label`. The token is what is submitted;
// no aliasing happens on the way out.
// =============================================================================

export interface SelectOption {
  value: string;
  label: string;
}

export const LEASE_TYPE_OPTIONS: SelectOption[] = [
  { value: 'nnn', label: 'NNN' },
  { value: 'gross', label: 'Gross' },
  { value: 'modified_gross', label: 'Modified Gross' },
];

export const RECOVERY_BASIS_OPTIONS: SelectOption[] = [
  { value: 'expense_stop_psf', label: 'Expense Stop ($/SF)' },
];

export const LEASING_COMMISSION_METHOD_OPTIONS: SelectOption[] = [
  { value: 'pct_of_total_contractual_base_rent', label: '% of Total Contractual Base Rent' },
];

// =============================================================================
// Blank state
// =============================================================================

export const BLANK_LEASE_LEVEL_PROPERTY_FORM_VALUES: LeaseLevelPropertyFormValues = {
  analysisStartDate: '',
  rentableAreaSf: '',
};

export const BLANK_LEASE_LEVEL_OPERATING_FORM_VALUES: LeaseLevelOperatingFormValues = {
  otherIncome: '',
  otherIncomeGrowth: '',
  creditLossPct: '',
  propertyTaxes: '',
  insurance: '',
  utilities: '',
  repairsMaintenance: '',
  otherOperatingExpenses: '',
  managementFeePct: '',
  expenseGrowth: '',
  recoverableExpenseRatio: '',
};

export const BLANK_MARKET_LEASING_FORM_VALUES: MarketLeasingFormValues = {
  marketRentPsf: '',
  marketRentGrowth: '',
  renewalRentPsf: '',
  renewalRentSpread: '',
  renewalTermMonths: '',
  successorEscalationPct: '',
  renewalDowntimeMonths: '',
  renewalFreeRentMonths: '',
  newTermMonths: '',
  newDowntimeMonths: '',
  newFreeRentMonths: '',
  renewalTiPsf: '',
  newTiPsf: '',
  // Unselected, not defaulted. Only one method exists today, but choosing it
  // here would still be this module stating an assumption on the analyst's
  // behalf -- and would quietly become wrong the day a second one ships.
  leasingCommissionMethod: '',
  renewalLcPct: '',
  newLcPct: '',
  renewalProbability: '',
  renewalLeaseType: '',
  renewalRecoveryBasis: '',
  renewalExpenseStopPsf: '',
  newLeaseType: '',
  newRecoveryBasis: '',
  newExpenseStopPsf: '',
};

/** A brand-new Lease-Level deal: every assumption blank, and no rent roll.
 *
 * Emphatically not a demo deal. A fabricated suite would be an underwriting
 * assumption the analyst never made, and one that analyses cleanly enough to be
 * mistaken for their own. D5.5B supplies the editors that let a real one be
 * entered. */
export const BLANK_LEASE_LEVEL_FORM_VALUES: LeaseLevelFormValues = {
  terms: BLANK_TERMS_FORM_VALUES,
  property: BLANK_LEASE_LEVEL_PROPERTY_FORM_VALUES,
  operating: BLANK_LEASE_LEVEL_OPERATING_FORM_VALUES,
  marketLeasing: BLANK_MARKET_LEASING_FORM_VALUES,
  rentRoll: [],
  leaseOrder: [],
  unmatchedLeases: [],
};

// =============================================================================
// Which scalars may be left blank
//
// Every field on these contracts is required *on the wire*. Three of the
// market-leasing fields are required-but-nullable -- "stated as absent" and
// "not stated" are different facts there -- and the two recovery bases are
// genuinely optional. Everything else cannot become a value at all if it is
// empty, which is a fact about the transport rather than an underwriting rule.
//
// Listed here, immediately beside the builders that already treat exactly these
// keys as optional, so both readings live in one file and one review.
// `leaseLevelConvert.test.ts` proves the list matches the builders: a form blank
// in exactly these fields converts, and a form blank in any other does not.
// =============================================================================

export const OPTIONAL_MARKET_LEASING_KEYS: readonly (keyof MarketLeasingFormValues)[] = [
  'renewalRentPsf',
  'renewalRecoveryBasis',
  'renewalExpenseStopPsf',
  'newRecoveryBasis',
  'newExpenseStopPsf',
];

/** camelCase form key -> snake_case wire field.
 *
 * The inverse of the single naming rule this module applies: every Lease-Level
 * form key is its wire field written in camelCase. Derived rather than listed,
 * so no second name table exists to drift from the contract. */
export function wireFieldName(key: string): string {
  return key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
}

/**
 * Every scalar that is blank and cannot be, reported at once.
 *
 * `parseNumber` throws on the *first* empty field, which is the behaviour Quick
 * and Detailed have always had and is fine across fourteen assumptions. Across
 * Lease-Level's forty-seven it would mean one refusal per missing field, and an
 * analyst discovering the form one error at a time.
 *
 * So the blanks are collected first, anchored to the fields that hold them, in
 * the same two issue shapes the backend uses -- `path`-keyed for the
 * Lease-Level contracts, `field_id`-keyed for the shared `terms`. The wording
 * matches the structural parser's own (`is required`) because it is answering
 * the same question the parser would: can this become the contract at all.
 *
 * This decides nothing about whether the deal is *valid*. A form with every
 * field filled produces no issues here and is sent, and the backend's answer is
 * the only one that counts.
 */
export function collectBlankScalarIssues(values: LeaseLevelFormValues): {
  leaseIssues: LeaseLevelIssue[];
  termsIssues: ValidationIssue[];
} {
  const leaseIssues: LeaseLevelIssue[] = [];
  const termsIssues: ValidationIssue[] = [];

  for (const key of Object.keys(values.terms) as (keyof AcquisitionTermsFormValues)[]) {
    if (values.terms[key].trim() === '') {
      termsIssues.push({
        field_id: TERMS_WIRE_IDS[key],
        category: 'MISSING_FIELD_ID',
        message: 'is required',
      });
    }
  }

  function collect(object: string, group: object, optional: readonly string[]) {
    // Keyed off the form values themselves rather than a field list, so a field
    // added to any of these contracts joins this check automatically.
    for (const [key, value] of Object.entries(group)) {
      if (value.trim() === '' && !optional.includes(key)) {
        leaseIssues.push({
          code: 'MALFORMED_FIELD',
          path: `${object}.${wireFieldName(key)}`,
          message: 'is required',
          severity: 'error',
        });
      }
    }
  }

  collect('property_inputs', values.property, []);
  collect('operating_inputs', values.operating, []);
  collect('market_leasing', values.marketLeasing, OPTIONAL_MARKET_LEASING_KEYS);

  return { leaseIssues, termsIssues };
}

// =============================================================================
// Form -> transport
// =============================================================================

/** A required date, sent exactly as entered.
 *
 * The only check is that something was typed and that it has the shape the wire
 * expects. Whether the 15th of a month is acceptable is D1's rule, and it is
 * refused by name (`ANALYSIS_START_NOT_MONTH_ALIGNED`) rather than corrected
 * here -- a client that snapped the date would silently underwrite a different
 * month than the analyst chose. */
function parseIsoDate(label: string, raw: string): string {
  const trimmed = raw.trim();
  if (trimmed === '') {
    throw new FormValidationError(`${label} is required.`);
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
    throw new FormValidationError(`${label} must be a date (YYYY-MM-DD).`);
  }
  return trimmed;
}

/** A nullable numeric field: blank means "stated as absent", which on these
 * contracts is a real, distinct value rather than a missing key. */
function parseOptionalNumber(label: string, raw: string): number | null {
  return raw.trim() === '' ? null : parseNumber(label, raw);
}

function parseSelected<T extends string>(
  label: string,
  raw: string,
  allowed: readonly T[],
): T {
  const trimmed = raw.trim();
  if (trimmed === '') {
    throw new FormValidationError(`${label} is required.`);
  }
  if (!(allowed as readonly string[]).includes(trimmed)) {
    throw new FormValidationError(`${label} is not a recognised value.`);
  }
  return trimmed as T;
}

function parseOptionalSelected<T extends string>(
  label: string,
  raw: string,
  allowed: readonly T[],
): T | null {
  return raw.trim() === '' ? null : parseSelected(label, raw, allowed);
}

const LEASE_TYPES = ['nnn', 'gross', 'modified_gross'] as const;
const RECOVERY_BASES = ['expense_stop_psf'] as const;
const COMMISSION_METHODS = ['pct_of_total_contractual_base_rent'] as const;

export function buildLeaseLevelPropertyInputsRequest(
  values: LeaseLevelPropertyFormValues,
): LeaseLevelPropertyInputsRequest {
  return {
    analysis_start_date: parseIsoDate('Analysis Start Date', values.analysisStartDate),
    rentable_area_sf: parseNumber('Rentable Area', values.rentableAreaSf),
  };
}

export function buildLeaseLevelOperatingInputsRequest(
  values: LeaseLevelOperatingFormValues,
): LeaseLevelOperatingInputsRequest {
  return {
    other_income: parseNumber('Other Income', values.otherIncome),
    other_income_growth: parsePercent('Other Income Growth', values.otherIncomeGrowth),
    credit_loss_pct: parsePercent('Credit Loss', values.creditLossPct),
    property_taxes: parseNumber('Property Taxes', values.propertyTaxes),
    insurance: parseNumber('Insurance', values.insurance),
    utilities: parseNumber('Utilities', values.utilities),
    repairs_maintenance: parseNumber('Repairs & Maintenance', values.repairsMaintenance),
    other_operating_expenses: parseNumber(
      'Other Operating Expenses',
      values.otherOperatingExpenses,
    ),
    management_fee_pct: parsePercent('Management Fee', values.managementFeePct),
    expense_growth: parsePercent('Expense Growth', values.expenseGrowth),
    recoverable_expense_ratio: parsePercent(
      'Recoverable Expense Ratio',
      values.recoverableExpenseRatio,
    ),
  };
}

export function buildMarketLeasingRequest(
  values: MarketLeasingFormValues,
): MarketLeasingAssumptionsRequest {
  return {
    market_rent_psf: parseNumber('Market Rent', values.marketRentPsf),
    market_rent_growth: parsePercent('Market Rent Growth', values.marketRentGrowth),
    renewal_rent_psf: parseOptionalNumber('Renewal Rent', values.renewalRentPsf),
    renewal_rent_spread: parsePercent('Renewal Rent Spread', values.renewalRentSpread),
    renewal_term_months: parseWholeNumber('Renewal Term', values.renewalTermMonths),
    successor_escalation_pct: parsePercent(
      'Future Lease Rent Escalation',
      values.successorEscalationPct,
    ),
    renewal_downtime_months: parseNumber('Renewal Downtime', values.renewalDowntimeMonths),
    renewal_free_rent_months: parseNumber('Renewal Free Rent', values.renewalFreeRentMonths),
    new_term_months: parseWholeNumber('New Tenant Term', values.newTermMonths),
    new_downtime_months: parseNumber('New Tenant Downtime', values.newDowntimeMonths),
    new_free_rent_months: parseNumber('New Tenant Free Rent', values.newFreeRentMonths),
    renewal_ti_psf: parseNumber('Renewal TI', values.renewalTiPsf),
    new_ti_psf: parseNumber('New Tenant TI', values.newTiPsf),
    leasing_commission_method: parseSelected<LeasingCommissionMethod>(
      'Leasing Commission Method',
      values.leasingCommissionMethod,
      COMMISSION_METHODS,
    ),
    renewal_lc_pct: parsePercent('Renewal LC', values.renewalLcPct),
    new_lc_pct: parsePercent('New Tenant LC', values.newLcPct),
    renewal_probability: parsePercent('Renewal Probability', values.renewalProbability),
    renewal_lease_type: parseSelected<LeaseType>(
      'Renewal Lease Type',
      values.renewalLeaseType,
      LEASE_TYPES,
    ),
    renewal_recovery_basis: parseOptionalSelected<RecoveryBasis>(
      'Renewal Recovery Basis',
      values.renewalRecoveryBasis,
      RECOVERY_BASES,
    ),
    renewal_expense_stop_psf: parseOptionalNumber(
      'Renewal Expense Stop',
      values.renewalExpenseStopPsf,
    ),
    new_lease_type: parseSelected<LeaseType>(
      'New Tenant Lease Type',
      values.newLeaseType,
      LEASE_TYPES,
    ),
    new_recovery_basis: parseOptionalSelected<RecoveryBasis>(
      'New Tenant Recovery Basis',
      values.newRecoveryBasis,
      RECOVERY_BASES,
    ),
    new_expense_stop_psf: parseOptionalNumber(
      'New Tenant Expense Stop',
      values.newExpenseStopPsf,
    ),
  };
}

/**
 * The five Lease-Level input objects, ready to send.
 *
 * **Changed at D5.5B.** D5.5A handed `suites` and `leases` through verbatim
 * because it had no editor and could not have produced them. Now the rent roll
 * is unfolded from the editable rows -- and the protection the verbatim hand-off
 * bought is bought instead by the round-trip tests, which prove a loaded deal
 * opened and saved with no edits reproduces its rent roll byte-for-byte.
 */
export function buildLeaseLevelInputsRequest(
  values: LeaseLevelFormValues,
): LeaseLevelInputsRequest {
  const { suites, leases } = buildRentRollRequests(values);
  return {
    property_inputs: buildLeaseLevelPropertyInputsRequest(values.property),
    operating_inputs: buildLeaseLevelOperatingInputsRequest(values.operating),
    market_leasing: buildMarketLeasingRequest(values.marketLeasing),
    suites,
    leases,
  };
}

export function buildLeaseLevelTermsRequest(
  values: AcquisitionTermsFormValues,
): AcquisitionTermsRequest {
  // The shared Detailed builder, unchanged: `AcquisitionTerms` means the same
  // thing in both modes, and a Lease-Level copy would be a second place for the
  // same eleven rules to drift.
  return buildAcquisitionTermsRequest(values);
}

// =============================================================================
// Transport -> form
// =============================================================================

/** The shared display formatter, unchanged. `formatDisplayNumber` already
 * strips the float artifacts a decoded wire value carries, and Quick and
 * Detailed already reopen their assumptions through it -- a second copy here
 * would be a second rounding convention, which is exactly the kind of quiet
 * divergence a financial form cannot afford. */
function displayNumber(value: number | null): string {
  return value === null ? '' : formatDisplayNumber(value);
}

/** Decimal wire rate -> percent-scale form string. The one arithmetic this
 * module performs, and the same `* 100` convention `convert.ts` has applied
 * since Phase 5: a unit change on a value the analyst typed, never a derivation
 * of one economic quantity from another. */
function displayPercent(value: number | null): string {
  return value === null ? '' : formatDisplayNumber(value * 100);
}

export function buildLeaseLevelPropertyFormValues(
  request: LeaseLevelPropertyInputsRequest,
): LeaseLevelPropertyFormValues {
  return {
    analysisStartDate: request.analysis_start_date,
    rentableAreaSf: displayNumber(request.rentable_area_sf),
  };
}

export function buildLeaseLevelOperatingFormValues(
  request: LeaseLevelOperatingInputsRequest,
): LeaseLevelOperatingFormValues {
  return {
    otherIncome: displayNumber(request.other_income),
    otherIncomeGrowth: displayPercent(request.other_income_growth),
    creditLossPct: displayPercent(request.credit_loss_pct),
    propertyTaxes: displayNumber(request.property_taxes),
    insurance: displayNumber(request.insurance),
    utilities: displayNumber(request.utilities),
    repairsMaintenance: displayNumber(request.repairs_maintenance),
    otherOperatingExpenses: displayNumber(request.other_operating_expenses),
    managementFeePct: displayPercent(request.management_fee_pct),
    expenseGrowth: displayPercent(request.expense_growth),
    recoverableExpenseRatio: displayPercent(request.recoverable_expense_ratio),
  };
}

export function buildMarketLeasingFormValues(
  request: MarketLeasingAssumptionsRequest,
): MarketLeasingFormValues {
  return {
    marketRentPsf: displayNumber(request.market_rent_psf),
    marketRentGrowth: displayPercent(request.market_rent_growth),
    renewalRentPsf: displayNumber(request.renewal_rent_psf),
    renewalRentSpread: displayPercent(request.renewal_rent_spread),
    renewalTermMonths: displayNumber(request.renewal_term_months),
    successorEscalationPct: displayPercent(request.successor_escalation_pct),
    renewalDowntimeMonths: displayNumber(request.renewal_downtime_months),
    renewalFreeRentMonths: displayNumber(request.renewal_free_rent_months),
    newTermMonths: displayNumber(request.new_term_months),
    newDowntimeMonths: displayNumber(request.new_downtime_months),
    newFreeRentMonths: displayNumber(request.new_free_rent_months),
    renewalTiPsf: displayNumber(request.renewal_ti_psf),
    newTiPsf: displayNumber(request.new_ti_psf),
    leasingCommissionMethod: request.leasing_commission_method,
    renewalLcPct: displayPercent(request.renewal_lc_pct),
    newLcPct: displayPercent(request.new_lc_pct),
    renewalProbability: displayPercent(request.renewal_probability),
    renewalLeaseType: request.renewal_lease_type,
    renewalRecoveryBasis: request.renewal_recovery_basis ?? '',
    renewalExpenseStopPsf: displayNumber(request.renewal_expense_stop_psf),
    newLeaseType: request.new_lease_type,
    newRecoveryBasis: request.new_recovery_basis ?? '',
    newExpenseStopPsf: displayNumber(request.new_expense_stop_psf),
  };
}

/** Hydrate a saved deal into editable form state.
 *
 * The rent roll is carried across by reference-free copy and never rebuilt:
 * D5.5A shows suite and lease *counts* and nothing more, so converting them to
 * strings and back would risk altering data on a screen that never displayed
 * it. */
export function buildLeaseLevelFormValues(
  deal: LeaseLevelDealFields,
  termsFormValues: AcquisitionTermsFormValues,
): LeaseLevelFormValues {
  const rentRoll = buildRentRollFormValues(deal.suites, deal.leases);
  return {
    terms: termsFormValues,
    property: buildLeaseLevelPropertyFormValues(deal.property_inputs),
    operating: buildLeaseLevelOperatingFormValues(deal.operating_inputs),
    marketLeasing: buildMarketLeasingFormValues(deal.market_leasing),
    ...rentRoll,
  };
}

// =============================================================================
// D5.5B -- the rent roll
//
// One form row per suite, unfolded on submit into the two flat transport arrays
// the engine contract defines. D4 acquisition supports at most one known lease
// per suite, so a suite-centric row matches the capability exactly and spares
// the analyst maintaining two tables cross-referenced by hand on `suite_id`.
//
// Every rule below is structural -- which fields the contract can represent, and
// when -- never economic. No rent, area total, term or date is computed here.
// =============================================================================

export const ESCALATION_BASIS_OPTIONS: SelectOption[] = [
  { value: 'none', label: 'None (flat rent)' },
  { value: 'lease_anniversary', label: 'Lease Anniversary' },
];

export const INITIAL_VACANCY_STRATEGY_OPTIONS: SelectOption[] = [
  { value: 'hold_vacant', label: 'Hold Vacant' },
  { value: 'market_lease_up', label: 'Market Lease-Up' },
];

const ESCALATION_BASES: readonly EscalationBasis[] = ['none', 'lease_anniversary'];
const VACANCY_STRATEGIES: readonly InitialVacancyStrategy[] = [
  'hold_vacant',
  'market_lease_up',
];

/** Local row identity. Never submitted, never persisted, never fingerprinted,
 * and never an underwriting assumption.
 *
 * A counter rather than anything derived from the row's contents: `suiteId` is
 * blank on a new row and duplicated while one is being retyped, so a
 * content-derived key would collide exactly when React most needs it stable. */
let nextRowSequence = 0;

export function nextRowId(): string {
  nextRowSequence += 1;
  return `row-${nextRowSequence}`;
}

/** A brand-new lease: every field blank.
 *
 * Nothing is seeded -- not the rent, not a term, not the dates, and above all
 * not NNN. Marking a suite occupied says only that a tenant exists; every
 * economic term of that tenancy is the analyst's to state. */
export function blankLeaseFormValues(): LeaseFormValues {
  return {
    leaseId: '',
    leasedAreaSf: '',
    tenantName: '',
    leaseStartDate: '',
    rentCommencementDate: '',
    leaseExpirationDate: '',
    baseRentPsf: '',
    escalationPct: '',
    escalationBasis: '',
    leaseType: '',
    recoveryBasis: '',
    expenseStopPsf: '',
    // The contract's own default for a lease an analyst enters. `SUCCESSOR` is
    // engine-generated and is never created here.
    origin: 'in_place',
  };
}

export const BLANK_INITIAL_VACANCY_FORM_VALUES: InitialVacancyFormValues = {
  // Unselected. Anchor does not assume vacant space stays vacant, and does not
  // assume it lets either -- `MISSING_INITIAL_VACANCY_TREATMENT` exists exactly
  // so the choice is made rather than inherited.
  strategy: '',
  initialLeaseUpMonths: '',
};

/** A brand-new suite row: blank, vacant, with no treatment chosen.
 *
 * Vacant because a suite with no lease *is* vacant -- the engine's own rule, not
 * a default chosen here. Blank because a fabricated area or rent would be an
 * assumption the analyst never made, sitting in a roll that looks entered. */
export function blankSuiteRow(): SuiteRowFormValues {
  return {
    rowId: nextRowId(),
    suiteId: '',
    suiteAreaSf: '',
    suiteLabel: '',
    marketRentPsf: '',
    lease: null,
    initialVacancy: { ...BLANK_INITIAL_VACANCY_FORM_VALUES },
    marketLeasingOverrideEnabled: false,
    marketLeasingOverride: { ...BLANK_MARKET_LEASING_FORM_VALUES },
  };
}

/** Occupied exactly when a lease exists -- the engine's rule, restated nowhere
 * else in this frontend and never stored as a field of its own. */
export function isRowOccupied(row: SuiteRowFormValues): boolean {
  return row.lease !== null;
}

// -----------------------------------------------------------------------------
// Form -> transport
// -----------------------------------------------------------------------------

function buildInitialVacancyRequest(
  values: InitialVacancyFormValues,
): InitialVacancyAssumptionsRequest {
  const strategy = parseSelected<InitialVacancyStrategy>(
    'Initial Vacancy Strategy',
    values.strategy,
    VACANCY_STRATEGIES,
  );
  return {
    strategy,
    // `HOLD_VACANT` must carry no lease-up period
    // (`INITIAL_LEASE_UP_ON_HOLD_VACANT`); `MARKET_LEASE_UP` requires one
    // (`MISSING_INITIAL_LEASE_UP_MONTHS`). Both are the contract's rules. This
    // only decides which of the analyst's typed values the shape can carry, so
    // a dormant lease-up figure never reaches the wire.
    initial_lease_up_months:
      strategy === 'market_lease_up'
        ? parseNumber('Initial Lease-Up Months', values.initialLeaseUpMonths)
        : null,
  };
}

export function buildSuiteRequest(row: SuiteRowFormValues): SuiteRequest {
  return {
    suite_id: row.suiteId.trim(),
    suite_area_sf: parseNumber('Suite Area', row.suiteAreaSf),
    // A blank label is an absent label, not an empty one: `None` means
    // "unlabelled", and sending "" would give every unlabelled suite a value it
    // does not have.
    suite_label: row.suiteLabel.trim() === '' ? null : row.suiteLabel.trim(),
    market_rent_psf: parseOptionalNumber('Suite Market Rent', row.marketRentPsf),
    // All-or-nothing (D0 24.2). Enabled submits the complete record; disabled
    // submits `null` -- never a partial merge, and never the dormant values the
    // form is still holding for the analyst.
    market_leasing_override: row.marketLeasingOverrideEnabled
      ? buildMarketLeasingRequest(row.marketLeasingOverride)
      : null,
    // An occupied suite must carry no treatment
    // (`INITIAL_VACANCY_ON_OCCUPIED_SUITE`), so dormant vacancy state is dropped
    // here rather than allowed to reach the wire.
    initial_vacancy: isRowOccupied(row)
      ? null
      : buildInitialVacancyRequest(row.initialVacancy),
  };
}

export function buildLeaseRequest(
  row: SuiteRowFormValues,
  lease: LeaseFormValues,
): LeaseRequest {
  return {
    lease_id: lease.leaseId.trim(),
    // Taken from the row that owns it, never typed twice -- which is what makes
    // `UNKNOWN_SUITE_REFERENCE` unreachable from this editor by construction.
    suite_id: row.suiteId.trim(),
    leased_area_sf: parseNumber('Leased Area', lease.leasedAreaSf),
    rent_commencement_date: parseIsoDate('Rent Commencement', lease.rentCommencementDate),
    lease_expiration_date: parseIsoDate('Lease Expiration', lease.leaseExpirationDate),
    base_rent_psf: parseNumber('Base Rent', lease.baseRentPsf),
    escalation_pct: parsePercent('Escalation', lease.escalationPct),
    escalation_basis: parseSelected<EscalationBasis>(
      'Escalation Basis',
      lease.escalationBasis,
      ESCALATION_BASES,
    ),
    lease_type: parseSelected<LeaseType>('Lease Type', lease.leaseType, LEASE_TYPES),
    tenant_name: lease.tenantName.trim() === '' ? null : lease.tenantName.trim(),
    lease_start_date:
      lease.leaseStartDate.trim() === ''
        ? null
        : parseIsoDate('Lease Start', lease.leaseStartDate),
    // Held, not chosen: whatever was loaded is what goes back.
    origin: lease.origin,
    recovery_basis: parseOptionalSelected<RecoveryBasis>(
      'Recovery Basis',
      lease.recoveryBasis,
      RECOVERY_BASES,
    ),
    expense_stop_psf: parseOptionalNumber('Expense Stop', lease.expenseStopPsf),
  };
}

/**
 * The rent roll, unfolded into the two arrays the contract defines.
 *
 * Suites follow row order, so the persisted `ordinal` follows the order the
 * analyst arranged. Leases replay `leaseOrder` first -- the order the loaded
 * deal carried, which the backend preserves independently of suite order -- and
 * anything not named there follows in row order. Without that, opening and
 * saving a deal whose leases were not stored in suite order would silently
 * reorder them.
 *
 * A row with no lease contributes a suite and no lease, which is exactly how
 * vacant space is represented, so a removed lease can never leave an orphan.
 */
export function buildRentRollRequests(values: LeaseLevelFormValues): {
  suites: SuiteRequest[];
  leases: LeaseRequest[];
} {
  const suites: SuiteRequest[] = [];
  const built: LeaseRequest[] = [];
  for (const row of values.rentRoll) {
    suites.push(buildSuiteRequest(row));
    if (row.lease !== null) {
      built.push(buildLeaseRequest(row, row.lease));
    }
  }

  const rank = (lease: LeaseRequest): number => {
    const index = values.leaseOrder.indexOf(lease.lease_id);
    return index === -1 ? Number.MAX_SAFE_INTEGER : index;
  };
  // Compared rather than subtracted: `a.rank - b.rank` is ordering, not
  // economics, but G-M7 audits arithmetic structurally and a carve-out for
  // "sorting" would be a hole shaped like anything. Comparison needs none.
  const leases = built
    .map((lease, position) => ({ lease, position, rank: rank(lease) }))
    .sort((a, b) => {
      if (a.rank !== b.rank) {
        return a.rank < b.rank ? -1 : 1;
      }
      return a.position < b.position ? -1 : 1;
    })
    .map((entry) => entry.lease);

  // Leases no row could claim are resubmitted verbatim so the backend still
  // reports on them. They cannot be created or saved through this UI.
  return { suites, leases: [...leases, ...values.unmatchedLeases] };
}

// -----------------------------------------------------------------------------
// Transport -> form
// -----------------------------------------------------------------------------

function buildLeaseFormValues(lease: LeaseRequest): LeaseFormValues {
  return {
    leaseId: lease.lease_id,
    leasedAreaSf: displayNumber(lease.leased_area_sf),
    tenantName: lease.tenant_name ?? '',
    leaseStartDate: lease.lease_start_date ?? '',
    rentCommencementDate: lease.rent_commencement_date,
    leaseExpirationDate: lease.lease_expiration_date,
    baseRentPsf: displayNumber(lease.base_rent_psf),
    escalationPct: displayPercent(lease.escalation_pct),
    escalationBasis: lease.escalation_basis,
    leaseType: lease.lease_type,
    recoveryBasis: lease.recovery_basis ?? '',
    expenseStopPsf: displayNumber(lease.expense_stop_psf),
    origin: lease.origin,
  };
}

/**
 * Fold the two transport arrays into one row per suite.
 *
 * A lease is matched to its suite by `suite_id`, the same key the engine binds
 * them with, and each lease is claimed at most once. Anything left unclaimed is
 * returned rather than dropped -- see `LeaseLevelFormValues.unmatchedLeases`.
 */
export function buildRentRollFormValues(
  suites: readonly SuiteRequest[],
  leases: readonly LeaseRequest[],
): { rentRoll: SuiteRowFormValues[]; leaseOrder: string[]; unmatchedLeases: LeaseRequest[] } {
  const claimed = new Set<LeaseRequest>();
  const rentRoll = suites.map((suite) => {
    const lease = leases.find(
      (candidate) => !claimed.has(candidate) && candidate.suite_id === suite.suite_id,
    );
    if (lease !== undefined) {
      claimed.add(lease);
    }
    return {
      rowId: nextRowId(),
      suiteId: suite.suite_id,
      suiteAreaSf: displayNumber(suite.suite_area_sf),
      suiteLabel: suite.suite_label ?? '',
      marketRentPsf: displayNumber(suite.market_rent_psf),
      lease: lease === undefined ? null : buildLeaseFormValues(lease),
      initialVacancy:
        suite.initial_vacancy === null
          ? { ...BLANK_INITIAL_VACANCY_FORM_VALUES }
          : {
              strategy: suite.initial_vacancy.strategy,
              initialLeaseUpMonths: displayNumber(
                suite.initial_vacancy.initial_lease_up_months,
              ),
            },
      marketLeasingOverrideEnabled: suite.market_leasing_override !== null,
      marketLeasingOverride:
        suite.market_leasing_override === null
          ? { ...BLANK_MARKET_LEASING_FORM_VALUES }
          : buildMarketLeasingFormValues(suite.market_leasing_override),
    };
  });

  return {
    rentRoll,
    leaseOrder: leases.map((lease) => lease.lease_id),
    unmatchedLeases: leases.filter((lease) => !claimed.has(lease)),
  };
}

// -----------------------------------------------------------------------------
/** Lease fields the contract declares nullable. Everything else on a lease is
 * required on the wire, so a blank one cannot become a value at all. */
export const OPTIONAL_LEASE_KEYS: readonly (keyof LeaseFormValues)[] = [
  'tenantName',
  'leaseStartDate',
  'recoveryBasis',
  'expenseStopPsf',
  'origin',
];

/** Suite fields the contract declares nullable. */
export const OPTIONAL_SUITE_KEYS: readonly string[] = ['suiteLabel', 'marketRentPsf'];

/**
 * Every rent-roll field that is blank and cannot be, anchored to its row.
 *
 * The same rule as the scalar collector, applied to the roll: a blank required
 * field cannot become a value, so there is no request to send, and reporting all
 * of them at once beats one refusal per field across thirty suites. It says
 * nothing about whether the deal is *valid* -- a fully typed roll produces
 * nothing here and is sent for the backend to judge.
 *
 * Paths use the array index each row will occupy, matching the index-keyed
 * convention `leasing/validation.py` uses for these fields, so the same row
 * resolver handles collected blanks and backend issues identically.
 */
export function collectRentRollBlankIssues(values: LeaseLevelFormValues): LeaseLevelIssue[] {
  const issues: LeaseLevelIssue[] = [];
  const required = (path: string) => {
    issues.push({
      code: 'MALFORMED_FIELD',
      path,
      message: 'is required',
      severity: 'error',
    });
  };

  let leaseIndex = 0;
  values.rentRoll.forEach((row, index) => {
    const at = `suites[${index}]`;
    for (const [key, value] of Object.entries(row)) {
      if (typeof value !== 'string' || OPTIONAL_SUITE_KEYS.includes(key)) {
        continue;
      }
      if (value.trim() === '') {
        required(`${at}.${wireFieldName(key)}`);
      }
    }

    if (row.marketLeasingOverrideEnabled) {
      for (const [key, value] of Object.entries(row.marketLeasingOverride)) {
        if (
          value.trim() === '' &&
          !(OPTIONAL_MARKET_LEASING_KEYS as readonly string[]).includes(key)
        ) {
          required(`${at}.market_leasing_override.${wireFieldName(key)}`);
        }
      }
    }

    if (!isRowOccupied(row)) {
      // A vacant suite states its treatment; Anchor picks neither strategy.
      if (row.initialVacancy.strategy.trim() === '') {
        required(`${at}.initial_vacancy.strategy`);
      } else if (
        row.initialVacancy.strategy === 'market_lease_up' &&
        row.initialVacancy.initialLeaseUpMonths.trim() === ''
      ) {
        required(`${at}.initial_vacancy.initial_lease_up_months`);
      }
    }

    if (row.lease !== null) {
      const leaseAt = `leases[${leaseIndex}]`;
      leaseIndex += 1;
      for (const [key, value] of Object.entries(row.lease)) {
        if (
          typeof value !== 'string' ||
          (OPTIONAL_LEASE_KEYS as readonly string[]).includes(key)
        ) {
          continue;
        }
        if (value.trim() === '') {
          required(`${leaseAt}.${wireFieldName(key)}`);
        }
      }
    }
  });

  return issues;
}

// Area reconciliation -- the D5.0 display-only carve-out
// -----------------------------------------------------------------------------

/**
 * Property rentable area against the sum of entered suite areas.
 *
 * The one arithmetic this gate performs, and it is addition of integers the
 * analyst typed. Approved at D5.0 (plan section 10.1) as an **input-validation
 * aid**, and it is never financial authority: it changes no value, allocates
 * nothing, creates no residual suite, and blocks no submission.
 * `RENTABLE_AREA_NOT_RECONCILED` from the backend remains the only thing that
 * can refuse an analysis.
 *
 * A blank or unparseable area contributes nothing and is counted separately, so
 * a half-typed roll reads as incomplete rather than as a shortfall.
 */
export function reconcileArea(values: LeaseLevelFormValues): {
  rentableAreaSf: number | null;
  allocatedSf: number;
  differenceSf: number | null;
  rowsWithoutArea: number;
} {
  const rentable = Number(values.property.rentableAreaSf.trim());
  const rentableAreaSf =
    values.property.rentableAreaSf.trim() === '' || !Number.isFinite(rentable)
      ? null
      : rentable;

  let allocatedSf = 0;
  let rowsWithoutArea = 0;
  for (const row of values.rentRoll) {
    const area = Number(row.suiteAreaSf.trim());
    if (row.suiteAreaSf.trim() === '' || !Number.isFinite(area)) {
      rowsWithoutArea += 1;
      continue;
    }
    allocatedSf += area;
  }

  return {
    rentableAreaSf,
    allocatedSf,
    differenceSf: rentableAreaSf === null ? null : rentableAreaSf - allocatedSf,
    rowsWithoutArea,
  };
}
