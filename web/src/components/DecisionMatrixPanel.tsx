/**
 * Phase 7 Gate P7.5 -- the Strategy x Scenario Decision Matrix.
 *
 * Each Strategy is a row group, Base Strategy first; each metric is a row
 * inside it; each Scenario is a column, Base first. When a saved Scenario
 * exists, two more columns give each Strategy's Worst Case and Range across
 * its Scenarios. Every cell is one complete deterministic analysis of one
 * Analysis Variant -- for a visible Investment (P7.6), every Unit's analysis,
 * consolidated by the backend.
 *
 * **Every figure is a backend field (P-5, Q22, DC-5).** A cell shows one
 * metric of its variant's Project results, and under it the backend's Delta vs
 * Base Scenario for the same Strategy. Worst Case and Range are the backend's
 * too, with the Scenarios it named. Metric labels are the backend catalog's
 * (a visible Investment's DSCR is its Minimum Aggregate DSCR). This component
 * formats and lays out; it subtracts, compares, sorts, ranks and averages
 * nothing. There is no winner, no score and no colour that means good or bad.
 *
 * **Honest cells (DC-2).** `N/A` carries its reason in a note under the table,
 * which the cell points to and its tooltip repeats. An invalid variant shows
 * `Invalid variant` with the validators' reasons in its own cell -- each naming
 * the Unit it concerns -- and every other cell stands. When Strategies hold for
 * different periods the backend omits Exit Value and Minimum DSCR, and one note
 * says why.
 *
 * **Current or out of date, never mixed (DC-7).** The table is shown only
 * while the package matches the saved state on screen; otherwise the
 * out-of-date notice replaces it until Refresh Matrix.
 *
 * The table scrolls inside its own region and never widens the page. Row and
 * group headers stay pinned while it scrolls. `data-cache-status` carries the
 * variant cache status for diagnostics and is never shown.
 */

import {
  BASE_SCENARIO_LABEL,
  BASE_STRATEGY_LABEL,
  DEAL_MATRIX_COPY,
  EMPTY_MATRIX_MESSAGE,
  formatDifference,
  formatMetricValue,
  formatSignedDifference,
  INVALID_VARIANT,
  issueUnitId,
  NOT_AVAILABLE,
  notAvailableText,
} from '../decisionMatrix';
import type { DecisionMatrixCopy } from '../decisionMatrix';
import type {
  DecisionCell,
  DecisionCellIssue,
  DecisionMatrix,
  DecisionMetricSpec,
  DecisionScenarioColumn,
  DecisionStrategyFigures,
  DecisionStrategyRow,
} from '../decisionTypes';
import { investmentIssueLead, withUnitNames } from '../investmentCatalog';
import type { InvestmentScenario } from '../scenarioTypes';
import type { InvestmentStrategy } from '../strategyTypes';
import type { DecisionMatrixState } from '../useDecisionMatrix';
import { StaleAnalysisNotice } from './StaleAnalysisNotice';

export interface DecisionMatrixPanelProps {
  matrix: DecisionMatrixState;
  dealId: string | null;
  /** P7.6: the visible Investment whose matrix this is, or `null` for a Deal. */
  investmentId?: string | null;
  /** The surface's words; a Deal's by default. */
  copy?: DecisionMatrixCopy;
  /** P7.6: each Unit's id, mapped to the name an analyst knows it by, so an
   * invalid variant's reasons name their Unit. */
  unitNames?: Readonly<Record<string, string>>;
  isDirty: boolean;
  /** The saved Strategies and Scenarios on screen, for their current labels. */
  strategies: InvestmentStrategy[];
  scenarios: InvestmentScenario[];
  isLoading: boolean;
  loadError: string | null;
  retryLoad: () => void;
}

const BLOCKED_REASON_ID = 'decision-matrix-blocked-reason';
const NO_NAMES: Readonly<Record<string, string>> = {};

