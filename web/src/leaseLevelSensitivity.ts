/**
 * D5.7 -- what the Lease-Level sensitivity workspace needs to know about the
 * eight targets and five metrics, in one place.
 *
 * **It computes nothing.** Every function here either formats a number the
 * backend returned, or applies the app's existing percent *unit convention* to a
 * value the analyst typed. There is no arithmetic operator anywhere in this
 * file: the percent conversion is delegated to `parsePercent` in `convert.ts`,
 * which Quick, Detailed and Lease-Level have shared since Phase 5, and every
 * display string comes from `format.ts`. The one piece of arithmetic this gate
 * adds lives alone in `leaseLevelSensitivityLadder.ts` (the D5.0-approved
 * candidate-generation carve-out) and is never reachable from a result surface.
 *
 * **Absolute values.** A candidate is the assumption value itself. `6.25` in an
 * Exit Cap Rate field means an exit cap of 6.25%, which reaches the wire as
 * `0.0625` through exactly the same conversion the Underwrite form uses. It is
 * never `+25 bps`, never `-6.67%`, and no baseline is consulted to interpret it.
 */

import { parseNumber, parsePercent } from './convert';
import { formatCurrency, formatMultiple, formatPercent } from './format';
import type { SuiteRowFormValues } from './leaseLevelTypes';
import type {
  LeaseLevelSensitivityMetricId,
  LeaseLevelSensitivityTargetId,
} from './leaseLevelSensitivityTypes';

// =============================================================================
// Targets
// =============================================================================

/**
 * How a target's values are entered and displayed.
 *
 * `percent` is the app's existing convention -- the analyst types `6.25`, the
 * wire carries `0.0625`. `currency` and `currency_psf` are entered and sent at
 * the same scale, so nothing converts them at all.
 */
export type TargetUnit = 'currency' | 'currency_psf' | 'percent';

/**
 * Which suite-level override shadows a property-default target.
 *
 * The asymmetry is measured, load-bearing, and restated from
 * `lease_level_sensitivity.py::_TARGETS`:
 *
 *   * `market_rent_psf` is shadowed by a **full** `market_leasing_override`
 *     *or* by a suite's scalar `market_rent_psf` -- either one stands in front
 *     of the property default rent.
 *   * `renewal_probability` is shadowed **only** by a full
 *     `market_leasing_override`. A suite carrying just a scalar market rent
 *     overrides the rent level and nothing else, so the property renewal
 *     probability still reaches it.
 *
 * `null` means no suite override can reach the target at all -- the four
 * acquisition terms live on `AcquisitionTerms`, and `expense_growth` /
 * `recoverable_expense_ratio` live on `LeaseLevelOperatingInputs`, which shares
 * no field name with `Suite`.
 */
export type ShadowRule = 'rent_or_full_override' | 'full_override_only' | null;

export interface LeaseLevelSensitivityTargetConfig {
  id: LeaseLevelSensitivityTargetId;
  /** The analyst-facing label. Raw snake_case is never shown. */
  label: string;
  unit: TargetUnit;
  /** Reused by `groupsThousands` so a candidate field groups its thousands
   * exactly as the same assumption's Underwrite field does. */
  prefix?: string;
  suffix?: string;
  shadowRule: ShadowRule;
}

/**
 * The eight supported targets, in the backend's declaration order.
 *
 * Exactly `LEASE_LEVEL_SUPPORTED_ASSUMPTIONS`. Adding a ninth entry here would
 * not make a ninth target work -- the runner would refuse it by name -- so the
 * list is deliberately a mirror and not a menu.
 */
export const LEASE_LEVEL_SENSITIVITY_TARGETS: LeaseLevelSensitivityTargetConfig[] = [
  {
    id: 'purchase_price',
    label: 'Purchase Price',
    unit: 'currency',
    prefix: '$',
    shadowRule: null,
  },
  { id: 'exit_cap_rate', label: 'Exit Cap Rate', unit: 'percent', suffix: '%', shadowRule: null },
  { id: 'ltv', label: 'LTV', unit: 'percent', suffix: '%', shadowRule: null },
  { id: 'interest_rate', label: 'Interest Rate', unit: 'percent', suffix: '%', shadowRule: null },
  {
    id: 'market_rent_psf',
    label: 'Market Rent / SF',
    unit: 'currency_psf',
    prefix: '$',
    suffix: '/SF',
    shadowRule: 'rent_or_full_override',
  },
  {
    id: 'renewal_probability',
    label: 'Renewal Probability',
    unit: 'percent',
    suffix: '%',
    shadowRule: 'full_override_only',
  },
  { id: 'expense_growth', label: 'Expense Growth', unit: 'percent', suffix: '%', shadowRule: null },
  {
    id: 'recoverable_expense_ratio',
    label: 'Recoverable Expense Ratio',
    unit: 'percent',
    suffix: '%',
    shadowRule: null,
  },
];

