/**
 * Phase 7 Gate P7.9 Stage 3 -- the `PARTNER(partner_id)` perspective of the
 * Decision Matrix.
 *
 * The same Strategy x Scenario grid, asking a third question: not "how does the
 * deal do" and not "how does this position do", but **how does this partner do**
 * -- what it contributes, what it is distributed, what it earns, how that
 * compares with the no-promote benchmark, and whether it earned a promote at
 * all.
 *
 * **Every figure is a backend field (P-5, Q22, DC-5).** Each cell is one metric
 * of one variant's Stage 1 `PartnerResult`, with the backend's Delta vs Base
 * Scenario under it; Worst Case and Range are the backend's too. This component
 * formats and lays out. It subtracts, compares, sorts, ranks and averages
 * nothing, and there is no winner, no score and no colour that means good or
 * bad.
 *
 * **Each cell states its own name and role (P-8).** A `partner_id` is the
 * identity; the name and role it is described by are presentation, and a
 * Strategy that replaces the Partnership whole may describe the same id
 * differently. So each applicable cell reports the name and role *its own*
 * resolved Partnership states, and one Strategy's terms never label another's.
 *
 * **Four honest cell states (DC-2, P-9).** An invalid variant shows its
 * validators' reasons. A valid variant with no Partnership, or whose Partnership
 * does not hold this partner, says the partner is absent -- which is different
 * from zero. A present partner whose upstream Common Equity Cash Flow is
 * unavailable reports N/A with the engine's own reason. And a Promote Earned
 * that does not apply, because the partner is not a stated promote participant,
 * is N/A with *that* reason -- never `0`.
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
import { PARTNER_ROLE_LABELS } from '../partnershipForm';
import type { PartnerDecisionCell, PartnerDecisionMatrix } from '../partnershipTypes';
import type { PartnerDecisionMatrixState } from '../usePartnerDecisionMatrix';
import { StaleAnalysisNotice } from './StaleAnalysisNotice';

export interface PartnerDecisionMatrixPanelProps {
  state: PartnerDecisionMatrixState;
  /** The element-id namespace (`decisionIdScope`). */
  ids: string;
  isDirty: boolean;
}

/** Each message is one string literal, never joined with `+`: this module is
 * asserted to contain no binary arithmetic operator, and the audit that forbids
 * browser math cannot tell a concatenated sentence from a sum. */
// prettier-ignore
export const PARTNER_ABSENT_MESSAGE =
  'Not a partner in this Strategy’s Partnership.';

// prettier-ignore
export const PARTNER_NOT_ANALYSED_MESSAGE =
  'This variant was not analysed for this partner.';

// prettier-ignore
export const NO_PARTNERS_MESSAGE =
  'No partners yet. Add a partnership to compare a partner across strategies and scenarios.';

// prettier-ignore
export const PARTNER_STALE_MESSAGE =
  'The saved underwriting, capital structure, partnerships, strategies or scenarios changed after this matrix ran. Run it again to update it.';

// prettier-ignore
export const PARTNER_SUBTITLE =
  'One partner across every strategy and scenario. Each cell is a complete deterministic analysis, described by the partnership that strategy resolved.';

// prettier-ignore
export const RUN_PARTNER_MESSAGE =
  'Choose a partner and run the matrix to compare it across strategies and scenarios.';

// prettier-ignore
export const PARTNER_IDENTITY_NOTE =
  'A partner is identified by its stable id. Its name and role are how each strategy’s partnership describes it, and may differ from cell to cell.';

function cellKey(cell: PartnerDecisionCell): string {
  return `${cell.strategy_id}|${cell.scenario_id}`;
}

/** How this cell's own Partnership describes the partner: its name, and its
 * role in that Partnership. Presentation from the authored contract -- stated
 * wherever the partner is present, including while its figures are
 * unavailable, because it does not come from the result. */
function CellIdentity({ cell }: { cell: PartnerDecisionCell }) {
  if (cell.partner_name === null && cell.partner_role === null) {
    return null;
  }
  return (
    <span className="partner-cell-identity">
      {cell.partner_name !== null && (
        <span className="partner-cell-name">{cell.partner_name}</span>
      )}
      {cell.partner_role !== null && (
        <span className="partner-cell-role">{PARTNER_ROLE_LABELS[cell.partner_role]}</span>
      )}
    </span>
  );
}

