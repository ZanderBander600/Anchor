/**
 * D5.7 -- two-way Lease-Level sensitivity: the builder and the matrix.
 *
 * Presentational, like its one-way sibling. No state, no request, no
 * arithmetic. Every figure is a field of the response, formatted.
 *
 * **Orientation is the response's.** `row_assumption` and `row_values` are the
 * rows; `column_assumption` and `column_values` are the columns;
 * `matrix[row][column]` is rendered at that intersection. Nothing is transposed
 * for layout, and the axes are named on screen so a reader never has to infer
 * which is which.
 *
 * **Repeating a target on both axes is not refused here.** The shipped runner
 * already rejects `row_assumption == column_assumption` for all three modes, so
 * this surface submits the analyst's choice and shows the backend's answer
 * rather than inventing a second, drifting copy of that rule.
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
  LeaseLevelSensitivityMetricId,
  LeaseLevelSensitivityTargetId,
  LeaseLevelTwoWaySensitivityResult,
} from '../leaseLevelSensitivityTypes';
import type { SuiteRowFormValues } from '../leaseLevelTypes';

export interface TwoWaySensitivityConfig {
  metric: LeaseLevelSensitivityMetricId;
  rowAssumption: LeaseLevelSensitivityTargetId;
  rowValues: string[];
  rowLadder: LadderDraft;
  columnAssumption: LeaseLevelSensitivityTargetId;
  columnValues: string[];
  columnLadder: LadderDraft;
}

export interface LeaseLevelTwoWaySensitivityProps {
  config: TwoWaySensitivityConfig;
  /** A React-style updater, for the reason its one-way sibling documents: the
   * two axes of this grid are routinely changed in the same turn, and a
   * value-taking setter would let one axis discard the other's change. */
  onConfigChange: (update: (previous: TwoWaySensitivityConfig) => TwoWaySensitivityConfig) => void;
  rentRoll: SuiteRowFormValues[];
  onRun: () => void;
  isRunning: boolean;
  error: string | null;
  result: LeaseLevelTwoWaySensitivityResult | null;
  /** D5.8A: where `result` came from, when that is worth saying -- `null` when
   * it came from a run in this session and needs no explanation. The table is
   * the same stored response either way; this only tells the reader whether
   * they are looking at the run they just pressed or the last saved one. */
  resultNote?: string | null;
}

