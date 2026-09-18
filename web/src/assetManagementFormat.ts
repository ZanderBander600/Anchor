/** Gate AM1 -- presentation helpers for Asset Management.
 *
 * Formatting and labelling only. Nothing here derives a financial result: it
 * never adds, subtracts, or computes a variance, a percentage, a total or an
 * assessment. Every figure it renders arrives already computed by
 * `anchor.asset_management.performance`.
 *
 * The one arithmetic operations present are scale conversions for display --
 * multiplying a fraction by 100 to print a percent, and dividing by a maximum
 * to place a point on a chart axis. Neither produces a financial result; both
 * are the same conversion `format.ts` already performs for every other percent
 * in the product.
 */

import type {
  Assessment,
  FinancialLine,
  LineVariance,
  PerformanceView,
} from './assetManagementTypes';

/** Every reportable line's label, matching `performance.py`'s `LINE_LABELS`
 * exactly so one line has one name in both languages. */
export const LINE_LABELS: Record<FinancialLine, string> = {
  occupancy: 'Occupancy',
  rental_revenue: 'Rental Revenue',
  other_income: 'Other Income',
  total_revenue: 'Total Revenue',
  property_taxes: 'Property Taxes',
  insurance: 'Insurance',
  utilities: 'Utilities',
  repairs_and_maintenance: 'Repairs and Maintenance',
  payroll: 'Payroll',
  management_fees: 'Management Fees',
  other_operating_expenses: 'Other Operating Expenses',
  total_operating_expenses: 'Total Operating Expenses',
  net_operating_income: 'Net Operating Income',
  capital_expenditures: 'Capital Expenditures',
  cash_flow_after_capex: 'Cash Flow After CapEx',
  debt_service: 'Debt Service',
  net_cash_flow: 'Net Cash Flow',
};

/** The editor's label for each authored input field. */
export const FIELD_LABELS: Record<string, string> = {
  occupancy: 'Occupancy',
  rental_revenue: 'Rental Revenue',
  other_income: 'Other Income',
  property_taxes: 'Property Taxes',
  insurance: 'Insurance',
  utilities: 'Utilities',
  repairs_and_maintenance: 'Repairs and Maintenance',
  payroll: 'Payroll',
  management_fees: 'Management Fees',
  other_operating_expenses: 'Other Operating Expenses',
  capital_expenditures: 'Capital Expenditures',
  debt_service: 'Debt Service',
};

/** The lines that read as subtotals, shown with emphasis. Presentation only:
 * the engine already decided what each line is. */
export const EMPHASIZED_LINES: ReadonlySet<FinancialLine> = new Set<FinancialLine>([
  'total_revenue',
  'total_operating_expenses',
  'net_operating_income',
  'net_cash_flow',
]);

/** The word shown in the Assessment column. Words, never colour alone. */
export const ASSESSMENT_LABELS: Record<Assessment, string> = {
  favorable: 'Favorable',
  unfavorable: 'Unfavorable',
  on_plan: 'On Plan',
  neutral: 'Neutral',
};

/** `null` prints as an em dash, not as 0 or N/A: the value is unavailable, and
 * a zero would assert something the engine deliberately refused to assert. */
export const UNAVAILABLE = '—';

export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return UNAVAILABLE;
  }
  const magnitude = Math.abs(value).toLocaleString('en-US', { maximumFractionDigits: 0 });
  // Accounting parentheses for a negative figure, matching the concept and the
  // convention analysts read statements in.
  return value < 0 ? `($${magnitude})` : `$${magnitude}`;
}

/** A fraction as a percent, e.g. 0.925 -> "92.5%". */
export function formatRate(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined) {
    return UNAVAILABLE;
  }
  return `${(value * 100).toFixed(decimals)}%`;
}

/** A variance percentage, in accounting parentheses when negative. */
export function formatVariancePct(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return UNAVAILABLE;
  }
  const magnitude = `${Math.abs(value * 100).toFixed(1)}%`;
  return value < 0 ? `(${magnitude})` : magnitude;
}

/** Percentage points, e.g. -2.5 -> "(2.5) pts". */
export function formatPoints(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return UNAVAILABLE;
  }
  const magnitude = `${Math.abs(value).toFixed(1)} pts`;
  return value < 0 ? `(${magnitude})` : magnitude;
}

/** One line's budget or actual figure, on whichever scale its unit says. */
export function formatFigure(line: LineVariance, value: number): string {
  return line.unit === 'percent' ? formatRate(value) : formatMoney(value);
}

/** One line's variance, on whichever scale its unit says. A percent line
 * reports percentage points; a currency line reports dollars. */
export function formatVariance(line: LineVariance): string {
  return line.unit === 'percent' ? formatPoints(line.variance_points) : formatMoney(line.variance);
}

/** `2027-03-01` -> `March 2027`. Parsed as a plain calendar month, never
 * through `new Date(string)`, which would apply the viewer's timezone and could
 * render March as February for anyone west of UTC. */
export function formatMonth(iso: string): string {
  const [year, month] = iso.split('-');
  const names = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
  ];
  const index = Number(month) - 1;
  return index >= 0 && index < 12 ? `${names[index]} ${year}` : iso;
}

/** `2027-03-01` -> `Mar 2027`, for a chart axis. */
export function formatMonthShort(iso: string): string {
  const full = formatMonth(iso);
  const [name, year] = full.split(' ');
  return year === undefined ? iso : `${name.slice(0, 3)} ${year}`;
}

/** `2026-10-01` -> `Oct 2026`, for the asset's acquisition date. */
export function formatAcquiredOn(iso: string): string {
  return formatMonthShort(iso);
}

export function viewLabel(view: PerformanceView): string {
  return view === 'monthly' ? 'Monthly' : 'Year to Date';
}

/** The class that carries an assessment's colour. Always paired with the word
 * in `ASSESSMENT_LABELS`, so colour is reinforcement and never the sole
 * carrier of the meaning. */
export function assessmentClass(assessment: Assessment): string {
  return `am-assessment am-assessment-${assessment.replace('_', '-')}`;
}