interface Labels {
  strategy: (row: DecisionStrategyRow) => string;
  scenario: (scenarioId: string | null) => string;
}

/** One note under the table. Identical reasons share one note. */
interface Notes {
  idFor: (text: string) => string;
  list: { id: string; text: string }[];
}

function collectNotes(): Notes {
  const byText = new Map<string, string>();
  const list: { id: string; text: string }[] = [];
  return {
    idFor(text) {
      const existing = byText.get(text);
      if (existing !== undefined) {
        return existing;
      }
      const id = `decision-note-${list.length}`;
      byText.set(text, id);
      list.push({ id, text });
      return id;
    },
    list,
  };
}

function NotAvailable({ text, noteId }: { text: string; noteId: string }) {
  return (
    <span className="decision-matrix-na" title={text} aria-describedby={noteId}>
      {NOT_AVAILABLE}
    </span>
  );
}

/** One validator's reason, with the Unit it concerns named first and the
 * analyst's reading of an Investment rule before the backend's own words. */
function CellReason({ issue, names }: { issue: DecisionCellIssue; names: Readonly<Record<string, string>> }) {
  const unitId = issueUnitId(issue.field);
  const unit = unitId === null ? undefined : (names[unitId] ?? unitId);
  const lead = investmentIssueLead(issue.code);
  return (
    <li>
      {unit !== undefined && <span className="decision-matrix-reason-unit">{`${unit}: `}</span>}
      {lead !== null && <span className="decision-matrix-reason-lead">{`${lead} `}</span>}
      {withUnitNames(issue.message, names)}
    </li>
  );
}

interface TableProps {
  matrix: DecisionMatrix;
  labels: Labels;
  caption: string;
  names: Readonly<Record<string, string>>;
}

