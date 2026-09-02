import type {
  AcquisitionFieldId,
  AcquisitionFormValues,
  AcquisitionRequest,
  ExcelIntakeReport,
  V2FieldId,
} from './types';
import { ACQUISITION_FIELD_IDS, V2_FIELD_IDS } from './types';

/**
 * Raised for client-side presence/parsing problems only. Domain rules
 * (e.g. "purchase price must be positive") are validated by the backend,
 * per AGENTS.md -- this layer never reproduces financial validation.
 */
export class FormValidationError extends Error {}

export function parseNumber(label: string, raw: string): number {
  const trimmed = raw.trim();
  if (trimmed === '') {
    throw new FormValidationError(`${label} is required.`);
  }
  const value = Number(trimmed);
  if (!Number.isFinite(value)) {
    throw new FormValidationError(`${label} must be a valid number.`);
  }
  return value;
}

/** Converts an analyst-facing percentage (e.g. "5.25") to a decimal fraction (0.0525). */
export function parsePercent(label: string, raw: string): number {
  return parseNumber(label, raw) / 100;
}

/** Like `parseNumber`, but also rejects a fractional value (Underwriting V2
 * Gate 6: `io_period` is whole years) -- immediate client-side feedback
 * mirroring the backend's `NON_WHOLE_NUMBER_IO_PERIOD` rule, rather than
 * waiting on a round trip to surface the same error. */
export function parseWholeNumber(label: string, raw: string): number {
  const value = parseNumber(label, raw);
  if (!Number.isInteger(value)) {
    throw new FormValidationError(`${label} must be a whole number.`);
  }
  return value;
}

export function buildAcquisitionRequest(
  values: AcquisitionFormValues,
): AcquisitionRequest {
  return {
    purchase_price: parseNumber('Purchase Price', values.purchasePrice),
    current_noi: parseNumber('Current NOI', values.currentNoi),
    occupancy: parsePercent('Occupancy', values.occupancy),
    noi_growth: parsePercent('NOI Growth', values.noiGrowth),
    hold_period: parseNumber('Hold Period', values.holdPeriod),
    exit_cap_rate: parsePercent('Exit Cap Rate', values.exitCapRate),
    ltv: parsePercent('LTV', values.ltv),
    interest_rate: parsePercent('Interest Rate', values.interestRate),
    amortization: parseNumber('Amortization', values.amortization),
    acquisition_cost_pct: parsePercent('Acquisition Costs', values.acquisitionCostPct),
    financing_fee_pct: parsePercent('Financing Fee', values.financingFeePct),
    disposition_cost_pct: parsePercent('Disposition Costs', values.dispositionCostPct),
    annual_capex_reserve: parseNumber('Annual CapEx Reserve', values.annualCapexReserve),
    io_period: parseWholeNumber('Interest-Only Period', values.ioPeriod),
  };
}

/**
 * The golden-deal fixture values (U9's tracked example workbook, the CLI's
 * canonical sample deal). Kept as-is for tests and as the OM/Excel
 * conversion baseline -- no longer used to pre-populate the form on initial
 * load; see `BLANK_FORM_VALUES` (U10). The five Underwriting V2 fields are
 * explicit zeros here (Gate 6) -- a fully specified, ready-to-analyze
 * legacy-equivalent deal, distinct from `BLANK_FORM_VALUES`'s unset state.
 */
export const DEFAULT_FORM_VALUES: AcquisitionFormValues = {
  purchasePrice: '50000000',
  currentNoi: '2500000',
  occupancy: '95',
  noiGrowth: '3',
  holdPeriod: '5',
  exitCapRate: '5.5',
  ltv: '65',
  interestRate: '5.25',
  amortization: '30',
  acquisitionCostPct: '0',
  financingFeePct: '0',
  dispositionCostPct: '0',
  annualCapexReserve: '0',
  ioPeriod: '0',
};

/**
 * The frozen Underwriting V2 golden case (Gate 4/6) -- all five V2 fields
 * simultaneously nonzero. Used as the Gate 6 UI integration fixture: tests
 * exercising the full 14-field flow, and the demonstration that Year 1 DSCR
 * (2.00x) and Minimum DSCR (~1.65x) render as visibly distinct values.
 */
export const V2_GOLDEN_FORM_VALUES: AcquisitionFormValues = {
  purchasePrice: '10000000',
  currentNoi: '600000',
  occupancy: '95',
  noiGrowth: '3',
  holdPeriod: '5',
  exitCapRate: '6.5',
  ltv: '60',
  interestRate: '5',
  amortization: '30',
  acquisitionCostPct: '2',
  financingFeePct: '1',
  dispositionCostPct: '2.5',
  annualCapexReserve: '50000',
  ioPeriod: '2',
};

