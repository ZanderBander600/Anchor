/**
 * Phase 7 Gate P7.9 Stage 3 -- Partnership, inside the Risk workspace.
 *
 * The fifth decision view, beside the Decision Matrix, the Strategies, the
 * Scenarios and the Capital Structure. It holds the **Base Partnership**: how
 * this Deal -- or this visible Investment -- divides its Common Equity Cash Flow
 * among its partners, unless a Strategy replaces it whole.
 *
 * **Simple until the analyst opts in.** A Deal with no Partnership shows one
 * sentence and Add Partnership, not waterfall controls nobody asked for. A Deal
 * never saved says it must be saved first, and requests nothing. The hidden
 * Investment the first saved Partnership creates is never shown: the object is
 * still called a Deal.
 *
 * **Downstream only (P-4).** Editing the Partnership invalidates the Partnership
 * result and the Partner matrix, and nothing else: the Project results, the
 * structured Capital Structure results and their matrices stay exactly as
 * current as they were. A Partnership analysis that is no longer current stays
 * on screen and is marked out of date, never silently reused and never silently
 * discarded.
 *
 * All state is `usePartnership`'s. This component renders it and forwards the
 * analyst's actions; it computes nothing.
 */

import { useEffect, useRef, useState } from 'react';
import { PARTNER_ROLE_LABELS, TIER_KIND_LABELS, conditionAuditLabels } from '../partnershipForm';
import type { Partnership } from '../partnershipTypes';
import type { PartnershipState } from '../usePartnership';
import { PartnershipEditor } from './PartnershipEditor';
import { PartnershipResults } from './PartnershipResults';
import { StaleAnalysisNotice } from './StaleAnalysisNotice';

// prettier-ignore
export const PARTNER_REFINANCE_NOTE =
  'This analysis includes a refinance. Partner returns are the primary investor view: each partner’s cash includes the refinance through the Common Equity cash flow, with no refinance tier and no special split.';

export interface PartnershipWorkspaceProps {
  state: PartnershipState;
  /** The element-id prefix, so a Deal's and an Investment's never collide. */
  prefix: string;
  /** Why the analyst cannot change the Partnership right now, or `null`. */
  blockedReason: string | null;
  /** True for a visible Investment, which words its subtitle differently. */
  isInvestment: boolean;
}

/** Each message is one string literal, never joined with `+`: this module is
 * asserted to contain no binary arithmetic operator, and the audit that forbids
 * browser math cannot tell a concatenated sentence from a sum. */
// prettier-ignore
export const STALE_PARTNERSHIP_MESSAGE =
  'The saved underwriting or partnership changed after this analysis ran. Run it again to update these results.';

// prettier-ignore
export const NO_PARTNERSHIP_MESSAGE =
  'No partnership yet. The Common Equity Cash Flow is reported whole, and no partner-level returns are produced.';

// prettier-ignore
export const DEAL_SUBTITLE =
  'How this deal’s Common Equity Cash Flow is divided among its partners — contributions, hurdles, catch-up and residual. A strategy may replace the whole partnership.';

// prettier-ignore
export const INVESTMENT_SUBTITLE =
  'How this investment’s Common Equity Cash Flow is divided among its partners — contributions, hurdles, catch-up and residual. A strategy may replace the whole partnership.';

// prettier-ignore
export const ANALYSIS_ABSENT_MESSAGE =
  'Run the analysis to see what each partner contributes and is distributed, how it compares with the no-promote benchmark, and the tier-by-tier audit behind both.';

// prettier-ignore
export const REMOVE_CONFIRM_MESSAGE =
  'Removing the partnership clears it entirely. The deal keeps its Common Equity Cash Flow and reports no partner-level returns.';

// prettier-ignore
export const REMOVE_CONFIRM_QUESTION =
  'Remove this partnership?';

function partnerCount(count: number): string {
  return count === 1 ? '1 partner' : `${count} partners`;
}

function tierCount(count: number): string {
  return count === 1 ? '1 tier' : `${count} tiers`;
}

/** The authored names, by id. The Stage 1 result deliberately carries no
 * display names, so the result surface is given the ones the Partnership this
 * analysis resolved states. */
function namesOf(partnership: Partnership | null): {
  partnerNames: Record<string, string>;
  tierNames: Record<string, string>;
} {
  const partnerNames: Record<string, string> = {};
  const tierNames: Record<string, string> = {};
  if (partnership !== null) {
    for (const partner of partnership.partners) {
      partnerNames[partner.partner_id] = partner.name;
    }
    for (const tier of partnership.tiers) {
      tierNames[tier.tier_id] = tier.name;
    }
  }
  return { partnerNames, tierNames };
}