function DecisionMatrixTable({ matrix, labels, caption, names }: TableProps) {
  const notes = collectNotes();
  const cells = new Map<string, DecisionCell>(
    matrix.cells.map((cell) => [`${cell.strategy_id}|${cell.scenario_id}`, cell]),
  );
  const figures = new Map<string, DecisionStrategyFigures>(
    matrix.strategy_figures.map((row) => [row.strategy_id, row]),
  );
  const cross = matrix.cross_scenario_figures;

  function valueCell(
    row: DecisionStrategyRow,
    column: DecisionScenarioColumn,
    spec: DecisionMetricSpec,
    metricIndex: number,
  ) {
    const cell = cells.get(`${row.strategy_id}|${column.scenario_id}`);
    const context = `${labels.strategy(row)} · ${labels.scenario(column.scenario_id)}`;
    if (cell === undefined) {
      return null;
    }
    if (cell.status === 'invalid') {
      return metricIndex === 0 ? (
        <td
          key={column.scenario_id}
          rowSpan={matrix.metrics.length}
          className="decision-matrix-status"
          data-column={column.scenario_id}
        >
          <span className="decision-matrix-invalid">{INVALID_VARIANT}</span>
          <ul className="decision-matrix-reasons">
            {cell.issues.map((issue, index) => (
              <CellReason key={`${issue.code}-${index}`} issue={issue} names={names} />
            ))}
          </ul>
        </td>
      ) : null;
    }
    const figure = cell.metrics.find((entry) => entry.metric === spec.metric);
    const delta = cell.deltas.find((entry) => entry.metric === spec.metric);
    if (figure === undefined) {
      return <td key={column.scenario_id} data-column={column.scenario_id} />;
    }
    if (figure.value === null) {
      const text = notAvailableText(spec, figure);
      return (
        <td key={column.scenario_id} className="decision-matrix-cell" data-column={column.scenario_id}>
          <NotAvailable text={text} noteId={notes.idFor(`${context}: ${text}`)} />
        </td>
      );
    }
    let deltaLine = null;
    if (!column.is_base && delta !== undefined) {
      if (delta.value !== null) {
        deltaLine = (
          <span className="decision-matrix-delta">
            {formatSignedDifference(spec.unit, delta.value)} vs Base
          </span>
        );
      } else {
        const text = delta.message ?? 'No Delta vs Base.';
        deltaLine = (
          <span className="decision-matrix-delta decision-matrix-na" title={text} aria-describedby={notes.idFor(`${context}: ${text}`)}>
            {NOT_AVAILABLE} vs Base
          </span>
        );
      }
    }
    return (
      <td
        key={column.scenario_id}
        className="decision-matrix-cell"
        data-column={column.scenario_id}
        data-cache-status={cell.cache_status ?? undefined}
      >
        <span className="decision-matrix-figure">{formatMetricValue(spec.unit, figure.value)}</span>
        {deltaLine}
      </td>
    );
  }

  function worstCell(row: DecisionStrategyRow, spec: DecisionMetricSpec) {
    const worst = figures.get(row.strategy_id)?.worst_cases.find((entry) => entry.metric === spec.metric);
    if (worst === undefined) {
      return <td key="worst" data-column="worst" />;
    }
    if (worst.value === null) {
      const text = worst.message ?? 'Not available.';
      return (
        <td key="worst" className="decision-matrix-cell decision-matrix-summary" data-column="worst">
          <NotAvailable text={text} noteId={notes.idFor(`${labels.strategy(row)} · Worst Case / Range: ${text}`)} />
        </td>
      );
    }
    return (
      <td key="worst" className="decision-matrix-cell decision-matrix-summary" data-column="worst">
        <span className="decision-matrix-figure">{formatMetricValue(spec.unit, worst.value)}</span>
        <span className="decision-matrix-delta">{labels.scenario(worst.scenario_id)}</span>
      </td>
    );
  }

  function rangeCell(row: DecisionStrategyRow, spec: DecisionMetricSpec) {
    const range = figures.get(row.strategy_id)?.ranges.find((entry) => entry.metric === spec.metric);
    if (range === undefined) {
      return <td key="range" data-column="range" />;
    }
    if (range.spread === null) {
      const text = range.message ?? 'Not available.';
      return (
        <td key="range" className="decision-matrix-cell decision-matrix-summary" data-column="range">
          <NotAvailable text={text} noteId={notes.idFor(`${labels.strategy(row)} · Worst Case / Range: ${text}`)} />
        </td>
      );
    }
    return (
      <td key="range" className="decision-matrix-cell decision-matrix-summary" data-column="range">
        <span className="decision-matrix-figure">{formatDifference(spec.unit, range.spread)}</span>
        <span className="decision-matrix-delta">
          Low: {labels.scenario(range.minimum_scenario_id)} · High: {labels.scenario(range.maximum_scenario_id)}
        </span>
      </td>
    );
  }

  const body = matrix.strategies.map((row) => {
    const label = labels.strategy(row);
    const groupId = `decision-group-${row.strategy_id}`;
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
            {matrix.scenarios.map((column) => valueCell(row, column, spec, metricIndex))}
            {cross && worstCell(row, spec)}
            {cross && rangeCell(row, spec)}
          </tr>
        ))}
      </tbody>
    );
  });

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
        aria-label="Decision matrix table"
        tabIndex={0}
      >
        <table className="decision-matrix">
          <caption className="visually-hidden">{caption}</caption>
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
                  {labels.scenario(column.scenario_id)}
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
          {body}
        </table>
      </div>
      <p className="decision-matrix-legend">
        Delta vs Base compares each scenario with the same strategy&apos;s Base scenario; rate
        differences are in percentage points.
        {cross &&
          ' Worst Case is the least favorable value across the strategy’s scenarios (the highest Total Equity Invested). Range is the highest less the lowest.'}
      </p>
      {notes.list.length > 0 && (
        <ul className="decision-matrix-notes" aria-label="Figures not available">
          {notes.list.map((note) => (
            <li key={note.id} id={note.id}>
              <span className="decision-matrix-note-marker">{NOT_AVAILABLE}</span> {note.text}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function DecisionMatrixPanel({
  matrix,
  dealId,
  investmentId = null,
  copy = DEAL_MATRIX_COPY,
  unitNames = NO_NAMES,
  isDirty,
  strategies,
  scenarios,
  isLoading,
  loadError,
  retryLoad,
}: DecisionMatrixPanelProps) {
  const report = matrix.report;
  const scopeId = investmentId ?? dealId;
  const showTable = report !== null && matrix.isCurrent;
  const blocked = scopeId !== null && matrix.hasComparison && isDirty;

  const labels: Labels = {
    strategy: (row) =>
      row.is_base
        ? BASE_STRATEGY_LABEL
        : (strategies.find((record) => record.strategy.strategy_id === row.strategy_id)?.strategy.name ??
          row.name),
    scenario: (scenarioId) => {
      const column = report?.matrix.scenarios.find((entry) => entry.scenario_id === scenarioId);
      if (column === undefined) {
        return scenarioId ?? '';
      }
      return column.is_base
        ? BASE_SCENARIO_LABEL
        : (scenarios.find((record) => record.scenario.scenario_id === scenarioId)?.scenario.name ??
            column.name);
    },
  };

  return (
    <section className="scenario-panel decision-matrix-panel" aria-labelledby="decision-matrix-title">
      <div className="scenario-panel-header">
        <div className="scenario-panel-heading">
          <h3 id="decision-matrix-title" className="scenario-panel-title">
            Decision Matrix
          </h3>
          <p className="scenario-panel-subtitle">{copy.subtitle}</p>
        </div>
        {scopeId !== null && matrix.hasComparison && (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => void matrix.run()}
            disabled={!matrix.canRun}
            aria-describedby={blocked ? BLOCKED_REASON_ID : undefined}
          >
            {matrix.isRunning ? 'Running…' : matrix.hasRun ? 'Refresh Matrix' : 'Run Decision Matrix'}
          </button>
        )}
      </div>

      {scopeId === null && <p className="scenario-blocked">{copy.unsaved}</p>}

      {isLoading && (
        <p className="scenario-muted" role="status">
          Loading strategies and scenarios…
        </p>
      )}

      {loadError !== null && (
        <div className="error-banner scenario-error" role="alert">
          <span>{loadError}</span>
          <button type="button" className="btn btn-ghost btn-xs" onClick={retryLoad}>
            Retry
          </button>
        </div>
      )}

      {scopeId !== null && !isLoading && loadError === null && !matrix.hasComparison && (
        <p className="decision-matrix-empty">{EMPTY_MATRIX_MESSAGE}</p>
      )}

      {blocked && (
        <p id={BLOCKED_REASON_ID} className="scenario-blocked" role="status">
          {copy.blocked}
        </p>
      )}

      {scopeId !== null && matrix.hasComparison && (
        <>
          {!matrix.hasRun && !isLoading && (
            <p className="scenario-muted">
              Run Decision Matrix to analyze every strategy under every scenario.
            </p>
          )}
          {matrix.isRunning && (
            <p className="scenario-muted" role="status" aria-live="polite">
              Running the decision matrix. Each cell is a complete analysis…
            </p>
          )}
          {matrix.error !== null && (
            <div className="error-banner scenario-error" role="alert">
              <span>{withUnitNames(matrix.error, unitNames)}</span>
              <button
                type="button"
                className="btn btn-ghost btn-xs"
                onClick={() => void matrix.run()}
                disabled={!matrix.canRun}
              >
                Retry
              </button>
            </div>
          )}
          {report !== null && !matrix.isCurrent && (
            <StaleAnalysisNotice message={isDirty ? copy.dirty : copy.stale} />
          )}
          {showTable && (
            <DecisionMatrixTable matrix={report.matrix} labels={labels} caption={copy.caption} names={unitNames} />
          )}
        </>
      )}
    </section>
  );
}
