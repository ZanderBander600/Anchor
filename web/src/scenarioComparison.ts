/**
 * Phase 7 Gate P7.3 -- the Scenario Comparison, v0.
 *
 * One implicit row, the current underwriting. One Base column, which is the
 * saved Deal's ordinary analysis. One column for each saved Scenario, from the
 * P7.2 Scenario analysis. There is no Strategy here: P7.4 owns Strategy, and
 * until then the single row is simply the underwriting as saved.
 *
 * **Every figure is one backend field.** A cell shows exactly one field of the
 * `AcquisitionResults` the backend returned for that column, formatted for
 * display. Nothing is summed, differenced, ranked or averaged. There is no
 * delta against Base, no worst or best case, no range and no expected value:
 * those are cross-cell figures, and Q22 / DC-5 reserve them for deterministic
 * backend code (P7.5).
 *
 * **Honest cells (DC-2).** A figure the engine did not report is `N/A` with the
 * engine's reason where it gives one. For an IRR that reason is its `IrrStatus`,
 * worded in `capitalEconomics.ts`, the one frontend home of that vocabulary. It
 * is never shown as zero, and never left as a blank.
 */

import { irrNotReportedExplanation } from './capitalEconomics';
import { formatCurrency, formatMultiple, formatPercent } from './format';
import type { LeaseLevelAcquisitionResults } from './leaseLevelTypes';
import { assertNeverMode } from './operatingMode';
import type { ScenarioVariantAnalysis, VariantCacheStatus } from './scenarioTypes';
import type { AcquisitionResults, DetailedAcquisitionResults, IrrStatus } from './types';

/** What one metric cell shows: the formatted figure, and why it is not
 * reported when it is not. */
export interface ComparisonFigure {
  text: string;
  /** Present exactly when `text` is `N/A`. */
  reason: string | null;
}

export interface ComparisonMetric {
  id: string;
  label: string;
  figure: (results: AcquisitionResults) => ComparisonFigure;
}

const NOT_REPORTED = 'N/A';

function reported(text: string): ComparisonFigure {
  return { text, reason: null };
}

function irrFigure(label: string, value: number | null, status: IrrStatus): ComparisonFigure {
  const reason = irrNotReportedExplanation(label, status);
  if (reason !== null) {
    return { text: NOT_REPORTED, reason };
  }
  if (value === null) {
    return { text: NOT_REPORTED, reason: `${label} is not reported for this result.` };
  }
  return reported(formatPercent(value));
}

/** The v0 headline metrics, in display order. Each is a scalar every operating
 * mode reports on the same `AcquisitionResults` contract. */
export const COMPARISON_METRICS: readonly ComparisonMetric[] = [
  {
    id: 'levered_irr',
    label: 'Levered IRR',
    figure: (results) => irrFigure('Levered IRR', results.levered_irr, results.levered_irr_status),
  },
  {
    id: 'unlevered_irr',
    label: 'Unlevered IRR',
    figure: (results) =>
      irrFigure('Unlevered IRR', results.unlevered_irr, results.unlevered_irr_status),
  },
  {
    id: 'equity_multiple',
    label: 'Equity Multiple',
    figure: (results) =>
      results.equity_multiple === null
        ? { text: NOT_REPORTED, reason: 'The Equity Multiple is not reported for this result.' }
        : reported(formatMultiple(results.equity_multiple)),
  },
  {
    id: 'total_profit',
    label: 'Total Profit',
    figure: (results) => reported(formatCurrency(results.total_profit)),
  },
  {
    id: 'exit_value',
    label: 'Exit Value',
    figure: (results) => reported(formatCurrency(results.exit_value)),
  },
  {
    id: 'min_dscr',
    label: 'Minimum DSCR',
    figure: (results) =>
      results.min_dscr === null
        ? { text: NOT_REPORTED, reason: 'No hold year reports a DSCR for this result.' }
        : reported(formatMultiple(results.min_dscr)),
  },
];

/** One column's state. Each column settles on its own, so one failure never
 * blanks another column. */
export type ComparisonCell =
  | { status: 'loading' }
  | { status: 'result'; results: AcquisitionResults; cacheStatus: VariantCacheStatus | null }
  /** The backend refused the variant (a 422): the Scenario does not resolve to
   * valid underwriting over the saved Deal. The reasons are the validators'
   * own words. */
  | { status: 'invalid'; reasons: string[] }
  /** The request itself failed: the API was unreachable, or the analysis could
   * not be completed. */
  | { status: 'error'; message: string };

/** A comparison run: one Base cell, and one cell per Scenario id. `token`
 * identifies the saved underwriting and the Scenario economics it ran against;
 * a comparison whose token no longer matches is out of date. */
export interface ScenarioComparison {
  token: string;
  base: ComparisonCell;
  scenarios: Record<string, ComparisonCell>;
}

/** The `AcquisitionResults` inside a Scenario analysis. Quick returns the
 * contract itself; Detailed and Lease-Level return it inside their envelope.
 * This only selects a field; it computes nothing. */
export function acquisitionResultsOf(analysis: ScenarioVariantAnalysis): AcquisitionResults {
  switch (analysis.operating_mode) {
    case 'quick':
      return analysis.results as AcquisitionResults;
    case 'detailed':
      return (analysis.results as DetailedAcquisitionResults).results;
    case 'lease_level':
      return (analysis.results as LeaseLevelAcquisitionResults).results;
    default:
      return assertNeverMode(analysis.operating_mode);
  }
}

/** Said when the saved underwriting or the Scenarios changed after a run.
 * One literal, never joined with `+`: see `StaleAnalysisNotice.tsx`. */
// prettier-ignore
export const STALE_COMPARISON_MESSAGE =
  'The saved underwriting or the scenarios changed after this comparison ran. Refresh Comparison to update it.';

/** Said while the base underwriting has unsaved edits. */
// prettier-ignore
export const DIRTY_COMPARISON_MESSAGE =
  'Base underwriting has unsaved changes. Save the deal, then Refresh Comparison.';

/** Why Run / Refresh Comparison cannot be pressed while the deal is dirty. */
export const SAVE_BEFORE_SCENARIOS_MESSAGE =
  'Save base underwriting changes before editing or running scenarios.';
