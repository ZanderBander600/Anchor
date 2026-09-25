/**
 * Phase 7 Gate P7.8B -- Capital Structure, inside the Risk workspace.
 *
 * The fourth decision view, beside the Decision Matrix, the Strategies and the
 * Scenarios. It holds the **Base Capital Structure**: the stack of positions
 * above Common Equity that this Deal -- or this visible Investment -- is
 * underwritten with, unless a Strategy replaces it whole.
 *
 * **Simple until the analyst opts in.** A Deal with no structure shows one
 * sentence and Add Capital Structure. A Deal never saved says it must be saved
 * first, and requests nothing. The hidden Investment the first saved structure
 * creates is never shown: the object is still called a Deal (Q4).
 *
 * **Downstream only.** Editing the structure invalidates the structured
 * analysis and nothing upstream: the Project results and the Project Decision
 * Matrix stay exactly as current as they were (P-4). A structured analysis that
 * is no longer current stays on screen and is marked out of date, never
 * silently reused and never silently discarded.
 *
 * All state is `useCapitalStructure`'s. This component renders it and forwards
 * the analyst's actions; it computes nothing.
 */

import { useEffect, useRef } from 'react';
import { POSITION_CLASS_LABELS } from '../capitalStructureForm';
import type { CapitalStructureState } from '../useCapitalStructure';
import { useValuationChoices } from '../useCapitalEventChoices';
import { CapitalStructureEditor } from './CapitalStructureEditor';
import type { ScopeUnit } from './CapitalStructureEditor';
import { CapitalStructureResults } from './CapitalStructureResults';
import { StaleAnalysisNotice } from './StaleAnalysisNotice';

export interface CapitalStructureWorkspaceProps {
  state: CapitalStructureState;
  /** The element-id prefix, so a Deal's and an Investment's never collide. */
  prefix: string;
  /** The Units a position may be scoped to. A Deal has exactly one. */
  units: ScopeUnit[];
  /** Those Units by id, for reporting a result's scope. */
  unitNames: Record<string, string>;
  /** Why the analyst cannot change the structure right now, or `null`. */
  blockedReason: string | null;
  /** True for a visible Investment, which words its subtitle differently. */
  isInvestment: boolean;
}

/** Each message is one string literal, never joined with `+`: this module is
 * asserted to contain no binary arithmetic operator, and the audit that forbids
 * browser math cannot tell a concatenated sentence from a sum. */
// prettier-ignore
export const STALE_STRUCTURED_MESSAGE =
  'The saved underwriting or capital structure changed after this analysis ran. Run it again to update these results.';

// prettier-ignore
export const NO_STRUCTURE_MESSAGE =
  'No capital structure yet. Each Unit keeps its acquisition loan and the residual, exactly as it is underwritten today.';

// prettier-ignore
export const DEAL_SUBTITLE =
  'The positions above Common Equity this deal is underwritten with — senior debt, mezzanine, preferred equity. A strategy may replace the whole structure.';

// prettier-ignore
export const INVESTMENT_SUBTITLE =
  'The positions above Common Equity this investment is underwritten with. A position is scoped to one Unit or to the whole Investment; a strategy may replace the whole structure.';

// prettier-ignore
export const ANALYSIS_ABSENT_MESSAGE =
  'Run the analysis to see what each position funds, earns and is owed, and any Funding Requirement it creates.';

function positionCount(count: number): string {
  return count === 1 ? '1 position' : `${count} positions`;
}

