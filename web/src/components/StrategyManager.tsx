/**
 * Phase 7 Gate P7.5 -- Strategies, inside the Risk workspace.
 *
 * A Strategy is what the analyst chooses: a bid, a financing package, a
 * Business Plan, the operating outcome underwritten for it, a hold. Each of
 * its five domains either inherits Base or replaces that whole domain. The Base
 * Strategy is the saved underwriting itself: implicit, always first, locked,
 * and never a stored row.
 *
 * **Opt-in.** A Deal with no Strategies shows the locked Base Strategy and Add
 * Strategy. An unsaved Deal says it must be saved first and requests nothing.
 * The hidden Investment the first Strategy creates is never shown.
 *
 * All state is `useStrategies'`, owned by `RiskDecisionWorkspace`; this
 * component renders it and forwards the analyst's actions. Deletion asks for
 * confirmation inline, with focus on the safe choice, never in a browser
 * dialog.
 */

import { useEffect, useRef } from 'react';
import {
  decisionIdScope,
  INVESTMENT_BASE_STRATEGY_DESCRIPTION,
  INVESTMENT_DIRTY_MESSAGE,
  INVESTMENT_STRATEGY_SUBTITLE,
  unitNames,
} from '../investmentCatalog';
import {
  describeStrategyOverlay,
  SAVE_BEFORE_STRATEGIES_MESSAGE,
  SAVE_DEAL_BEFORE_STRATEGIES_MESSAGE,
  STRATEGY_RESOLVES_TO_BASE_MESSAGE,
  strategyDomainsReplaced,
} from '../strategyCatalog';
import type { StrategyOverlay } from '../strategyTypes';
import type { StrategiesState } from '../useStrategies';
import { StrategyEditor } from './StrategyEditor';

export interface StrategyManagerProps {
  state: StrategiesState;
}

const BLOCKED_REASON_ID = 'strategy-blocked-reason';
const EDITOR_ID = 'strategy-editor';

/** One saved overlay as a line. A visible Investment's names its Unit. */
function overlayLine(state: StrategiesState, overlay: StrategyOverlay): string {
  if (state.investment === null) {
    return describeStrategyOverlay(overlay);
  }
  const name = unitNames(state.units)[overlay.unit_id] ?? overlay.unit_id;
  return `${name} · ${describeStrategyOverlay(overlay)}`;
}

function blockedReason(state: StrategiesState): string | null {
  if (state.investment !== null) {
    return state.isDirty ? INVESTMENT_DIRTY_MESSAGE : null;
  }
  if (state.dealId === null) {
    return SAVE_DEAL_BEFORE_STRATEGIES_MESSAGE;
  }
  return state.isDirty ? SAVE_BEFORE_STRATEGIES_MESSAGE : null;
}

