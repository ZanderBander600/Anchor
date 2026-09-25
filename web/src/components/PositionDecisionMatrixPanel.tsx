/**
 * Phase 7 Gate P7.8B -- the `POSITION(position_id)` perspective of the Decision
 * Matrix.
 *
 * The same Strategy x Scenario grid, asking a different question: not "how does
 * the deal do", but **how does this position do** -- what it funds, what it
 * earns, where it attaches and detaches, and whether its claim was met.
 *
 * **Every figure is a backend field (P-5, Q22, DC-5).** Each cell is one metric
 * of one variant's structured result, with the backend's Delta vs Base Scenario
 * under it; Worst Case and Range are the backend's too. This component formats
 * and lays out. It subtracts, compares, sorts, ranks and averages nothing, and
 * there is no winner, no score and no colour that means good or bad.
 *
 * **Three honest cell states (DC-2, P-9).** An invalid variant shows its
 * validators' reasons. A valid variant whose Strategy does not hold this
 * position says so in the analyst's words -- it is *absent*, which is different
 * from zero and different from unavailable. A valid variant that holds it may
 * still report no *return*, with the engine's own reason, while its structural
 * metrics stand.
 */

import {
  BASE_SCENARIO_LABEL,
  BASE_STRATEGY_LABEL,
  formatDifference,
  formatMetricValue,
  formatSignedDifference,
  INVALID_VARIANT,
  NOT_AVAILABLE,
} from '../decisionMatrix';
import type { PositionDecisionCell, PositionDecisionMatrix } from '../capitalTypes';
import type { PositionDecisionMatrixState } from '../usePositionDecisionMatrix';
import { CapitalEventMatrixNote } from './CapitalEventMatrixNote';
import { StaleAnalysisNotice } from './StaleAnalysisNotice';

export interface PositionDecisionMatrixPanelProps {
  state: PositionDecisionMatrixState;
  /** The element-id namespace (`decisionIdScope`). */
  ids: string;
  isDirty: boolean;
}

/** Each message is one string literal, never joined with `+`. */
// prettier-ignore
export const POSITION_ABSENT_MESSAGE =
  'Not present in this Strategy’s Capital Structure.';

// prettier-ignore
export const POSITION_NOT_ANALYSED_MESSAGE =
  'This variant was not analysed for this position.';

// prettier-ignore
export const NO_POSITIONS_MESSAGE =
  'No capital positions yet. Add a capital structure to compare a position across strategies and scenarios.';

// prettier-ignore
export const POSITION_STALE_MESSAGE =
  'The saved underwriting, capital structure, strategies or scenarios changed after this matrix ran. Run it again to update it.';

// prettier-ignore
export const POSITION_SUBTITLE =
  'One position across every strategy and scenario. Each cell is a complete deterministic analysis; a strategy that does not hold this position says so.';

// prettier-ignore
export const RUN_POSITION_MESSAGE =
  'Choose a position and run the matrix to compare it across strategies and scenarios.';

function cellKey(cell: PositionDecisionCell): string {
  return `${cell.strategy_id}|${cell.scenario_id}`;
}

