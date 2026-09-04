import { formatCurrency, formatMultiple, formatPercent } from './format';
import type { AcquisitionResults } from './types';
import type { UnderwriteTabId } from './underwrite';

/**
 * Sprint C Gate C3 -- the Live Case rail's metric definitions.
 *
 * Every metric here is a DIRECT READ of a field the deterministic engine
 * already returned on `AcquisitionResults`, formatted by the existing
 * `format.ts` helpers. Nothing is derived, combined, scaled, or recomputed:
 * there is no arithmetic in this module, and adding any would put a
 * financial calculation in the frontend, which the architecture forbids.
 *
 * Reading `noi_by_year[0]`, or the last element of a cumulative series, is
 * selection rather than calculation -- the engine produced every element.
 * A value the engine returned as `null` (an IRR that did not solve, a DSCR
 * with no debt service) formats to "N/A" through the existing helpers; it is
 * never substituted with a zero.
 */

export interface LiveMetric {
  id: string;
  label: string;
  /** Already formatted for display. "N/A" when the engine returned null. */
  value: string;
  caption?: string;
}

type MetricReader = (results: AcquisitionResults) => LiveMetric;

/** Reads one element of an engine-produced series. Returns `null` -- which
 * the formatters render as "N/A" -- rather than defaulting to 0, so an
 * absent series can never be displayed as a real figure. */
function at(series: (number | null)[], index: number): number | null {
  return series[index] ?? null;
}

function lastOf(series: (number | null)[]): number | null {
  return series.length === 0 ? null : (series[series.length - 1] ?? null);
}

const READERS: Record<string, MetricReader> = {
  levered_irr: (r) => ({
    id: 'levered_irr',
    label: 'Levered IRR',
    value: formatPercent(r.levered_irr),
  }),
  unlevered_irr: (r) => ({
    id: 'unlevered_irr',
    label: 'Unlevered IRR',
    value: formatPercent(r.unlevered_irr),
  }),
  equity_multiple: (r) => ({
    id: 'equity_multiple',
    label: 'Equity Multiple',
    value: formatMultiple(r.equity_multiple),
  }),
  year_1_coc: (r) => ({
    id: 'year_1_coc',
    label: 'Year 1 Levered CoC',
    value: formatPercent(at(r.levered_cash_on_cash_by_year, 0)),
  }),
  year_1_dscr: (r) => ({
    id: 'year_1_dscr',
    label: 'Year 1 DSCR',
    value: formatMultiple(at(r.dscr_by_year, 0)),
    caption: r.min_dscr === null ? undefined : `Min ${formatMultiple(r.min_dscr)}`,
  }),
  min_dscr: (r) => ({
    id: 'min_dscr',
    label: 'Minimum DSCR',
    value: formatMultiple(r.min_dscr),
  }),
  going_in_cap_rate: (r) => ({
    id: 'going_in_cap_rate',
    label: 'Going-In Cap Rate',
    value: formatPercent(r.going_in_cap_rate),
  }),
  year_1_noi: (r) => ({
    id: 'year_1_noi',
    label: 'Year 1 NOI',
    value: formatCurrency(at(r.noi_by_year, 0)),
  }),
  final_year_noi: (r) => ({
    id: 'final_year_noi',
    label: 'Final Year NOI',
    value: formatCurrency(lastOf(r.noi_by_year)),
  }),
  initial_equity: (r) => ({
    id: 'initial_equity',
    label: 'Initial Equity',
    value: formatCurrency(r.initial_equity),
  }),
  loan_amount: (r) => ({
    id: 'loan_amount',
    label: 'Loan Amount',
    value: formatCurrency(r.loan_amount),
  }),
  year_1_debt_yield: (r) => ({
    id: 'year_1_debt_yield',
    label: 'Year 1 Debt Yield',
    value: formatPercent(r.year_1_debt_yield),
  }),
  exit_noi: (r) => ({ id: 'exit_noi', label: 'Exit NOI', value: formatCurrency(r.exit_noi) }),
  exit_value: (r) => ({
    id: 'exit_value',
    label: 'Exit Value',
    value: formatCurrency(r.exit_value),
  }),
  net_sale_proceeds: (r) => ({
    id: 'net_sale_proceeds',
    label: 'Net Sale Proceeds',
    value: formatCurrency(r.net_sale_proceeds),
  }),
};

/**
 * Which metrics the rail emphasises for the tab the analyst is editing.
 *
 * A static lookup table, deliberately not a computation: each tab names four
 * already-computed figures its own assumptions move. Every list keeps a
 * return measure so the headline never disappears mid-edit.
 */
const TAB_METRICS: Record<UnderwriteTabId, string[]> = {
  acquisition: ['levered_irr', 'equity_multiple', 'initial_equity', 'going_in_cap_rate'],
  operations: ['year_1_noi', 'final_year_noi', 'levered_irr', 'year_1_coc'],
  debt: ['loan_amount', 'year_1_dscr', 'min_dscr', 'year_1_debt_yield'],
  exit: ['exit_noi', 'exit_value', 'net_sale_proceeds', 'levered_irr'],
  results: ['levered_irr', 'equity_multiple', 'year_1_coc', 'year_1_dscr'],
};

/** The base case: the four headline returns, shown on Results and used as
 * the rail's default emphasis. */
export const BASE_LIVE_METRIC_IDS = TAB_METRICS.results;

export function liveMetricsFor(tab: UnderwriteTabId, results: AcquisitionResults): LiveMetric[] {
  return TAB_METRICS[tab].map((id) => READERS[id](results));
}