/**
 * The App's initial `AssumptionsForm` state (U10): every field blank, so a
 * new session never appears to have a deal already loaded. `parseNumber`
 * already rejects a blank required field with a `FormValidationError`
 * rather than defaulting it to `0` (see `convert.test.ts`), so this is safe
 * to submit as-is -- clicking Analyze Deal on it surfaces the existing
 * validation error instead of silently reaching the engine. The five
 * Underwriting V2 fields (Gate 6) are blank for exactly the same reason:
 * the analyst must consciously enter a value for each, including 0 if zero
 * is intended -- never silently defaulted.
 */
export const BLANK_FORM_VALUES: AcquisitionFormValues = {
  purchasePrice: '',
  currentNoi: '',
  occupancy: '',
  noiGrowth: '',
  holdPeriod: '',
  exitCapRate: '',
  ltv: '',
  interestRate: '',
  amortization: '',
  acquisitionCostPct: '',
  financingFeePct: '',
  dispositionCostPct: '',
  annualCapexReserve: '',
  ioPeriod: '',
};

export interface FieldConfig {
  key: keyof AcquisitionFormValues;
  label: string;
  prefix?: string;
  suffix?: string;
}

export interface FieldGroup {
  title: string;
  fields: FieldConfig[];
}

/** The 14 canonical assumptions grouped for display -- shared by
 * `AssumptionsForm` and `ExcelReviewPanel` (Excel Ingestion Review) so both
 * surfaces group, label, and format (currency/percent/years) every field
 * identically rather than maintaining a second, potentially-drifting field
 * list. Lives here (not in a component file) purely so both components can
 * import it without one depending on the other. */
export const ASSUMPTIONS_FIELD_GROUPS: FieldGroup[] = [
  {
    title: 'Acquisition',
    fields: [
      { key: 'purchasePrice', label: 'Purchase Price', prefix: '$' },
      { key: 'currentNoi', label: 'Current NOI', prefix: '$' },
      { key: 'occupancy', label: 'Occupancy', suffix: '%' },
    ],
  },
  {
    title: 'Growth & Exit',
    fields: [
      { key: 'noiGrowth', label: 'NOI Growth', suffix: '%' },
      { key: 'holdPeriod', label: 'Hold Period', suffix: 'yrs' },
      { key: 'exitCapRate', label: 'Exit Cap Rate', suffix: '%' },
    ],
  },
  {
    title: 'Transaction Costs',
    fields: [
      { key: 'acquisitionCostPct', label: 'Acquisition Costs', suffix: '%' },
      { key: 'financingFeePct', label: 'Financing Fee', suffix: '%' },
      { key: 'dispositionCostPct', label: 'Disposition Costs', suffix: '%' },
    ],
  },
  {
    title: 'Operations',
    fields: [{ key: 'annualCapexReserve', label: 'Annual CapEx Reserve', prefix: '$' }],
  },
  {
    title: 'Financing',
    fields: [
      { key: 'ltv', label: 'LTV', suffix: '%' },
      { key: 'interestRate', label: 'Interest Rate', suffix: '%' },
      { key: 'amortization', label: 'Amortization', suffix: 'yrs' },
      { key: 'ioPeriod', label: 'Interest-Only Period', suffix: 'yrs' },
    ],
  },
];

export const DEFAULT_TARGET_LEVERED_IRR_PERCENT = '10.00';
export const DEFAULT_TARGET_HEADLINE_DSCR = '1.20';
export const DEFAULT_TARGET_EQUITY_MULTIPLE = '1.50';

// =============================================================================
// Phase 10A -- OM ingestion candidate values -> AssumptionsForm handoff
// (U9, KTD4/KTD5). Converts a raw ingestion candidate value string (as
// proposed by the classifier -- see FIELD_DESCRIPTIONS in
// src/anchor/ingestion/prompts.py) into the plain, percent-scale
// numeric string AssumptionsForm's fields expect. Reuses no financial
// validation of its own; the existing buildAcquisitionRequest/AssumptionsForm
// path above remains the sole authority once a value reaches the form.
// =============================================================================

/** Human-readable label for each of the 9 AcquisitionInputs fields, for
 * display in the OM review UI. */
export const ACQUISITION_FIELD_LABELS: Record<AcquisitionFieldId, string> = {
  purchase_price: 'Purchase Price',
  current_noi: 'Current NOI',
  occupancy: 'Occupancy',
  noi_growth: 'NOI Growth',
  hold_period: 'Hold Period',
  exit_cap_rate: 'Exit Cap Rate',
  ltv: 'LTV',
  interest_rate: 'Interest Rate',
  amortization: 'Amortization',
};

