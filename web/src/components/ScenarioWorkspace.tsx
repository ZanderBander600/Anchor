/**
 * Phase 7 Gate P7.3 -- Scenarios, inside the Risk workspace.
 *
 * A Scenario is a named, coherent view of the world: a set of overrides on
 * selected assumptions of the saved underwriting. Sensitivity stays separate:
 * a mechanical one- or two-variable perturbation, with its own tab, its own
 * state and its own words.
 *
 * P7.5 made this the Scenario manager and editor only. Comparison moved to the
 * Decision Matrix tab, the one comparison surface for Strategies and Scenarios
 * alike, so there is no second comparison authority here.
 *
 * **Simple until the analyst opts in.** A Deal with no Scenarios shows one
 * short sentence and the Add Scenario button. A Deal never saved says it must
 * be saved first, and requests nothing. The hidden Investment the first
 * Scenario creates is never shown: the object is still called a Deal.
 *
 * All state is `useScenarios'`, owned by `RiskDecisionWorkspace`. This
 * component renders it and forwards the analyst's actions; it computes
 * nothing.
 */

import { useEffect, useRef } from 'react';
import {
  decisionIdScope,
  INVESTMENT_DIRTY_MESSAGE,
  INVESTMENT_SCENARIO_SUBTITLE,
  unitNames,
} from '../investmentCatalog';
import { describeScenarioOverride } from '../scenarioCatalog';
import type { ScenarioOverride } from '../scenarioTypes';
import { SAVE_BEFORE_SCENARIOS_MESSAGE } from '../useScenarios';
import type { ScenariosState } from '../useScenarios';
import { ScenarioEditor } from './ScenarioEditor';

export interface ScenarioWorkspaceProps {
  state: ScenariosState;
}

const BLOCKED_REASON_ID = 'scenario-blocked-reason';
const EDITOR_ID = 'scenario-editor';

function overrideCount(count: number): string {
  return count === 1 ? '1 override' : `${count} overrides`;
}

/** One saved override as a phrase. A visible Investment's names its Unit. */
function overridePhrase(state: ScenariosState, override: ScenarioOverride): string {
  if (state.investment === null) {
    return describeScenarioOverride(override);
  }
  const name = unitNames(state.units)[override.unit_id] ?? override.unit_id;
  return `${name} · ${describeScenarioOverride(override)}`;
}

/** Why the analyst cannot change Scenarios right now, or `null`. */
function blockedReason(state: ScenariosState): string | null {
  if (state.investment !== null) {
    return state.isDirty ? INVESTMENT_DIRTY_MESSAGE : null;
  }
  if (state.dealId === null) {
    return 'Save this deal before adding scenarios.';
  }
  return state.isDirty ? SAVE_BEFORE_SCENARIOS_MESSAGE : null;
}

export function ScenarioWorkspace({ state }: ScenarioWorkspaceProps) {
  const reason = blockedReason(state);
  const ids = decisionIdScope(state.investment !== null);
  const editorId = `${ids}${EDITOR_ID}`;
  const blockedReasonId = `${ids}${BLOCKED_REASON_ID}`;
  const addButton = useRef<HTMLButtonElement>(null);
  const cancelDeleteButton = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(false);
  const isCreating = state.editor !== null && state.editor.scenarioId === null;

  // Focus returns to Add Scenario when the editor closes, rather than being
  // dropped on the page.
  useEffect(() => {
    if (wasEditing.current && state.editor === null) {
      addButton.current?.focus();
    }
    wasEditing.current = state.editor !== null;
  }, [state.editor]);

  // The safe choice takes focus when a deletion asks for confirmation.
  useEffect(() => {
    if (state.pendingDeleteId !== null) {
      cancelDeleteButton.current?.focus();
    }
  }, [state.pendingDeleteId]);

  return (
    <div className="scenario-workspace">
      <section className="scenario-panel" aria-labelledby={`${ids}scenario-manager-title`}>
        <div className="scenario-panel-header">
          <div className="scenario-panel-heading">
            <h3 id={`${ids}scenario-manager-title`} className="scenario-panel-title">
              Scenarios
            </h3>
            <p className="scenario-panel-subtitle">
              {state.investment !== null
                ? INVESTMENT_SCENARIO_SUBTITLE
                : 'Create named Downside, Upside, or other views by overriding selected assumptions. Compare them in the Decision Matrix.'}
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
            Add Scenario
          </button>
        </div>

        {reason !== null && (
          <p id={blockedReasonId} className="scenario-blocked" role="status">
            {reason}
          </p>
        )}

        {(state.listStatus === 'idle' || state.listStatus === 'loading') && (
          <p className="scenario-muted" role="status">
            Loading scenarios…
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

        {state.listStatus === 'ready' && state.scenarios.length === 0 && state.editor === null && (
          <p className="scenario-muted">No scenarios yet. Base is the saved underwriting.</p>
        )}

        {state.scenarios.length > 0 && (
          <ul className="scenario-list" aria-label="Saved scenarios">
            {state.scenarios.map((record) => {
              const { scenario_id: scenarioId, name, description, overrides } = record.scenario;
              const isPendingDelete = state.pendingDeleteId === scenarioId;
              const isEditingThis = state.editor?.scenarioId === scenarioId;
              return (
                <li key={scenarioId} className="scenario-list-item">
                  <div className="scenario-list-identity">
                    <span className="scenario-list-name">{name}</span>
                    {description !== null && description.trim() !== '' && (
                      <span className="scenario-list-description">{description}</span>
                    )}
                  </div>
                  <div className="scenario-list-overrides">
                    <span className="scenario-list-count">{overrideCount(overrides.length)}</span>
                    {overrides.length > 0 && (
                      <span className="scenario-list-summary">
                        {overrides.map((override) => overridePhrase(state, override)).join(' · ')}
                      </span>
                    )}
                  </div>
                  <div className="scenario-list-actions">
                    {isPendingDelete ? (
                      <div
                        className="scenario-delete-confirm"
                        role="group"
                        aria-label={`Confirm deleting ${name}`}
                      >
                        <span className="scenario-delete-question">Delete this scenario?</span>
                        <button
                          type="button"
                          className="btn btn-danger btn-xs"
                          onClick={() => void state.confirmDelete()}
                          disabled={state.isDeleting}
                        >
                          {state.isDeleting ? 'Deleting…' : 'Delete Scenario'}
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
                          onClick={() => state.openEdit(scenarioId)}
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
                          onClick={() => state.requestDelete(scenarioId)}
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
        )}

        {state.editor !== null && (
          <ScenarioEditor id={editorId} state={state} editor={state.editor} />
        )}
      </section>
    </div>
  );
}
