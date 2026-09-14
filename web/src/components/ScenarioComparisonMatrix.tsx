/**
 * Phase 7 Gate P7.3 -- the Scenario Comparison matrix, v0.
 *
 * One implicit row group, "Current Underwriting", under a Base column and one
 * column per saved Scenario. Each metric row reads one backend field per
 * column. P7.5 adds real Strategy rows and the backend cross-cell figures
 * (Q22); this table has neither.
 *
 * **What a cell may show (DC-2).**
 * - A formatted backend figure.
 * - `N/A`, with the engine's reason in a note under the table. The cell points
 *   to that note, and its tooltip repeats it.
 * - For a whole column: `Invalid variant` with the validators' reasons,
 *   `Running…`, or a failed request with a Retry.
 * A figure is never replaced by zero and never left blank.
 *
 * **Current or out of date, never mixed (DC-7).** The table is shown only while
 * the comparison matches the saved underwriting and Scenarios on screen.
 * Otherwise the out-of-date notice replaces it until the analyst presses
 * Refresh Comparison.
 *
 * The table scrolls inside its own region on a narrow screen. It never widens
 * the page. `data-column` names each cell's column for tests and browser QA;
 * `data-cache-status` carries the P7.2 cache status the same way, without ever
 * showing it to the analyst.
 */

import {
  COMPARISON_METRICS,
  DIRTY_COMPARISON_MESSAGE,
  STALE_COMPARISON_MESSAGE,
} from '../scenarioComparison';
import type { ComparisonCell, ComparisonMetric } from '../scenarioComparison';
import type { ScenariosState } from '../useScenarios';
import { StaleAnalysisNotice } from './StaleAnalysisNotice';

export interface ScenarioComparisonMatrixProps {
  state: ScenariosState;
  /** The id of the sentence saying why Run is unavailable, if it is. */
  blockedReasonId: string | null;
}

interface Column {
  key: string;
  label: string;
  isBase: boolean;
  cell: ComparisonCell | undefined;
  retry: () => void;
}

interface Note {
  id: string;
  text: string;
}

function noteId(columnKey: string, metric: ComparisonMetric): string {
  return `scenario-note-${columnKey}-${metric.id}`;
}

function StatusCell({ column }: { column: Column }) {
  const cell = column.cell;
  if (cell === undefined) {
    return <span className="scenario-matrix-status-label">Not run</span>;
  }
  switch (cell.status) {
    case 'loading':
      return <span className="scenario-matrix-status-label">Running…</span>;
    case 'invalid':
      return (
        <>
          <span className="scenario-matrix-status-label scenario-matrix-invalid">Invalid variant</span>
          <ul className="scenario-matrix-reasons">
            {cell.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </>
      );
    case 'error':
      return (
        <>
          <span className="scenario-matrix-status-label scenario-matrix-invalid">
            {column.isBase ? 'Base analysis failed' : 'Analysis failed'}
          </span>
          <p className="scenario-matrix-message">{cell.message}</p>
          <button
            type="button"
            className="btn btn-ghost btn-xs"
            onClick={column.retry}
            aria-label={`Retry ${column.label}`}
          >
            Retry
          </button>
        </>
      );
    case 'result':
      return null;
  }
}

export function ScenarioComparisonMatrix({ state, blockedReasonId }: ScenarioComparisonMatrixProps) {
  const comparison = state.comparison;
  const hasRun = comparison !== null;
  const showTable = comparison !== null && state.isComparisonCurrent;

  const columns: Column[] =
    comparison === null
      ? []
      : [
          {
            key: 'base',
            label: 'Base',
            isBase: true,
            cell: comparison.base,
            retry: () => void state.retryBase(),
          },
          ...state.scenarios.map((record) => ({
            key: record.scenario.scenario_id,
            label: record.scenario.name,
            isBase: false,
            cell: comparison.scenarios[record.scenario.scenario_id],
            retry: () => void state.retryScenario(record.scenario.scenario_id),
          })),
        ];

  const notes: Note[] = columns.flatMap((column) => {
    const cell = column.cell;
    if (cell === undefined || cell.status !== 'result') {
      return [];
    }
    return COMPARISON_METRICS.flatMap((metric) => {
      const { reason } = metric.figure(cell.results);
      return reason === null ? [] : [{ id: noteId(column.key, metric), text: `${column.label}: ${reason}` }];
    });
  });

  return (
    <section className="scenario-panel scenario-comparison" aria-labelledby="scenario-comparison-title">
      <div className="scenario-panel-header">
        <div className="scenario-panel-heading">
          <h3 id="scenario-comparison-title" className="scenario-panel-title">
            Scenario Comparison
          </h3>
          <p className="scenario-panel-subtitle">
            Base is the saved underwriting. Each column is a complete deterministic analysis.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => void state.runComparison()}
          disabled={!state.canRun}
          aria-describedby={blockedReasonId ?? undefined}
        >
          {state.isRunning ? 'Running…' : hasRun ? 'Refresh Comparison' : 'Run Comparison'}
        </button>
      </div>

      {!hasRun && (
        <p className="scenario-muted">
          Run Comparison to analyze Base and every saved scenario side by side.
        </p>
      )}

      {hasRun && !showTable && (
        <StaleAnalysisNotice
          message={state.isDirty ? DIRTY_COMPARISON_MESSAGE : STALE_COMPARISON_MESSAGE}
        />
      )}

      {showTable && (
        <>
          <div
            className="scenario-matrix-scroll"
            role="region"
            aria-label="Scenario comparison table"
            tabIndex={0}
          >
            <table className="scenario-matrix" aria-busy={state.isRunning}>
              <caption className="visually-hidden">
                Headline results of the current underwriting under Base and each saved scenario
              </caption>
              <thead>
                <tr>
                  <th scope="col" className="scenario-matrix-corner">
                    <span className="visually-hidden">Metric</span>
                  </th>
                  {columns.map((column) => (
                    <th
                      key={column.key}
                      scope="col"
                      className={column.isBase ? 'scenario-matrix-base' : undefined}
                      data-column={column.key}
                      data-cache-status={
                        column.cell?.status === 'result' && column.cell.cacheStatus !== null
                          ? column.cell.cacheStatus
                          : undefined
                      }
                    >
                      {column.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr className="scenario-matrix-group">
                  <th scope="rowgroup">Current Underwriting</th>
                  <td colSpan={columns.length} />
                </tr>
                {COMPARISON_METRICS.map((metric, metricIndex) => (
                  <tr key={metric.id}>
                    <th scope="row">{metric.label}</th>
                    {columns.map((column) => {
                      const cell = column.cell;
                      if (cell === undefined || cell.status !== 'result') {
                        return metricIndex === 0 ? (
                          <td
                            key={column.key}
                            rowSpan={COMPARISON_METRICS.length}
                            className="scenario-matrix-status"
                            data-column={column.key}
                          >
                            <StatusCell column={column} />
                          </td>
                        ) : null;
                      }
                      const figure = metric.figure(cell.results);
                      return (
                        <td
                          key={column.key}
                          className={
                            figure.reason === null
                              ? 'scenario-matrix-figure'
                              : 'scenario-matrix-figure scenario-matrix-na'
                          }
                          data-column={column.key}
                          title={figure.reason ?? undefined}
                          aria-describedby={
                            figure.reason === null ? undefined : noteId(column.key, metric)
                          }
                        >
                          {figure.text}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {notes.length > 0 && (
            <ul className="scenario-matrix-notes" aria-label="Figures not reported">
              {notes.map((note) => (
                <li key={note.id} id={note.id}>
                  <span className="scenario-matrix-note-marker">N/A</span> {note.text}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
