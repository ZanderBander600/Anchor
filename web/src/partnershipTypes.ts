/**
 * Phase 7 Gate P7.9 Stage 3 -- the typed wire contracts of the Partnership API.
 *
 * Mirrors, field for field, what `src/anchor/api.py` returns for the persisted
 * Partnership, the Partnership variant fingerprint and analysis, the Partner
 * perspectives and the `PARTNER` Decision Matrix. Nothing here computes,
 * resolves or validates anything: the Stage 1 validator decides what a
 * Partnership may say, and the Stage 1 engine produces every figure the
 * waterfall leads to.
 *
 * **Every typed variant carries its `kind`.** A tier's split rule and a hurdle's
 * condition are unions, and JSON cannot tell a union member apart by its fields,
 * so the backend sends the discriminator its one codec
 * (`anchor.deals.partnership_codec`) spells, and this file reads it. A hurdle's
 * subject and a catch-up's recipient carry their own Stage 1 `kind`. Nothing is
 * inferred from which fields happen to be present.
 *
 * **`null` is a statement, not an absence.** On the Partnership routes a
 * `partnership` of `null` means *this owner states no Partnership*, and on a
 * Strategy's `PARTNERSHIP` root overlay it means *this Strategy deliberately has
 * none* -- which is a different thing from omitting the overlay, which inherits
 * the Base Partnership.
 *
 * **`partner_id` is the identity (P-8).** A partner's `name` and `role` are
 * presentation: the role is reporting-only, it never selects a subject,
 * recipient or participant, it is excluded from every fingerprint, and it may
 * differ between the Base Partnership and each Strategy's own. Every matrix cell
 * therefore carries its *own* `partner_name` and `partner_role`.
 *
 * **Three layers of identity.** `project_source_fingerprint` is the Project
 * variant's own; `structured_source_fingerprint` is that plus the resolved
 * Capital Structure; `partnership_source_fingerprint` is *that* plus the
 * resolved Partnership's economics -- and is `null` when the variant resolves no
 * Partnership at all (FP-2).
 */

import type { PrimaryReturnView } from './capitalTypes';
import type { IrrStatus } from './types';

// =============================================================================
// The authored contract
// =============================================================================

/** Mirrors `PartnerRole`. Reporting only: it selects nothing. */
export type PartnerRole = 'lp' | 'gp' | 'co_investor';

/** Mirrors `ContributionRule`. One member in v1, and still stated explicitly. */
export type ContributionRule = 'pro_rata_by_commitment';

/** Mirrors `TierKind`. */
export type TierKind = 'hurdle' | 'catch_up' | 'residual';

/** Mirrors `SplitRule`. */
export type SplitRule = 'explicit' | 'pro_rata_by_contribution';

/** Mirrors `HurdleSubjectKind` (Q1). */
export type HurdleSubjectKind = 'partner' | 'investor_class' | 'economic_account';

/** Mirrors `EconomicAccount`. One member in v1. */
export type EconomicAccount = 'all_common_equity';

/** Mirrors `HurdleCombinator`. Required even for a single condition. */
export type HurdleCombinator = 'all' | 'any';

/** Mirrors `AccrualConvention`, the one enum P7.7 and P7.9 share (Q21). */
export type PartnershipAccrualConvention = 'simple' | 'annual_compound';

/** Mirrors `SimpleDistributionOrder`. Required on a SIMPLE condition, and
 * forbidden on any other. */
export type SimpleDistributionOrder = 'accrued_return_first' | 'capital_first';

/** Mirrors `CatchUpRecipientKind`. There is deliberately no economic-account
 * member: an all-partners recipient would make the target share meaningless
 * (Section 4.3). */
export type CatchUpRecipientKind = 'partner' | 'investor_class';

/** Mirrors `Partner`. `investor_class` is economic wherever a hurdle or a
 * catch-up names it; `name` and `role` are presentation. */
export interface Partner {
  partner_id: string;
  name: string;
  role: PartnerRole;
  investor_class: string | null;
  commitment_share: number;
}

/** Mirrors `BenchmarkShare` and `SplitShare`: both are one partner's share of
 * one table. They are separate backend types over identical wire fields. */