function PositionTable({ matrix, ids }: { matrix: PositionDecisionMatrix; ids: string }) {
  const cells = new Map<string, PositionDecisionCell>(matrix.cells.map((cell) => [cellKey(cell), cell]));
  const figures = new Map(matrix.strategy_figures.map((row) => [row.strategy_id, row]));
  const cross = matrix.cross_scenario_figures;

  function strategyLabel(row: { strategy_id: string; name: string; is_base: boolean }): string {
    return row.is_base ? BASE_STRATEGY_LABEL : row.name;
  }

  function scenarioLabel(scenarioId: string | null): string {
    const column = matrix.scenarios.find((entry) => entry.scenario_id === scenarioId);
    if (column === undefined) {
      return scenarioId ?? '';
    }
    return column.is_base ? BASE_SCENARIO_LABEL : column.name;
  }

  function valueCell(
    strategyId: string,
    scenarioId: string,
    spec: PositionDecisionMatrix['metrics'][number],
    metricIndex: number,
  ) {
    const cell = cells.get(`${strategyId}|${scenarioId}`);
    if (cell === undefined) {
      return null;
    }
    if (cell.status === 'invalid') {
      return metricIndex === 0 ? (
        <td
          key={scenarioId}
          rowSpan={matrix.metrics.length}
          className="decision-matrix-status"
          data-column={scenarioId}
        >
          <span className="decision-matrix-invalid">{INVALID_VARIANT}</span>
          <ul className="decision-matrix-reasons">
            {cell.issues.map((issue, index) => (
              <li key={`${issue.code}-${index}`}>{issue.message}</li>
            ))}
          </ul>
        </td>
      ) : null;
    }
    if (cell.applicability !== 'present') {
      return metricIndex === 0 ? (
        <td
          key={scenarioId}
          rowSpan={matrix.metrics.length}
          className="decision-matrix-status capital-cell-absent"
          data-column={scenarioId}
        >
          {cell.applicability === 'not_present'
            ? POSITION_ABSENT_MESSAGE
            : POSITION_NOT_ANALYSED_MESSAGE}
        </td>
      ) : null;
    }
    const figure = cell.metrics.find((entry) => entry.metric === spec.metric);
    const delta = cell.deltas.find((entry) => entry.metric === spec.metric);
    if (figure === undefined) {
      return <td key={scenarioId} data-column={scenarioId} />;
    }
    if (figure.value === null) {
      const text = figure.message ?? cell.unavailable_message ?? `${spec.label} is not available.`;
      return (
        <td key={scenarioId} className="decision-matrix-cell" data-column={scenarioId}>
          <span className="decision-matrix-na" title={text}>
            {NOT_AVAILABLE}
          </span>
          <span className="capital-result-reason">{text}</span>
        </td>
      );
    }
    let deltaLine = null;
    const column = matrix.scenarios.find((entry) => entry.scenario_id === scenarioId);
    if (column !== undefined && !column.is_base && delta !== undefined && delta.value !== null) {
      deltaLine = (
        <span className="decision-matrix-delta">
          {formatSignedDifference(spec.unit, delta.value)} vs Base
        </span>
      );
    }
    return (
      <td key={scenarioId} className="decision-matrix-cell" data-column={scenarioId}>
        <span className="decision-matrix-figure">{formatMetricValue(spec.unit, figure.value)}</span>
        {deltaLine}
      </td>
    );
  }

  function summaryCell(
    strategyId: string,
    spec: PositionDecisionMatrix['metrics'][number],
    kind: 'worst' | 'range',
  ) {
    const row = figures.get(strategyId);
    if (kind === 'worst') {
      const worst = row?.worst_cases.find((entry) => entry.metric === spec.metric);
      if (worst === undefined || worst.value === null) {
        return (
          <td key="worst" className="decision-matrix-cell decision-matrix-summary" data-column="worst">
            <span className="decision-matrix-na">{NOT_AVAILABLE}</span>
          </td>
        );
      }
      return (
        <td key="worst" className="decision-matrix-cell decision-matrix-summary" data-column="worst">
          <span className="decision-matrix-figure">{formatMetricValue(spec.unit, worst.value)}</span>
          <span className="decision-matrix-delta">{scenarioLabel(worst.scenario_id)}</span>
        </td>
      );
    }
    const range = row?.ranges.find((entry) => entry.metric === spec.metric);
    if (range === undefined || range.spread === null) {
      return (
        <td key="range" className="decision-matrix-cell decision-matrix-summary" data-column="range">
          <span className="decision-matrix-na">{NOT_AVAILABLE}</span>
        </td>
      );
    }
    return (
      <td key="range" className="decision-matrix-cell decision-matrix-summary" data-column="range">
        <span className="decision-matrix-figure">{formatDifference(spec.unit, range.spread)}</span>
      </td>
    );
  }

  return (
    <>
      {matrix.omitted_metrics.length > 0 && (
        <p className="decision-matrix-horizon" role="note">
          {matrix.omitted_metrics[0].message}
        </p>
      )}
      <div
        className="decision-matrix-scroll"
        role="region"
        aria-label="Position decision matrix table"
        tabIndex={0}
      >
        <table className="decision-matrix">
          <caption className="visually-hidden">
            {`${matrix.position_name} under each strategy and scenario, with the backend’s Delta vs Base, Worst Case and Range`}
          </caption>
          <thead>
            <tr>
              <th scope="col" className="decision-matrix-corner">
                Metric
              </th>
              {matrix.scenarios.map((column) => (
                <th
                  key={column.scenario_id}
                  scope="col"
                  className={column.is_base ? 'decision-matrix-base' : undefined}
                  data-column={column.scenario_id}
                >
                  {scenarioLabel(column.scenario_id)}
                </th>
              ))}
              {cross && (
                <th scope="col" className="decision-matrix-summary-head" data-column="worst">
                  Worst Case
                </th>
              )}
              {cross && (
                <th scope="col" className="decision-matrix-summary-head" data-column="range">
                  Range
                </th>
              )}
            </tr>
          </thead>
          {matrix.strategies.map((row) => {
            const label = strategyLabel(row);
            const groupId = `${ids}position-group-${row.strategy_id}`;
            return (
              <tbody key={row.strategy_id} className="decision-matrix-rowgroup" aria-labelledby={groupId}>
                <tr className="decision-matrix-group">
                  <th scope="rowgroup" id={groupId}>
                    <span className="decision-matrix-group-name">{label}</span>
                    {row.hold_period !== null && (
                      <span className="decision-matrix-hold">{row.hold_period}-year hold</span>
                    )}
                  </th>
                  {matrix.scenarios.map((column) => (
                    <td key={column.scenario_id} />
                  ))}
                  {cross && <td />}
                  {cross && <td />}
                </tr>
                {matrix.metrics.map((spec, metricIndex) => (
                  <tr key={spec.metric} data-metric={spec.metric}>
                    <th scope="row">
                      {spec.label}
                      <span className="visually-hidden">, {label}</span>
                    </th>
                    {matrix.scenarios.map((column) =>
                      valueCell(row.strategy_id, column.scenario_id, spec, metricIndex),
                    )}
                    {cross && summaryCell(row.strategy_id, spec, 'worst')}
                    {cross && summaryCell(row.strategy_id, spec, 'range')}
                  </tr>
                ))}
              </tbody>
            );
          })}
        </table>
      </div>
    </>
  );
}

