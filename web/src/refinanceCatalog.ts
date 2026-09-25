/**
 * Refinance & Capital Events V1 Stage 3 -- the analyst's words for every typed
 * refinance state.
 *
 * The engine's own `unavailable_message` is a precise sentence built from
 * typed objects, but at its layer a Unit has no analyst name and is named by
 * its id (Refinance V1 Section 23.4 item 6). So an analyst surface never
 * prints it: it translates the stable `reason_code`, and names the refinance by
 * its label, the scope by its Deal or Investment name and each loan by its own
 * name (Section 15.3). Nothing here computes a figure; it only says which
 * figure is shown and why another is not.
 */

import { unavailableReasonLabel } from './memoCatalog';
import { formatCurrency } from './format';
import type {
  ConstraintKind,
  RefinanceResult,
  RefinanceStatus,
  RefinanceUnavailableReason,
  RetiringPositionRef,
} from './capitalTypes';

export const REFINANCE_STATUS_LABELS: Readonly<Record<RefinanceStatus, string>> = {
  executed: 'Executed',
  unavailable: 'Unavailable',
  not_executable: 'Not executable',
  blocked: 'Blocked',
};

export const CONSTRAINT_LABELS: Readonly<Record<ConstraintKind, string>> = {
  fixed_cap: 'Fixed maximum proceeds',
  max_ltv: 'Maximum LTV',
  min_dscr: 'Minimum DSCR',
};

/** The primary economic answer of an executed refinance, by the direction the
 * engine reports. Never decided from the sign here. */
export const DIRECTION_HEADINGS: Readonly<Record<'distribution' | 'contribution' | 'zero', string>> = {
  distribution: 'Cash returned to Common Equity',
  contribution: 'Common Equity contribution required',
  zero: 'Cash returned to Common Equity',
};

export const DIRECTION_NOTES: Readonly<Record<'distribution' | 'contribution' | 'zero', string>> = {
  distribution: 'Net refinance cash distributed to Common Equity at the refinance date.',
  contribution:
    'The payoff and costs exceed the new loan: Common Equity contributes the difference at the refinance date. It is not a Funding Requirement.',
  zero: 'The new loan exactly covers the payoff and costs: no cash is returned and none is required.',
};

/** A currency amount without its sign, for a figure whose heading already
 * says which way the cash moves. Formatting only: the text of the engine's
 * own figure, never a recomputed one. */
export function magnitudeText(value: number): string {
  return formatCurrency(value).replace(/^-/, '');
}

/** Where a refinance applies, as the analyst knows it. */
export function scopeText(
  scope: { kind: 'unit' | 'investment'; unit_id: string | null },
  unitNames: Record<string, string>,
): string {
  if (scope.kind === 'investment') {
    return 'the whole Investment';
  }
  return unitNames[scope.unit_id ?? ''] ?? 'this Unit';
}

/** A retiring loan by name: an authored position's own name, or a Unit's
 * acquisition loan. Never its identity. */
export function retiringName(
  ref: RetiringPositionRef,
  positionNames: Record<string, string>,
  unitNames: Record<string, string>,
  multiUnit: boolean,
): string {
  if (ref.kind === 'legacy_acquisition_loan') {
    return multiUnit ? `Acquisition loan — ${unitNames[ref.unit_id] ?? 'Unit'}` : 'Acquisition loan';
  }
  return positionNames[ref.position_id] ?? 'A loan no longer in this structure';
}

/** "End of Year N" for an event's hold year, as the engine reports it. */
export function eventDateText(result: { hold_year: number }): string {
  return `End of Year ${result.hold_year}`;
}

interface ReasonContext {
  label: string;
  scope: string;
  holdYear: number;
  forwardYear: number | null;
  valuationLabel: string | null;
  valuationReason: string | null;
}

