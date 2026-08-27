import type { AcquisitionFieldId, AcquisitionFormValues, AcquisitionRequest } from './types';
import { ACQUISITION_FIELD_IDS } from './types';

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
  };
}

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
};

export const DEFAULT_TARGET_LEVERED_IRR_PERCENT = '10.00';
export const DEFAULT_TARGET_HEADLINE_DSCR = '1.20';
export const DEFAULT_TARGET_EQUITY_MULTIPLE = '1.50';

// =============================================================================
// Phase 10A -- OM ingestion candidate values -> AssumptionsForm handoff
// (U9, KTD4/KTD5). Converts a raw ingestion candidate value string (as
// proposed by the classifier -- see FIELD_DESCRIPTIONS in
// src/mini_anchor/ingestion/prompts.py) into the plain, percent-scale
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

/** Fields whose natural unit is a percentage/ratio -- the classifier may
 * propose either the literal percentage ("5.5%") or the decimal-fraction
 * equivalent ("0.055"); AssumptionsForm always wants the percent-scale
 * number ("5.5"). Mirrors `_PERCENT_SCALE_FIELD_IDS` in
 * `src/mini_anchor/ingestion/classifier_provider.py`. */
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