const TARGETS_BY_ID: Record<LeaseLevelSensitivityTargetId, LeaseLevelSensitivityTargetConfig> =
  Object.fromEntries(
    LEASE_LEVEL_SENSITIVITY_TARGETS.map((target) => [target.id, target]),
  ) as Record<LeaseLevelSensitivityTargetId, LeaseLevelSensitivityTargetConfig>;

export function sensitivityTarget(
  id: LeaseLevelSensitivityTargetId,
): LeaseLevelSensitivityTargetConfig {
  return TARGETS_BY_ID[id];
}

/** The label for a target id the *response* named. Falls back to the raw string
 * so a contract change surfaces as a visibly odd header rather than a plausible
 * wrong one. */
export function targetLabel(id: string): string {
  return TARGETS_BY_ID[id as LeaseLevelSensitivityTargetId]?.label ?? id;
}

// =============================================================================
// Metrics
// =============================================================================

export interface LeaseLevelSensitivityMetricConfig {
  id: LeaseLevelSensitivityMetricId;
  label: string;
  /** How a result cell is rendered. Presentation only -- the value itself is
   * whatever the backend returned. */
  display: 'percent' | 'multiple' | 'currency';
}

/** The five metrics, with the exact backend identifiers. */
export const LEASE_LEVEL_SENSITIVITY_METRICS: LeaseLevelSensitivityMetricConfig[] = [
  { id: 'levered_irr', label: 'Levered IRR', display: 'percent' },
  { id: 'unlevered_irr', label: 'Unlevered IRR', display: 'percent' },
  { id: 'equity_multiple', label: 'Equity Multiple', display: 'multiple' },
  { id: 'headline_dscr', label: 'Headline DSCR', display: 'multiple' },
  { id: 'exit_value', label: 'Exit Value', display: 'currency' },
];

const METRICS_BY_ID: Record<LeaseLevelSensitivityMetricId, LeaseLevelSensitivityMetricConfig> =
  Object.fromEntries(
    LEASE_LEVEL_SENSITIVITY_METRICS.map((metric) => [metric.id, metric]),
  ) as Record<LeaseLevelSensitivityMetricId, LeaseLevelSensitivityMetricConfig>;

export function metricLabel(id: string): string {
  return METRICS_BY_ID[id as LeaseLevelSensitivityMetricId]?.label ?? id;
}

// =============================================================================
// Display / wire conversion
// =============================================================================

/**
 * One candidate value, from what the analyst typed to what the wire carries.
 *
 * The *only* transformation is the unit convention, and it is the shipped one:
 * `parsePercent` for a percentage field, `parseNumber` for everything else --
 * byte-identical to what the Underwrite form does with the same assumption.
 * Nothing is clamped, rounded, reordered, deduplicated or compared to a
 * baseline, so the value the analyst can see is the value the backend
 * evaluates.
 *
 * Throws `FormValidationError` (from `convert.ts`) for a blank or unparseable
 * entry, which the workspace reports rather than silently dropping the value.
 */
export function candidateToWireValue(
  target: LeaseLevelSensitivityTargetConfig,
  raw: string,
): number {
  return target.unit === 'percent'
    ? parsePercent(target.label, raw)
    : parseNumber(target.label, raw);
}

/** One assumption value from the response, as a row or column header. */
export function formatTargetValue(assumption: string, value: number): string {
  const target = TARGETS_BY_ID[assumption as LeaseLevelSensitivityTargetId];
  if (target === undefined) {
    return String(value);
  }
  if (target.unit === 'percent') {
    return formatPercent(value, 2);
  }
  if (target.unit === 'currency_psf') {
    return `$${value.toFixed(2)}/SF`;
  }
  return formatCurrency(value);
}

