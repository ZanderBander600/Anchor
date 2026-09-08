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
 * **D5.7A -- the baseline is stated once, above the table.** It is the
 * response's own `baseline_assumption_value` / `baseline_metric_value`, read
 * and formatted; nothing here re-runs the analysis, infers the baseline from a
 * candidate or averages anything. The standalone baseline *row* is gone,
 * because an analyst who includes the baseline in the candidate series -- the
 * usual case -- was reading the same figure twice.
 *
 * The candidate series itself is untouched: no value is deduplicated, dropped,
 * reordered or synthesised, and the candidate that equals the baseline stays in
 * the table like any other. It is merely marked `Base`, and only when it
 * **equals** the baseline assumption value exactly. There is no nearest-value
 * search and no interpolation, so a series that omits the baseline gets the
 * context line and no highlighted row at all.
 */
function OneWayResultTable({ result }: { result: LeaseLevelOneWaySensitivityResult }) {
  const assumption = targetLabel(result.assumption);
  const metric = metricLabel(result.metric);
  const hasUndefined = result.metric_values.some((value) => value === null);

  return (
    <div className="sensitivity-result">
      <p className="sensitivity-baseline-line">
        Baseline: {assumption}{' '}
        {formatTargetValue(result.assumption, result.baseline_assumption_value)} · {metric}{' '}
        {formatSensitivityMetricValue(result.metric, result.baseline_metric_value)}
      </p>
      <div className="table-scroll">
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
            {result.assumption_values.map((value, index) => {
              const isBaseline = value === result.baseline_assumption_value;
              return (
                <tr key={index}>
                  <th scope="row">{formatTargetValue(result.assumption, value)}</th>
                  <td
                    className={
                      isBaseline ? 'sensitivity-cell sensitivity-baseline' : 'sensitivity-cell'
                    }
                  >
                    {formatSensitivityMetricValue(result.metric, result.metric_values[index])}
                    {isBaseline && <span className="sensitivity-baseline-tag"> Base</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {hasUndefined && <p className="sensitivity-note">{UNDEFINED_METRIC_NOTE}</p>}
    </div>
  );
}