export function StrategyManager({ state }: StrategyManagerProps) {
  const reason = blockedReason(state);
  const ids = decisionIdScope(state.investment !== null);
  const editorId = `${ids}${EDITOR_ID}`;
  const blockedReasonId = `${ids}${BLOCKED_REASON_ID}`;
  const addButton = useRef<HTMLButtonElement>(null);
  const cancelDeleteButton = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(false);
  const isCreating = state.editor !== null && state.editor.strategyId === null;

  useEffect(() => {
    if (wasEditing.current && state.editor === null) {
      addButton.current?.focus();
    }
    wasEditing.current = state.editor !== null;
  }, [state.editor]);

  useEffect(() => {
    if (state.pendingDeleteId !== null) {
      cancelDeleteButton.current?.focus();
    }
  }, [state.pendingDeleteId]);

  return (
    <div className="scenario-workspace">
      <section className="scenario-panel" aria-labelledby={`${ids}strategy-manager-title`}>
        <div className="scenario-panel-header">
          <div className="scenario-panel-heading">
            <h3 id={`${ids}strategy-manager-title`} className="scenario-panel-title">
              Strategies
            </h3>
            <p className="scenario-panel-subtitle">
              {state.investment !== null
                ? INVESTMENT_STRATEGY_SUBTITLE
                : 'Alternative decisions: bid, financing, business plan, operating outcome and hold. Each domain inherits Base or replaces it whole. Compare them in the Decision Matrix.'}
            </p>
          </div>
          <button
            ref={addButton}
            type="button"
            className="btn btn-primary btn-sm"
            onClick={state.openNew}
            disabled={!state.canEdit || state.editor !== null}
            aria-expanded={isCreating}
            aria-controls={isCreating ? editorId : undefined}
            aria-describedby={reason === null ? undefined : blockedReasonId}
          >
            Add Strategy
          </button>
        </div>

        {reason !== null && (
          <p id={blockedReasonId} className="scenario-blocked" role="status">
            {reason}
          </p>
        )}

        {(state.listStatus === 'idle' || state.listStatus === 'loading') && (
          <p className="scenario-muted" role="status">
            Loading strategies…
          </p>
        )}

        {state.listStatus === 'error' && (
          <div className="error-banner scenario-error" role="alert">
            <span>{state.loadError}</span>
            <button type="button" className="btn btn-ghost btn-xs" onClick={state.retryLoad}>
              Retry
            </button>
          </div>
        )}

        <ul className="scenario-list" aria-label="Strategies">
          <li className="scenario-list-item strategy-list-base">
            <div className="scenario-list-identity">
              <span className="scenario-list-name">Base Strategy</span>
              <span className="scenario-list-description">
                {state.investment !== null
                  ? INVESTMENT_BASE_STRATEGY_DESCRIPTION
                  : 'The saved underwriting. Edit it on Underwrite.'}
              </span>
            </div>
            <div className="scenario-list-overrides">
              <span className="scenario-list-count">Implicit</span>
              <span className="scenario-list-summary">Every domain is the saved Base.</span>
            </div>
            <div className="scenario-list-actions">
              <span className="strategy-locked-tag">Locked</span>
            </div>
          </li>
          {state.strategies.map((record) => {
            const { strategy_id: strategyId, name, description, overlays } = record.strategy;
            const replaced = strategyDomainsReplaced(record.strategy);
            const isPendingDelete = state.pendingDeleteId === strategyId;
            const isEditingThis = state.editor?.strategyId === strategyId;
            return (
              <li key={strategyId} className="scenario-list-item">
                <div className="scenario-list-identity">
                  <span className="scenario-list-name">{name}</span>
                  {description !== null && description.trim() !== '' && (
                    <span className="scenario-list-description">{description}</span>
                  )}
                </div>
                <div className="scenario-list-overrides">
                  <span className="scenario-list-count">
                    {replaced.length === 0 ? 'Inherits Base' : `Replaces: ${replaced.join(' · ')}`}
                  </span>
                  {overlays.length === 0 ? (
                    <span className="scenario-list-summary">{STRATEGY_RESOLVES_TO_BASE_MESSAGE}</span>
                  ) : (
                    <ul className="strategy-overlay-summary">
                      {overlays.map((overlay) => (
                        <li key={`${overlay.unit_id}:${overlay.domain}`}>{overlayLine(state, overlay)}</li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="scenario-list-actions">
                  {isPendingDelete ? (
                    <div className="scenario-delete-confirm" role="group" aria-label={`Confirm deleting ${name}`}>
                      <span className="scenario-delete-question">Delete this strategy?</span>
                      <button
                        type="button"
                        className="btn btn-danger btn-xs"
                        onClick={() => void state.confirmDelete()}
                        disabled={state.isDeleting || !state.canEdit}
                      >
                        {state.isDeleting ? 'Deleting…' : 'Delete Strategy'}
                      </button>
                      <button
                        ref={cancelDeleteButton}
                        type="button"
                        className="btn btn-ghost btn-xs"
                        onClick={state.cancelDelete}
                        disabled={state.isDeleting}
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="btn btn-ghost btn-xs"
                        onClick={() => state.openEdit(strategyId)}
                        disabled={!state.canEdit || state.editor !== null}
                        aria-expanded={isEditingThis}
                        aria-controls={isEditingThis ? editorId : undefined}
                        aria-label={`Edit ${name}`}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn btn-remove btn-xs"
                        onClick={() => state.requestDelete(strategyId)}
                        disabled={!state.canEdit || state.pendingDeleteId !== null}
                        aria-label={`Delete ${name}`}
                      >
                        Delete
                      </button>
                    </>
                  )}
                </div>
                {isPendingDelete && state.deleteError !== null && (
                  <p className="scenario-inline-error" role="alert">
                    {state.deleteError}
                  </p>
                )}
              </li>
            );
          })}
        </ul>

        {state.editor !== null && <StrategyEditor id={editorId} state={state} editor={state.editor} />}
      </section>
    </div>
  );
}
