/**
 * Refinance & Capital Events V1 Stage 3 -- the action that downloads the
 * separate Refinance & Capital Structure Audit workbook (Section 25.1).
 *
 * Offered only for an analysis whose structure states a refinance. It is
 * enabled only while that analysis is the current one for the saved state and
 * every refinance executed; otherwise it says why, beside the control. The
 * server re-checks all of it and refuses with its own words.
 */

import { useId } from 'react';
import type { StructuredVariantAnalysis } from '../capitalTypes';
import { useCapitalEventAudit } from '../useCapitalEventAudit';

// prettier-ignore
export const AUDIT_STALE_REASON =
  'Run the analysis again: the audit describes the saved state, and the analysis on screen is out of date.';

// prettier-ignore
export const AUDIT_NOT_EXECUTED_REASON =
  'A refinance did not execute for this analysis, so its audit would be partial. Resolve its stated reason first.';

// prettier-ignore
export const AUDIT_DESCRIPTION =
  'A formula-level audit of the refinance: the payoff amortization, every sizing capacity and the binding constraint, the bridge, the replacement loan to the sale and the Common Equity return, reconciled with Anchor.';

export function CapitalEventAuditAction({
  analysis,
  isCurrent,
}: {
  analysis: StructuredVariantAnalysis;
  isCurrent: boolean;
}) {
  const reasonId = useId();
  const events = analysis.result.capital_events ?? [];
  const audit = useCapitalEventAudit({
    investmentId: analysis.investment_id,
    strategyId: analysis.strategy_id,
    scenarioId: analysis.scenario_id,
    fingerprint: analysis.structured_source_fingerprint,
  });
  if (events.length === 0) {
    return null;
  }
  const executed = events.every((event) => event.status === 'executed');
  const reason = !isCurrent ? AUDIT_STALE_REASON : !executed ? AUDIT_NOT_EXECUTED_REASON : null;
  const running = audit.outcome.status === 'running';
  return (
    <div className="capital-event-audit">
      <div className="capital-event-audit-text">
        <span className="capital-event-audit-title">Refinance &amp; Capital Structure Audit</span>
        <span className="capital-event-audit-description">{AUDIT_DESCRIPTION}</span>
      </div>
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        onClick={() => void audit.download()}
        disabled={reason !== null || running}
        aria-describedby={reason === null ? undefined : reasonId}
      >
        {running ? 'Exporting…' : 'Export Audit (.xlsx)'}
      </button>
      {reason !== null && (
        <p id={reasonId} className="capital-event-audit-reason">
          {reason}
        </p>
      )}
      {reason === null && audit.outcome.status === 'done' && (
        <p className="capital-event-audit-status" role="status">
          {`Exported ${audit.outcome.filename}.`}
        </p>
      )}
      {reason === null && audit.outcome.status === 'error' && (
        <p className="capital-event-audit-error" role="alert">
          {audit.outcome.message}
        </p>
      )}
    </div>
  );
}
