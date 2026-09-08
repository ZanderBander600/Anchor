/**
 * D5.6 -- presentation helpers for the Lease-Level result surfaces.
 *
 * Its own module rather than an addition to `format.ts`, which is pinned
 * byte-identical by the backend's G37 guardrail and shared with Quick and
 * Detailed. Everything here formats; nothing here computes. There is no
 * arithmetic in this file at all, which is what lets the G-M7 audit cover it
 * without an exception.
 *
 * `formatCurrency`, `formatPercent` and `formatMultiple` are reused unchanged
 * from `format.ts` -- including their established `N/A` for `null`, which is
 * exactly the treatment an undefined IRR needs.
 */

/** Month names indexed by the two-character month of an ISO date.
 *
 * A lookup rather than `Number(mm) - 1`: no arithmetic, no `Date`, and so no
 * timezone in which `2027-01-01` can become December. The wire string is read
 * literally. */
const MONTH_NAMES: Record<string, string> = {
  '01': 'Jan',
  '02': 'Feb',
  '03': 'Mar',
  '04': 'Apr',
  '05': 'May',
  '06': 'Jun',
  '07': 'Jul',
  '08': 'Aug',
  '09': 'Sep',
  '10': 'Oct',
  '11': 'Nov',
  '12': 'Dec',
};

/**
 * `2027-01-01` -> `Jan 2027`.
 *
 * An analyst reads a month, not a period index. The index remains on the
 * contract and is still available for support questions; it is simply not what
 * a column header should say.
 *
 * Returns the raw string unchanged if it is not an ISO date, so a contract
 * change surfaces as a visibly odd label rather than as a plausible wrong one.
 */
export function formatMonthLabel(monthStart: string): string {
  const parsed = /^(\d{4})-(\d{2})-\d{2}$/.exec(monthStart);
  if (parsed === null) {
    return monthStart;
  }
  const [, year, month] = parsed;
  const name = MONTH_NAMES[month];
  return name === undefined ? monthStart : `${name} ${year}`;
}

/** Square feet with thousands separators and no decimals. */
export function formatSquareFeet(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return 'N/A';
  }
  return `${value.toLocaleString('en-US', { maximumFractionDigits: 0 })} SF`;
}

/**
 * A coverage ratio, as `1.45x`.
 *
 * Distinct from `formatMultiple` only in intent -- both render `x` -- but named
 * for what it is so a DSCR column never reads as an equity multiple.
 */
export function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return 'N/A';
  }
  return `${value.toFixed(2)}x`;
}

/**
 * The label for an IRR the engine could not define.
 *
 * `levered_irr` is `null` when the levered cash flows change sign more than
 * once -- typically a mid-hold leasing-capital year. That is a real, defensible
 * outcome of a real deal, not a failure and emphatically not zero: showing
 * `0.0%` would turn a healthy deal into a broken-looking one, and showing an
 * error would say Anchor could not answer when in fact it did.
 */
export const UNDEFINED_IRR_LABEL = 'Not uniquely defined';
