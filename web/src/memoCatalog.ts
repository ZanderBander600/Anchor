/**
 * Phase 7 Gate P7.10 Stage 4 -- the Investment Memo's presentation vocabulary.
 *
 * One place for every analyst-facing word the memo workspace says, so the
 * product cannot call the same thing two names in two panels. Nothing here
 * computes; it maps stored tokens to professional English and holds the copy
 * that explains a refusal.
 *
 * **No implementation vocabulary reaches the analyst.** Section 2 of the Stage 4
 * brief forbids enum names, internal ids, fingerprints and database terms in
 * normal views, so every backend token is translated here and
 * `web/src/memoArchitecture.test.ts` proves no raw token reaches a rendered
 * string.
 *
 * **The two decision acts are named differently on purpose (R-F).** An analyst
 * *recommends*; a committee *decides*. The labels below never let one read as
 * the other, and a committee outcome nobody has recorded reads "Not yet
 * recorded" rather than "Pending", which is an outcome somebody chose.
 */

import type {
  AnalystRecommendation,
  DecisionPerspectiveKind,
  EvidenceSourceKind,
  ExecutionComplexity,
  InvestmentCommitteeOutcome,
  MemoSectionKind,
  RiskSeverity,
  TermPriority,
} from './memoTypes';

export const MEMO_LIBRARY_LABEL = 'Investment Committee';
export const MEMO_WORKSPACE_LABEL = 'Investment Memo';

export const ANALYST_RECOMMENDATION_LABEL = 'Analyst Recommendation';
export const COMMITTEE_DECISION_LABEL = 'Investment Committee Decision';

/** What an unrecorded committee outcome reads as. The API returns `null` for
 * "nothing recorded" and `pending` for "the committee recorded that it is
 * pending"; those are different facts and the product says so. */
export const COMMITTEE_DECISION_UNRECORDED = 'Not yet recorded';

/** Section 8's label for a claim that cites no source. */
export const UNSOURCED_CLAIM_LABEL = 'Analyst Assertion — Source Not Attached';

export const RECOMMENDATION_LABELS: Record<AnalystRecommendation, string> = {
  approve: 'Approve',
  approve_with_conditions: 'Approve with Conditions',
  revise_and_resubmit: 'Revise and Resubmit',
  decline: 'Decline',
  insufficient_information: 'Insufficient Information',
};

export const RECOMMENDATION_ORDER: AnalystRecommendation[] = [
  'approve',
  'approve_with_conditions',
  'revise_and_resubmit',
  'decline',
  'insufficient_information',
];

export const COMMITTEE_LABELS: Record<InvestmentCommitteeOutcome, string> = {
  pending: 'Pending',
  approved: 'Approved',
  approved_with_conditions: 'Approved with Conditions',
  deferred: 'Deferred',
  declined: 'Declined',
};

export const COMMITTEE_ORDER: InvestmentCommitteeOutcome[] = [
  'pending',
  'approved',
  'approved_with_conditions',
  'deferred',
  'declined',
];

export const COMPLEXITY_LABELS: Record<ExecutionComplexity, string> = {
  low: 'Low',
  moderate: 'Moderate',
  high: 'High',
  not_assessed: 'Not Assessed',
};

export const COMPLEXITY_ORDER: ExecutionComplexity[] = ['low', 'moderate', 'high', 'not_assessed'];

export const SEVERITY_LABELS: Record<RiskSeverity, string> = {
  low: 'Low',
  moderate: 'Moderate',
  high: 'High',
  not_assessed: 'Not Assessed',
};

export const SEVERITY_ORDER: RiskSeverity[] = ['low', 'moderate', 'high', 'not_assessed'];

export const PRIORITY_LABELS: Record<TermPriority, string> = {
  required: 'Required',
  desired: 'Desired',
  negotiable: 'Negotiable',
};

export const PRIORITY_ORDER: TermPriority[] = ['required', 'desired', 'negotiable'];

export const EVIDENCE_KIND_LABELS: Record<EvidenceSourceKind, string> = {
  case_document: 'Case Document',
  rent_comp: 'Rent Comparable',
  sales_comp: 'Sales Comparable',
  broker_research: 'Broker Research',
  analyst_assumption: 'Analyst Assumption',
  imported_model: 'Imported Model',
  ai_extracted_approved: 'Extracted, Analyst Approved',
  other: 'Other',
};

export const EVIDENCE_KIND_ORDER: EvidenceSourceKind[] = [
  'case_document',
  'rent_comp',
  'sales_comp',
  'broker_research',
  'analyst_assumption',
  'imported_model',
  'ai_extracted_approved',
  'other',
];

export const PERSPECTIVE_LABELS: Record<DecisionPerspectiveKind, string> = {
  project: 'Project',
  position: 'Position',
  partner: 'Partner',
};

/** Each authored section: its heading, and the one line that says what belongs
 * in it. The hint is product copy, not validation -- nothing here refuses an
 * item for being in the "wrong" section. */
export const SECTION_LABELS: Record<MemoSectionKind, { title: string; hint: string }> = {
  thesis: {
    title: 'Investment Thesis',
    hint: 'Why this is the preferred use of capital.',
  },
  business_plan_milestone: {
    title: 'Business Plan',
    hint: 'The milestones this investment is underwritten to achieve.',
  },
  structural_protection: {
    title: 'Structural Protections',
    hint: 'What protects this position if the plan does not hold.',
  },
  reputational_concern: {
    title: 'Reputational Concerns',
    hint: 'Concerns that are not financial but still bear on the decision.',
  },
  dealbreaker: {
    title: 'Dealbreakers',
    hint: 'What would end this transaction outright.',
  },
  condition_to_approval: {
    title: 'Conditions to Approval',
    hint: 'What must be satisfied before closing.',
  },
};

