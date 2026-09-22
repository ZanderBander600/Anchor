/**
 * Phase 7 Gate P7.10 Stage 4 -- the Investment Memo wire contracts.
 *
 * These mirror the accepted Stage 2 and Stage 4 API exactly. Every token below
 * is the backend's own wire value, and `tests/test_p7_10_stage_4_architecture.py`
 * compares each union here against the Python enum it mirrors, so a member added
 * on one side and forgotten on the other fails rather than silently narrowing
 * what the product can represent.
 *
 * **Nothing here is computed.** A memo carries no amount, rate, return, delta or
 * ranking: every figure the workspace and the report show arrives already
 * computed and already formatted from the backend, as
 * `MemoReportMetric.value`. The frontend selects and displays; it never derives.
 * `web/src/memoArchitecture.test.ts` parses every Stage 4 module and rejects
 * arithmetic, aggregation, ordering by value and re-parsing.
 *
 * **Two decision acts, never one (R-F).** `analyst_recommendation` lives on the
 * draft and is the analyst's proposal. `InvestmentCommitteeOutcome` is recorded
 * against a *published version*, after publication, through its own route. They
 * are different types here because they are different acts, and no code path
 * converts one into the other.
 *
 * **Stage 4 ships no AI.** There is no proposal, prompt, grounding or AI state
 * in this file or in any module that imports it. Stage 3 is deferred and
 * unstarted.
 */

/** The analyst's proposed action (Section 7.2). Never the committee's. */
export type AnalystRecommendation =
  | 'approve'
  | 'approve_with_conditions'
  | 'revise_and_resubmit'
  | 'decline'
  | 'insufficient_information';

/** The committee's own outcome (Section 7.5). A deliberately different
 * vocabulary from the analyst's: `deferred` is a committee outcome, and
 * `insufficient_information` and `revise_and_resubmit` are analyst
 * recommendations, so neither list can stand in for the other. */
export type InvestmentCommitteeOutcome =
  | 'pending'
  | 'approved'
  | 'approved_with_conditions'
  | 'deferred'
  | 'declined';

/** An analyst-authored qualitative label. Never calculated from a return. */
export type ExecutionComplexity = 'low' | 'moderate' | 'high' | 'not_assessed';

/** A risk's analyst-authored severity. Stating a mitigant never lowers it. */
export type RiskSeverity = 'low' | 'moderate' | 'high' | 'not_assessed';

/** How hard the analyst will hold a term. */
export type TermPriority = 'required' | 'desired' | 'negotiable';

/** Which authored list a plain text item belongs to. Risks and terms are
 * absent because each carries fields an ordinary item does not. */
export type MemoSectionKind =
  | 'thesis'
  | 'structural_protection'
  | 'reputational_concern'
  | 'dealbreaker'
  | 'condition_to_approval'
  | 'business_plan_milestone';

/** What kind of source an Evidence Reference names. */
export type EvidenceSourceKind =
  | 'case_document'
  | 'rent_comp'
  | 'sales_comp'
  | 'broker_research'
  | 'analyst_assumption'
  | 'imported_model'
  | 'ai_extracted_approved'
  | 'other';

/** Which stakeholder's returns the recommendation is made from. */
export type DecisionPerspectiveKind = 'project' | 'position' | 'partner';

/** One authored statement in one section, with the sources it rests on. */
export interface MemoItem {
  item_id: string;
  section: MemoSectionKind;
  display_order: number;
  text: string;
  /** The Evidence References supporting *this claim* (R-G). Zero is a real
   * answer: an unsupported statement is a storable analyst assertion, labelled
   * as one, never silently upgraded to a sourced fact. */
  evidence_ids: string[];
}

export interface MemoRiskItem {
  item_id: string;
  display_order: number;
  text: string;
  severity: RiskSeverity;
  residual_risk: RiskSeverity;
  mitigant: string | null;
  evidence_ids: string[];
}