export const ACQUISITION_FIELD_TO_FORM_KEY: Record<AcquisitionFieldId, keyof AcquisitionFormValues> = {
  purchase_price: 'purchasePrice',
  current_noi: 'currentNoi',
  occupancy: 'occupancy',
  noi_growth: 'noiGrowth',
  hold_period: 'holdPeriod',
  exit_cap_rate: 'exitCapRate',
  ltv: 'ltv',
  interest_rate: 'interestRate',
  amortization: 'amortization',
};

/** Human-readable label for each of the five Underwriting V2 fields
 * (Gate 6), for display in Excel/OM review messaging. */
export const V2_FIELD_LABELS: Record<V2FieldId, string> = {
  acquisition_cost_pct: 'Acquisition Costs',
  financing_fee_pct: 'Financing Fee',
  disposition_cost_pct: 'Disposition Costs',
  annual_capex_reserve: 'Annual CapEx Reserve',
  io_period: 'Interest-Only Period',
};

export const V2_FIELD_TO_FORM_KEY: Record<V2FieldId, keyof AcquisitionFormValues> = {
  acquisition_cost_pct: 'acquisitionCostPct',
  financing_fee_pct: 'financingFeePct',
  disposition_cost_pct: 'dispositionCostPct',
  annual_capex_reserve: 'annualCapexReserve',
  io_period: 'ioPeriod',
};

/**
 * Underwriting V2 Gate 6: builds the "additional assumptions require
 * review" banner text for a legacy/partial Excel upload, naming exactly the
 * defaulted V2 fields in canonical order. Returns `null` when nothing was
 * defaulted (a complete fourteen-field workbook), so the caller can skip
 * rendering the banner entirely -- phrased as required additional
 * assumptions, never as something "missing" from the workbook.
 */
export function buildV2ReviewMessage(defaultedFieldIds: V2FieldId[]): string | null {
  if (defaultedFieldIds.length === 0) {
    return null;
  }
  const defaulted = new Set(defaultedFieldIds);
  const labels = V2_FIELD_IDS.filter((fieldId) => defaulted.has(fieldId)).map(
    (fieldId) => V2_FIELD_LABELS[fieldId],
  );
  const verb = labels.length === 1 ? 'requires' : 'require';
  return (
    `Additional underwriting assumptions ${verb} review before analyzing or saving: ` +
    `${labels.join(', ')}. This workbook does not include ${labels.length === 1 ? 'this value' : 'these values'} -- enter ${labels.length === 1 ? 'it' : 'them'} below.`
  );
}

/** Fields whose natural unit is a percentage/ratio -- the classifier may
 * propose either the literal percentage ("5.5%") or the decimal-fraction
 * equivalent ("0.055"); AssumptionsForm always wants the percent-scale
 * number ("5.5"). Mirrors `_PERCENT_SCALE_FIELD_IDS` in
 * `src/anchor/ingestion/classifier_provider.py`. */
const PERCENT_SCALE_FIELD_IDS: ReadonlySet<AcquisitionFieldId> = new Set([
  'occupancy',
  'noi_growth',
  'exit_cap_rate',
  'ltv',
  'interest_rate',
]);

/** Strips currency/percent formatting (``$``, ``%``, commas, whitespace)
 * from a candidate value string and parses the remaining number. Returns
 * `null` if the result isn't a finite number. */
function parseCandidateNumber(raw: string): number | null {
  const cleaned = raw.replace(/[^0-9.-]/g, '');
  if (cleaned === '' || cleaned === '-' || cleaned === '.' || cleaned === '-.') {
    return null;
  }
  const value = Number(cleaned);
  return Number.isFinite(value) ? value : null;
}

/**
 * Converts one acquisition-field candidate's raw value string to the plain
 * numeric string `AcquisitionFormValues`/`AssumptionsForm` expects. Returns
 * `null` if the value can't be parsed as a number, so the caller can leave
 * that field out of the pre-fill rather than write a garbage value into the
 * form.
 */
export function candidateValueToFormValue(fieldId: AcquisitionFieldId, rawValue: string): string | null {
  const number = parseCandidateNumber(rawValue);
  if (number === null) {
    return null;
  }
  if (!PERCENT_SCALE_FIELD_IDS.has(fieldId)) {
    return String(number);
  }
  // A literal "%" sign, or a magnitude too large to plausibly be a decimal
  // fraction, means the value is already percent-scale; otherwise treat it
  // as the decimal-fraction equivalent and scale up to match the form.
  const isAlreadyPercentScale = rawValue.includes('%') || Math.abs(number) > 1;
  const percentValue = isAlreadyPercentScale ? number : number * 100;
  return String(percentValue);
}

