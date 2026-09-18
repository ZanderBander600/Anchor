/** Gate AM1 -- the Asset Management wire contracts.
 *
 * Mirrors `anchor.asset_management.contracts` exactly. Types only: this file
 * declares no function, and nothing in the Asset Management frontend computes a
 * financial result. Every total, variance, percentage, assessment, attention
 * item and trend point arrives already computed by the Python engine; React
 * formats and displays them.
 *
 * `null` is always "unavailable", never zero: `noi_margin` when there is no
 * revenue, `variance_pct` when the budget is zero, and `variance_points` on
 * every line that is not a percentage.
 */

/** A Managed Asset: an owned building, created once from a saved Deal. */
export interface ManagedAsset {
  id: string;
  /** Provenance, not ownership. The Deal remains an acquisition analysis. */
  source_deal_id: string;
  name: string;
  acquisition_date: string;
  property_type: string | null;
  market: string | null;
  /** The Deal's authoritative analysis fingerprint, frozen at creation. */
  acquisition_fingerprint: string;
  created_at: string;
  updated_at: string;
}

/** One month's operating figures: either the approved budget or the actuals.
 * `occupancy` is a fraction in [0, 1], matching the repository's existing
 * occupancy convention; it is presented in percent by the formatter. */
export interface OperatingFigures {
  occupancy: number;
  rental_revenue: number;
  other_income: number;
  property_taxes: number;
  insurance: number;
  utilities: number;
  repairs_and_maintenance: number;
  payroll: number;
  management_fees: number;
  other_operating_expenses: number;
  capital_expenditures: number;
  debt_service: number;
}

/** Every field of `OperatingFigures`, in statement order. The single list the
 * editor, the request body and the tests all read, so a field cannot be added
 * to the contract and silently missed by one of them. */
export const FIGURE_FIELDS = [
  'occupancy',
  'rental_revenue',
  'other_income',
  'property_taxes',
  'insurance',
  'utilities',
  'repairs_and_maintenance',
  'payroll',
  'management_fees',
  'other_operating_expenses',
  'capital_expenditures',
  'debt_service',
] as const satisfies readonly (keyof OperatingFigures)[];

export type FigureField = (typeof FIGURE_FIELDS)[number];

export interface MonthlyAssetReport {
  managed_asset_id: string;
  reporting_month: string;
  /** Frozen at creation. The editor renders it read-only thereafter. */
  budget: OperatingFigures;
  actual: OperatingFigures;
  commentary: string | null;
  created_at: string;
  updated_at: string;
}

export type FinancialLine =
  | 'occupancy'
  | 'rental_revenue'
  | 'other_income'
  | 'total_revenue'
  | 'property_taxes'
  | 'insurance'
  | 'utilities'
  | 'repairs_and_maintenance'
  | 'payroll'
  | 'management_fees'
  | 'other_operating_expenses'
  | 'total_operating_expenses'
  | 'net_operating_income'
  | 'capital_expenditures'
  | 'cash_flow_after_capex'
  | 'debt_service'
  | 'net_cash_flow';

/** `neutral` is a statement, not an absence: the line has no favorable
 * direction at all, which is why it can never be confused with `on_plan`. */
export type Assessment = 'favorable' | 'unfavorable' | 'on_plan' | 'neutral';

export type VarianceDirection =
  | 'higher_is_favorable'
  | 'lower_is_favorable'
  | 'no_direction';

export type UnitOfMeasure = 'currency' | 'percent';

export interface PeriodTotals {
  total_revenue: number;
  total_operating_expenses: number;
  net_operating_income: number;
  cash_flow_after_capex: number;
  net_cash_flow: number;
  /** `null` when total revenue is zero: unavailable, not zero or infinite. */
  noi_margin: number | null;
}

export interface LineVariance {
  line: FinancialLine;
  unit: UnitOfMeasure;
  /** Carried by the engine so the frontend never re-derives favorability from
   * a line's name -- the one place that could quietly disagree with it. */
  direction: VarianceDirection;
  budget: number;
  actual: number;
  variance: number;
  /** `null` when the budget is zero. The variance itself is always present. */
  variance_pct: number | null;
  /** Percentage points, on percent lines only. `null` on every dollar line. */
  variance_points: number | null;
  assessment: Assessment;
}

export interface AttentionItem {
  line: FinancialLine;
  /** States the direction in words, so the item never depends on colour. */
  message: string;
  assessment: Assessment;
}

export interface NoiTrendPoint {
  reporting_month: string;
  budget_net_operating_income: number;
  actual_net_operating_income: number;
}

export interface PeriodPerformance {
  budget: PeriodTotals;
  actual: PeriodTotals;
  lines: LineVariance[];
  attention: AttentionItem[];
}

export interface AssetPerformanceResult {
  managed_asset_id: string;
  reporting_month: string;
  monthly: PeriodPerformance;
  /** Carries no occupancy line: a sum of occupancy rates is not a fact. */
  year_to_date: PeriodPerformance;
  year_to_date_months: number;
  noi_trend: NoiTrendPoint[];
  commentary: string | null;
}

export interface AssetPerformanceResponse {
  managed_asset: ManagedAsset;
  result: AssetPerformanceResult;
  /** Every month that has a saved report, for the month picker. */
  reported_months: string[];
}

/** One structural refusal from the API. */
export interface AssetReportIssue {
  code: string;
  message: string;
  scope: string | null;
  field: string | null;
}

/** The typed frozen-budget conflict (HTTP 409).
 *
 * Deliberately distinct from a validation failure: the submitted budget may be
 * perfectly well-formed, and what is refused is the authority to change it. */
export interface BudgetImmutableConflict {
  code: 'budget_immutable';
  message: string;
  reporting_month: string;
  changed_fields: string[];
}

/** The period a Monthly Performance view is showing. */
export type PerformanceView = 'monthly' | 'year_to_date';