export interface MemoTermItem {
  item_id: string;
  display_order: number;
  text: string;
  priority: TermPriority;
  evidence_ids: string[];
}

export interface MemoEvidenceReference {
  evidence_id: string;
  investment_id: string;
  source_kind: EvidenceSourceKind;
  title: string;
  reference: string;
  as_of_date: string | null;
  /** The analyst's own approval state. An unapproved source is a real record:
   * it exists and is visible, it simply cannot support a published claim. */
  approved: boolean;
  display_order: number;
}

/** The one decision cell the memo recommends. Naming it selects; it changes no
 * Strategy, Scenario, position or Partnership. */
export interface SelectedDecision {
  strategy_id: string;
  scenario_id: string;
  perspective: DecisionPerspectiveKind;
  position_id: string | null;
  partner_id: string | null;
}

/** The one mutable draft belonging to an Investment. */
export interface InvestmentMemoDraft {
  memo_id: string;
  investment_id: string;
  prepared_by: string | null;
  decision_ask: string;
  analyst_recommendation: AnalystRecommendation;
  executive_summary: string;
  execution_complexity: ExecutionComplexity;
  return_on_time_notes: string;
  selected_decision: SelectedDecision | null;
  items: MemoItem[];
  risk_items: MemoRiskItem[];
  term_items: MemoTermItem[];
  /** The reusable register: the sources the package presents as a whole. It is
   * distinct from, and does not replace, each item's own `evidence_ids`. */
  evidence_ids: string[];
  /** The memo's explicit statement of which valuation views it includes. It is
   * the only thing that makes a view a published dependency -- never inferred
   * from display order, existence or recency (Section 22.6). */
  selected_valuation_timepoint_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface InvestmentCommitteeDecision {
  memo_version_id: string;
  decision: InvestmentCommitteeOutcome;
  decision_note: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
}

/** One frozen claim-to-evidence link of a published version. */
export interface MemoClaimEvidence {
  claim_kind: 'item' | 'risk' | 'term';
  item_id: string;
  evidence_id: string;
  ordinal: number;
}

/** One valuation view as a published version froze it. `value` is `null` for an
 * unavailable view and is never zero-filled. */
export interface MemoVersionValuation {
  timepoint_id: string;
  kind: string;
  label: string;
  model_month: number;
  scope_kind: string;
  status: string;
  value: number | null;
  unavailable_reason: string | null;
  unavailable_message: string | null;
  selected: boolean;
  consumed: boolean;
}

export interface MemoDependency {
  dependency_class: string;
  scope_id: string;
  fingerprint: string;
}

export interface InvestmentMemoVersion {
  version_id: string;
  investment_id: string;
  version_number: number;
  prepared_by: string | null;
  decision_ask: string;
  analyst_recommendation: AnalystRecommendation;
  executive_summary: string;
  execution_complexity: ExecutionComplexity;
  return_on_time_notes: string;
  selected_decision: SelectedDecision;
  items: MemoItem[];
  risk_items: MemoRiskItem[];
  term_items: MemoTermItem[];
  evidence: MemoEvidenceReference[];
  claim_evidence: MemoClaimEvidence[];
  valuations: MemoVersionValuation[];
  dependencies: MemoDependency[];
  memo_content_fingerprint: string;
  published_fingerprint: string;
  created_at: string;
}

/** Why a published version no longer matches the state it was published
 * against. `current_fingerprint` is `null` where the dependency can no longer
 * be computed at all -- a named condition, never a silent equality. */
export interface MemoStaleDependency {
  dependency_class: string;
  scope_id: string;
  published_fingerprint: string;
  current_fingerprint: string | null;
  reason: string;
}

export interface MemoFreshnessReport {
  investment_id: string;
  version_id: string;
  version_number: number;
  freshness: 'current' | 'stale';
  stale_classes: string[];
  stale_dependencies: MemoStaleDependency[];
}

/** One specific reason the draft may not be published. Never a generic
 * failure: the product disables publication with these and says which. */
export interface PublicationRefusal {
  code: string;
  message: string;
  scope_id: string | null;
  field: string | null;
  /** The valuation's *own* structured reason, where a required view is
   * unavailable. Carried through rather than flattened. */
  unavailable_reason: string | null;
}

export interface PublicationReadiness {
  investment_id: string;
  publishable: boolean;
  refusals: PublicationRefusal[];
}

/** One structural refusal from a memo or evidence write. */
export interface MemoIssue {
  code: string;
  message: string;
  item_id: string | null;
  field: string | null;
}

// ---------------------------------------------------------------------------
// Valuation views (Sections 5, 6.2)
// ---------------------------------------------------------------------------

export interface ValuationUnavailable {
  status: string;
  reason_code: string;
  reason: string;
  scope_id: string | null;
  model_month: number | null;
}

export interface ValuationUnitView {
  unit_id: string;
  status: string;
  value: number | null;
  /** `true` for an analyst-supplied value, which is displayed as
   * **Analyst-Supplied Value** everywhere so no reader can mistake an analyst's
   * own number for an Anchor valuation (Section 5.4). */
  analyst_supplied: boolean;
  forward_noi: number | null;
  cap_rate: number | null;
  evidence_id: string | null;
  unavailable: ValuationUnavailable | null;
}

export interface ValuationView {
  timepoint_id: string;
  kind: string;
  label: string;
  model_month: number;
  scope_kind: string;
  status: string;
  value: number | null;
  unavailable: ValuationUnavailable | null;
  unit_views: ValuationUnitView[];
}

export interface ValuationFundingState {
  position_id: string;
  event_id: string;
  timepoint_id: string;
  status: string;
  /** Deliberately absent on an unresolved funding: Section 6.2 requires the
   * state to carry no amount at all rather than a fabricated or zero one. */
  amount: number | null;
  unavailable: ValuationUnavailable | null;
}

export interface ValuationSurface {
  investment_id: string;
  strategy_id: string;
  scenario_id: string;
  unit_ids: string[];
  hold_period: number;
  views: ValuationView[];
  evidence_blocked: unknown[];
  funding_states: ValuationFundingState[];
  consumed_timepoint_ids: string[];
  project_source_fingerprint: string;
  structured_source_fingerprint: string;
  valuation_definition_fingerprint: string;
  valuation_result_fingerprint: string;
}

export interface ValuationTimepointMethod {
  kind: 'direct_cap' | 'analyst_value';
  cap_rate?: number;
  amount?: number;
  evidence_id?: string;
}

export interface UnitValuationInstruction {
  unit_id: string;
  method: ValuationTimepointMethod;
}

export interface ValuationTimepoint {
  timepoint_id: string;
  investment_id: string;
  kind: 'as_is' | 'stabilized' | 'custom';
  label: string;
  model_month: number;
  unit_instructions: UnitValuationInstruction[];
  display_order: number;
}

// ---------------------------------------------------------------------------
// The assembled report (Stage 4)
// ---------------------------------------------------------------------------

/** Which memo state a report was assembled from. A `draft_preview` may never
 * become a final PDF; only a `published_version` may. */
export type MemoReportOrigin = 'draft_preview' | 'published_version';

export type ReportFreshness = 'current' | 'stale' | 'not_applicable';

export interface ReportUnavailable {
  reason_code: string;
  reason: string;
  /** What the surface prints in place of a number. Never `0`, `$0`, `-` or an
   * empty string. */
  label: string;
}

/** One labelled figure. Exactly one of `value` and `unavailable` is set, and
 * `value` is already formatted by the backend -- the frontend never formats a
 * report figure itself, because formatting is where a rounding convention could
 * diverge from Anchor's. */
export interface MemoReportMetric {
  label: string;
  value: string | null;
  unavailable: ReportUnavailable | null;
  note: string | null;
}

export interface MemoReportTable {
  caption: string;
  headers: string[];
  rows: string[][];
  align_right: number[];
  emphasize_rows: number[];
  note: string | null;
}

export interface MemoReportNarrativeItem {
  text: string;
  detail: string | null;
  labels: string[];
  evidence_labels: string[];
  /** `false` when the claim cites nothing, which the surface labels rather than
   * leaving the claim looking sourced. */
  sourced: boolean;
}

export interface MemoReportEvidenceEntry {
  title: string;
  source_kind: string;
  reference: string;
  as_of_date: string | null;
  approved: boolean;
  cited_by: string[];
}

export interface MemoReportValuation {
  label: string;
  kind: string;
  timing: string;
  scope: string;
  value: string | null;
  unavailable: ReportUnavailable | null;
  selected: boolean;
  consumed: boolean;
  system_controlled: boolean;
  analyst_supplied: boolean;
}

export interface MemoReportDisclosure {
  title: string;
  detail: string;
  scope: string | null;
}

export interface MemoReportSection {
  title: string;
  subtitle: string | null;
  narrative: MemoReportNarrativeItem[];
  metrics: MemoReportMetric[];
  tables: MemoReportTable[];
  body: string | null;
  disclosures: MemoReportDisclosure[];
}

export interface MemoReportPackage {
  origin: MemoReportOrigin;
  investment_id: string;
  investment_name: string;
  asset_type: string | null;
  market: string | null;
  version_number: number | null;
  version_id: string | null;
  published_at: string | null;
  prepared_by: string | null;
  generated_at: string;
  decision_ask: string;
  analyst_recommendation: string;
  committee_decision: string | null;
  committee_note: string | null;
  executive_summary: string;
  strategy_label: string;
  scenario_label: string;
  perspective_label: string;
  freshness: ReportFreshness;
  stale_classes: string[];
  verification_code: string | null;
  key_metrics: MemoReportMetric[];
  valuations: MemoReportValuation[];
  sections: MemoReportSection[];
  evidence: MemoReportEvidenceEntry[];
  disclosures: MemoReportDisclosure[];
  concluding_statement: string | null;
  confidentiality: string;
}

// ---------------------------------------------------------------------------
// The library
// ---------------------------------------------------------------------------

/** One row of the Investment Committee library.
 *
 * Deliberately carries no freshness: computing it would cost one full analysis
 * per row. Freshness is a per-version question the workspace asks for the one
 * version it is showing. */
export interface MemoLibraryEntry {
  investment_id: string;
  /** Set when this memo belongs to a standalone Deal's hidden one-unit
   * Investment; the product keeps saying "Deal" for it throughout. */
  deal_id: string | null;
  name: string;
  unit_count: number;
  asset_type: string | null;
  asset_subtype: string | null;
  has_draft: boolean;
  draft_updated_at: string | null;
  analyst_recommendation: AnalystRecommendation | null;
  committee_decision: InvestmentCommitteeOutcome | null;
  latest_version_id: string | null;
  latest_version_number: number | null;
  latest_published_at: string | null;
  version_count: number;
  strategy_id: string | null;
  scenario_id: string | null;
  perspective: DecisionPerspectiveKind | null;
}

/**
 * The PUT body for a draft.
 *
 * Deliberately not `InvestmentMemoDraft`: `memo_id`, `investment_id`,
 * `created_at` and `updated_at` are the store's to set, and a client that sent
 * them would be claiming authority over identity and timestamps it does not
 * have. The API refuses an unexpected key, so this shape is exact rather than
 * approximate.
 */
export interface MemoDraftRequest {
  prepared_by: string | null;
  decision_ask: string;
  analyst_recommendation: AnalystRecommendation;
  executive_summary: string;
  execution_complexity: ExecutionComplexity;
  return_on_time_notes: string;
  selected_decision: SelectedDecision | null;
  items: MemoItem[];
  risk_items: MemoRiskItem[];
  term_items: MemoTermItem[];
  evidence_ids: string[];
  selected_valuation_timepoint_ids: string[];
}