export interface PartnerShareRow {
  partner_id: string;
  share: number;
}

/** Mirrors `PromoteBenchmark` (Q2): a literal table, one share per partner,
 * never derived from or linked to the commitment shares. */
export interface PromoteBenchmark {
  shares: PartnerShareRow[];
}

/** Mirrors `TierSplit`. `pro_rata_by_contribution` carries no fields, and is
 * refused on a catch-up tier (R-D). */
export type TierSplit =
  | { kind: 'explicit'; shares: PartnerShareRow[] }
  | { kind: 'pro_rata_by_contribution' };

/** Mirrors `HurdleSubject`: the fields the kind does not use are `null`. */
export interface HurdleSubject {
  kind: HurdleSubjectKind;
  partner_id: string | null;
  investor_class: string | null;
  account: EconomicAccount | null;
}

/** Mirrors `HurdleCondition`. An `irr` condition states its accrual convention
 * always, and its SIMPLE distribution order only when it is SIMPLE. */
export type HurdleCondition =
  | {
      kind: 'irr';
      condition_id: string;
      rate: number;
      accrual_convention: PartnershipAccrualConvention;
      simple_distribution_order: SimpleDistributionOrder | null;
    }
  | { kind: 'moic'; condition_id: string; multiple: number };

/** Mirrors `HurdleTerms`. */
export interface HurdleTerms {
  hurdle_subject: HurdleSubject;
  conditions: HurdleCondition[];
  combinator: HurdleCombinator;
}

/** Mirrors `CatchUpRecipient`. */
export interface CatchUpRecipient {
  kind: CatchUpRecipientKind;
  partner_id: string | null;
  investor_class: string | null;
}

/** Mirrors `CatchUpTerms`. The rate is not stored: it is the recipient's
 * aggregate share in the tier's explicit split, and the result reports it. */
export interface CatchUpTerms {
  recipient: CatchUpRecipient;
  target_profit_share: number;
}

/** Mirrors `WaterfallTier`. `hurdle` is set exactly on a `hurdle` tier and
 * `catch_up` exactly on a `catch_up` tier; a `residual` tier has neither. */
export interface WaterfallTier {
  tier_id: string;
  name: string;
  sequence: number;
  kind: TierKind;
  split: TierSplit | null;
  hurdle: HurdleTerms | null;
  catch_up: CatchUpTerms | null;
}

/** Mirrors `Partnership`. Every economic field is stated: an empty
 * `promote_participant_ids` is the explicit "no one is measured for promote",
 * never an omission. */
export interface Partnership {
  partners: Partner[];
  contribution_rule: ContributionRule;
  promote_benchmark: PromoteBenchmark;
  promote_participant_ids: string[];
  tiers: WaterfallTier[];
}

/** `GET`/`PUT /deals/{id}/partnership`. A standalone Deal reports no Investment
 * until one of its contracts materializes the hidden wrapper; reading creates
 * neither. `partnership` is `null` when the Deal states none. */
export interface DealPartnership {
  deal_id: string;
  investment_id: string | null;
  partnership: Partnership | null;
}

/** `GET`/`PUT /investments/{id}/partnership`. */
export interface InvestmentPartnership {
  investment_id: string;
  partnership: Partnership | null;
}

/** One entry of a structured 422. A Stage 1 *validation* issue carries
 * `partner_id`, `tier_id` and `field`; a Stage 1 *execution* issue carries
 * `tier_id` and `period`. Both arrive in this one shape, with the fields the
 * other does not use absent -- so they are optional here rather than invented. */
export interface PartnershipIssue {
  code: string;
  message: string;
  partner_id: string | null;
  tier_id: string | null;
  field: string | null;
  period: number | null;
}

// =============================================================================
// The result
// =============================================================================

/** Mirrors `PartnershipStatus`. */
export type PartnershipStatus = 'complete' | 'unavailable';

/** Mirrors `PartnershipUnavailableReason`. */
export type PartnershipUnavailableReason = 'common_equity_unavailable';

/** Mirrors `CommonEquityUnavailableReason`: the upstream reason an unavailable
 * Partnership carries through unchanged. */
export type CommonEquityUnavailableReason = 'unresolved_funding_requirement';

