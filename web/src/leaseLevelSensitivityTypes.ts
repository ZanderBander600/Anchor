/**
 * D5.7 -- the Lease-Level sensitivity transport contracts.
 *
 * Its own module for the same reason `leaseLevelTypes.ts` exists: `types.ts` is
 * the hand-maintained mirror of the Quick/Detailed wire shapes, and its
 * `TwoWaySensitivityResult` narrows `metric` to the two metrics the *preset*
 * panel offers (`levered_irr | headline_dscr`). Lease-Level sensitivity serves
 * all five backend metrics, so reusing that interface would mean widening a
 * type Quick and Detailed depend on. These are separate declarations over the
 * same backend contracts instead, and nothing in Quick or Detailed is touched.
 *
 * Both result interfaces mirror `OneWaySensitivityResult` and
 * `TwoWaySensitivityResult` in `src/anchor/analysis/contracts.py` exactly. A
 * `null` in `metric_values`/`matrix` is the authoritative "this scenario was
 * fully underwritten and the metric is mathematically undefined" answer -- it is
 * never a failure, and is never reshaped here.
 */

/**
 * The eight targets `LEASE_LEVEL_SUPPORTED_ASSUMPTIONS` publishes, in the
 * backend's own declaration order.
 *
 * A closed union rather than `string`: an unsupported target cannot be spelled,
 * so the selector cannot offer one and `tsc` rejects a typo. Everything the
 * D4.6B runner defers -- downtime, TI, LC, free rent, lease term, CapEx,
 * management fee, credit loss, and every suite- or lease-specific target -- is
 * absent by construction.
 */
export type LeaseLevelSensitivityTargetId =
  | 'purchase_price'
  | 'exit_cap_rate'
  | 'ltv'
  | 'interest_rate'
  | 'market_rent_psf'
  | 'renewal_probability'
  | 'expense_growth'
  | 'recoverable_expense_ratio';

/** The five metrics `SUPPORTED_METRICS` publishes, which Lease-Level reuses
 * whole. */
export type LeaseLevelSensitivityMetricId =
  | 'levered_irr'
  | 'unlevered_irr'
  | 'equity_multiple'
  | 'headline_dscr'
  | 'exit_value';

/** The `POST /sensitivity/one-way` controls, beside the Lease-Level inputs. */
export interface LeaseLevelOneWaySensitivityControls {
  assumption: LeaseLevelSensitivityTargetId;
  /** Absolute assumption values on the **wire** scale, in the analyst's order.
   * Never a relative shock and never a delta. */
  values: number[];
  metric: LeaseLevelSensitivityMetricId;
}

/** The `POST /sensitivity` controls, beside the Lease-Level inputs. */
export interface LeaseLevelTwoWaySensitivityControls {
  row_assumption: LeaseLevelSensitivityTargetId;
  row_values: number[];
  column_assumption: LeaseLevelSensitivityTargetId;
  column_values: number[];
  metric: LeaseLevelSensitivityMetricId;
}

/** Mirrors `OneWaySensitivityResult` in `src/anchor/analysis/contracts.py`.
 * `metric_values[i]` corresponds exactly to `assumption_values[i]`. */
export interface LeaseLevelOneWaySensitivityResult {
  assumption: string;
  metric: string;
  baseline_assumption_value: number;
  baseline_metric_value: number | null;
  assumption_values: number[];
  metric_values: (number | null)[];
}

/** Mirrors `TwoWaySensitivityResult` in `src/anchor/analysis/contracts.py`.
 * `matrix[row][column]` corresponds exactly to `row_values[row]` and
 * `column_values[column]` -- row-major, and never transposed on the way in. */
export interface LeaseLevelTwoWaySensitivityResult {
  row_assumption: string;
  column_assumption: string;
  metric: string;
  baseline_row_value: number;
  baseline_column_value: number;
  baseline_metric_value: number | null;
  row_values: number[];
  column_values: number[];
  matrix: (number | null)[][];
}
