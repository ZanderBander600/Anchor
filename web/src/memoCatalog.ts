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

/**
 * Analyst-facing sentences for every typed unavailable reason.
 *
 * The backend's own `reason` is a precise developer-facing sentence that names
 * the Investment, the Unit and the timepoint by their opaque ids -- right for a
 * log, and exactly what Section 2 keeps out of an analyst view. The stable
 * thing is the `reason_code`, so the workspace translates that.
 *
 * Mirrors `_UNAVAILABLE_LABELS` in `src/anchor/reporting/assembly.py`, and
 * `tests/test_p7_10_stage_4_architecture.py` holds the two tables to the same
 * key set so neither can drift.
 */
export const UNAVAILABLE_REASON_LABELS: Record<string, string> = {
  not_authored: 'No valuation is authored at this timepoint.',
  incomplete_units:
    'At least one Unit has no value at this timepoint, so the Investment has none.',
  non_positive_forward_noi:
    'Forward NOI is not positive at this timepoint, so direct capitalization has no meaning here.',
  evidence_not_approved:
    'The analyst-supplied value rests on a source that has not been approved.',
  variant_invalid: 'The selected Strategy and Scenario did not resolve.',
  funding_requirement_unresolved: 'A value-sized funding could not be sized.',
  result_unavailable: 'Anchor did not report this figure for the selected analysis.',
  stale_dependency: 'This figure rests on state that has changed since publication.',
  not_implemented_for_scope: 'Unavailable — Not Implemented for This Scope.',
  reserved_exit_month:
    'This timepoint falls at the exit month, whose value is the system-derived Exit view.',
  outside_hold_horizon:
    'This timepoint falls beyond the selected analysis’s hold period. The same definition may resolve under a longer hold.',
  unit_not_in_variant: 'This valuation names a Unit the selected analysis does not hold.',
  unit_not_valued: 'The selected analysis holds a Unit this valuation does not instruct.',
};

/** One unavailable state as analyst-facing text, by its stable code. */
export function unavailableReasonLabel(reasonCode: string | null | undefined): string {
  if (reasonCode === null || reasonCode === undefined) {
    return 'No value is reported here.';
  }
  return UNAVAILABLE_REASON_LABELS[reasonCode] ?? 'No value is reported here.';
}

/**
 * Analyst-facing sentences for every publication refusal.
 *
 * **Added after browser QA at the Stage 4 independent review.** Readiness used
 * to print the backend's own `message`, on the reasoning that a refusal should
 * not be paraphrased. Cross-mode QA showed what that actually puts on screen:
 * *"Investment '2fa67abf88a2445a8d41eb27fa1af123' has no value at valuation
 * timepoint 'as-is-3b93ed': '5889bb98…' (unit_not_valued)"* -- three opaque
 * ids and a raw code, in the one place an analyst is being asked to go and fix
 * something. That is the implementation vocabulary Section 2 keeps out of an
 * analyst view, and it is the same problem the unavailable reasons above were
 * already translated to avoid.
 *
 * So refusals are translated the same way, from the same kind of stable code,
 * and `tests/test_p7_10_stage_4_architecture.py` holds this table to
 * `PublicationRefusalCode` exactly as it holds the one above. Nothing is
 * softened: each sentence says what is wrong and what would fix it. The
 * upstream `unavailable_reason`, where a refusal carries one, is appended
 * through the table above, so a valuation still states its own specific
 * reason.
 */
export const PUBLICATION_REFUSAL_LABELS: Record<string, string> = {
  memo_invalid: 'The memo is not complete enough to publish. Its own issues say what is missing.',
  no_selected_decision:
    'No decision cell is selected. A memo recommends one Strategy, Scenario and perspective.',
  selected_strategy_missing: 'The Strategy this memo was written against no longer exists.',
  selected_scenario_missing: 'The Scenario this memo was written against no longer exists.',
  selected_perspective_missing:
    'The position or partner this memo was written from is not a perspective of this Investment.',
  selected_cell_unresolved:
    'The selected Strategy, Scenario and perspective do not currently produce a complete result.',
  blank_decision_ask: 'The decision being requested is blank.',
  evidence_not_found: 'A source this memo cites is no longer in the register.',
  evidence_not_approved:
    'A source this memo cites has not been approved, so the memo would present it as supporting.',
  valuation_unavailable_for_required_view:
    'A valuation this memo depends on has no value, and no version is published with a figure invented in its place.',
};

/** One publication refusal as analyst-facing text, with its own upstream
 * reason appended where the refusal carries one. */
export function publicationRefusalLabel(
  code: string,
  unavailableReason?: string | null,
): string {
  const sentence =
    PUBLICATION_REFUSAL_LABELS[code] ?? 'This memo cannot be published yet.';
  if (unavailableReason === null || unavailableReason === undefined) {
    return sentence;
  }
  return [sentence, unavailableReasonLabel(unavailableReason)].join(' ');
}

/** Whether a scope is a stored record's opaque id rather than something the
 * analyst named. Those are shown to nobody; an id the analyst chose, such as a
 * valuation timepoint or a position, is shown as it is. */
export function isOpaqueId(scope: string | null | undefined): boolean {
  return typeof scope === 'string' && /^[0-9a-f]{12,}$/.test(scope);
}

/**
 * A stored timestamp as a date an analyst reads.
 *
 * The wire carries a full ISO instant, which is exactly right for an identity
 * and exactly wrong in a library row or on a memorandum: a reader wants
 * "Sep 21, 2026", not "2026-09-22T00:41:20.099030+00:00". One function, so the
 * library and the version list cannot render the same fact two ways.
 *
 * An unparseable value is returned as recorded rather than dropped -- a
 * timestamp nobody can read still beats a row that silently lost it.
 */
export function displayDate(value: string | null | undefined): string | null {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}