export function PositionDecisionMatrixPanel({ state, ids, isDirty }: PositionDecisionMatrixPanelProps) {
  const selectId = `${ids}position-select`;
  const report = state.report;

  return (
    <section className="scenario-panel capital-position-matrix" aria-labelledby={`${ids}position-matrix-title`}>
      <div className="scenario-panel-header">
        <div className="scenario-panel-heading">
          <h3 id={`${ids}position-matrix-title`} className="scenario-panel-title">
            Position
          </h3>
          <p className="scenario-panel-subtitle">{POSITION_SUBTITLE}</p>
        </div>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => void state.run()}
          disabled={!state.canRun}
        >
          {state.isRunning ? 'Running…' : state.hasRun ? 'Refresh Matrix' : 'Run Position Matrix'}
        </button>
      </div>

      {state.listStatus === 'loading' && (
        <p className="scenario-muted" role="status">
          Loading positions…
        </p>
      )}

      {state.listStatus === 'error' && (
        <div className="error-banner scenario-error" role="alert">
          <span>{state.listError}</span>
          <button type="button" className="btn btn-ghost btn-xs" onClick={state.retryList}>
            Retry
          </button>
        </div>
      )}

      {state.listStatus === 'ready' && state.positions.length === 0 && (
        <p className="scenario-muted">{NO_POSITIONS_MESSAGE}</p>
      )}

      {state.positions.length > 0 && (
        <div className="field capital-position-picker">
          <label className="field-label" htmlFor={selectId}>
            Position
          </label>
          <select
            id={selectId}
            className="field-input scenario-select"
            value={state.selectedPositionId ?? ''}
            onChange={(event) => state.selectPosition(event.target.value)}
          >
            {state.positions.map((position) => (
              <option key={position.position_id} value={position.position_id}>
                {position.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {state.error !== null && (
        <div className="error-banner scenario-error" role="alert">
          <span>{state.error}</span>
        </div>
      )}

      {report === null
        ? state.positions.length > 0 && <p className="scenario-muted">{RUN_POSITION_MESSAGE}</p>
        : null}

      {report !== null && !state.isCurrent && <StaleAnalysisNotice message={POSITION_STALE_MESSAGE} />}

      {report !== null && state.isCurrent && !isDirty && (
        <CapitalEventMatrixNote
          investmentId={report.investment_id}
          token={report.matrix.matrix_fingerprint ?? ''}
        />
      )}

      {report !== null && state.isCurrent && !isDirty && (
        <PositionTable matrix={report.matrix} ids={ids} />
      )}
    </section>
  );
}
