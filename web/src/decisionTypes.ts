/**
 * Phase 7 Gate P7.5 -- the typed wire contract of the Decision Matrix.
 *
 * Mirrors, field for field, `POST /investments/{id}/decision-matrix`
 * (`anchor.deals.decision_matrix.DecisionMatrixReport` over
 * `anchor.decision.comparison.DecisionMatrix`). Every number in it -- each
 * cell's metrics, each Delta vs Base Scenario, each Worst Case and each Range
 * -- is the backend's. The frontend formats these fields and derives nothing
 * from them (P-5, Q22, DC-5).
 *
 * Each cell's `results` is the existing `AcquisitionResults`, never a second
 * shape. `metric` is a plain string: the backend catalog decides which metrics
 * exist and which apply to this matrix.
 */

import type { VariantCacheStatus } from './scenarioTypes';
import type { AcquisitionResults, IrrStatus, OperatingMode } from './types';

/** A decimal rate (a difference of rates is in rate points), a ratio shown as
 * `1.85x`, or dollars. */
export type DecisionMetricUnit = 'rate' | 'multiple' | 'currency';

export type DecisionMetricDirection = 'higher_is_better' | 'lower_is_better';

/** One applicable Project metric, with the analyst's label. */
export interface DecisionMetricSpec {
  metric: string;
  label: string;
  unit: DecisionMetricUnit;
  direction: DecisionMetricDirection;
  horizon_dependent: boolean;
}

/** Why a figure is not available (DC-2). */
export type DecisionFigureReason =
  | 'invalid_variant'
  | 'irr_not_defined'
  | 'not_reported'
  | 'base_scenario_invalid'
  | 'base_scenario_not_reported'
  | 'scenario_invalid'
  | 'scenario_not_reported';

/** A cell a cross-cell figure read, and its source fingerprint. */
export interface DecisionCellSource {
  strategy_id: string;
  scenario_id: string;
  source_fingerprint: string;
}

/** One cell's value for one metric, or `null` with its reason. */
export interface DecisionMetricValue {
  metric: string;
  value: number | null;
  irr_status: IrrStatus | null;
  reason: DecisionFigureReason | null;
  message: string | null;
}

/** The backend's Delta vs Base Scenario: this cell less the same Strategy's
 * Base Scenario cell. `is_baseline` marks the Base Scenario cell itself. */
export interface DecisionDeltaVsBase {
  metric: string;
  value: number | null;
  is_baseline: boolean;
  reason: DecisionFigureReason | null;
  message: string | null;
  sources: DecisionCellSource[];
}

/** The backend's Worst Case across one Strategy's Scenarios. */
export interface DecisionWorstCase {
  metric: string;
  direction: DecisionMetricDirection;
  value: number | null;
  scenario_id: string | null;
  scenario_name: string | null;
  reason: DecisionFigureReason | null;
  message: string | null;
  unavailable_scenario_ids: string[];
  sources: DecisionCellSource[];
}

/** The backend's Range across one Strategy's Scenarios. */
export interface DecisionScenarioRange {
  metric: string;
  minimum: number | null;
  minimum_scenario_id: string | null;
  maximum: number | null;
  maximum_scenario_id: string | null;
  spread: number | null;
  reason: DecisionFigureReason | null;
  message: string | null;
  unavailable_scenario_ids: string[];
  sources: DecisionCellSource[];
}

/** One validator's reason a variant is invalid, in its own words. A visible
 * Investment's cell (P7.6) may also be refused by the Investment rules
 * (`investment`), and roots `field` at the Unit it concerns:
 * `units[<unit_id>].<field>`. */
export interface DecisionCellIssue {
  source: 'strategy' | 'scenario' | 'lease_level' | 'investment';
  code: string;
  message: string;
  field: string | null;
}

/** One Strategy x Scenario variant. `cache_status` is operational metadata,
 * carried for diagnostics and never shown as investment information. */
export interface DecisionCell {
  strategy_id: string;
  scenario_id: string;
  status: 'valid' | 'invalid';
  issues: DecisionCellIssue[];
  source_fingerprint: string | null;
  cache_status: VariantCacheStatus | null;
  hold_period: number | null;
  results: AcquisitionResults | null;
  metrics: DecisionMetricValue[];
  deltas: DecisionDeltaVsBase[];
}

export interface DecisionStrategyRow {
  strategy_id: string;
  name: string;
  is_base: boolean;
  hold_period: number | null;
}

export interface DecisionScenarioColumn {
  scenario_id: string;
  name: string;
  is_base: boolean;
}

export interface DecisionStrategyFigures {
  strategy_id: string;
  worst_cases: DecisionWorstCase[];
  ranges: DecisionScenarioRange[];
}

export interface DecisionOmittedMetric {
  metric: string;
  reason: 'different_hold_periods';
  message: string;
}

/** The whole comparison package. */
export interface DecisionMatrix {
  perspective: 'project';
  strategies: DecisionStrategyRow[];
  scenarios: DecisionScenarioColumn[];
  metrics: DecisionMetricSpec[];
  omitted_metrics: DecisionOmittedMetric[];
  hold_periods: number[];
  cross_scenario_figures: boolean;
  cells: DecisionCell[];
  strategy_figures: DecisionStrategyFigures[];
  matrix_fingerprint: string | null;
  matrix_fingerprint_reason: string | null;
}

/** `POST /investments/{id}/decision-matrix`. */
export interface DecisionMatrixReport {
  investment_id: string;
  unit_id: string;
  operating_mode: OperatingMode;
  matrix: DecisionMatrix;
}