/** Mirrors `PromoteUnavailableReason`. A non-participant's Promote Earned is
 * N/A with this reason, and never `0` (R-E, P-9). */
export type PromoteUnavailableReason = 'not_a_promote_participant';

/** Mirrors `MoicUnavailableReason`. */
export type MoicUnavailableReason = 'no_contributions';

/** Mirrors `PartnerShare`: one partner's applied share in one period. */
export interface AppliedPartnerShare {
  partner_id: string;
  share: number;
}

/** Mirrors `PeriodShares`: the shares a tier actually applied in one period. */
export interface PeriodShares {
  period: number;
  shares: AppliedPartnerShare[];
}

/** Mirrors `PartnerTierAmount`. Attribution amounts are **signed**: only a
 * partner's `promote_earned` total is floored at zero, never a single tier's
 * share of it, or the reconciliation would break. */
export interface PartnerTierAmount {
  tier_id: string;
  sequence: number;
  amount: number;
}

/** Mirrors `PartnerPeriodAmounts`: one partner's amounts from one tier, by
 * period. */
export interface PartnerPeriodAmounts {
  partner_id: string;
  amounts: number[];
}

/** Mirrors `HurdleAccountRecord`: one condition's account in one period. The
 * three SIMPLE-only fields are `null` on an `annual_compound` condition. */
export interface HurdleAccountRecord {
  condition_id: string;
  period: number;
  opening_balance: number;
  accrual: number;
  subject_contributions: number;
  subject_distributions_before_tier: number;
  subject_distributions_from_tier: number;
  subject_distributions_after_tier: number;
  closing_balance: number;
  capacity_at_entry: number | null;
  satisfied_at_close: boolean;
  simple_distribution_order: SimpleDistributionOrder | null;
  outstanding_capital: number | null;
  accrued_return: number | null;
}

/** Mirrors `CatchUpPeriodRecord`. `profit_domain_open` is the ratified `P > 0`
 * domain test (Q4): while it is false the capacity is zero. */
export interface CatchUpPeriodRecord {
  period: number;
  partnership_profit_at_entry: number;
  recipient_profit_at_entry: number;
  profit_domain_open: boolean;
  capacity_at_entry: number;
  paid: number;
  partnership_profit_at_exit: number;
  recipient_profit_at_exit: number;
  caught_up: boolean;
}

/** Mirrors `TierRemaining`. */
export interface TierRemaining {
  tier_id: string;
  sequence: number;
  remaining: number;
}

/** Mirrors `PeriodRecord`. The period index is the input series' own: `0` is
 * closing and `t >= 1` is hold year `t`. No contract stores "year". */
export interface PeriodRecord {
  period: number;
  common_equity_cash_flow: number;
  total_contributions: number;
  total_distributions: number;
  remaining_after_tier: TierRemaining[];
}

/** Mirrors `TierResult`. The hurdle fields are set on a `hurdle` tier, the
 * catch-up fields on a `catch_up` tier, and `catch_up_rate` is derived from the
 * split rather than stored. */
export interface TierResult {
  tier_id: string;
  sequence: number;
  kind: TierKind;
  split_rule: SplitRule;
  shares_by_period: PeriodShares[];
  hurdle_subject: HurdleSubject | null;
  subject_partner_ids: string[] | null;
  combinator: HurdleCombinator | null;
  catch_up_recipient: CatchUpRecipient | null;
  recipient_partner_ids: string[] | null;
  catch_up_rate: number | null;
  target_profit_share: number | null;
  amounts: number[];
  partner_amounts: PartnerPeriodAmounts[];
  conditions: HurdleAccountRecord[];
  catch_up_records: CatchUpPeriodRecord[];
}

/** Mirrors `PartnerResult`.
 *
 * Three concepts the product must never blur (Q3, R-B):
 * `distribution_advantage` / `distribution_disadvantage` is total cash above or
 * below the benchmark, **capital included**, and is never called promote;
 * `promote_earned` is profit distributions above the benchmark, **excluding
 * returned capital**, and is reported only for a stated participant; and
 * `benchmark_capital_subordination` is the partner's *own* capital the benchmark
 * world would have returned and the waterfall did not.
 *
 * `benchmark_equals_commitment` is informational only -- the engine never
 * equates the two tables -- and a `false` must be disclosed on screen (R-A). */