function PartnerTable({ matrix, ids }: { matrix: PartnerDecisionMatrix; ids: string }) {
  const cells = new Map<string, PartnerDecisionCell>(
    matrix.cells.map((cell) => [cellKey(cell), cell]),
  );
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
    spec: PartnerDecisionMatrix['metrics'][number],
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
          className="decision-matrix-status partner-cell-absent"
          data-column={scenarioId}
        >
          {cell.applicability === 'not_present'
            ? PARTNER_ABSENT_MESSAGE
            : PARTNER_NOT_ANALYSED_MESSAGE}
        </td>
      ) : null;
    }
    const figure = cell.metrics.find((entry) => entry.metric === spec.metric);
    const delta = cell.deltas.find((entry) => entry.metric === spec.metric);
    if (figure === undefined) {
      return <td key={scenarioId} data-column={scenarioId} />;
    }
    if (figure.value === null) {
      // The backend's own reason, whichever it is: a Promote Earned that does
      // not apply to a non-participant, an IRR the convention does not define,
      // or an upstream Common Equity Cash Flow that is unavailable. Never a
      // zero, and never this component's own words.
      const text = figure.message ?? cell.unavailable_message ?? `${spec.label} is not available.`;
      return (
        <td key={scenarioId} className="decision-matrix-cell" data-column={scenarioId}>
          {metricIndex === 0 && <CellIdentity cell={cell} />}
          <span className="decision-matrix-na" title={text}>
            {NOT_AVAILABLE}
          </span>
          <span className="partner-result-reason">{text}</span>
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
        {metricIndex === 0 && <CellIdentity cell={cell} />}
        <span className="decision-matrix-figure">{formatMetricValue(spec.unit, figure.value)}</span>
        {deltaLine}
      </td>
    );
  }

  function summaryCell(
    strategyId: string,
    spec: PartnerDecisionMatrix['metrics'][number],
    kind: 'worst' | 'range',
  ) {
    const row = figures.get(strategyId);
    if (kind === 'worst') {
      const worst = row?.worst_cases.find((entry) => entry.metric === spec.metric);
      if (worst === undefined || worst.value === null) {
        return (
          <td
            key="worst"
            className="decision-matrix-cell decision-matrix-summary"
            data-column="worst"
          >
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
      <p className="decision-matrix-horizon" role="note">
        {PARTNER_IDENTITY_NOTE}
      </p>
      {matrix.omitted_metrics.length > 0 && (
        <p className="decision-matrix-horizon" role="note">
          {matrix.omitted_metrics[0].message}
        </p>
      )}
      <div
        className="decision-matrix-scroll"
        role="region"
        aria-label="Partner decision matrix table"
        tabIndex={0}
      >
        <table className="decision-matrix">
          <caption className="visually-hidden">
            {`${matrix.partner_name} under each strategy and scenario, with the backend’s Delta vs Base, Worst Case and Range`}
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
            const groupId = `${ids}partner-group-${row.strategy_id}`;
            return (
              <tbody
                key={row.strategy_id}
                className="decision-matrix-rowgroup"
                aria-labelledby={groupId}
              >
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

export function PartnerDecisionMatrixPanel({
  state,
  ids,
  isDirty,
}: PartnerDecisionMatrixPanelProps) {
  const selectId = `${ids}partner-select`;
  const report = state.report;

  return (
    <section
      className="scenario-panel partnership-partner-matrix"
      aria-labelledby={`${ids}partner-matrix-title`}
    >
      <div className="scenario-panel-header">
        <div className="scenario-panel-heading">
          <h3 id={`${ids}partner-matrix-title`} className="scenario-panel-title">
            Partner
          </h3>
          <p className="scenario-panel-subtitle">{PARTNER_SUBTITLE}</p>
        </div>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => void state.run()}
          disabled={!state.canRun}
        >
          {state.isRunning ? 'Running…' : state.hasRun ? 'Refresh Matrix' : 'Run Partner Matrix'}
        </button>
      </div>

      {state.listStatus === 'loading' && (
        <p className="scenario-muted" role="status">
          Loading partners…
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

      {state.listStatus === 'ready' && state.partners.length === 0 && (
        <p className="scenario-muted">{NO_PARTNERS_MESSAGE}</p>
      )}

      {state.partners.length > 0 && (
        <div className="field partnership-partner-picker">
          <label className="field-label" htmlFor={selectId}>
            Partner
          </label>
          <select
            id={selectId}
            className="field-input scenario-select"
            value={state.selectedPartnerId ?? ''}
            onChange={(event) => state.selectPartner(event.target.value)}
          >
            {state.partners.map((partner) => (
              <option key={partner.partner_id} value={partner.partner_id}>
                {partner.name}
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
        ? state.partners.length > 0 && <p className="scenario-muted">{RUN_PARTNER_MESSAGE}</p>
        : null}

      {/* A matrix that is no longer current stays on screen -- it is real work
        * against real saved inputs -- and is labelled out of date above the
        * table it describes. It is never silently presented as current. */}
      {report !== null && !(state.isCurrent && !isDirty) && (
        <StaleAnalysisNotice message={PARTNER_STALE_MESSAGE} />
      )}

      {report !== null && <PartnerTable matrix={report.matrix} ids={ids} />}
    </section>
  );
}
