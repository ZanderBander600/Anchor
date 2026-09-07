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
 * structure -- the market, then the renewal branch, then the new-tenant branch,
 * then the leasing capital both share. Twenty-three inputs in one unbroken
 * column is a wall nobody reads carefully, and these are exactly the
 * assumptions that most reward reading carefully.
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
    title: 'Renewal Branch',
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
    title: 'New-Tenant Branch',
    fields: [
      { key: 'newTermMonths', label: 'New Term', suffix: 'mo' },
      { key: 'newDowntimeMonths', label: 'New Downtime', suffix: 'mo' },
      { key: 'newFreeRentMonths', label: 'New Free Rent', suffix: 'mo' },
    ],
  },
  {
    title: 'Leasing Capital',
    fields: [
      { key: 'renewalTiPsf', label: 'Renewal TI', prefix: '$', suffix: '/SF' },
      { key: 'newTiPsf', label: 'New TI', prefix: '$', suffix: '/SF' },
      { key: 'renewalLcPct', label: 'Renewal LC', suffix: '%' },
      { key: 'newLcPct', label: 'New LC', suffix: '%' },
    ],
  },
  {
    title: 'Successor Escalation',
    fields: [
      { key: 'successorEscalationPct', label: 'Successor Escalation', suffix: '%' },
    ],
  },
];

/** The expense stops, which are numeric but belong beside their lease-structure
 * selects rather than in a numeric group of their own. */
export const MARKET_LEASING_EXPENSE_STOP_FIELDS: LeaseLevelFieldConfig<
  keyof MarketLeasingFormValues
>[] = [
  { key: 'renewalExpenseStopPsf', label: 'Renewal Expense Stop', prefix: '$', suffix: '/SF' },
  { key: 'newExpenseStopPsf', label: 'New Expense Stop', prefix: '$', suffix: '/SF' },
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
  suites: [],
  leases: [],
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
      'Successor Escalation',
      values.successorEscalationPct,
    ),
    renewal_downtime_months: parseNumber('Renewal Downtime', values.renewalDowntimeMonths),
    renewal_free_rent_months: parseNumber('Renewal Free Rent', values.renewalFreeRentMonths),
    new_term_months: parseWholeNumber('New Term', values.newTermMonths),
    new_downtime_months: parseNumber('New Downtime', values.newDowntimeMonths),
    new_free_rent_months: parseNumber('New Free Rent', values.newFreeRentMonths),
    renewal_ti_psf: parseNumber('Renewal TI', values.renewalTiPsf),
    new_ti_psf: parseNumber('New TI', values.newTiPsf),
    leasing_commission_method: parseSelected<LeasingCommissionMethod>(
      'Leasing Commission Method',
      values.leasingCommissionMethod,
      COMMISSION_METHODS,
    ),
    renewal_lc_pct: parsePercent('Renewal LC', values.renewalLcPct),
    new_lc_pct: parsePercent('New LC', values.newLcPct),
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
      'New Lease Type',
      values.newLeaseType,
      LEASE_TYPES,
    ),
    new_recovery_basis: parseOptionalSelected<RecoveryBasis>(
      'New Recovery Basis',
      values.newRecoveryBasis,
      RECOVERY_BASES,
    ),
    new_expense_stop_psf: parseOptionalNumber('New Expense Stop', values.newExpenseStopPsf),
  };
}

/**
 * The five Lease-Level input objects, ready to send.
 *
 * `suites` and `leases` pass through **exactly as loaded**. D5.5A edits no rent
 * roll, so anything other than a verbatim hand-off would be this gate silently
 * changing data it does not own.
 */
export function buildLeaseLevelInputsRequest(
  values: LeaseLevelFormValues,
): LeaseLevelInputsRequest {
  return {
    property_inputs: buildLeaseLevelPropertyInputsRequest(values.property),
    operating_inputs: buildLeaseLevelOperatingInputsRequest(values.operating),
    market_leasing: buildMarketLeasingRequest(values.marketLeasing),
    suites: values.suites,
    leases: values.leases,
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
  return {
    terms: termsFormValues,
    property: buildLeaseLevelPropertyFormValues(deal.property_inputs),
    operating: buildLeaseLevelOperatingFormValues(deal.operating_inputs),
    marketLeasing: buildMarketLeasingFormValues(deal.market_leasing),
    suites: [...deal.suites],
    leases: [...deal.leases],
  };
}
