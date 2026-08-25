import type { AcquisitionFormValues, AcquisitionRequest } from './types';

/**
 * Raised for client-side presence/parsing problems only. Domain rules
 * (e.g. "purchase price must be positive") are validated by the backend,
 * per AGENTS.md -- this layer never reproduces financial validation.
 */
export class FormValidationError extends Error {}

function parseNumber(label: string, raw: string): number {
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
function parsePercent(label: string, raw: string): number {
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