/**
 * The label for a metric the backend could not define for a scenario.
 *
 * `null` means the scenario was valid and fully underwritten but the metric has
 * no unique answer -- a levered IRR does not exist for the multiple-sign-change
 * cash flow a rollover year's TI/LC routinely produces. It is emphatically not
 * zero, not an error and not a skipped cell, and the table says so in text
 * rather than by colour or by an empty space.
 */
export const UNDEFINED_METRIC_LABEL = 'N/A';

/** One metric cell from the response. Formats; never recomputes. */
export function formatSensitivityMetricValue(metric: string, value: number | null): string {
  if (value === null) {
    return UNDEFINED_METRIC_LABEL;
  }
  const config = METRICS_BY_ID[metric as LeaseLevelSensitivityMetricId];
  if (config === undefined) {
    return String(value);
  }
  if (config.display === 'currency') {
    return formatCurrency(value);
  }
  if (config.display === 'multiple') {
    return formatMultiple(value);
  }
  return formatPercent(value);
}

// =============================================================================
// Shadowing -- an informational aid, never the authority
// =============================================================================

/**
 * The suites whose overrides shadow `target`, read off the rent roll the
 * analyst is looking at.
 *
 * This exists so the conflict is visible *before* a run rather than only in a
 * refusal afterwards. It reproduces no financial logic: it reads the same two
 * suite fields the backend predicate reads and reports which rows carry them.
 * The backend remains authoritative -- a run against a shadowed target is still
 * sent, and `SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE` is still what
 * refuses it.
 *
 * The two predicates differ, exactly as `_TARGETS` does: a scalar suite market
 * rent shadows Market Rent / SF alone and never Renewal Probability.
 */
export function shadowingSuites(
  target: LeaseLevelSensitivityTargetConfig,
  rentRoll: SuiteRowFormValues[],
): string[] {
  if (target.shadowRule === null) {
    return [];
  }
  const rule = target.shadowRule;
  const shadowing: string[] = [];
  for (const row of rentRoll) {
    const fullOverride = row.marketLeasingOverrideEnabled;
    const scalarRent = row.marketRentPsf.trim() !== '';
    const shadowed = rule === 'full_override_only' ? fullOverride : fullOverride || scalarRent;
    if (shadowed) {
      shadowing.push(row.suiteId.trim() === '' ? '(unnamed suite)' : row.suiteId.trim());
    }
  }
  return shadowing;
}

/** The sentence shown beside a shadowed target, or `null` when nothing shadows
 * it. Names the rule that applies, so the two are never confused. */
export function shadowingNotice(
  target: LeaseLevelSensitivityTargetConfig,
  rentRoll: SuiteRowFormValues[],
): string | null {
  const suites = shadowingSuites(target, rentRoll);
  if (suites.length === 0) {
    return null;
  }
  const single = suites.length === 1;
  const overrides = single ? 'override' : 'overrides';
  const reason =
    target.shadowRule === 'full_override_only'
      ? `full market-leasing ${overrides}`
      : `a market-rent or full market-leasing ${overrides}`;
  const verb = single ? 'uses' : 'use';
  const plural = single ? 'suite' : 'suites';
  // One template literal, no string concatenation: this module is asserted to
  // contain no binary `+` at all, so the audit that forbids browser arithmetic
  // here needs no exception for prose.
  return `Unavailable for property-wide sensitivity: ${suites.length} ${plural} ${verb} ${reason} (${suites.join(', ')}). Perturbing the property default would not reach them, so the analysis refuses the run rather than returning a table that reads as property-wide and is not.`;
}

/**
 * The option label for a target, carrying its availability in words.
 *
 * Textual, never colour alone, and never a disabled option the analyst cannot
 * reach: the backend is the authority on a shadowed target, so the choice stays
 * live and its refusal stays real.
 */
export function targetOptionLabel(
  target: LeaseLevelSensitivityTargetConfig,
  rentRoll: SuiteRowFormValues[],
): string {
  return shadowingNotice(target, rentRoll) === null
    ? target.label
    : `${target.label} — unavailable (suite overrides)`;
}

/** Why an `N/A` is not a failure. Shown beneath a table that contains one. */
export const UNDEFINED_METRIC_NOTE =
  'N/A means the scenario was fully underwritten and the metric is not uniquely defined for it — most often a levered IRR whose cash flows change sign more than once. It is not a failed scenario and not zero.';
