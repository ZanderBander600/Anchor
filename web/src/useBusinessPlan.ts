/**
 * Phase 6 Gate D6.6 -- one mode's Business Plan state.
 *
 * Each operating mode holds its own open deal, so each holds its own plan --
 * but through this one hook, over the one draft shape in `businessPlan.ts`.
 * Quick, Detailed and Lease-Level therefore cannot drift into three Business
 * Plan behaviours: they share how a plan is held, validated, submitted,
 * refused, loaded and cleared, and differ only in which deal it belongs to.
 *
 * The hook owns no dirty flag and no staleness. Each mode already has one
 * dirty snapshot and one downstream-reset rule; the plan joins those rather
 * than growing a second system beside them.
 */

import { useState } from 'react';
import { ApiError } from './api';
import {
  blankBusinessPlanDraft,
  businessPlanDraftFromInput,
  prepareBusinessPlanInput,
  placeBusinessPlanApiIssues,
  validateBusinessPlanDraft,
} from './businessPlan';
import type {
  BusinessPlanDraft,
  BusinessPlanFieldIssue,
  BusinessPlanInput,
} from './businessPlan';

/** Said once, wherever a request could not be built because of the plan. */
export const BUSINESS_PLAN_INCOMPLETE_MESSAGE =
  'Some Business Plan rows are incomplete or invalid. They are marked in the Business Plan section of the Acquisition tab.';

export interface BusinessPlanState {
  /** The plan exactly as the editor shows it. */
  draft: BusinessPlanDraft;
  /** Everything the editor should mark: client issues once a submission has
   * been attempted, and the backend's issues from the last refusal. */
  issues: BusinessPlanFieldIssue[];
  /** An edit from the editor. The caller also runs its own downstream reset,
   * exactly as for any other assumption. */
  change: (next: BusinessPlanDraft) => void;
  /** The plan as the wire contract, or `null` after marking why not. Every
   * request that carries deal state takes its plan from here. */
  prepare: () => BusinessPlanInput | null;
  /** Places a refusal's Business Plan issues on their rows, resolved against
   * the plan that request actually carried. True when there were any. */
  recordApiFailure: (caught: unknown, submitted: BusinessPlanInput | null) => boolean;
  clearApiIssues: () => void;
  /** Hydrates a saved deal's plan, exactly, and returns the draft so the
   * caller's saved snapshot holds the same value. */
  load: (plan: BusinessPlanInput | null | undefined) => BusinessPlanDraft;
  /** A new, empty plan -- for New Deal and for deleting the open deal. */
  reset: () => BusinessPlanDraft;
}

export function useBusinessPlan(): BusinessPlanState {
  const [draft, setDraft] = useState<BusinessPlanDraft>(blankBusinessPlanDraft);
  // Client issues stay quiet until a submission is attempted, so a row the
  // analyst has just added is not greeted with "required" before they type.
  // Once shown they track the draft live, and disappear as rows are fixed.
  const [showValidation, setShowValidation] = useState(false);
  const [apiIssues, setApiIssues] = useState<BusinessPlanFieldIssue[]>([]);

  const clientIssues = showValidation ? validateBusinessPlanDraft(draft) : [];

  function load(plan: BusinessPlanInput | null | undefined): BusinessPlanDraft {
    const next = businessPlanDraftFromInput(plan);
    setDraft(next);
    setShowValidation(false);
    setApiIssues([]);
    return next;
  }

  return {
    draft,
    issues: [...clientIssues, ...apiIssues],
    change(next) {
      setDraft(next);
      // A refusal describes the plan that was sent; once the analyst edits it,
      // the placement may no longer be true. The next submission re-asks.
      setApiIssues([]);
    },
    prepare() {
      // A new submission supersedes the last refusal; if this one is refused
      // too, `recordApiFailure` places its issues afresh.
      setApiIssues([]);
      const prepared = prepareBusinessPlanInput(draft);
      if (!prepared.ok) {
        setShowValidation(true);
        return null;
      }
      setShowValidation(false);
      return prepared.plan;
    },
    recordApiFailure(caught, submitted) {
      const found =
        caught instanceof ApiError && submitted !== null
          ? placeBusinessPlanApiIssues(caught.businessPlanIssues, submitted)
          : [];
      setApiIssues(found);
      return found.length > 0;
    },
    clearApiIssues() {
      setApiIssues([]);
    },
    load,
    reset() {
      return load(null);
    },
  };
}