export interface PartnerResult {
  partner_id: string;
  role: PartnerRole;
  investor_class: string | null;
  commitment_share: number;
  benchmark_share: number;
  benchmark_equals_commitment: boolean;
  is_promote_participant: boolean;
  contributions: number[];
  distributions: number[];
  net_cash_flows: number[];
  total_contributions: number;
  total_distributions: number;
  profit: number;
  irr: number | null;
  irr_status: IrrStatus;
  moic: number | null;
  moic_unavailable_reason: MoicUnavailableReason | null;
  benchmark_distributions: number[];
  total_benchmark_distributions: number;
  capital_returned: number;
  profit_distributions: number;
  benchmark_capital_returned: number;
  benchmark_profit_distributions: number;
  distribution_difference: number;
  distribution_advantage: number;
  distribution_disadvantage: number;
  capital_return_difference: number;
  profit_distribution_difference: number;
  promote_earned: number | null;
  promote_unavailable_reason: PromoteUnavailableReason | null;
  benchmark_capital_subordination: number;
  distributions_by_tier: PartnerTierAmount[];
  capital_return_difference_by_tier: PartnerTierAmount[];
  profit_distribution_difference_by_tier: PartnerTierAmount[];
  promote_attribution_by_tier: PartnerTierAmount[] | null;
}

/** Mirrors `PartnershipResult`.
 *
 * An `unavailable` result is a **successful** analysis whose upstream Common
 * Equity Cash Flow could not be produced: `partners`, `tiers` and `periods` are
 * `null`, never zero-filled, and `upstream_reason` with
 * `upstream_requirement_ids` says which Funding Requirements are unresolved. */
export interface PartnershipResult {
  status: PartnershipStatus;
  unavailable_reason: PartnershipUnavailableReason | null;
  unavailable_message: string | null;
  upstream_reason: CommonEquityUnavailableReason | null;
  upstream_requirement_ids: string[];
  cadence: 'annual';
  promote_participant_ids: string[];
  common_equity_cash_flows: number[] | null;
  common_equity_total_profit: number | null;
  partners: PartnerResult[] | null;
  tiers: TierResult[] | null;
  periods: PeriodRecord[] | null;
}

/** Which root executed the Partnership. A hidden one-unit Investment is still
 * called a Deal on screen. */
export type PartnershipRootKind = 'hidden_unit' | 'visible_investment';

/** Which owner stated the Partnership this variant resolved. */
export type PartnershipSource = 'base' | 'strategy';

/** `GET /investments/{id}/partnership-variants/{strategy}/{scenario}/fingerprint`. */
export interface PartnershipVariantFingerprint {
  investment_id: string;
  strategy_id: string;
  scenario_id: string;
  root_kind: PartnershipRootKind;
  unit_ids: string[];
  partnership: Partnership | null;
  partnership_source: PartnershipSource;
  project_source_fingerprint: string;
  structured_source_fingerprint: string;
  partnership_source_fingerprint: string | null;
}

/** `POST /investments/{id}/partnership-variants/{strategy}/{scenario}/analysis`.
 *
 * `result` is `null` exactly when `partnership` is `null`.
 * `project_cache_status` is operational metadata about the Project half only. */
export interface PartnershipVariantAnalysis {
  investment_id: string;
  strategy_id: string;
  scenario_id: string;
  root_kind: PartnershipRootKind;
  unit_ids: string[];
  hold_period: number;
  partnership: Partnership | null;
  partnership_source: PartnershipSource;
  project_source_fingerprint: string;
  structured_source_fingerprint: string;
  partnership_source_fingerprint: string | null;
  project_cache_status: string;
  result: PartnershipResult | null;
  /** Refinance & Capital Events V1: present only when the structured variant
   * states a capital event. Partner returns are then the primary investor
   * view, refinance included. */
  primary_return?: PrimaryReturnView;
}

// =============================================================================
// The PARTNER perspective
// =============================================================================