export function PartnershipWorkspace({
  state,
  prefix,
  blockedReason,
  isInvestment,
}: PartnershipWorkspaceProps) {
  const editorId = `${prefix}partnership-editor`;
  const blockedReasonId = `${prefix}partnership-blocked-reason`;
  const addButton = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(false);
  const removeButton = useRef<HTMLButtonElement>(null);
  const cancelRemoveButton = useRef<HTMLButtonElement>(null);
  /** **Which** Partnership the analyst has asked to remove and not yet
   * confirmed, rather than merely *that* one was asked about. Removal clears a
   * whole authored contract, so it is confirmed inline -- in the product's own
   * words, where the thing being removed is still on screen -- rather than
   * through a browser dialog that steals focus and cannot say what is lost.
   *
   * Holding the subject, not a boolean, is what makes the confirmation
   * self-invalidating: a question about a Partnership that is no longer on
   * screen is not a question any more. A successful removal drops `saved` to
   * `null` and the confirmation closes with it, and loading a *different*
   * Partnership -- another Deal opened into this same mounted workspace --
   * closes it too, so a question asked about one contract can never be answered
   * against another. A failed removal leaves `saved` exactly as it was, so the
   * confirmation stays open and the analyst can try again or cancel. */
  const [confirmingRemovalOf, setConfirmingRemovalOf] = useState<Partnership | null>(null);
  const wasConfirmingRemove = useRef(false);

  // Focus returns to the opening control when the editor closes, rather than
  // being dropped on the page.
  useEffect(() => {
    if (wasEditing.current && !state.hasDraft) {
      addButton.current?.focus();
    }
    wasEditing.current = state.hasDraft;
  }, [state.hasDraft]);

  const saved = state.saved;
  const isEmpty = saved === null;

  /** Whether the confirmation is on screen: only while the Partnership it asks
   * about is still the one loaded. */
  const isConfirmingRemove = confirmingRemovalOf !== null && confirmingRemovalOf === saved;

  // Opening the confirmation moves focus to Cancel -- the safe choice. Closing
  // it hands focus to whichever control the analyst can now act on: the Remove
  // control that opened it when they cancelled, or -- when the removal
  // succeeded and took that control with it -- the Add Partnership control that
  // replaced it. React nulls the ref of an unmounted button, so the fallback is
  // the transition, not a guess about it. Focus is never left on a detached
  // node, which would drop a keyboard analyst back to the top of the document.
  useEffect(() => {
    if (isConfirmingRemove) {
      cancelRemoveButton.current?.focus();
    } else if (wasConfirmingRemove.current) {
      (removeButton.current ?? addButton.current)?.focus();
    }
    wasConfirmingRemove.current = isConfirmingRemove;
  }, [isConfirmingRemove]);
  const analysis = state.analysis;
  const resolvedPartnership = analysis?.partnership ?? saved;
  const { partnerNames, tierNames } = namesOf(resolvedPartnership);
  const conditionLabels = conditionAuditLabels(resolvedPartnership);

  return (
    <div className="scenario-workspace partnership-workspace">
      <section className="scenario-panel" aria-labelledby={`${prefix}partnership-title`}>
        <div className="scenario-panel-header">
          <div className="scenario-panel-heading">
            <h3 id={`${prefix}partnership-title`} className="scenario-panel-title">
              Partnership
            </h3>
            <p className="scenario-panel-subtitle">
              {isInvestment ? INVESTMENT_SUBTITLE : DEAL_SUBTITLE}
            </p>
          </div>
          <button
            ref={addButton}
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => {
              // Opening the editor is not removing.
              setConfirmingRemovalOf(null);
              if (isEmpty) {
                state.add();
              } else {
                state.edit();
              }
            }}
            disabled={blockedReason !== null || state.hasDraft || state.listStatus !== 'ready'}
            aria-expanded={state.hasDraft}
            aria-controls={state.hasDraft ? editorId : undefined}
            aria-describedby={blockedReason === null ? undefined : blockedReasonId}
          >
            {isEmpty ? 'Add Partnership' : 'Edit Partnership'}
          </button>
        </div>

        {blockedReason !== null && (
          <p id={blockedReasonId} className="scenario-blocked" role="status">
            {blockedReason}
          </p>
        )}

        {(state.listStatus === 'idle' || state.listStatus === 'loading') && (
          <p className="scenario-muted" role="status">
            Loading partnership…
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
          <p className="scenario-muted">{NO_PARTNERSHIP_MESSAGE}</p>
        )}

        {state.listStatus === 'ready' && saved !== null && !state.hasDraft && (
          <>
            <ul className="scenario-list partnership-saved-list" aria-label="Saved partners">
              {saved.partners.map((partner) => (
                <li key={partner.partner_id} className="scenario-list-item">
                  <div className="scenario-list-identity">
                    <span className="scenario-list-name">{partner.name}</span>
                    <span className="scenario-list-description">
                      {PARTNER_ROLE_LABELS[partner.role]}
                    </span>
                  </div>
                  <div className="scenario-list-overrides">
                    <span className="scenario-list-count">
                      {saved.promote_participant_ids.includes(partner.partner_id)
                        ? 'Promote participant'
                        : 'No promote'}
                    </span>
                  </div>
                </li>
              ))}
            </ul>

            <ul className="scenario-list partnership-saved-list" aria-label="Saved waterfall tiers">
              {saved.tiers.map((tier) => (
                <li key={tier.tier_id} className="scenario-list-item">
                  <div className="scenario-list-identity">
                    <span className="scenario-list-name">{tier.name}</span>
                    <span className="scenario-list-description">
                      {TIER_KIND_LABELS[tier.kind]}
                    </span>
                  </div>
                  <div className="scenario-list-overrides">
                    <span className="scenario-list-count">{`Sequence ${tier.sequence}`}</span>
                  </div>
                </li>
              ))}
            </ul>

            <p className="scenario-muted partnership-saved-count">
              {`${partnerCount(saved.partners.length)}, ${tierCount(saved.tiers.length)}`}
            </p>

            <div className="partnership-card-actions">
              {isConfirmingRemove ? (
                <div
                  className="partnership-remove-confirm"
                  role="group"
                  aria-label="Confirm removing the partnership"
                >
                  <span className="partnership-remove-question">{REMOVE_CONFIRM_QUESTION}</span>
                  <p className="partnership-section-note">{REMOVE_CONFIRM_MESSAGE}</p>
                  <div className="partnership-card-actions">
                    <button
                      type="button"
                      className="btn btn-danger btn-xs"
                      onClick={() => void state.remove()}
                      disabled={blockedReason !== null || state.isSaving}
                    >
                      {state.isSaving ? 'Removing…' : 'Remove Partnership'}
                    </button>
                    <button
                      ref={cancelRemoveButton}
                      type="button"
                      className="btn btn-ghost btn-xs"
                      onClick={() => setConfirmingRemovalOf(null)}
                      disabled={state.isSaving}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  ref={removeButton}
                  type="button"
                  className="btn btn-remove btn-xs"
                  onClick={() => setConfirmingRemovalOf(saved)}
                  disabled={blockedReason !== null || state.isSaving}
                >
                  Remove Partnership
                </button>
              )}
            </div>
          </>
        )}

        {state.saveError !== null && !state.hasDraft && (
          <div className="error-banner scenario-error" role="alert">
            <span>{state.saveError}</span>
          </div>
        )}

        {state.hasDraft && state.draft !== null && (
          <PartnershipEditor
            id={editorId}
            prefix={`${prefix}partnership`}
            form={state.draft}
            onChange={state.change}
            issues={state.saveIssues}
            saveError={state.saveError}
            isSaving={state.isSaving}
            locked={blockedReason !== null}
            lockedReason={blockedReason}
            onSave={() => void state.save()}
            onCancel={state.cancel}
          />
        )}
      </section>

      <section className="scenario-panel" aria-labelledby={`${prefix}partnership-analysis-title`}>
        <div className="scenario-panel-header">
          <div className="scenario-panel-heading">
            <h3 id={`${prefix}partnership-analysis-title`} className="scenario-panel-title">
              Partnership Analysis
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
            {state.isAnalyzing ? 'Analyzing…' : analysis === null ? 'Run Analysis' : 'Run Again'}
          </button>
        </div>

        {state.analysisError !== null && (
          <div className="error-banner scenario-error" role="alert">
            <span>{state.analysisError}</span>
            {state.analysisIssues.length > 0 && (
              <ul className="scenario-editor-feedback-list">
                {state.analysisIssues.map((issue) => (
                  <li key={`${issue.code}:${issue.partner_id ?? ''}:${issue.tier_id ?? ''}:${issue.message}`}>
                    {issue.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {analysis === null ? (
          <p className="scenario-muted">{ANALYSIS_ABSENT_MESSAGE}</p>
        ) : (
          <>
            {!state.isAnalysisCurrent && (
              <StaleAnalysisNotice message={STALE_PARTNERSHIP_MESSAGE} />
            )}
            {analysis.result !== null && analysis.primary_return !== undefined && (
              <p className="refinance-reference-notice" role="note">
                {PARTNER_REFINANCE_NOTE}
              </p>
            )}
            {analysis.result === null ? (
              <p className="scenario-muted">{NO_PARTNERSHIP_MESSAGE}</p>
            ) : (
              <PartnershipResults
                result={analysis.result}
                partnerNames={partnerNames}
                tierNames={tierNames}
                conditionLabels={conditionLabels}
              />
            )}
          </>
        )}
      </section>
    </div>
  );
}