/**
 * Builds the `AcquisitionFormValues` subset for a set of analyst-approved
 * ingestion candidate values, keyed by acquisition field id. A field whose
 * value can't be parsed as a number is silently excluded rather than
 * corrupting the form -- the analyst can still enter it manually, exactly
 * as an unapproved/rejected/missing field already does (R11).
 */
export function buildApprovedFormValues(
  approvedValues: Partial<Record<AcquisitionFieldId, string>>,
): Partial<AcquisitionFormValues> {
  const result: Partial<AcquisitionFormValues> = {};
  for (const fieldId of ACQUISITION_FIELD_IDS) {
    const rawValue = approvedValues[fieldId];
    if (rawValue === undefined) {
      continue;
    }
    const formValue = candidateValueToFormValue(fieldId, rawValue);
    if (formValue !== null) {
      result[ACQUISITION_FIELD_TO_FORM_KEY[fieldId]] = formValue;
    }
  }
  return result;
}

// =============================================================================
// Phase 10B -- Excel ingestion (web upload) / saved-deal-open candidate
// values -> AssumptionsForm handoff. Unlike OM's buildApprovedFormValues,
// the backend Excel upload endpoint and GET /deals/{id} both always return
// a fully validated, complete AcquisitionRequest (never a partial/candidate
// result), so this is a plain, always-complete numeric conversion -- the
// inverse of buildAcquisitionRequest. `buildFormValuesFromAcquisitionInputs`
// itself never blanks anything (0 is a real value, e.g. a saved deal's
// persisted zero, and must render as 0, never blank); the Excel-specific
// Underwriting V2 Gate 6 blanking of defaulted V2 fields lives in
// `buildFormValuesFromExcelIntakeReport` below, which layers on top of it.
// =============================================================================

/** Rounds to a sane display precision and strips binary-float noise
 * introduced by the `* 100` percent-scale conversion below (e.g. so
 * `0.1 * 100` never renders as `"10.000000000000002"`). Real acquisition
 * inputs never need more than a handful of decimal places. */
function formatDisplayNumber(value: number): string {
  return String(Math.round(value * 1e6) / 1e6);
}

/**
 * Converts a fully validated `AcquisitionRequest` (the shape the backend
 * Excel upload endpoint, `GET /deals/{id}`, and `/analyze` all use) into the
 * percent-scale `AcquisitionFormValues` strings `AssumptionsForm` expects.
 * All fourteen fields are always present and always rendered as their real
 * value -- including an explicit 0 -- since a workbook/deal that failed
 * validation never reaches this function.
 */
export function buildFormValuesFromAcquisitionInputs(
  inputs: AcquisitionRequest,
): AcquisitionFormValues {
  return {
    purchasePrice: formatDisplayNumber(inputs.purchase_price),
    currentNoi: formatDisplayNumber(inputs.current_noi),
    occupancy: formatDisplayNumber(inputs.occupancy * 100),
    noiGrowth: formatDisplayNumber(inputs.noi_growth * 100),
    holdPeriod: formatDisplayNumber(inputs.hold_period),
    exitCapRate: formatDisplayNumber(inputs.exit_cap_rate * 100),
    ltv: formatDisplayNumber(inputs.ltv * 100),
    interestRate: formatDisplayNumber(inputs.interest_rate * 100),
    amortization: formatDisplayNumber(inputs.amortization),
    acquisitionCostPct: formatDisplayNumber(inputs.acquisition_cost_pct * 100),
    financingFeePct: formatDisplayNumber(inputs.financing_fee_pct * 100),
    dispositionCostPct: formatDisplayNumber(inputs.disposition_cost_pct * 100),
    annualCapexReserve: formatDisplayNumber(inputs.annual_capex_reserve),
    ioPeriod: formatDisplayNumber(inputs.io_period),
  };
}

/**
 * Underwriting V2 Gate 6: converts a `POST /ingestion/excel` response
 * (Gate 5's `ExcelIntakeReport`) into `AcquisitionFormValues`, blanking
 * exactly the V2 fields the backend reports as defaulted (absent from the
 * workbook) rather than displaying its neutral-zero compatibility value as
 * though the analyst had entered it. Every supplied field -- the original
 * nine plus any V2 field actually present in the workbook -- is populated
 * normally via `buildFormValuesFromAcquisitionInputs`. A complete
 * fourteen-field workbook (`defaulted_v2_field_ids` empty) is therefore
 * identical to that plain conversion.
 */
export function buildFormValuesFromExcelIntakeReport(
  report: ExcelIntakeReport,
): AcquisitionFormValues {
  const values = buildFormValuesFromAcquisitionInputs(report.inputs);
  for (const fieldId of report.defaulted_v2_field_ids) {
    values[V2_FIELD_TO_FORM_KEY[fieldId]] = '';
  }
  return values;
}