export function LeaseLevelTwoWaySensitivity({
  config,
  onConfigChange,
  rentRoll,
  onRun,
  isRunning,
  error,
  result,
  resultNote = null,
}: LeaseLevelTwoWaySensitivityProps) {
  const rowTarget = sensitivityTarget(config.rowAssumption);
  const columnTarget = sensitivityTarget(config.columnAssumption);
  const rowNotice = shadowingNotice(rowTarget, rentRoll);
  const columnNotice = shadowingNotice(columnTarget, rentRoll);

  return (
    <div className="sensitivity-builder">
      <div className="sensitivity-controls">
        <label className="field sensitivity-select">
          <span className="field-label">Metric</span>
          <select
            id="lease-level-two-way-metric"
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
      </div>

      <section className="sensitivity-axis" aria-label="Rows">
        <h4 className="sensitivity-axis-title">Rows</h4>
        <label className="field sensitivity-select">
          <span className="field-label">Row Assumption</span>
          <select
            id="lease-level-two-way-row-assumption"
            className="field-input"
            value={config.rowAssumption}
            disabled={isRunning}
            onChange={(event) =>
              onConfigChange((previous) => ({
                ...previous,
                rowAssumption: event.target.value as LeaseLevelSensitivityTargetId,
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
        {rowNotice && (
          <p className="sensitivity-shadow-notice" role="note">
            {rowNotice}
          </p>
        )}
        <CandidateValueEditor
          idPrefix="lease-level-two-way-row"
          legend={`Row ${rowTarget.label} candidate value`}
          target={rowTarget}
          values={config.rowValues}
          onChange={(rowValues) => onConfigChange((previous) => ({ ...previous, rowValues }))}
          ladder={config.rowLadder}
          onLadderChange={(rowLadder) => onConfigChange((previous) => ({ ...previous, rowLadder }))}
          disabled={isRunning}
        />
      </section>

      <section className="sensitivity-axis" aria-label="Columns">
        <h4 className="sensitivity-axis-title">Columns</h4>
        <label className="field sensitivity-select">
          <span className="field-label">Column Assumption</span>
          <select
            id="lease-level-two-way-column-assumption"
            className="field-input"
            value={config.columnAssumption}
            disabled={isRunning}
            onChange={(event) =>
              onConfigChange((previous) => ({
                ...previous,
                columnAssumption: event.target.value as LeaseLevelSensitivityTargetId,
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
        {columnNotice && (
          <p className="sensitivity-shadow-notice" role="note">
            {columnNotice}
          </p>
        )}
        <CandidateValueEditor
          idPrefix="lease-level-two-way-column"
          legend={`Column ${columnTarget.label} candidate value`}
          target={columnTarget}
          values={config.columnValues}
          onChange={(columnValues) => onConfigChange((previous) => ({ ...previous, columnValues }))}
          ladder={config.columnLadder}
          onLadderChange={(columnLadder) => onConfigChange((previous) => ({ ...previous, columnLadder }))}
          disabled={isRunning}
        />
      </section>

      <div className="sensitivity-run-row">
        <button type="button" className="btn btn-primary" disabled={isRunning} onClick={onRun}>
          {isRunning ? 'Running Sensitivity…' : 'Run Sensitivity'}
        </button>
      </div>

      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}

      {result && resultNote !== null && (
        <p className="field-hint sensitivity-restored-note">{resultNote}</p>
      )}
      {result && <TwoWayResultMatrix result={result} />}
    </div>
  );
}

/**
 * The authoritative matrix, in the response's own orientation.
 *
 * A real `<table>` with real header cells: the column values are `<th
 * scope="col">`, the row values are `<th scope="row">`, so the grid is
 * navigable rather than a wall of numbers. Cells are not cards; the density is
 * the point.
 *
 * A cell is highlighted as the baseline only when its row value **and** column
 * value equal `baseline_row_value` and `baseline_column_value` exactly -- the
 * two figures the response supplies for precisely this purpose. No nearest
 * value is searched for, and no baseline is placed by position.
 *
 * **D5.7A -- the corner says which way each assumption runs.** The column
 * assumption is named first with a rightward cue, the row assumption second
 * with a downward one, so the grid reads without the caption above it. Both
 * labels come from the response's own axis ids; neither is hard-coded, and the
 * order of the two lines is a statement about direction, not about the data.
 * The arrows are decorative (`aria-hidden`) and the direction is carried in
 * words as well, so a screen reader hears "Column assumption: Purchase Price"
 * rather than a bare pair of labels. Nothing about the matrix itself moves:
 * rows are still `row_values`, columns are still `column_values`, and
 * `matrix[row][column]` is still rendered where the response puts it.
 */
function TwoWayResultMatrix({ result }: { result: LeaseLevelTwoWaySensitivityResult }) {
  const rowLabel = targetLabel(result.row_assumption);
  const columnLabel = targetLabel(result.column_assumption);
  const metric = metricLabel(result.metric);
  const hasUndefined = result.matrix.some((row) => row.some((cell) => cell === null));

  return (
    <div className="sensitivity-result">
      <p className="sensitivity-baseline-line">
        Baseline: {rowLabel} {formatTargetValue(result.row_assumption, result.baseline_row_value)},{' '}
        {columnLabel} {formatTargetValue(result.column_assumption, result.baseline_column_value)},{' '}
        {metric} {formatSensitivityMetricValue(result.metric, result.baseline_metric_value)}
      </p>
      <div className="table-scroll">
        <table className="sensitivity-table">
          <caption className="sensitivity-caption">
            {metric}: {rowLabel} (rows) × {columnLabel} (columns)
          </caption>
          <thead>
            <tr>
              <th className="sensitivity-corner sensitivity-axis-corner" scope="col">
                <span className="sensitivity-axis-line">
                  <span className="visually-hidden">Column assumption: </span>
                  {columnLabel}
                  <span className="sensitivity-axis-arrow" aria-hidden="true">
                    {' →'}
                  </span>
                </span>
                <span className="sensitivity-axis-line">
                  <span className="visually-hidden">Row assumption: </span>
                  {rowLabel}
                  <span className="sensitivity-axis-arrow" aria-hidden="true">
                    {' ↓'}
                  </span>
                </span>
              </th>
              {result.column_values.map((columnValue, columnIndex) => (
                <th key={columnIndex} scope="col">
                  {formatTargetValue(result.column_assumption, columnValue)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.row_values.map((rowValue, rowIndex) => (
              <tr key={rowIndex}>
                <th scope="row">{formatTargetValue(result.row_assumption, rowValue)}</th>
                {result.matrix[rowIndex].map((cell, columnIndex) => {
                  const isBaseline =
                    rowValue === result.baseline_row_value &&
                    result.column_values[columnIndex] === result.baseline_column_value;
                  return (
                    <td
                      key={columnIndex}
                      className={
                        isBaseline ? 'sensitivity-cell sensitivity-baseline' : 'sensitivity-cell'
                      }
                    >
                      {formatSensitivityMetricValue(result.metric, cell)}
                      {isBaseline && <span className="sensitivity-baseline-tag"> (Base)</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hasUndefined && <p className="sensitivity-note">{UNDEFINED_METRIC_NOTE}</p>}
    </div>
  );
}
