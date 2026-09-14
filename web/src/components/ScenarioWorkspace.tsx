/**
 * Phase 7 Gate P7.3 -- Scenarios, inside the Risk workspace.
 *
 * A Scenario is a named, coherent view of the world: a set of overrides on
 * selected assumptions of the saved underwriting. It is compared column by
 * column in the Scenario Comparison below the list. Sensitivity stays separate:
 * a mechanical one- or two-variable perturbation, with its own tab, its own
 * state and its own words.
 *
 * **Simple until the analyst opts in.** A Deal with no Scenarios shows one
 * short sentence and the Add Scenario button, and no comparison table. A Deal
 * never saved says it must be saved first, and requests nothing. The hidden
 * Investment the first Scenario creates is never shown: the object is still
 * called a Deal.
 *
 * All state is `useScenarios`'. This component renders it and forwards the
 * analyst's actions; it computes nothing.
 */

import { useEffect, useRef } from 'react';
import { describeScenarioOverride } from '../scenarioCatalog';
import { SAVE_BEFORE_SCENARIOS_MESSAGE } from '../scenarioComparison';
import { useScenarios } from '../useScenarios';
import type { ScenariosState, UseScenariosOptions } from '../useScenarios';
import { ScenarioComparisonMatrix } from './ScenarioComparisonMatrix';
import { ScenarioEditor } from './ScenarioEditor';

export type ScenarioWorkspaceProps = UseScenariosOptions;

const BLOCKED_REASON_ID = 'scenario-blocked-reason';
const EDITOR_ID = 'scenario-editor';

function overrideCount(count: number): string {
  return count === 1 ? '1 override' : `${count} overrides`;
}

/** Why the analyst cannot change or run Scenarios right now, or `null`. */
function blockedReason(state: ScenariosState): string | null {
  if (state.dealId === null) {
    return 'Save this deal before adding scenarios.';
  }
  return state.isDirty ? SAVE_BEFORE_SCENARIOS_MESSAGE : null;
}

export function ScenarioWorkspace(props: ScenarioWorkspaceProps) {
  const state = useScenarios(props);
  const reason = blockedReason(state);
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
      <section className="scenario-panel" aria-labelledby="scenario-manager-title">
        <div className="scenario-panel-header">
          <div className="scenario-panel-heading">
            <h3 id="scenario-manager-title" className="scenario-panel-title">
              Scenarios
            </h3>
            <p className="scenario-panel-subtitle">
              Create named Downside, Upside, or other views by overriding selected assumptions.
            </p>
          </div>
          <button
            ref={addButton}
            type="button"
            className="btn btn-primary btn-sm"
            onClick={state.openNew}
            disabled={!state.canEdit || state.editor !== null}
            aria-expanded={isCreating}
            aria-controls={isCreating ? EDITOR_ID : undefined}
            aria-describedby={reason === null ? undefined : BLOCKED_REASON_ID}
          >
            Add Scenario
          </button>
        </div>

        {reason !== null && (
          <p id={BLOCKED_REASON_ID} className="scenario-blocked" role="status">
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
                        {overrides.map(describeScenarioOverride).join(' · ')}
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
                          aria-controls={isEditingThis ? EDITOR_ID : undefined}
                          aria-label={`Edit ${name}`}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-xs"
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
          <ScenarioEditor id={EDITOR_ID} state={state} editor={state.editor} />
        )}
      </section>

      {state.listStatus === 'ready' && state.scenarios.length > 0 && (
        <ScenarioComparisonMatrix
          state={state}
          blockedReasonId={reason === null ? null : BLOCKED_REASON_ID}
        />
      )}
    </div>
  );
}