const REASON_SENTENCES: Readonly<Record<RefinanceUnavailableReason, (context: ReasonContext) => string>> = {
  event_outside_hold_horizon: (c) =>
    `“${c.label}” is at the end of Year ${c.holdYear}, which is not before the sale in this analysis, so it cannot execute here. It may execute under a longer hold.`,
  timepoint_not_found: (c) =>
    `The valuation that “${c.label}” measures its maximum LTV against no longer exists. No other value is used in its place.`,
  model_month_mismatch: (c) =>
    `${c.valuationLabel === null ? 'The referenced valuation' : `The valuation “${c.valuationLabel}”`} is dated at a different time than “${c.label}”. A valuation is never moved to match a refinance.`,
  scope_not_covered: (c) =>
    `${c.valuationLabel === null ? 'The referenced valuation' : `The valuation “${c.valuationLabel}”`} has no value for ${c.scope}. No other scope’s value is used.`,
  valuation_unavailable: (c) =>
    `${c.valuationLabel === null ? 'The referenced valuation' : `The valuation “${c.valuationLabel}”`} has no value for ${c.scope} in this analysis. ${unavailableReasonLabel(c.valuationReason)} It is never read as zero or replaced by the purchase price.`,
  evidence_not_approved: (c) =>
    `${c.valuationLabel === null ? 'The referenced valuation' : `The valuation “${c.valuationLabel}”`} is analyst-supplied and its Evidence Reference is not approved. The typed amount is not used until the evidence is approved.`,
  forward_noi_unavailable: (c) =>
    `There is no forward NOI for ${c.scope}${c.forwardYear === null ? '' : ` in Year ${c.forwardYear}`} in this analysis, so the minimum DSCR cannot be sized. No valuation stands in for it.`,
  non_positive_forward_noi: (c) =>
    `Forward NOI for ${c.scope}${c.forwardYear === null ? '' : ` in Year ${c.forwardYear}`} is zero or negative, so the minimum DSCR supports no loan. It is never floored.`,
  retiring_position_absent: () =>
    'A loan it repays does not exist in this analysis — for example, the acquisition loan when this variant finances with none.',
  retiring_position_not_outstanding: () =>
    'A loan it repays is already fully repaid before the refinance date in this analysis.',
  non_positive_capacity: () =>
    'The least of its sizing capacities is zero or negative, so no replacement loan can be funded. The old loans are not silently kept in place.',
  upstream_unresolved_funding: () =>
    'A Funding Requirement in its scope, at or before the refinance, is unresolved, so the refinance cannot settle.',
  upstream_capital_event_not_executed: () =>
    'A Unit refinance in this Investment did not execute, so this Investment refinance cannot settle either.',
};

export interface RefinanceTextContext {
  unitNames: Record<string, string>;
  valuationLabels: Record<string, string>;
}

function contextOf(result: RefinanceResult, context: RefinanceTextContext): ReasonContext {
  const valuationId = result.value_dependency?.timepoint_id ?? null;
  return {
    label: result.label,
    scope: scopeText(result.scope, context.unitNames),
    holdYear: result.hold_year,
    forwardYear: result.noi_dependency?.forward_year ?? null,
    valuationLabel: valuationId === null ? null : (context.valuationLabels[valuationId] ?? null),
    valuationReason: result.value_dependency?.valuation_unavailable_reason ?? null,
  };
}

/** Why a refinance did not execute, in the analyst's words. */
export function refinanceReasonText(result: RefinanceResult, context: RefinanceTextContext): string | null {
  if (result.unavailable_reason === null) {
    return null;
  }
  return REASON_SENTENCES[result.unavailable_reason](contextOf(result, context));
}

/** Why one sizing capacity is unknowable, in the analyst's words. */
export function capacityReasonText(
  reason: RefinanceUnavailableReason | null,
  result: RefinanceResult,
  context: RefinanceTextContext,
): string | null {
  return reason === null ? null : REASON_SENTENCES[reason](contextOf(result, context));
}

/** Why Common Equity has no figures when a refinance did not execute. */
export function commonEquityUnavailableText(results: RefinanceResult[]): string {
  const notExecuted = results.filter((result) => result.status !== 'executed').map((result) => `“${result.label}”`);
  return notExecuted.length === 0
    ? 'Common Equity is not reported for this analysis.'
    : `Common Equity is not reported: ${notExecuted.join(', ')} did not execute for this analysis, so the cash after it is unknowable. Property and project results are unaffected, and the acquisition-financing figures are not a substitute.`;
}

/** The acquisition-financing reference label (R-P rule 3). */
export const ACQUISITION_REFERENCE_LABEL = 'Acquisition financing — excludes later capital events';

/** The Scenario limitation Section 13.3 obliges Stage 3 to disclose. */
export const SCENARIO_RATE_LIMITATION =
  'A Scenario’s interest-rate change applies to the acquisition loan only. A replacement loan’s rate is a Capital Structure term, so alternative refinance terms are modelled as separate Strategies.';

export const DSCR_BASIS_TEXT =
  'V1 basis: the replacement loan’s actual scheduled debt service in its first twelve months, interest-only months included.';

/** The note a Position or Partner Decision Matrix carries when any Strategy's
 * Capital Structure includes a refinance: these perspectives are
 * refinance-adjusted, unlike the Project figures. */
export const MATRIX_REFINANCE_NOTE =
  'Position and Partner figures include each strategy’s refinance: Common Equity and Partner returns here are the refinance-adjusted answers. Project figures are the acquisition-financing reference.';