/** One addressable `PARTNER(partner_id)` perspective: the union of the stable
 * ids the Base Partnership and every Strategy's own hold.
 *
 * `name` is one deterministic label for the selector, so the analyst never has
 * to select an opaque id. It is **not** an invariant of the partner: the matrix
 * reports each cell's own name and role beside its figures. There is
 * deliberately no perspective-level role. */
export interface PartnerPerspective {
  partner_id: string;
  name: string;
  present_in_base: boolean;
  strategy_ids: string[];
}

/** `GET /investments/{id}/partner-perspectives`. */
export interface PartnerPerspectives {
  investment_id: string;
  partners: PartnerPerspective[];
}

/** Whether the selected partner took part in one cell.
 *
 * - `present`: the variant is valid and its resolved Partnership holds the
 *   partner. Its metrics are reported, or N/A with the Partnership's own reason
 *   while the upstream Common Equity Cash Flow is unavailable.
 * - `not_present`: the variant is valid and has no Partnership, or its
 *   Partnership does not hold the partner.
 * - `not_analysed`: the variant is invalid, so nothing was analysed. */
export type PartnerApplicability = 'present' | 'not_present' | 'not_analysed';

/** One Strategy x Scenario cell of a Partner matrix.
 *
 * `partner_name` and `partner_role` describe the partner **as this cell's own
 * resolved Partnership states it**, so one Strategy's terms never label
 * another's. Both are `null` where the partner is not present. */
export interface PartnerDecisionCell {
  strategy_id: string;
  scenario_id: string;
  status: 'valid' | 'invalid';
  applicability: PartnerApplicability;
  partner_name: string | null;
  partner_role: PartnerRole | null;
  issues: { source: string; code: string; message: string; field: string | null }[];
  project_source_fingerprint: string | null;
  structured_source_fingerprint: string | null;
  partnership_source_fingerprint: string | null;
  source_fingerprint: string | null;
  hold_period: number | null;
  partnership_status: PartnershipStatus | null;
  unavailable_reason: PartnershipUnavailableReason | null;
  unavailable_message: string | null;
  is_promote_participant: boolean | null;
  metrics: {
    metric: string;
    value: number | null;
    irr_status: IrrStatus | null;
    reason: string | null;
    message: string | null;
  }[];
  deltas: {
    metric: string;
    value: number | null;
    is_baseline: boolean;
    reason: string | null;
    message: string | null;
  }[];
}

/** The Partner comparison package. Its `matrix_fingerprint` includes the
 * selected `partner_id` and every cell's source fingerprint, so two partners
 * over the same variants never share one. There is no matrix-level role: a role
 * belongs to the cell that states it. */
export interface PartnerDecisionMatrix {
  perspective: 'partner';
  partner_id: string;
  partner_name: string;
  strategies: { strategy_id: string; name: string; is_base: boolean; hold_period: number | null }[];
  scenarios: { scenario_id: string; name: string; is_base: boolean }[];
  metrics: {
    metric: string;
    label: string;
    unit: 'rate' | 'multiple' | 'currency';
    direction: 'higher_is_better' | 'lower_is_better';
    horizon_dependent: boolean;
  }[];
  omitted_metrics: { metric: string; reason: string; message: string }[];
  hold_periods: number[];
  cross_scenario_figures: boolean;
  cells: PartnerDecisionCell[];
  strategy_figures: {
    strategy_id: string;
    worst_cases: {
      metric: string;
      direction: 'higher_is_better' | 'lower_is_better';
      value: number | null;
      scenario_id: string | null;
      scenario_name: string | null;
      reason: string | null;
      message: string | null;
    }[];
    ranges: {
      metric: string;
      minimum: number | null;
      maximum: number | null;
      spread: number | null;
      reason: string | null;
      message: string | null;
    }[];
  }[];
  matrix_fingerprint: string | null;
  matrix_fingerprint_reason: string | null;
}

/** `POST /investments/{id}/partner-decision-matrix/{partner_id}`. */
export interface PartnerDecisionMatrixReport {
  investment_id: string;
  root_kind: PartnershipRootKind;
  unit_ids: string[];
  partner: PartnerPerspective;
  matrix: PartnerDecisionMatrix;
}
