/**
 * D5.7 -- one-way Lease-Level sensitivity: the builder and its result table.
 *
 * Presentational. It holds no state, runs no request and computes nothing: the
 * configuration comes in as props, the run is the workspace's, and every figure
 * below is a field of the response formatted for display. There is no
 * arithmetic in this file.
 *
 * The analyst chooses the metric, the assumption and the candidate values
 * themselves. There is no preset, no package and no "standard" scenario set:
 * the preset endpoint is never called for Lease-Level, and no button here
 * silently populates an assumption.
 */

import { CandidateValueEditor } from './CandidateValueEditor';
import type { LadderDraft } from '../leaseLevelSensitivityLadder';
import {
  LEASE_LEVEL_SENSITIVITY_METRICS,
  LEASE_LEVEL_SENSITIVITY_TARGETS,
  UNDEFINED_METRIC_NOTE,
  formatSensitivityMetricValue,
  formatTargetValue,
  metricLabel,
  sensitivityTarget,
  shadowingNotice,
  targetLabel,
  targetOptionLabel,
} from '../leaseLevelSensitivity';
import type {
  LeaseLevelOneWaySensitivityResult,
  LeaseLevelSensitivityMetricId,
  LeaseLevelSensitivityTargetId,
} from '../leaseLevelSensitivityTypes';
import type { SuiteRowFormValues } from '../leaseLevelTypes';

export interface OneWaySensitivityConfig {
  metric: LeaseLevelSensitivityMetricId;
  assumption: LeaseLevelSensitivityTargetId;
  values: string[];
  ladder: LadderDraft;
}

export interface LeaseLevelOneWaySensitivityProps {
  config: OneWaySensitivityConfig;
  /** A React-style updater rather than a value.
   *
   * Two controls changed in the same event turn -- pressing both Fill buttons
   * of a two-way grid, say -- would otherwise both read the same stale config
   * and the second would discard the first. Taking a function makes each change
   * apply to whatever the configuration actually is at that moment. */
  onConfigChange: (update: (previous: OneWaySensitivityConfig) => OneWaySensitivityConfig) => void;
  rentRoll: SuiteRowFormValues[];
  onRun: () => void;
  isRunning: boolean;
  error: string | null;
  result: LeaseLevelOneWaySensitivityResult | null;
}

export function LeaseLevelOneWaySensitivity({
  config,
  onConfigChange,
  rentRoll,
  onRun,
  isRunning,
  error,
  result,
}: LeaseLevelOneWaySensitivityProps) {
  const target = sensitivityTarget(config.assumption);
  const notice = shadowingNotice(target, rentRoll);

  return (
    <div className="sensitivity-builder">
      <div className="sensitivity-controls">
        <label className="field sensitivity-select">
          <span className="field-label">Metric</span>
          <select
            id="lease-level-one-way-metric"
            className="field-input"
            value={config.metric}
            disabled={isRunning}
            onChange={(event) =>
              onConfigChange((previous) => ({
                ...previous,
                metric: event.target.value as LeaseLevelSensitivityMetricId,
              }))
            }
          >
            {LEASE_LEVEL_SENSITIVITY_METRICS.map((metric) => (
              <option key={metric.id} value={metric.id}>
                {metric.label}
              </option>
            ))}
          </select>
        </label>

        <label className="field sensitivity-select">
          <span className="field-label">Assumption</span>
          <select
            id="lease-level-one-way-assumption"
            className="field-input"
            value={config.assumption}
            disabled={isRunning}
            onChange={(event) =>
              onConfigChange((previous) => ({
                ...previous,
                assumption: event.target.value as LeaseLevelSensitivityTargetId,
              }))
            }
          >
            {LEASE_LEVEL_SENSITIVITY_TARGETS.map((option) => (
              <option key={option.id} value={option.id}>
                {targetOptionLabel(option, rentRoll)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {notice && (
        <p className="sensitivity-shadow-notice" role="note">
          {notice}
        </p>
      )}

      <CandidateValueEditor
        idPrefix="lease-level-one-way"
        legend={`${target.label} candidate value`}
        target={target}
        values={config.values}
        onChange={(values) => onConfigChange((previous) => ({ ...previous, values }))}
        ladder={config.ladder}
        onLadderChange={(ladder) => onConfigChange((previous) => ({ ...previous, ladder }))}
        disabled={isRunning}
      />

      <div className="sensitivity-run-row">
        <button
          type="button"
          className="btn btn-primary"
          disabled={isRunning}
          onClick={onRun}
        >
          {isRunning ? 'Running Sensitivity…' : 'Run Sensitivity'}
        </button>
      </div>

      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}

      {result && <OneWayResultTable result={result} />}
    </div>
  );
}

/**
 * The result, exactly as returned.
 *
 * `metric_values[i]` belongs to `assumption_values[i]`, and the rows are
 * rendered in that order -- nothing is sorted or reordered for presentation. A
 * `null` metric reads `N/A`, which the note below the table explains: the
 * scenario was underwritten and the metric has no unique answer. It is never
 * `0`, never blank, and never dropped.
 *
 * The baseline row is the response's own `baseline_assumption_value` /
 * `baseline_metric_value`. A candidate row is additionally marked as the
 * baseline only when its value **equals** that figure exactly; no nearest-value
 * search and no interpolation happens anywhere.
 */
function OneWayResultTable({ result }: { result: LeaseLevelOneWaySensitivityResult }) {
  const assumption = targetLabel(result.assumption);
  const metric = metricLabel(result.metric);
  const hasUndefined = result.metric_values.some((value) => value === null);

  return (
    <div className="table-scroll sensitivity-result">
      <table className="sensitivity-table sensitivity-one-way-table">
        <caption className="sensitivity-caption">
          {metric} across {assumption}
        </caption>
        <thead>
          <tr>
            <th scope="col">{assumption}</th>
            <th scope="col">{metric}</th>
          </tr>
        </thead>
        <tbody>
          <tr className="sensitivity-baseline-row">
            <th scope="row">
              {formatTargetValue(result.assumption, result.baseline_assumption_value)}
              <span className="sensitivity-baseline-tag"> Baseline</span>
            </th>
            <td className="sensitivity-cell">
              {formatSensitivityMetricValue(result.metric, result.baseline_metric_value)}
            </td>
          </tr>
          {result.assumption_values.map((value, index) => {
            const isBaseline = value === result.baseline_assumption_value;
            return (
              <tr key={index}>
                <th scope="row">
                  {formatTargetValue(result.assumption, value)}
                  {isBaseline && <span className="sensitivity-baseline-tag"> Baseline</span>}
                </th>
                <td className={isBaseline ? 'sensitivity-cell sensitivity-baseline' : 'sensitivity-cell'}>
                  {formatSensitivityMetricValue(result.metric, result.metric_values[index])}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {hasUndefined && <p className="sensitivity-note">{UNDEFINED_METRIC_NOTE}</p>}
    </div>
  );
}