/** The order authored sections are presented in, in the workspace and the
 * report alike. Thesis leads because it is the argument. */
export const SECTION_ORDER: MemoSectionKind[] = [
  'thesis',
  'business_plan_milestone',
  'structural_protection',
  'reputational_concern',
  'dealbreaker',
  'condition_to_approval',
];

/** Analyst-facing names for the backend's thirteen dependency classes. A stale
 * memo says "the Business Plan changed", never `business_plan`. */
export const DEPENDENCY_LABELS: Record<string, string> = {
  investment_membership: 'Investment membership',
  underwriting: 'Unit underwriting',
  business_plan: 'Business Plan',
  strategy: 'Strategy definition',
  scenario: 'Scenario definition',
  project_variant: 'Project analysis',
  capital_structure: 'Capital Structure',
  partnership: 'Partnership',
  valuation_definitions: 'Valuation definitions',
  valuation_results: 'Valuation results',
  decision_perspective: 'Decision perspective',
  evidence: 'Evidence',
  memo_content: 'Memo content',
};

/**
 * How a publication refusal is grouped for the analyst.
 *
 * The backend returns one typed refusal per problem. Presenting thirteen codes
 * as a flat red list asks the analyst to work out what to *do*, so each code is
 * mapped to the action that fixes it. The backend's own message and affected
 * scope are always shown beneath -- grouping adds a heading, and never replaces
 * the reason.
 */
export type RefusalGroup = 'content' | 'decision' | 'evidence' | 'valuation';

export const REFUSAL_GROUPS: Record<string, RefusalGroup> = {
  memo_invalid: 'content',
  blank_decision_ask: 'content',
  no_selected_decision: 'decision',
  selected_strategy_missing: 'decision',
  selected_scenario_missing: 'decision',
  selected_perspective_missing: 'decision',
  selected_cell_unresolved: 'decision',
  evidence_not_found: 'evidence',
  evidence_not_approved: 'evidence',
  valuation_unavailable_for_required_view: 'valuation',
};

export const REFUSAL_GROUP_LABELS: Record<RefusalGroup, { title: string; action: string }> = {
  content: {
    title: 'Complete the memo',
    action: 'Required narrative is missing or not yet well formed.',
  },
  decision: {
    title: 'Resolve the decision context',
    action: 'The Strategy, Scenario and perspective this memo recommends must currently resolve.',
  },
  evidence: {
    title: 'Approve the cited sources',
    action: 'A claim cites a source that is missing or that you have not approved.',
  },
  valuation: {
    title: 'Resolve the included valuations',
    // prettier-ignore
    action: 'A valuation this memo includes, or that a value-sized funding consumes, has no value. A view you are only exploring does not appear here.',
  },
};

export function refusalGroupOf(code: string): RefusalGroup {
  return REFUSAL_GROUPS[code] ?? 'content';
}

/** The order refusal groups are shown in: the decision context first, because
 * an unresolved cell usually explains the valuation failures beneath it. */
export const REFUSAL_GROUP_ORDER: RefusalGroup[] = ['decision', 'valuation', 'evidence', 'content'];

/** What leaving the memo would discard, worded for the confirmation, or `null`
 * when nothing would be lost. */
export function memoLeaveWarning(isDirty: boolean): string | null {
  return isDirty
    ? 'This memo has unsaved changes. Leaving now discards them.'
    : null;
}

/** Namespaced element ids, so the memo workspace's tabs and panels never
 * collide with an open Deal's or an Investment's own. */
export function memoId(suffix: string): string {
  return `memo-${suffix}`;
}

/** The label a valuation view carries in the workspace: what it is, and why it
 * is in this memo. */
export function valuationRoleLabel(options: {
  selected: boolean;
  consumed: boolean;
  systemControlled: boolean;
}): string {
  if (options.systemControlled) {
    return 'System-derived';
  }
  if (options.selected && options.consumed) {
    return 'Included; consumed by funding';
  }
  if (options.consumed) {
    return 'Consumed by funding';
  }
  if (options.selected) {
    return 'Included in this memo';
  }
  return 'Exploratory — not included';
}

/** What the analyst is told about an exploratory view, so "not included" never
 * reads as a problem to fix. */
// prettier-ignore
export const EXPLORATORY_VALUATION_HINT =
  'A view you have not included, and that no funding consumes, is working state. It never blocks publication and you are never asked to delete it.';

export const DRAFT_PREVIEW_BANNER =
  'Draft preview — not published. Figures follow the current analysis and will move as you work.';

// prettier-ignore
export const PUBLISHED_IMMUTABLE_HINT =
  'A published version is a permanent record and cannot be edited. Continue in the draft and publish again to record a change.';

// prettier-ignore
export const STALE_VERSION_HINT =
  'The analysis has changed since this version was published. The published version itself is unchanged; what follows describes what has moved since.';

// prettier-ignore
export const DELETE_EVIDENCE_IN_USE_HINT =
  'This source cannot be removed while a claim or a valuation still cites it. Detach it first, so no claim is left pointing at a source that no longer exists.';

/** The reserved implicit Base keys.
 *
 * The backend names the Base Strategy and Base Scenario by these keys rather
 * than storing a row for either, so "the Base cell" is an ordinary selection
 * and not a missing one. `tests/test_p7_10_stage_4_architecture.py` compares
 * both against `anchor.analysis.strategy`, so they cannot drift.
 */
export const BASE_STRATEGY_KEY = 'base';
export const BASE_SCENARIO_KEY = 'base';

export const BASE_STRATEGY_NAME = 'Base Strategy';
export const BASE_SCENARIO_NAME = 'Base Scenario';
