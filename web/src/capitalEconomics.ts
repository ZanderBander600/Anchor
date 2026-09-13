/**
 * Phase 6 Gate D6.7 -- the Capital Economics vocabulary.
 *
 * The words, and the few display decisions, around the figures the Capital
 * Economics results section shows. Every figure itself is one field of the
 * engine's `AcquisitionResults`, read directly by
 * `components/CapitalEconomicsSection.tsx`. Sources & Uses totals, the owner
 * cash-flow chain, Total Equity Invested, Total Cash Returned, Total Profit, the
 * Equity Multiple, both IRRs and the Net Additional Equity Requirement are
 * computed once, in Python, and never again in the browser.
 *
 * **No arithmetic.** `capitalEconomics.test.tsx` parses this module and the
 * section and allows exactly one arithmetic expression between them: the
 * `index + 1` in `holdYearLabel`, which turns an array position into the words
 * "Year 1". It is a position, not a value. There is no sum, no difference, no
 * ratio, no `reduce` and no `Math` -- a total the engine did not report is a
 * total this surface does not show.
 */

import type { IrrStatus } from './types';

/** The statuses under which the engine reports no IRR. */
export type UnreportedIrrStatus = Exclude<IrrStatus, 'defined'>;

/**
 * Why an IRR is not reported: the frontend's one mapping from `IrrStatus` to
 * words.
 *
 * Each clause restates the backend status it names (Gate D6.3, `IrrStatus` in
 * `engine/contracts.py`) and nothing more. None offers another return or a
 * second root, and none says the deal "has no IRR": Anchor's convention
 * declines to report one, which is a different statement.
 */
export const IRR_NOT_REPORTED_REASONS: Record<UnreportedIrrStatus, string> = {
  no_nonzero_cash_flow: 'every modeled cash flow is zero',
  first_nonzero_not_negative: 'the modeled cash flows do not begin with an investment',
  no_positive_cash_flow: 'the modeled cash flows contain no positive cash flow',
  multiple_sign_changes: 'the modeled cash-flow pattern changes sign more than once',
  root_outside_search_domain: "the return falls outside Anchor's supported search domain",
  numerical_failure: 'the deterministic IRR calculation encountered a numerical issue',
};

/** "Levered IRR is not reported because ..." for a status under which the
 * engine reports no IRR, or `null` when it reported one. Keyed on the status,
 * never on the value being `null`, so the reason is always the engine's own. */
export function irrNotReportedExplanation(metric: string, status: IrrStatus): string | null {
  if (status === 'defined') {
    return null;
  }
  return `${metric} is not reported because ${IRR_NOT_REPORTED_REASONS[status]}.`;
}

/** "Year 1" for array position 0 -- the section's one arithmetic expression. */
export function holdYearLabel(index: number): string {
  return `Year ${index + 1}`;
}

/** True when every entry is exactly zero. A presentation decision -- whether a
 * column or a schedule has anything to show -- never a total. A zero here is a
 * real deterministic zero, not a missing value: the D6 series are never null. */
export function isEveryEntryZero(values: readonly number[]): boolean {
  return values.every((value) => value === 0);
}

/** The labels of the hold years whose entry is above zero, in year order. */
export function holdYearsAboveZero(values: readonly number[]): string[] {
  return values.flatMap((value, index) => (value > 0 ? [holdYearLabel(index)] : []));
}

/** The class a signed currency figure carries. A negative figure is set apart
 * by colour *in addition to* the minus sign `formatCurrency` already writes, so
 * its sign never depends on colour alone. A positive figure keeps the normal
 * treatment: the section reports economics and does not grade them. */
export function signClass(value: number): string | undefined {
  return value < 0 ? 'capital-economics-negative' : undefined;
}