export function CapitalStructureWorkspace({
  state,
  prefix,
  units,
  unitNames,
  blockedReason,
  isInvestment,
}: CapitalStructureWorkspaceProps) {
  const editorId = `${prefix}capital-editor`;
  const blockedReasonId = `${prefix}capital-blocked-reason`;
  const addButton = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(false);

  // Focus returns to the opening control when the editor closes, rather than
  // being dropped on the page.
  useEffect(() => {
    if (wasEditing.current && !state.hasDraft) {
      addButton.current?.focus();
    }
    wasEditing.current = state.hasDraft;
  }, [state.hasDraft]);

  const isEmpty = state.saved.positions.length === 0;
  // Refinance V1 Stage 3: the valuations an LTV constraint may reference, by
  // label, for the editor's selector and the results' LTV operand.
  const valuations = useValuationChoices(state.investmentId);
  const valuationLabels = Object.fromEntries(
    valuations.choices.map((choice) => [choice.timepointId, choice.label] as const),
  );

  return (
    <div className="scenario-workspace capital-workspace">
      <section className="scenario-panel" aria-labelledby={`${prefix}capital-title`}>
        <div className="scenario-panel-header">
          <div className="scenario-panel-heading">
            <h3 id={`${prefix}capital-title`} className="scenario-panel-title">
              Capital Structure
            </h3>
            <p className="scenario-panel-subtitle">
              {isInvestment ? INVESTMENT_SUBTITLE : DEAL_SUBTITLE}
            </p>
          </div>
          <button
            ref={addButton}
            type="button"
            className="btn btn-primary btn-sm"
            onClick={state.edit}
            disabled={blockedReason !== null || state.hasDraft || state.listStatus !== 'ready'}
            aria-expanded={state.hasDraft}
            aria-controls={state.hasDraft ? editorId : undefined}
            aria-describedby={blockedReason === null ? undefined : blockedReasonId}
          >
            {isEmpty ? 'Add Capital Structure' : 'Edit Capital Structure'}
          </button>
        </div>

        {blockedReason !== null && (
          <p id={blockedReasonId} className="scenario-blocked" role="status">
            {blockedReason}
          </p>
        )}

        {(state.listStatus === 'idle' || state.listStatus === 'loading') && (
          <p className="scenario-muted" role="status">
            Loading capital structure…
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

        {state.listStatus === 'ready' && isEmpty && !state.hasDraft && (
          <p className="scenario-muted">{NO_STRUCTURE_MESSAGE}</p>
        )}

        {state.listStatus === 'ready' && !isEmpty && !state.hasDraft && (
          <ul className="scenario-list capital-saved-list" aria-label="Saved capital structure">
            {state.saved.positions.map((position) => (
              <li key={position.position_id} className="scenario-list-item">
                <div className="scenario-list-identity">
                  <span className="scenario-list-name">{position.name}</span>
                  <span className="scenario-list-description">
                    {POSITION_CLASS_LABELS[position.position_class]}
                  </span>
                </div>
                <div className="scenario-list-overrides">
                  <span className="scenario-list-count">
                    {position.scope.kind === 'investment'
                      ? 'Whole Investment'
                      : (unitNames[position.scope.unit_id ?? ''] ?? 'Unit')}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}

        {state.listStatus === 'ready' && !isEmpty && !state.hasDraft && (
          <p className="scenario-muted capital-saved-count">
            {positionCount(state.saved.positions.length)}
          </p>
        )}

        {state.hasDraft && state.draft !== null && (
          <CapitalStructureEditor
            id={editorId}
            prefix={prefix}
            form={state.draft}
            onChange={state.change}
            issues={state.saveIssues}
            saveError={state.saveError}
            isSaving={state.isSaving}
            locked={blockedReason !== null}
            lockedReason={blockedReason}
            onSave={() => void state.save()}
            onCancel={state.cancel}
            units={units}
            valuationOwnerId={state.investmentId}
          />
        )}
      </section>

      <section className="scenario-panel" aria-labelledby={`${prefix}capital-analysis-title`}>
        <div className="scenario-panel-header">
          <div className="scenario-panel-heading">
            <h3 id={`${prefix}capital-analysis-title`} className="scenario-panel-title">
              Structured Analysis
            </h3>
            <p className="scenario-panel-subtitle">
              Base strategy under the base scenario. Every figure is the engine’s.
            </p>
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => void state.analyze()}
            disabled={!state.canAnalyze}
          >
            {state.isAnalyzing ? 'Analyzing…' : state.analysis === null ? 'Run Analysis' : 'Run Again'}
          </button>
        </div>

        {state.analysisError !== null && (
          <div className="error-banner scenario-error" role="alert">
            <span>{state.analysisError}</span>
            {state.analysisIssues.length > 0 && (
              <ul className="scenario-editor-feedback-list">
                {state.analysisIssues.map((issue) => (
                  <li key={`${issue.code}:${issue.position_id ?? ''}:${issue.message}`}>
                    {issue.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {state.analysis === null ? (
          <p className="scenario-muted">{ANALYSIS_ABSENT_MESSAGE}</p>
        ) : (
          <>
            {!state.isAnalysisCurrent && <StaleAnalysisNotice message={STALE_STRUCTURED_MESSAGE} />}
            <CapitalStructureResults
              result={state.analysis.result}
              unitNames={unitNames}
              primaryReturn={state.analysis.primary_return}
              valuationLabels={valuationLabels}
            />
          </>
        )}
      </section>
    </div>
  );
}
