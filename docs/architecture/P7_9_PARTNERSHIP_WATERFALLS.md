# P7.9 Partnership Waterfalls + Investor Returns

Status: **Ratified.** The human review approved this contract with the
reviewer's recommended decisions (Section 19). It is the authority for P7.9.
**Stage 1 (Section 17.1) is complete and accepted** in PR #34 (`70b92e2`).
Stages 2 and 3 have not started: no P7.9 migration, persistence, fingerprint,
API or UI exists.

History:

- **Revision 1** proposed the contract.
- **Revision 2** applied the human review of revision 1:
  - Promote Earned excludes returned capital and is reported only for
    designated participants;
  - the catch-up has a positive-profit domain and a typed recipient;
  - SIMPLE distribution order is an explicit field;
  - `PRO_RATA_BY_CONTRIBUTION` is supported;
  - the catch-up rate has one authority;
  - the no-floor compound balance is confirmed;
  - Common Equity Total Profit has one authority.
- **The ratification patch** records the final decisions and renames two
  results: `benchmark_capital_subordination` (was `subordination`) and
  `promote_attribution_by_tier` (was `promote_earned_by_tier`).
- **Stage 1 implementation clarifications** (Stage 1 review; no financial
  decision changed, R-A to R-E untouched):
  - the seam reads the whole `StructuredCapitalResult` (Sections 2, 3 and
    17.1);
  - `contracts.py` may import two calculation-free Capital Structure shapes
    (Section 16.5);
  - mutation proofs run in-process under an isolated monkeypatch (Section
    16.6);
  - financial results carry no display names, and
    `PartnershipResult.cadence` is always stated (Section 12).

Base: `main` @ `79cb524`.
Branch: `feature/p7-9-partnership-waterfalls`.
Risk: Tier 1 (financial / contract critical).

`docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md` is the authority
(Sections 3, 13, 14, 15, 17.3, 18, 19, 21.3 and 22.6). The P7.7 and P7.8
records (`P7_7_CAPITAL_STRUCTURE_FOUNDATION.md`,
`P7_8_STRUCTURED_POSITION_ECONOMICS.md`, `P7_8_PRODUCT_INTEGRATION.md`) record
the layer this gate consumes. This document settles the four P7.9 questions of
Section 21.3 and fixes the contracts the implementation must follow. It
reopens no ratified decision and changes no P7.7 or P7.8 convention.

---

## 1. Authority, scope and engine-scope approval

### 1.1 Engine-scope approval (Q16)

The human granted engine-scope approval for **the P7.9 Partnership Waterfall
and Investor Return layer only**. It covers:

- new downstream Partnership contracts: partners, contribution rule,
  no-promote benchmark, promote participants, waterfall tiers, hurdle subjects
  and conditions, catch-up terms;
- deterministic allocation of the annual Common Equity Cash Flow into partner
  contributions and partner distributions;
- hurdle accounts under `SIMPLE` (with an explicit distribution order),
  `ANNUAL_COMPOUND` and MOIC conditions;
- the deterministic catch-up;
- the no-promote benchmark allocation, the capital-return / profit
  decomposition, Promote Earned, benchmark capital subordination and their per-tier
  attribution;
- partner returns (IRR, MOIC, profit, contributions, distributions), using the
  existing `anchor.engine.returns` functions unchanged;
- new result contracts;
- in later sessions of this gate: persistence, migration, fingerprints, the
  Strategy `PARTNERSHIP` domain, the API, the `PARTNER` decision perspective
  and the product UI (Section 17).

It does **not** authorize:

- P7.10 or any valuation-timepoint, AI, memo or reporting work;
- refinancing or recapitalization;
- monthly waterfalls or any intra-year allocation;
- taxes;
- fees, of any kind, routed through the waterfall (PW-6, TC-5);
- any change to Property, Business Plan, consolidation, Capital Structure,
  debt, IRR or any upstream formula;
- unrelated cleanup.

### 1.2 Frozen upstream

`debt.py`, `acquisition.py`, `noi.py`, `returns.py`,
`consolidation/engine.py`, every module in `src/anchor/capital_structure/`,
and `deals/structured_variants.py` stay byte-identical to `79cb524` through
Stage 1. Stage 2 may add to `deals/` and `api.py`, and must leave the financial
modules untouched. A ledger guard proves both (Section 16.5).

### 1.3 Dependency

```
COMMON EQUITY CASH FLOW  ->  PARTNERSHIP ECONOMICS  ->  INVESTOR RETURNS
```

The waterfall reads one annual series and never learns how it was produced:
a Unit, an Investment, with or without structured positions (§13.1). Three
namespaces stay separate (§14, NS-1, NS-2): project returns, position returns
and partner returns. No partner figure is appended to `AcquisitionResults`,
`ConsolidatedResults` or `StructuredCapitalResult`.

---

## 2. The Common Equity seam (inspection of `79cb524`)

There is exactly one seam, and it is the same for both analysis roots.

| Item | Location | Role for P7.9 |
|---|---|---|
| `CommonEquityReturns` | `capital_structure/execution_contracts.py` | **The input.** `cash_flows` (`t = 0..H`, or `None`), `status`, `unavailable_reason`, `unavailable_message`, `total_profit`, `total_equity_invested`, `total_cash_returned`, `irr`, `irr_status`, `equity_multiple` |
| `StructuredCapitalResult` | same | **The adapter's argument** (Stage 1 clarification). It carries `common_equity`, the `hold_period` the series must match, and the `funding_requirements` whose unresolved ids an unavailable Partnership reports. `CommonEquityReturns` carries neither the ids nor the hold period |
| `execute_unit_capital_structure` / `execute_investment_capital_structure` | `capital_structure/execution.py` | The producers. With no authored position, `cash_flows` *is* `AcquisitionResults.levered_cash_flows` or `ConsolidatedResults.levered_cash_flows` (P7.7 parity oracle) |
| `common_equity_outcome` | `capital_structure/foundation.py` | Sets `cash_flows = None` with `unresolved_funding_requirement` whenever any Funding Requirement is unresolved |
| `common_equity_metrics` | `capital_structure/metrics.py` | `evaluate_irr`, `calculate_equity_multiple` and `calculate_project_return_totals` on the final residual. It is the definition of Common Equity Total Profit that PW-5 reconciles to |
| `analyze_structured_variant` → `StructuredVariantAnalysis` | `deals/structured_variants.py` | The product entry point (Stage 2). It carries `result`, `hold_period` and `structured_source_fingerprint` for either root |

Findings:

- **Unambiguous.** Both roots, and both "no structure" and "authored
  structure", reach the waterfall through
  `StructuredCapitalResult.common_equity.cash_flows`. P7.9 never reads
  `levered_cash_flows` directly. Doing so would bypass the
  structured positions and the unresolved-funding rule.
- **Closing sign.** P7.8 refuses a root closing flow above **+$0.01**
  (`overfunded_closing`), so `CECF_0 <= +0.01`. A fully financed closing
  (`CECF_0 = 0`) is valid. The waterfall treats every period by its sign
  alone, and needs no special case for `t = 0`.
- **Unavailability.** When `cash_flows is None`, the partnership is
  unavailable with the upstream reason (Section 13). It is never zero-filled.
- **Scope.** The Partnership belongs to the analysis root, the Investment
  (hidden or visible), and allocates the root's Common Equity. It never
  allocates a Unit's residual inside a visible Investment.

---

## 3. Input contract

```
CashFlowCadence            StrEnum: ANNUAL ("annual")              # v1's only member

CommonEquityCashFlowInput
  cadence                  CashFlowCadence                          # a property of the series (PW-4)
  cash_flows               tuple[float, ...]                        # index 0 = closing; finite; len >= 2
```

- **One authority for Common Equity Total Profit.** The input carries no
  profit field. The engine derives `common_equity_total_profit` from
  `cash_flows` with `calculate_project_return_totals`, in `partnership/metrics.py`,
  the package's only importer of `anchor.engine.returns`. A literal input
  therefore cannot pair a series with a contradictory profit. This is the same
  function `common_equity_metrics` applies to the same series, and the Stage 1
  adapter test proves the derived figure is **bit-identical** to
  `CommonEquityReturns.total_profit` on every P7.7 / P7.8 fixture (Section
  16.2).
- **Period keys.** Accounts, records and results are keyed by the period
  index of the input series. For `ANNUAL`, index `t` is D6 period `t`: `0` is
  closing and `t >= 1` is hold year `t`. A future `MONTHLY` cadence would key
  by model month under D6 Section 4. No contract stores "year".
- **Accrual periods.** For `ANNUAL`, period `0` accrues nothing and each
  period `t >= 1` accrues one year at the stated annual rate. Accrual for any
  other cadence is a separate ratification (Section 18).
- **Adapter (Stage 1 signatures).**

  ```
  common_equity_input(structured: StructuredCapitalResult)
      -> CommonEquityCashFlowInput | CommonEquityUnavailable
  execute_partnership(partnership: Partnership, structured: StructuredCapitalResult)
      -> PartnershipResult
  allocate_partnership(partnership: Partnership, common_equity: CommonEquityCashFlowInput)
      -> PartnershipResult
  ```

  - `common_equity_input` passes `structured.common_equity.cash_flows` through
    untouched after checking that its length is `structured.hold_period + 1`.
  - When the series is unavailable, it returns a `CommonEquityUnavailable`
    marker instead: the upstream reason and message, plus the ids of the
    `UNRESOLVED` entries in `structured.funding_requirements`.
  - A missing series without an unresolved-funding reason is refused
    (`invalid_common_equity_series`).
  - `common_equity.py` is the only P7.9 module that reads
    `anchor.capital_structure` results. The waterfall engine imports neither
  `capital_structure` nor `deals`, which is what keeps it input-agnostic
  (§13.1). Tests may therefore drive it with literal and legacy series.

---

## 4. Partnership contracts

Every contract is a frozen, slotted, keyword-only dataclass. Enums follow the
`StrEnum` convention: upper-case members, lower-case wire values. **No field
that carries economics has a default.** An empty tuple is a stated value,
never an omitted one.

```
Partnership
  partners                 tuple[Partner, ...]           # >= 1; canonical order: partner_id
  contribution_rule        ContributionRule              # required; no default
  promote_benchmark        PromoteBenchmark              # required; no default (Q2)
  promote_participant_ids  tuple[str, ...]               # required; may be empty; canonical: sorted (Section 4.2)
  tiers                    tuple[WaterfallTier, ...]     # canonical order: sequence

Partner
  partner_id               str                           # stable, opaque (P-8)
  name                     str                           # display only; not in fingerprints (FP-1)
  role                     PartnerRole                   # LP | GP | CO_INVESTOR; reporting only
  investor_class           str | None                    # stable class token; economic when a hurdle or catch-up names it
  commitment_share         float                         # [0, 1]; shares sum to 1

ContributionRule           StrEnum: PRO_RATA_BY_COMMITMENT   # v1's only member

PromoteBenchmark
  shares                   tuple[BenchmarkShare, ...]     # exactly one per partner

BenchmarkShare
  partner_id               str
  share                    float                          # [0, 1]; shares sum to 1

WaterfallTier
  tier_id                  str                            # stable, opaque
  name                     str                            # display only
  sequence                 int                            # >= 1; unique; economic order (P-7)
  kind                     TierKind                       # HURDLE | CATCH_UP | RESIDUAL
  split                    TierSplit                      # required on every kind; no default
  hurdle                   HurdleTerms | None             # iff HURDLE
  catch_up                 CatchUpTerms | None            # iff CATCH_UP

TierSplit                  ExplicitSplit | ProRataByContribution
ExplicitSplit
  shares                   tuple[SplitShare, ...]         # exactly one per partner; sum to 1
SplitShare
  partner_id, share        str, float                     # [0, 1]
ProRataByContribution      (no fields)                    # supported in v1 (Section 6.2)

HurdleTerms
  hurdle_subject           HurdleSubject                  # required; no default (Q1)
  conditions               tuple[HurdleCondition, ...]    # >= 1
  combinator               HurdleCombinator               # ALL | ANY; required even for one condition

HurdleSubject                                              # Section 4.1
  kind                     HurdleSubjectKind              # PARTNER | INVESTOR_CLASS | ECONOMIC_ACCOUNT
  partner_id               str | None                     # iff PARTNER
  investor_class           str | None                     # iff INVESTOR_CLASS
  account                  EconomicAccount | None         # iff ECONOMIC_ACCOUNT

EconomicAccount            StrEnum: ALL_COMMON_EQUITY     # v1's only member

HurdleCondition            IrrHurdle | MoicHurdle
IrrHurdle
  condition_id             str
  rate                     float                          # finite, >= 0; annual
  accrual_convention       AccrualConvention              # SIMPLE | ANNUAL_COMPOUND (reuses P7.7's enum)
  simple_distribution_order SimpleDistributionOrder | None
                                                          # required iff SIMPLE; forbidden otherwise
MoicHurdle
  condition_id             str
  multiple                 float                          # finite, >= 1.0
                                                          # (has no distribution-order field)

SimpleDistributionOrder    StrEnum: ACCRUED_RETURN_FIRST ("accrued_return_first"),
                                    CAPITAL_FIRST ("capital_first")

HurdleCombinator           StrEnum: ALL ("all"), ANY ("any")

CatchUpTerms                                              # Section 9
  recipient                CatchUpRecipient
  target_profit_share      float                          # (0, 1)

CatchUpRecipient                                          # Section 4.3
  kind                     CatchUpRecipientKind           # PARTNER | INVESTOR_CLASS
  partner_id               str | None                     # iff PARTNER
  investor_class           str | None                     # iff INVESTOR_CLASS
```

- **One authority for the catch-up rate.** The rate is the recipient's
  aggregate share in the tier's `ExplicitSplit`: the summed shares of every
  recipient member. There is no stored rate field. The split states the
  recipient's rate and how the non-recipient remainder is divided. The derived
  `catch_up_rate` is reported in the results (Section 12).
- **`AccrualConvention` is reused** from `capital_structure/contracts.py`, so
  one extensible enum carries Q21 everywhere. It is an import of a shape
  only; no capital-structure behavior is consumed.
- **Named templates** ("American", "European", "8% pref, 20% promote") may
  exist later as UI presets that *produce* tier lists (§22.6). They are never
  engine branches.

### 4.1 Hurdle subject (Q1)

| Kind | Members | Typical use |
|---|---|---|
| `PARTNER(partner_id)` | that partner | "until the LP has received an 8% IRR" |
| `INVESTOR_CLASS(investor_class)` | every partner whose `investor_class` equals the token | "until the Class A investors have received ..." |
| `ECONOMIC_ACCOUNT(ALL_COMMON_EQUITY)` | every partner | "until all invested capital has earned ..." |

- A multi-member subject has **one aggregate account**: the members' summed
  contributions and summed distributions. The hurdle measures the group's
  aggregate return, not each member's. When the tier's split does not divide
  cash among members in their contribution ratio, individual members' returns
  differ, and each partner's own IRR is reported (Section 12).
- `ALL_COMMON_EQUITY` is valid only because it is chosen explicitly (PW-1). It
  resolves at execution to the current partner set, so adding a partner is an
  economic edit that changes the fingerprint.
- `role` never selects a subject (it is reporting only).

### 4.2 Promote participants

- `promote_participant_ids` explicitly names the partners for whom Promote
  Earned is reported. It is a required economic field with no default.
- **No role inference.** `LP`, `GP` and `CO_INVESTOR` remain reporting-only.
  A `GP` partner that is not named has no Promote Earned, and a partner of any
  role may be named.
- **Zero participants** (the empty tuple) is valid. It states a partnership
  in which no one is measured for promote, such as a pari passu venture.
  Every partner then reports Promote Earned as not applicable.
- **One or more participants** are valid. For example, two sponsor entities
  may each be named, and each is measured separately against its own
  benchmark.
- **Validation.** Each id must be a known partner and ids must be unique.
- **Fingerprint.** The sorted tuple is part of the partnership's economic
  fingerprint. It changes no allocation, but it changes a reported financial
  figure, so it is economic configuration (FP-1).

### 4.3 Catch-up recipient

| Kind | Members |
|---|---|
| `PARTNER(partner_id)` | that partner |
| `INVESTOR_CLASS(investor_class)` | every partner with that class token |

- `CatchUpRecipientKind` has **no** `ECONOMIC_ACCOUNT` member. An
  all-partners recipient would make the target share meaningless, because the
  recipient's profit would always equal partnership profit. A wire payload
  that states it is refused (`unsupported_catch_up_recipient`).
- A class recipient is one aggregate:
  - its rate is the members' summed split share;
  - its profit is the members' summed profit;
  - the split divides the catch-up among members.

---

## 5. Validation

### 5.1 Structural (`PartnershipValidationError`)

Issues are reported in a deterministic order: partners by id, then the
benchmark, then promote participants, then tiers by sequence. The order never
depends on list order. `bool` is refused wherever a number or an int is
expected.

| Code | Refused |
|---|---|
| `no_partners` | an empty partner list |
| `duplicate_partner_id` / `blank_partner_id` | identity |
| `invalid_share` | any commitment, benchmark or explicit split share that is not finite in `[0, 1]` |
| `shares_do_not_sum_to_one` | commitment, benchmark or explicit split shares whose canonical-order sum differs from 1 by more than `SHARE_SUM_TOLERANCE = 1e-9` |
| `benchmark_partner_set_mismatch` / `split_partner_set_mismatch` | a share table that omits a partner, names an unknown one, or names one twice |
| `unknown_promote_participant` / `duplicate_promote_participant` | a promote participant that is not a partner, or one named twice |
| `no_tiers` | an empty tier list |
| `duplicate_tier_id` / `duplicate_sequence` / `invalid_sequence` | identity and order |
| `residual_not_last` / `residual_count` | anything other than exactly one `RESIDUAL`, holding the greatest sequence |
| `kind_terms_mismatch` | `hurdle` without `HURDLE`, `catch_up` without `CATCH_UP`, or the reverse |
| `missing_split` | a tier without a split rule (there is no default) |
| `missing_hurdle_subject` | a `HURDLE` without a subject (there is no default) |
| `invalid_hurdle_subject` | a subject with the wrong fields for its kind |
| `unknown_subject_partner` / `empty_investor_class` | a subject or catch-up recipient that resolves to no partner |
| `hurdle_subject_has_no_share_in_tier` | an `ExplicitSplit` hurdle whose subject's summed share is 0, so the tier could never reach its hurdle |
| `no_conditions` / `duplicate_condition_id` | conditions |
| `invalid_rate` / `invalid_multiple` | a rate that is not finite and `>= 0`; a multiple that is not finite and `>= 1` |
| `missing_accrual_convention` | an `IrrHurdle` without one (Q21: never assumed) |
| `missing_simple_distribution_order` | a `SIMPLE` condition without one |
| `unexpected_simple_distribution_order` | an order stated on an `ANNUAL_COMPOUND` condition |
| `invalid_catch_up_recipient` / `unsupported_catch_up_recipient` | a recipient with the wrong fields for its kind, or an account recipient |
| `catch_up_requires_explicit_split` | a `CATCH_UP` tier with `ProRataByContribution` (the rate must be a stated term, checkable before execution) |
| `invalid_target_profit_share` | a target outside `(0, 1)` |
| `catch_up_rate_not_above_target` | an aggregate recipient split share `<=` the target, so the catch-up could never terminate (Section 9) |

### 5.2 Execution (`PartnershipExecutionError`)

The v1 executor refuses what it cannot run. It never moves the contract to a
supported convention and never partially executes it (the P7.8 precedent).
Every structurally valid split rule is executable. The only split refusal is a
data-dependent one.

| Code | Refused |
|---|---|
| `unsupported_cadence` | any input cadence other than `ANNUAL` |
| `unsupported_contribution_rule` | a future `ContributionRule` member |
| `unsupported_accrual_convention` | a future `AccrualConvention` member |
| `no_contributions_for_pro_rata_split` | a `ProRataByContribution` tier that must distribute positive cash while total cumulative contributions are zero. The refusal names the tier and period |
| `subject_without_split_share` | a `ProRataByContribution` hurdle whose subject has a positive balance but a zero current share (defensive; unreachable under `PRO_RATA_BY_COMMITMENT`, Section 6.2) |
| `invalid_common_equity_series` | fewer than two periods, or a non-finite value |

---

## 6. Constants, shares and arithmetic discipline

### 6.1 Constants and allocation

- `SHARE_SUM_TOLERANCE = 1e-9` (share tables only).
- `WATERFALL_AMOUNT_TOLERANCE = 1e-6` dollars. The following are treated as
  zero or satisfied at or below it:
  - a hurdle or catch-up capacity (zero);
  - a hurdle balance (satisfied);
  - partnership profit tested by the catch-up domain (Section 9) (not
    positive).

  It guards floating-point residue only, and it never rounds a reported
  figure.
- **Allocation with a remainder partner.** A dollar amount `X` is divided by a
  share table as follows: every partner except the *remainder partner*
  receives `share x X`, and the remainder partner receives `X` minus the
  canonical-order sum of the others. The remainder partner is the partner with
  the largest share, with ties going to the lowest `partner_id`. Each
  allocation therefore reconciles to `X` up to one floating-point
  subtraction, and a zero-share partner never receives residue. A 100% share
  yields `X` exactly, which is what the one-partner neutrality oracle relies
  on (Section 16.2).
- Every sum runs in canonical order: partners by id, tiers by sequence,
  conditions by id, periods ascending.

### 6.2 `ProRataByContribution`

When a tier with this rule distributes in period `t`, its shares are:

```
share_p,t = cumulative_contributions_p,(0..t) / sum_q cumulative_contributions_q,(0..t)
```

- These are cumulative *actual* partner contributions through `t`. Because an
  annual period is never both a contribution and a distribution (PW-4), this
  equals the cumulative total through `t - 1`.
- The shares are recomputed each distributing period, recorded per tier and
  period, and allocated with the Section 6.1 remainder rule.
- If the denominator is zero when the tier must distribute positive cash, the
  executor raises `no_contributions_for_pro_rata_split` (Section 5.2). A tier
  that distributes nothing in that period needs no shares and raises nothing.
- A hurdle subject's share is the members' summed current share. A subject
  with a positive balance has positive contributions, so its share is
  positive; `subject_without_split_share` is defensive only.
- Under `PRO_RATA_BY_COMMITMENT` (v1's only contribution rule), these shares
  equal the commitment shares whenever the denominator is positive, within
  floating-point residue. The rule is kept as its own economic statement,
  because a future contribution rule will separate them.

---

## 7. Period ordering

For each period `t = 0..H` of the input:

1. **Open.** Every hurdle account opens at its closing balance from `t-1`
   (zero at `t = 0`).
2. **Accrue.** For `t >= 1`, every IRR-condition account accrues one year on
   its opening state (Section 8). Cash dated `t` never accrues in period `t`.
   That matches `evaluate_irr`, which discounts the cash at `t` by exactly `t`
   periods.
3. **Contribute** (only when `CECF_t < 0`). `max(-CECF_t, 0)` is allocated by
   `commitment_share` (Section 6.1) into partner contributions, which are the
   partnership's capital calls (§13.4). Every account whose subject contains a
   contributing partner is increased.
4. **Distribute** (only when `CECF_t > 0`). `max(CECF_t, 0)` enters the tiers
   in ascending `sequence`. Each tier takes `min(remaining, capacity)`,
   divides it by its split (explicit, or the Section 6.2 shares), and posts
   each subject member's receipt to **every** hurdle account whose subject
   contains that member, before the next tier is evaluated. The `RESIDUAL`
   tier takes whatever remains.
5. **Benchmark.** `max(CECF_t, 0)` is also divided, in full and independently,
   by the `promote_benchmark` shares (Section 11).
6. **Close.** Each account's closing state, each tier's amount and shares, and
   the partner totals are recorded.

Because an annual period is either a net contribution or a net distribution
(PW-4), steps 3 and 4 never both run in one period, and no intra-period
ordering question arises. A period with `CECF_t = 0` (including `-0.0`) only
opens, accrues and closes.

**Tiers are re-entered every period.** A tier satisfied in period `t` can bind
again in `t+1`: its account may accrue back above zero, or a later capital
call may reopen it. This is the cumulative (look-back) waterfall that PW-3
describes, and the source of its IRR equivalence.

---

## 8. Hurdle accounts

Each condition of each `HURDLE` tier has its own account over that tier's
subject `S`. `C_S,t` and `D_S,t` are the subject members' summed contributions
and distributions in period `t`, from **every** tier.

### 8.1 `ANNUAL_COMPOUND` (PW-3, as ratified)

```
B_t = B_(t-1) x (1 + r) + C_S,t - D_S,t          (t >= 1)
B_0 = C_S,0 - D_S,0
```

- **No floor (confirmed convention).** A negative balance is the subject's
  surplus above the hurdle. It carries forward and compounds at `r` like any
  other balance. This is PW-3's formula applied literally, and it preserves
  the cumulative IRR look-back identity: `B_t <= 0` exactly when the subject's
  future value at `r` through `t` is non-negative, which for a conventional
  series means its IRR through `t` is at least `r`.
- A later capital call is absorbed by the compounded surplus before the tier
  binds again. Flooring at zero would erase earned surplus, re-trigger the
  hurdle early, and break the oracle. The no-floor rule has a boundary test
  (Section 16.3).

### 8.2 `SIMPLE`

The state is `(K, A)`. `K` is outstanding capital and may be negative, which
records capital returned in excess. `A` is accrued, unpaid return and is never
negative. `order` is the condition's required `simple_distribution_order`.

```
accrue (t >= 1):   A = A + r x max(K, 0)                  # capital only, never accrued return
contribute:        K = K + C_S,t
distribute d, ACCRUED_RETURN_FIRST:
                   paid_A = min(d, A);            A = A - paid_A
                   K = K - (d - paid_A)                                   # may go negative
distribute d, CAPITAL_FIRST:
                   paid_K = min(d, max(K, 0));    K = K - paid_K
                   paid_A = min(d - paid_K, A);   A = A - paid_A
                   K = K - (d - paid_K - paid_A)                          # excess: K goes negative
balance:           B = K + A
```

- Accrual is on outstanding capital only, never on accrued return (PW-3).
- **The order is required and has no default.** Both orders reduce `B` by
  exactly `d`, so a same-period capacity is unaffected. The difference
  appears in **later accrual**: capital-first leaves less capital
  outstanding to accrue. Fixture F3 (Section 16.1) proves it.
- The order applies only to `SIMPLE`. `ANNUAL_COMPOUND` has a single balance
  and refuses the field. `MoicHurdle` has no such field.
- A later capital call nets against a negative `K` before any new capital
  accrues.

### 8.3 MOIC

```
B_t = m x cumulative C_S,(0..t) - cumulative D_S,(0..t)
```

There is no accrual. `m = 1.0` is return of capital.

### 8.4 Capacity and the combinator

For a `HURDLE` tier with subject share `sigma_S` (the canonical sum of the
current split shares of `S`'s members), each condition `k` has capacity:

```
cap_k = 0                         if B_k <= WATERFALL_AMOUNT_TOLERANCE
cap_k = B_k / sigma_S             otherwise
```

Every tier dollar moves every one of the tier's accounts by exactly `sigma_S`
per dollar, so the capacity is exact and needs no iteration. For an
`ExplicitSplit`, validation guarantees `sigma_S > 0`. For
`ProRataByContribution`, see Section 6.2.

| Combinator | Tier capacity | Meaning |
|---|---|---|
| `ALL` | `max_k cap_k` | the tier pays until **every** condition is met: "the later of", "the greater of 1.5x or 12%" |
| `ANY` | `min_k cap_k` | the tier pays until **any** condition is met: "the earlier of", "the lesser of" |

With `ANY`, a condition already met gives the tier zero capacity for the
period.

---

## 9. Catch-up (Q4)

A `CATCH_UP` tier with recipient members `R`, derived rate
`c = sum of the split shares of R`, and target `tau`:

- **Profit basis.** Cumulative profit is distributions minus contributions,
  from period 0 through the current point, including distributions already
  made by earlier tiers in the current period:
  - partnership profit `P = sum over all partners (sum D_p - sum C_p)`;
  - recipient profit `Pr = sum over p in R (sum D_p - sum C_p)`.

  Every distribution counts, from every tier. The recipient's profit includes
  its members' ordinary pro-rata investor profit.
- **Return of capital.** Capital is excluded by construction, because returned
  capital nets against contributions. No tier label decides what is "profit".
- **Domain: positive partnership profit only.** A target share of
  cumulative profit has no meaning while partnership profit is not positive:

  ```
  capacity = 0                                          if P <= WATERFALL_AMOUNT_TOLERANCE
  capacity = max(0, (tau x P - Pr) / (c - tau))         if P >  WATERFALL_AMOUNT_TOLERANCE
  paid     = min(remaining, capacity)
  ```

  This holds even when `Pr < tau x P` with `P < 0`, where the recipient
  appears mathematically "behind" a negative target (fixture F9).
- **Termination test (P > 0).** The tier pays until `Pr >= tau x P`. A
  payment `x` moves `Pr` by `c x x` and `P` by `x`, so the closed form above
  is exact. `c > tau` is guaranteed by validation. After a payment,
  `P + x > 0` still holds.
- **Non-recipient share.** `(1 - c) x paid` goes to the non-recipient
  partners by their split shares, exactly as the split states. Inside a class
  recipient, the members' split shares divide `c x paid`. A 100% catch-up
  states `c = 1` and zero for every non-recipient.
- **Re-entry.** The test is re-run in every distribution period against
  cumulative totals. The catch-up is therefore never paid twice for the same
  profit, and it resumes if later tiers leave the recipient behind the target
  while `P > 0`.
- **Modeling note.** When the sponsor's co-investment should not count toward
  the catch-up target, model the co-investment and the promote interest as two
  partners, and make the promote partner the recipient. The engine never
  infers that split.

---

## 10. The residual tier

`RESIDUAL` has no terms. It takes all remaining cash and divides it by its
split (explicit, or `ProRataByContribution`). Validation guarantees exactly
one, holding the last sequence, so every distribution dollar is allocated in
every period.

---

## 11. Benchmark, capital / profit decomposition, Promote Earned and benchmark capital subordination (Q2, Q3)

### 11.1 The benchmark (Q2)

- `promote_benchmark` is a **literal share table**, required on every
  Partnership, with exactly one share per partner (zero allowed), summing to 1
  (Section 5.1). There is no default, and it is **never derived from, linked
  to or validated equal to `commitment_share`**. A UI may offer a
  "copy commitment shares" action that writes literal values. If commitments
  later change, the benchmark does not follow.
- The result reports `benchmark_equals_commitment` (per-partner exact
  equality, informational only) so a reviewer can see the two figures side by
  side without the engine equating them.
- The benchmark allocation distributes the same `max(CECF_t, 0)` entirely by
  the benchmark shares, period by period (PW-6), with the Section 6.1
  remainder rule. It has no tiers, hurdles or catch-up. **Contributions are
  not benchmarked:** each partner's contributions `C_p` are the same in both
  worlds.

### 11.2 The deterministic decomposition

For each partner `p`, with horizon totals `C_p` (contributions), `D_p`
(actual distributions) and `M_p` (benchmark distributions):

```
capital_returned_p                 = min(D_p, C_p)
profit_distributions_p             = D_p - capital_returned_p                   # = max(D_p - C_p, 0)
benchmark_capital_returned_p       = min(M_p, C_p)
benchmark_profit_distributions_p   = M_p - benchmark_capital_returned_p         # = max(M_p - C_p, 0)

distribution_difference_p          = D_p - M_p                                   # signed
capital_return_difference_p        = capital_returned_p - benchmark_capital_returned_p       # signed
profit_distribution_difference_p   = profit_distributions_p - benchmark_profit_distributions_p   # signed
```

- **Horizon basis.** A partner's distributions return its own contributed
  capital first, measured over the whole horizon, and only the excess is
  profit. This matches the D6 project totals (Total Equity Invested and Total
  Cash Returned are horizon sums). A running, period-by-period basis was
  rejected: a profit distribution followed by a later capital call would be
  reported as profit the partner never earns over the horizon.
- **Return of own capital is excluded** from profit in both worlds by the
  `min(., C_p)` terms.
- **Ordinary no-promote ownership is excluded** by subtracting the benchmark
  world's profit distributions.

### 11.3 Reported figures (Q3)

| Figure | Who | Definition | Meaning |
|---|---|---|---|
| `distribution_difference` | every partner | signed `D_p - M_p` | the audit primitive; its components are below |
| `distribution_advantage` / `distribution_disadvantage` | every partner | `max(d, 0)` / `max(-d, 0)` | total cash above or below the benchmark, capital included; never called promote |
| `capital_return_difference` | every partner | signed | own capital recovered versus the benchmark world |
| `profit_distribution_difference` | every partner | signed | profit received versus the benchmark world |
| **`promote_earned`** | **promote participants only** | `max(profit_distribution_difference_p, 0)` | profit distributions above the no-promote benchmark, excluding returned capital (Q23) |
| **`benchmark_capital_subordination`** | every partner | `max(-capital_return_difference_p, 0)` | own capital the benchmark world would have returned but the waterfall did not, because another claim ranked ahead |

- For a partner not in `promote_participant_ids`, `promote_earned` is `None`
  with `promote_unavailable_reason = NOT_A_PROMOTE_PARTICIPANT`. It is not
  applicable, and never zero (P-9).
- A participant whose profit difference is not positive reports
  `promote_earned = 0.0`.
- Profit a non-participant cedes, such as an LP bearing the promote, is its
  negative `profit_distribution_difference` (and part of its distribution
  disadvantage). It is not benchmark capital subordination, because its capital was not
  subordinated.
- **No `sum(promote_earned) = sum(benchmark_capital_subordination)` identity.** Returned capital
  is excluded from promote and profit is excluded from benchmark capital subordination, so the
  two totals are unrelated in general. Fixture F5 shows promote 0 against
  benchmark capital subordination 85,000.

### 11.4 Tier attribution

- **Actual side.** A partner's actual distribution entries
  `(period t, tier sequence j, amount)` are ordered by `(t, j)`. The first
  `capital_returned_p` dollars in that order are capital; the rest are
  profit. An entry may split across the boundary.
- **Benchmark side.** Its entries are the per-tier slices of the benchmark:
  `X_j,t` (the tier's cash in period `t`) divided by the benchmark shares with
  the remainder rule. They are ordered the same way and split at
  `benchmark_capital_returned_p`. Because `sum_j X_j,t = max(CECF_t, 0)`,
  these slices sum to the benchmark allocation of each period (up to Section
  6.1 residue).
- **Per tier.** For each tier `j`:

  ```
  capital_return_difference_by_tier_p,j     = actual capital in j  - benchmark capital in j
  profit_distribution_difference_by_tier_p,j = actual profit in j   - benchmark profit in j
  promote_attribution_by_tier_p,j = profit_distribution_difference_by_tier_p,j   if promote_earned_p > 0
                             = 0                                           if promote_earned_p = 0
                             (absent for non-participants)
  ```

- **Reconciliation.** Each family sums over tiers to its partner total, and
  `promote_attribution_by_tier` sums to `promote_earned`.
- **Attributions are signed.** A tier may carry a negative profit difference
  inside a positive Promote Earned, so an individual
  `promote_attribution_by_tier` value may be negative. Only the partner total,
  `promote_earned`, is floored at zero. The tier table shows the net. Flooring
  each tier separately would break the reconciliation.

---

## 12. Result contracts

```
PartnershipStatus          COMPLETE | UNAVAILABLE
PartnershipUnavailableReason
                           COMMON_EQUITY_UNAVAILABLE
PromoteUnavailableReason   NOT_A_PROMOTE_PARTICIPANT
MoicUnavailableReason      NO_CONTRIBUTIONS

PartnershipResult
  status, unavailable_reason, unavailable_message
  upstream_reason                    CommonEquityUnavailableReason | None
  upstream_requirement_ids           tuple[str, ...]
  cadence                            CashFlowCadence
  promote_participant_ids            tuple[str, ...]
  common_equity_cash_flows           tuple[float, ...] | None      # the input, echoed
  common_equity_total_profit         float | None                  # derived (Section 3)
  partners                           tuple[PartnerResult, ...] | None   # by partner_id
  tiers                              tuple[TierResult, ...] | None      # by sequence
  periods                            tuple[PeriodRecord, ...] | None

PartnerResult
  partner_id, role, investor_class, commitment_share, benchmark_share
  benchmark_equals_commitment        bool
  is_promote_participant             bool
  contributions                      tuple[float, ...]      # per period, >= 0
  distributions                      tuple[float, ...]      # per period, >= 0
  net_cash_flows                     tuple[float, ...]      # distributions - contributions
  total_contributions, total_distributions, profit
  irr, irr_status                    evaluate_irr(net_cash_flows)
  moic                               float | None           # total_distributions / total_contributions
  moic_unavailable_reason            MoicUnavailableReason | None
  benchmark_distributions            tuple[float, ...]
  total_benchmark_distributions
  capital_returned, profit_distributions
  benchmark_capital_returned, benchmark_profit_distributions
  distribution_difference            float                  # signed
  distribution_advantage             float                  # >= 0
  distribution_disadvantage          float                  # >= 0
  capital_return_difference          float                  # signed
  profit_distribution_difference     float                  # signed
  promote_earned                     float | None           # >= 0; None iff not a participant
  promote_unavailable_reason         PromoteUnavailableReason | None
  benchmark_capital_subordination    float                  # >= 0
  distributions_by_tier              tuple[PartnerTierAmount, ...]   # by sequence
  capital_return_difference_by_tier  tuple[PartnerTierAmount, ...]   # signed
  profit_distribution_difference_by_tier tuple[PartnerTierAmount, ...]   # signed
  promote_attribution_by_tier        tuple[PartnerTierAmount, ...] | None   # participants only; signed

TierResult
  tier_id, sequence, kind
  split_rule                         EXPLICIT | PRO_RATA_BY_CONTRIBUTION
  shares_by_period                   tuple[PeriodShares, ...]      # the shares actually applied
  hurdle_subject, subject_partner_ids                          (HURDLE)
  combinator                                                   (HURDLE)
  catch_up_recipient, recipient_partner_ids,
  catch_up_rate (derived), target_profit_share                 (CATCH_UP)
  amounts                            tuple[float, ...]      # X_j,t per period
  partner_amounts                    tuple[PartnerPeriodAmounts, ...]
  conditions                         tuple[HurdleAccountRecord, ...]   (HURDLE; by condition_id)
  catch_up_records                   tuple[CatchUpPeriodRecord, ...]   (CATCH_UP)

HurdleAccountRecord                  # one per condition, per period
  condition_id, period, opening_balance, accrual, subject_contributions,
  subject_distributions_before_tier, subject_distributions_from_tier,
  subject_distributions_after_tier, closing_balance,
  capacity_at_entry, satisfied_at_close
  simple_distribution_order, outstanding_capital, accrued_return   (SIMPLE only)

CatchUpPeriodRecord
  period, partnership_profit_at_entry, recipient_profit_at_entry,
  profit_domain_open                 bool   # P > tolerance at entry
  capacity_at_entry, paid, partnership_profit_at_exit, recipient_profit_at_exit,
  caught_up

PeriodRecord
  period, common_equity_cash_flow, total_contributions, total_distributions,
  remaining_after_tier                tuple[TierRemaining, ...]
```

- **Partner returns reuse `anchor.engine.returns` unchanged** (P-3), in one
  module that is its only importer. IRR is `evaluate_irr` on `net_cash_flows`.
  Totals are `calculate_project_return_totals` and MOIC is
  `calculate_equity_multiple` on the same series. Because each annual period
  is one-signed for every partner, the sign split of `net_cash_flows` equals
  the contribution and distribution totals exactly. There is no XIRR and no
  second IRR solver.
- **MOIC** is `None` with `NO_CONTRIBUTIONS` for a partner that never
  contributes, such as a promote-only partner with `commitment_share = 0`.
  That partner's IRR is N/A with the existing `FIRST_NONZERO_NOT_NEGATIVE`
  status (or `NO_NONZERO_CASH_FLOW`). Neither is shown as zero or infinity.
- **Vocabulary.** "Capital call" and "contribution" appear only in these
  results (§13.4). Partner IRR is never labeled as the project or Common
  Equity IRR (NS-1). "Promote Earned" labels only `promote_earned`.
  Distribution advantage is never captioned as promote.

---

## 13. Invalid, unavailable and N/A states

| State | Raised / reported | Partner figures |
|---|---|---|
| The Partnership contract is invalid | `PartnershipValidationError` with Section 5.1 issues | none; no result |
| A contract v1 cannot execute (Section 5.2), including a pro-rata split with no contributions to divide by | `PartnershipExecutionError` | none; no result |
| The Project variant is invalid, or the structure is invalid or not executable | the upstream error, unchanged (P7.8B's three refusals) | none; no result |
| Upstream Common Equity unavailable (unresolved Funding Requirement) | `PartnershipResult` with `UNAVAILABLE`, `COMMON_EQUITY_UNAVAILABLE`, the upstream reason and requirement ids, and a message naming them | `None`, never zero-filled |
| A partner IRR the convention rejects | `irr = None`, `irr_status` from `evaluate_irr` | the rest stand |
| A partner with no contributions | `moic = None`, `NO_CONTRIBUTIONS` | the rest stand |
| A partner that is not a promote participant | `promote_earned = None`, `NOT_A_PROMOTE_PARTICIPANT`; `promote_attribution_by_tier = None` | the rest stand |
| A tier that never pays, a catch-up already caught up, or a catch-up while `P <= 0` | not an error; zero amounts, with account and catch-up records showing why | stand |
| Negative Common Equity Total Profit | not an error | stand; profits may be negative |

An unavailable Partnership is a successful analysis, as in P7.8B: the request
succeeds and upstream Project and Position results remain as they are.

---

## 14. Conservation and reporting identities (required tests)

With `tol_t = 1e-6 + 1e-12 x |CECF_t|` per period, and the sum of the
per-period tolerances for horizon totals:

**Cash conservation (exact up to residue):**

1. `sum_p contributions_p,t = max(-CECF_t, 0)` for every `t` (PW-5).
2. `sum_p distributions_p,t = max(CECF_t, 0)` for every `t` (PW-5).
3. `sum_j X_j,t = max(CECF_t, 0)` for every `t`: the tiers exhaust each
   distribution.
4. `sum_p partner_amounts_p,j,t = X_j,t` for every tier and period.
5. `sum_p benchmark_distributions_p,t = max(CECF_t, 0)` for every `t`: the
   actual and benchmark allocations conserve the same cash.
6. `sum_p profit_p = common_equity_total_profit` (PW-5), and
   `common_equity_total_profit` is bit-identical to
   `CommonEquityReturns.total_profit` through the adapter.

**Signed differences (exact up to residue):**

7. `sum_p distribution_difference_p = 0`.
8. `distribution_difference_p = capital_return_difference_p + profit_distribution_difference_p`.
9. `sum_p capital_return_difference_p = -sum_p profit_distribution_difference_p`.
   Neither sum is zero in general.
10. `capital_returned_p + profit_distributions_p = D_p`, and the same holds on
    the benchmark side with `M_p`.
11. `profit_p = profit_distributions_p - (C_p - capital_returned_p)`.
12. `distribution_advantage_p - distribution_disadvantage_p = distribution_difference_p`,
    and at most one of the two is non-zero.

**Promote and benchmark capital subordination:**

13. `promote_earned_p` is `None` iff `p` is not a participant. Otherwise it
    is `max(profit_distribution_difference_p, 0)`.
14. `benchmark_capital_subordination_p = max(-capital_return_difference_p, 0)`.
15. **Tier reconciliation.**
    - `sum_j capital_return_difference_by_tier_p,j = capital_return_difference_p`;
    - `sum_j profit_distribution_difference_by_tier_p,j = profit_distribution_difference_p`;
    - `sum_j promote_attribution_by_tier_p,j = promote_earned_p`.
16. There is deliberately **no** identity between total Promote Earned and
    total benchmark capital subordination (Section 11.3). A test asserts that fixture F5 breaks
    it, so nobody reintroduces it.

**Domains:**

17. Every per-period contribution, distribution, tier amount and benchmark
    amount, and every advantage, disadvantage, Promote Earned and
    benchmark capital subordination, is finite and `>= 0`.

---

## 15. Worked example (generic LP / GP)

### 15.1 Terms

- Partners: `lp` (role LP, commitment 90%), `gp` (role GP, commitment 10%).
- Contribution rule: `PRO_RATA_BY_COMMITMENT`.
- Benchmark (stated explicitly): `lp` 90%, `gp` 10%.
- Promote participants (stated explicitly): `(gp)`.
- Common Equity Cash Flow: `t0 -1,000,000`; `t1 -100,000` (a capital call);
  `t2 +60,000`; `t3 +1,900,000`. Total profit: **860,000**.

| Seq | Tier | Kind | Terms | Split lp / gp |
|---|---|---|---|---|
| 10 | `pref` | HURDLE | subject `PARTNER(lp)`; IRR 8% `ANNUAL_COMPOUND`; `ALL` | explicit 90 / 10 |
| 20 | `catch_up` | CATCH_UP | recipient `PARTNER(gp)`; target 20% of cumulative profit | explicit 40 / 60 (derived rate 60%) |
| 30 | `promote_1` | HURDLE | subject `PARTNER(lp)`; IRR 12% `ANNUAL_COMPOUND`; `ALL` | explicit 80 / 20 |
| 40 | `promote_2` | RESIDUAL | none | explicit 70 / 30 |

The example uses `ANNUAL_COMPOUND` hurdles, which take no distribution order.
Its SIMPLE counterpart (fixture F2) states `ACCRUED_RETURN_FIRST`.

### 15.2 Contributions

| t | CECF | lp | gp |
|---|---|---|---|
| 0 | -1,000,000 | 900,000 | 100,000 |
| 1 | -100,000 | 90,000 | 10,000 |

### 15.3 Hurdle accounts (subject `lp`)

| t | `pref` 8% | `promote_1` 12% |
|---|---|---|
| 0 | 900,000.00 | 900,000.00 |
| 1 | 900,000 x 1.08 + 90,000 = 1,062,000.00 | 900,000 x 1.12 + 90,000 = 1,098,000.00 |
| 2, after accrual | 1,146,960.00 | 1,229,760.00 |
| 2, after `lp` receives 54,000 | 1,092,960.00 | 1,175,760.00 |
| 3, after accrual | 1,180,396.80 | 1,316,851.20 |

### 15.4 Distributions

**t = 2 (60,000).** `pref` capacity is 1,146,960 / 0.9 = 1,274,400, which is
more than the cash. `pref` pays 60,000: `lp` 54,000, `gp` 6,000.

**t = 3 (1,900,000).**

1. **`pref`.** Capacity 1,180,396.80 / 0.9 = **1,311,552.00**, paid as `lp`
   1,180,396.80 and `gp` 131,155.20. Remaining: 588,448.00. `pref` closes at
   0. `promote_1` falls to 1,316,851.20 - 1,180,396.80 = 136,454.40.
2. **`catch_up`.** Contributions to date are 1,100,000 and distributions
   1,371,552, so P = 271,552.00 > 0 and the domain is open. `gp` has
   137,155.20 - 110,000 = 27,155.20, so Pr = 27,155.20. Capacity =
   (0.20 x 271,552 - 27,155.20) / (0.60 - 0.20) = 27,155.20 / 0.40 =
   **67,888.00**, paid as `gp` 40,732.80 and `lp` 27,155.20. Remaining:
   520,560.00.
   Check: Pr = 67,888.00 = 20% of P = 339,440.00.
   `promote_1` falls to 136,454.40 - 27,155.20 = 109,299.20.
3. **`promote_1`.** Capacity 109,299.20 / 0.8 = **136,624.00**, paid as `lp`
   109,299.20 and `gp` 27,324.80. Remaining: 383,936.00.
4. **`promote_2`.** Pays **383,936.00**: `lp` 268,755.20, `gp` 115,180.80.

Tier totals at t3: 1,311,552 + 67,888 + 136,624 + 383,936 = 1,900,000 ✓.

### 15.5 Partner results

| | lp | gp | Sum |
|---|---|---|---|
| Contributions `C` | 990,000.00 | 110,000.00 | 1,100,000 ✓ |
| Distributions `D` | 1,639,606.40 | 320,393.60 | 1,960,000 ✓ |
| Net series | -900,000 / -90,000 / 54,000 / 1,585,606.40 | -100,000 / -10,000 / 6,000 / 314,393.60 | CECF ✓ |
| Profit | 649,606.40 | 210,393.60 | 860,000 ✓ |
| MOIC | 1.6562x | 2.9127x | |
| IRR (`evaluate_irr`) | 19.14% | 44.57% | Common Equity 22.18% |
| Benchmark distributions `M` | 54,000 + 1,710,000 = 1,764,000.00 | 6,000 + 190,000 = 196,000.00 | 1,960,000 ✓ |
| Capital returned (actual / benchmark) | 990,000 / 990,000 | 110,000 / 110,000 | |
| Profit distributions (actual / benchmark) | 649,606.40 / 774,000.00 | 210,393.60 / 86,000.00 | |
| Distribution difference | -124,393.60 | +124,393.60 | 0 ✓ |
| Capital-return difference | 0.00 | 0.00 | 0 |
| Profit-distribution difference | -124,393.60 | +124,393.60 | 0 |
| Distribution advantage / disadvantage | 0 / 124,393.60 | 124,393.60 / 0 | |
| **Promote Earned** | not applicable (not a participant) | **124,393.60** | |
| **Benchmark capital subordination** | 0.00 | 0.00 | |

**`gp` tier attribution.** `gp`'s entries in order are:

- t2 `pref` 6,000, all capital;
- t3 `pref` 131,155.20, split 104,000 capital and 27,155.20 profit;
- everything after that, all profit.

The benchmark slices (10% of each tier's cash) split the same way: t2 `pref`
6,000 and t3 `pref` 131,155.20, which is 104,000 capital and 27,155.20 profit.

| Tier | Actual profit | Benchmark profit | Promote Earned by tier |
|---|---|---|---|
| `pref` | 27,155.20 | 27,155.20 | **0** |
| `catch_up` | 40,732.80 | 6,788.80 | **33,944.00** |
| `promote_1` | 27,324.80 | 13,662.40 | **13,662.40** |
| `promote_2` | 115,180.80 | 38,393.60 | **76,787.20** |

The tier values sum to **124,393.60** ✓, and every capital-return difference
by tier is 0. `lp` carries the mirror-image negative profit differences, as
promote borne, not benchmark capital subordination.

**Built-in IRR oracle.** `lp`'s series truncated at `pref`,
`(-900,000, -90,000, 54,000, 1,180,396.80)`, has IRR exactly 8%. Adding its
catch-up and `promote_1` receipts gives t3 = 1,316,851.20, which has IRR
exactly 12%.

### 15.6 Variations on the same terms (boundary fixtures)

| CECF t3 | Outcome | `gp` Promote Earned |
|---|---|---|
| 1,100,000 | `pref` not met (`lp` IRR 1.88%); all cash is `pref` at 90 / 10; every difference is 0 | **0.00** |
| 1,340,000 | `pref` met; `catch_up` partial: 28,448 paid (`gp` 17,068.80, `lp` 11,379.20) | **14,224.00**, all in `catch_up` |
| 1,900,000 | the full example above | **124,393.60** |

---

## 16. Verification plan

### 16.1 Hand fixtures (literal expected values)

Unless stated otherwise: `lp` 90% / `gp` 10% commitment, benchmark 90 / 10,
promote participants `(gp)`, and 8% hurdles on subject `PARTNER(lp)`.

**F1. The Section 15 example,** at all three t3 values.

**F2. SIMPLE vs ANNUAL_COMPOUND** (unpaid accrual).
- Setup: CECF `(-1,000,000, 0, +1,300,000)`; one 8% hurdle, split 90 / 10;
  residual 80 / 20.
- SIMPLE (`ACCRUED_RETURN_FIRST`; no distribution precedes the tier, so the
  order is inert here): accrual is 72,000 + 72,000, the balance is 1,044,000,
  the tier pays 1,160,000 and the residual 140,000.
- ANNUAL_COMPOUND: the balance is 900,000 x 1.08² = 1,049,760, the tier pays
  1,166,400 and the residual 133,600.

**F3. SIMPLE distribution order changes later accrual.**
- Setup: CECF `(-1,000,000, +50,000, 0, +1,300,000)`; one 8% SIMPLE hurdle,
  split 90 / 10; residual 80 / 20. At t1 `lp` receives 45,000 against
  accrued 72,000.

| | `ACCRUED_RETURN_FIRST` | `CAPITAL_FIRST` |
|---|---|---|
| After t1: K / A | 900,000 / 27,000 | 855,000 / 72,000 |
| t2 accrual | **72,000** | **68,400** |
| t3 accrual | 72,000 | 68,400 |
| t3 balance K + A | 900,000 + 171,000 = 1,071,000 | 855,000 + 208,800 = 1,063,800 |
| t3 hurdle tier | 1,190,000 | 1,182,000 |
| t3 residual (80 / 20) | 110,000 | 118,000 |
| `lp` / `gp` total distributions | 1,204,000 / 146,000 | 1,203,200 / 146,800 |

**F4. ALL vs ANY.**
- Setup: CECF `(-1,000,000, 0, +2,000,000)`; conditions [IRR 10%
  `ANNUAL_COMPOUND`, MOIC 1.5x]; split 90 / 10; residual 80 / 20.
- The accounts are 1,089,000 and 1,350,000.
- `ALL` pays 1,500,000, then 500,000 residual.
- `ANY` pays 1,210,000, then 790,000 residual.

**F5. Downside benchmark capital subordination.** This is the revision-1 counterexample.
- Setup: CECF `(-1,000,000, 0, +950,000)`; return of capital MOIC 1.0x,
  split 100 / 0; residual 80 / 20.

| | lp | gp |
|---|---|---|
| C / D / M | 900,000 / 940,000 / 855,000 | 100,000 / 10,000 / 95,000 |
| Capital returned (actual / benchmark) | 900,000 / 855,000 | 10,000 / 95,000 |
| Profit distributions (actual / benchmark) | 40,000 / 0 | 0 / 0 |
| Distribution difference | +85,000 | -85,000 |
| Capital-return difference | **+45,000** | **-85,000** |
| Profit-distribution difference | **+40,000** | 0 |
| Promote Earned | not applicable | **0.00** |
| Benchmark capital subordination | 0 | **85,000** |
| Capital-return difference by tier | ROC +90,000, residual -45,000 | ROC -90,000, residual +5,000 |

Revision 1 reported `lp` Promote Earned of 85,000 here, which is corrected.
Total promote (0) ≠ total benchmark capital subordination (85,000), which proves identity 16.

**F6. The subject matters.**
- Setup: CECF `(-1,000,000, 0, +1,500,000)`; the F5 tiers.
- Subject `PARTNER(lp)` pays 900,000, then 600,000 residual.
- Subject `ECONOMIC_ACCOUNT(ALL_COMMON_EQUITY)` pays 1,000,000, then 500,000
  residual.

**F7. The benchmark differs from commitment.**
- Setup: commitment 90 / 10, benchmark 95 / 5, participants `(gp)`; a single
  `RESIDUAL` with `ProRataByContribution`.

| CECF t2 | `gp` C / D / M | `gp` capital diff | `gp` profit diff | `gp` Promote Earned | Revision-1 value | `lp` benchmark capital subordination |
|---|---|---|---|---|---|---|
| 800,000 (loss) | 100,000 / 80,000 / 40,000 | +40,000 | 0 | **0.00** | 40,000 | **40,000** |
| 1,500,000 (gain) | 100,000 / 150,000 / 75,000 | +25,000 | +50,000 | **50,000.00** | 75,000 | 0 |

- In the loss case, all of `gp`'s +40,000 advantage is returned capital, so
  none of it is promote.
- In the gain case, `gp` receives 10% of profit against a stated 5%
  no-promote interest, so 50,000 is above the benchmark (R-A in Section 19.2).

**F8. A promote-only participant** (zero contributions).
- Setup: partners `lp` (commitment 100%) and `sp` (commitment 0%); benchmark
  100 / 0; participants `(sp)`; CECF `(-1,000,000, 0, +1,500,000)`.
- Tiers: 8% compound pref (subject `lp`, split 100 / 0); catch-up to `sp`
  (split 0 / 100, derived rate 100%, target 20%); residual 80 / 20.

| Step | Amount |
|---|---|
| Pref | 1,000,000 x 1.08² = 1,166,400 to `lp` |
| Catch-up | P = 166,400, Pr = 0, capacity (33,280 - 0) / 0.8 = **41,600** to `sp` |
| Residual | 292,000: `lp` 233,600, `sp` 58,400 |

- `sp` totals: C = 0, D = 100,000, M = 0, capital returned 0, profit
  distributions 100,000.
- `sp` Promote Earned is **100,000**: 41,600 in the catch-up and 58,400 in
  the residual. Its MOIC is N/A (`NO_CONTRIBUTIONS`), and its IRR is N/A
  (`FIRST_NONZERO_NOT_NEGATIVE`).
- `lp` has a profit difference of -100,000.
- Check: `sp` holds 100,000, which is 20% of the 500,000 profit.

**F9. The catch-up cannot pay while `P <= 0`.**
- Setup: CECF `(-1,000,000, 0, +950,000)`; ROC MOIC 1.0x (split 100 / 0);
  catch-up to `gp` (split 0 / 100, target 20%); residual 80 / 20.
- After ROC: P = -100,000 and Pr = -100,000. That is below
  tau x P = -20,000, so the unguarded formula would give capacity
  (-20,000 + 100,000) / 0.8 = 100,000.
- **Required:** the domain is closed, the catch-up pays 0, and the residual
  pays 50,000 (`lp` 40,000, `gp` 10,000). The results equal F5.
- The unguarded mutant would pay `gp` 50,000 as catch-up.

**F10. `ProRataByContribution` neutrality.**
- Setup: CECF `(-1,000,000, -50,000, +30,000, +1,400,000)`; a pref and a
  residual that both use `ProRataByContribution`.
- Required: every partner figure equals the same partnership with explicit
  90 / 10 splits, within `tol_t`. `lp` receives 1,287,000 and `gp` 143,000.

**F11. `ProRataByContribution` with a zero denominator.**
- CECF `(0, +500, -1,000, +2,000)` with a pro-rata residual raises
  `no_contributions_for_pro_rata_split`, naming the tier and period 1.
- The same series with an explicit split executes.
- CECF `(0, 0, -1,000, +2,000)` with the pro-rata residual executes, because
  no cash needs shares before the first contribution.

**F12. A class recipient.**
- Setup: `lp` 90%; `g1` and `g2` 5% each, both class `sponsor`; benchmark
  equal to commitment; participants `(g1, g2)`; CECF
  `(-1,000,000, 0, +1,500,000)`.
- Tiers: pref 8% compound (subject `lp`, split 90 / 5 / 5); catch-up to
  `INVESTOR_CLASS(sponsor)` (split 0 / 50 / 50, derived rate 100%, target
  20%); residual 80 / 10 / 10.

| Step | Amount |
|---|---|
| Pref | 1,166,400 |
| Catch-up | P = 166,400, class Pr = 16,640, capacity **20,800** |
| Residual | 312,800 |

- Each sponsor has D = 100,000 and M = 75,000, so Promote Earned is
  **25,000**: 9,360 in the catch-up and 15,640 in the residual.
- `lp` has a profit difference of -50,000.
- Check: the class holds 37,440, which is 20% of 187,200.

### 16.2 Independent oracles

- **IRR look-back oracle (method-independent).** For `ANNUAL_COMPOUND`
  hurdles, a bisection over the tier amount at each period uses `evaluate_irr`
  on the subject's series, not the account formula. It must find the same tier
  amounts on generated conventional series, including a surplus later
  absorbed by a capital call, which confirms the no-floor rule.
- **Exact-rational oracle.** A `fractions.Fraction` restatement of Sections
  6-11 in the test tree (`tests/_p7_9_rational_oracle.py`) reproduces every
  hand fixture exactly. The float engine must agree within `tol_t`.
- **One-partner neutrality.** A single partner with every share at 100%, and
  no promote participant, reports IRR, `irr_status`, MOIC and profit
  **bit-identical** to `CommonEquityReturns`, for the P7.7 and P7.8 fixture
  set (Quick, Detailed, Lease-Level, Investment, structured and unresolved).
- **Total-profit authority.** For the same fixture set, the adapter's derived
  `common_equity_total_profit` is bit-identical to
  `CommonEquityReturns.total_profit`. The input contract has no profit field
  (a dataclass-field test).
- **Pari passu neutrality.** A single `RESIDUAL` split equal to the benchmark
  (explicit, and `ProRataByContribution` with benchmark = commitment) gives
  zero differences, zero benchmark capital subordination and zero Promote Earned for every
  designated participant.
- **Catch-up closure.** Whenever a catch-up leaves cash for a later tier,
  `Pr = tau x P` within `tol_t` and `P > 0`.
- **Catch-up domain property.** On generated series, no catch-up amount is
  ever positive in a period whose `P` at entry is `<= WATERFALL_AMOUNT_TOLERANCE`.
- **MOIC closure.** Whenever a MOIC-only tier leaves cash for a later tier,
  the subject's cumulative distributions equal `m` times its contributions.
- **Decomposition property.** On generated series, and for every partner:
  - `capital_returned = min(D, C)`, derived independently from the totals;
  - identities 7-15 hold;
  - `promote_earned <= profit_distributions`;
  - `benchmark_capital_subordination <= C`.
- **Seam oracle (Stage 1 and 2).** A partnership over a structured variant
  reads `StructuredCapitalResult.common_equity.cash_flows` and never
  `levered_cash_flows`. With a mezzanine position present, the two series
  differ, and the partner totals reconcile to the former.
- **§17.3 fixture 2 (`portfolio_property_debt_jv`).** Stage 2 adds the
  waterfall half: three or more property units with per-unit mortgages, and
  the Section 15 terms over the consolidated series, with a hand-prepared
  expected table. P7.11 owns the full end-to-end acceptance.

### 16.3 Boundary cases

**Series and closing:**
- `CECF_0 = 0` (fully financed);
- `CECF_0` in `(0, +0.01]` (a distribution before any contribution: it goes
  to the residual, or raises F11's refusal under a pro-rata split);
- an all-zero series;
- a negative-profit series;
- `hold_period = 1`.

**Hurdle accounts:**
- a capital call after a distribution;
- a subject surplus later absorbed by a capital call (a negative compounding
  balance; a SIMPLE negative `K` under both orders);
- the no-floor rule: a surplus carried two years and compounded, with the
  exact expected balance;
- rate `0` (SIMPLE = ANNUAL_COMPOUND = MOIC 1.0x);
- multiple exactly `1.0`;
- a tier satisfied in one year and reopened by accrual the next;
- `ANY` with one condition already met;
- the cash exhausted exactly at a tier boundary.

**Splits and subjects:**
- a zero-share partner in a split (never receives residue);
- an investor-class subject with two members;
- permutation of the partner, tier and promote-participant lists (identical
  results and fingerprints).

**Catch-up:**
- a 100% catch-up;
- a class catch-up recipient;
- a catch-up with `P` exactly at the tolerance, just above it, negative, and
  zero;
- a catch-up already satisfied on entry.

**Promote:**
- a promote-only partner (commitment 0: MOIC N/A, IRR status);
- zero promote participants;
- two promote participants;
- a `GP`-role partner that is not a participant (Promote Earned N/A);
- an `LP`-role partner that is a participant;
- a participant with a negative profit difference (Promote Earned 0.0);
- an entry split exactly at the capital boundary in tier attribution.

**IRR:**
- a multiple-sign-change partner series (IRR N/A with its status).

### 16.4 Negative tests

Every Section 5.1 and 5.2 code has at least one test, including:

- **Missing fields:**
  - a subject, accrual convention, split rule or SIMPLE distribution order;
  - `promote_participant_ids` omitted (not defaulted to empty).
- **Misplaced or invalid fields:**
  - a distribution order on an `ANNUAL_COMPOUND` condition;
  - an unknown or duplicate promote participant;
  - a benchmark missing a partner, and a benchmark equal to commitments that
    is still required;
  - shares summing to `1 + 2e-9`;
  - `bool` shares and sequences.
- **Tier structure:**
  - two residual tiers, or a residual that is not last;
  - an explicit subject with a zero tier share.
- **Catch-up terms:**
  - a rate equal to its target;
  - an `economic_account` recipient;
  - a class recipient with no members;
  - a catch-up with `ProRataByContribution`.
- **Execution:**
  - a non-annual cadence;
  - a `NaN` in the series;
  - F11's zero-denominator refusal;
  - an unavailable upstream (no figures; reason and ids carried).

### 16.5 Architecture guards

- A production ledger for P7.9 Stage 1, measured from `5cb327d` (the
  contract-ratification merge; Stage 1 began there).
- **Inherited guards that P7.9 would trip (inspected at `79cb524`):**
  - `test_p7_8b_changed_exactly_its_authorized_backend_files` measures
    `f5850ad..working tree`. It is re-pinned to P7.8B's committed range
    `f5850ad..69af6fe` (the P7.8B head merged as `cf403c2`'s second parent),
    with a boundary test that `cf403c2`'s parents are `a9f9b09` and `69af6fe`.
  - `_CAPITAL_STRUCTURE_IMPORTERS` is an exact working-tree allowlist. It gains
    exactly `anchor/partnership/common_equity.py` and
    `anchor/partnership/contracts.py`, and nothing else.
  - **Inherited D4.6B guard (Stage 1 review).**
    `test_g37_the_financial_layers_are_unchanged_and_only_dispatch_moved`
    already failed on `main`: PR #31, a documentation-only change, edited
    `web/README.md`. `_PERMITTED_WEB` gains exactly that file, and the guard's
    rejection test keeps its teeth.
  - The P7.8B `_FROZEN` and `_PROTECTED` guards stay as they are. P7.9 edits
    none of those paths.
  - The P7.8A ledger is already pinned to `a9f9b09..f5850ad`. The P7.2 helper
    is not invoked against the working tree.
- Byte identity of the Section 1.2 frozen modules.
- **Capital Structure imports (Stage 1 clarification).**
  - `partnership/contracts.py` imports exactly two calculation-free shapes
    from `anchor.capital_structure.contracts`: `AccrualConvention` (Q21, one
    enum everywhere) and `CommonEquityUnavailableReason` (the typed upstream
    reason an unavailable result carries).
  - `partnership/common_equity.py` imports the structured result shapes.
  - Every other module takes these shapes through `partnership.contracts`.
  - The waterfall engine imports neither `anchor.capital_structure` nor
    `anchor.deals`.
  - Only `partnership/metrics.py` imports `anchor.engine.returns`.
- **No default on any economic field** (dataclass introspection), including
  `promote_participant_ids`, `split` and `simple_distribution_order`.
- **No role inference.** No module in the package reads `Partner.role` except
  to copy it into `PartnerResult` (an AST guard).
- **No duplicate authority.** No contract has a `catch_up_rate` or
  `total_profit` input field.
- The anti-overfitting guard (P7.0) covers the new package.
- No fee, tax, clawback or monthly identifier in the package.

### 16.6 Mutation proofs

Each mutant targets one explicit invariant.

**Method (Stage 1 clarification).** Mutants run in-process
(`tests/test_p7_9_mutation_proofs.py`), following the P7.8B precedent. This
replaces scratch copies and removes the known `pythonpath` trap by
construction. For every mutant:

1. **The target is this repository's code.** The patched module's file must
   resolve to this repository's `src/anchor/partnership`, and the patched
   name must be a real engine function.
2. **The fixture passes before the mutation.**
3. **The mutant is isolated.** It is applied inside its own
   `pytest.MonkeyPatch` context, and the fixture must fail under it: by an
   assertion, by an unexpected refusal or, for a refusal fixture, by pytest's
   "did not raise".
4. **The engine is restored.** After the context exits, the fixture must
   pass again, which proves the real engine is back.

| # | Mutant | Invariant | Killed by |
|---|---|---|---|
| M1 | accrual applied after the period's contribution (cash accrues in its own period) | accrual timing matches `evaluate_irr` | F1; IRR look-back oracle |
| M2 | SIMPLE accrues on `K + A` | SIMPLE never compounds (PW-3) | F2 |
| M3 | `CAPITAL_FIRST` executes as `ACCRUED_RETURN_FIRST` | the stated SIMPLE order governs | F3 (t2 accrual 68,400) |
| M4 | the hurdle account uses every partner's flows regardless of subject | the hurdle subject (Q20) | F6 |
| M5 | catch-up capacity divides by `c` instead of `c - tau` | the catch-up closed form (Q4) | F1 (`catch_up` = 67,888); catch-up closure |
| M6 | the catch-up `P > 0` domain test is removed | no catch-up while `P <= 0` | F9 (0 vs 50,000); domain property |
| M7 | `promote_earned` uses `distribution_difference` (returned capital included) | promote excludes returned capital (Q23) | F5 (none on `lp`), F7 loss case (0 vs 40,000) |
| M8 | a `GP`-role partner is treated as a participant | no role inference | the non-participant GP boundary (N/A vs a value) |
| M9 | the benchmark allocation reads `commitment_share` | the benchmark is independent (Q2) | F7 |
| M10 | a zero pro-rata denominator falls back to a substitute table (equal shares) | a deterministic refusal, not a silent substitute | F11 |

A pro-rata split that reads commitment shares instead of cumulative
contributions is an *equivalent* mutant under v1's only contribution rule. It
is recorded as such rather than claimed as a kill.

---

## 17. Module boundaries and staged implementation

### 17.1 Stage 1: deterministic contracts and engine (Tier 1)

New package `src/anchor/partnership/`:

| Module | Contents |
|---|---|
| `contracts.py` | shapes only: the Section 3, 4 and 12 contracts, issue codes and errors |
| `validation.py` | `validate_partnership`, canonical order, subject and recipient resolution; share sums are its only arithmetic |
| `allocation.py` | share allocation with the remainder partner; contribution, pro-rata-by-contribution and benchmark allocation |
| `accounts.py` | the SIMPLE (both orders), ANNUAL_COMPOUND and MOIC account states; capacity and combinator |
| `waterfall.py` | the Section 7 period loop, tier execution and catch-up; `allocate_partnership` |
| `attribution.py` | the Section 11 decomposition, Promote Earned, benchmark capital subordination and tier attribution |
| `metrics.py` | partner returns and the derived Common Equity Total Profit; the only importer of `anchor.engine.returns` |
| `common_equity.py` | `common_equity_input(structured: StructuredCapitalResult)` and `execute_partnership(partnership, structured: StructuredCapitalResult)`; the only reader of `anchor.capital_structure` results |
| `__init__.py` | exports |

Tests: `tests/test_p7_9_partnership_contracts.py`,
`test_p7_9_hurdle_accounts.py`, `test_p7_9_catch_up.py`,
`test_p7_9_pro_rata_split.py`, `test_p7_9_waterfall_fixtures.py`,
`test_p7_9_promote_attribution.py`, `test_p7_9_conservation.py`,
`test_p7_9_oracles.py`, `test_p7_9_partnership_architecture.py`,
`test_p7_9_mutation_proofs.py`, `tests/_p7_9_rational_oracle.py`, and
`tests/_p7_9_fixtures.py` (the contract builders and fixtures F1-F12; a Stage 1
implementation clarification).

### 17.2 Stage 2: persistence, migration, fingerprints and API (Tier 2 over a frozen Tier 1 engine)

- `deals/store.py`: schema **v12**, additive tables following the v11 marker
  pattern: `partnerships` (`owner_kind` `base` | `strategy`), `partners`,
  `partnership_benchmark_shares`, `partnership_promote_participants`,
  `waterfall_tiers` (including the split-rule token),
  `waterfall_tier_splits`, `waterfall_hurdle_conditions` (including the SIMPLE
  distribution order), `waterfall_catch_up_terms` (the recipient kind and
  token). Typed columns and no JSON blobs. A token the contract does not know
  fails closed. An explicit empty participant set is distinguishable from a
  missing one (a count column on `partnerships`).
- `analysis/strategy.py`: `StrategyDomain.PARTNERSHIP` joins
  `INVESTMENT_STRATEGY_DOMAINS`, with whole-domain replacement and the same
  three marker states as Capital Structure. The Project pathway never sees it.
- `deals/partnership_codec.py`: wire kinds for the typed unions (split rule,
  subject, condition, catch-up recipient).
- `deals/partnership_variants.py`: `analyze_structured_variant` →
  `execute_partnership`, with no second route to the Common Equity series.
- **Fingerprint.** `PARTNERSHIP source = f(structured source fingerprint,
  resolved partnership canonical economics)`.
  - **Included:** partner ids, `investor_class` and commitment shares;
    benchmark shares; the sorted `promote_participant_ids`; tier ids,
    sequence, kind and split rule with its shares; subject; conditions,
    including the accrual convention and SIMPLE order; combinator; catch-up
    recipient and target.
  - **Excluded:** partner and tier names, and `role` (FP-1).
  - **Order:** partners by id and tiers by sequence (§15.5).
  - No partnership means no partnership fingerprint and no key (FP-2).
  - Editing a partnership invalidates the partnership result and the PARTNER
    matrix only.
- `deals/decision_matrix.py`: the `PARTNER(partner_id)` perspective (DC-3).
  - Metrics: contributions, distributions, IRR, MOIC, profit, distribution
    difference, Promote Earned and benchmark capital subordination.
  - Promote Earned is a not-applicable cell for a non-participant.
  - The P7.8B not-applicable and unavailable cell states apply.
- `api.py`: `GET`/`PUT /deals/{id}/partnership`,
  `GET`/`PUT /investments/{id}/partnership`, a fingerprint route and an
  analysis route under `/investments/{id}/partnership-variants/{strategy}/{scenario}/`,
  `GET /investments/{id}/partner-perspectives`, and
  `POST /investments/{id}/partner-decision-matrix/{partner_id}`.
- Lifecycle: deleting a Strategy, Investment or Deal removes its partnership
  rows. P-8 partner identity is stable across Base and Strategy partnerships.
- A compatibility oracle from a real v11 database proves every recorded
  response unchanged.

### 17.3 Stage 3: product UI and browser QA (Tier 3)

- `web/src/partnershipTypes.ts`, `partnershipForm.ts`,
  `usePartnership.ts`, `usePartnerDecisionMatrix.ts`, the Partnership editor,
  the result surface (partner table, tier audit, benchmark and promote
  attribution), and the Partner matrix. `api.ts` changes are additive only.
- `web/src/partnershipArchitecture.test.ts`: the no-arithmetic guard. Every
  figure is a backend field.
- **No invented defaults.** These read "Choose…" until stated:
  - the subject, accrual convention and SIMPLE order;
  - the split rule, contribution rule and benchmark;
  - the catch-up recipient.

  Promote participants are an explicit multi-select that the analyst must
  confirm, including "none".
- The result surface separates distribution advantage / disadvantage,
  Promote Earned and benchmark capital subordination under their own labels, and never
  captions an advantage as promote.
- Browser QA at 1440, 1280 and 390, with Claude-provided screenshots and
  interactive verification. Visual acceptance stays human-owned.

Each stage stops for review. Finishing one never starts the next.

---

## 18. Deferred scope

Not in P7.9, and not introduced implicitly by any decision here:

- monthly (or any non-annual) partnership waterfalls, and non-annual accrual;
- clawbacks, GP give-backs and escrow;
- participating preferred equity and kickers;
- GP-funds-overruns and fixed-amount contribution rules; defaulting partners;
- sponsor-fee routing (acquisition, asset-management or other fees) through
  the waterfall;
- taxes, withholding and tax distributions;
- scenario probabilities and expected value;
- P7.10 valuation timepoints, AI grounding for investors, the Investment Memo
  and institutional reporting;
- refinancing and recapitalization;
- named waterfall templates as anything other than UI presets.

Not supported by design, rather than deferred:

- an `ECONOMIC_ACCOUNT` catch-up recipient (Section 4.3);
- `ProRataByContribution` on a `CATCH_UP` tier (Section 5.1).

---

## 19. Human ratification record

The human review ratified the P7.9 contract with the reviewer's recommended
decisions. The ratified decisions below govern P7.9. A ratified decision can be
reopened only by a new human ratification (§21).

### 19.1 Ratified conventions

| # | Question | Ratified convention |
|---|---|---|
| Q1 | Hurdle-subject field and type | `HurdleTerms.hurdle_subject: HurdleSubject`, required on every `HURDLE`, with no default. The kinds are `PARTNER(partner_id)`, `INVESTOR_CLASS(investor_class)` and `ECONOMIC_ACCOUNT(ALL_COMMON_EQUITY)`. A multi-member subject has one aggregate account |
| Q2 | Benchmark shares | `Partnership.promote_benchmark`, a literal table with one share per partner, summing to 1, required, with no default. It is never linked to or derived from `commitment_share`, and equality is reported as information only |
| Q3 | Below-benchmark reporting and Promote Earned | Horizon decomposition: `capital_returned = min(D, C)`, profit = the rest, and the same on the benchmark side. Reported: a signed distribution difference split into capital-return and profit-distribution differences; advantage and disadvantage; **Promote Earned = max(profit difference, 0), only for `promote_participant_ids`**; **`benchmark_capital_subordination` = max(-capital-return difference, 0)**. Signed tier attribution (`promote_attribution_by_tier` for participants) with an earliest-first capital boundary reconciles to each. There is no Promote Earned = benchmark capital subordination identity |
| Q4 | Catch-up | Recipient: `PARTNER` or `INVESTOR_CLASS`, never an account. Rate: the recipient's aggregate share in the explicit split (not stored; reported). Basis: cumulative distributions minus contributions across all tiers. **Domain: capacity is 0 while `P <= 0`**. Otherwise `max(0, (tau x P - Pr)/(c - tau))`, with `c > tau` validated. It is re-tested every distribution period |
| 5 | SIMPLE distribution order | Required `simple_distribution_order` (`ACCRUED_RETURN_FIRST` \| `CAPITAL_FIRST`) on SIMPLE conditions only, with no default |
| 6 | `PRO_RATA_BY_CONTRIBUTION` | Supported on hurdle and residual tiers, using cumulative actual contributions through the period. A zero denominator when cash must be split raises `no_contributions_for_pro_rata_split` |
| 7 | Catch-up rate | One authority, the split; the derived rate is reported |
| 8 | Negative compound balances | No floor; surplus carries forward and compounds (confirmed) |
| 9 | Common Equity Total Profit | No input field. It is derived with `calculate_project_return_totals`, and the adapter proves it bit-identical to `CommonEquityReturns.total_profit` |
| 10 | Promote participants | Required `promote_participant_ids`: zero, one or many; any role; no inference; fingerprinted |

### 19.2 Review questions, resolved

| # | Question | Ratified decision |
|---|---|---|
| R-A | The benchmark differs from contribution shares | **Retain PW-6's period-by-period benchmark.** Benchmark shares stay explicit and independent of commitment shares. The capital-first alternative, which would reopen Q23, is rejected. A mismatch (`benchmark_equals_commitment = false`) must be clearly disclosed in the product (Stage 3). Fixture F7's gain case (Promote Earned 50,000) is the ratified behavior |
| R-B | The meaning of subordination | **Benchmark capital-return shortfall only**, reported as `benchmark_capital_subordination = max(-capital_return_difference, 0)`. Profit a non-participant cedes is its negative profit-distribution difference and distribution disadvantage, never subordination |
| R-C | Decomposition basis | **Whole-hold capital / profit decomposition** (`capital_returned = min(D, C)`), with **earliest-first capital attribution** by (period, tier sequence) on both the actual and benchmark sides |
| R-D | Catch-up split rule | **A catch-up tier requires an explicit split** (`catch_up_requires_explicit_split`) |
| R-E | Non-participant Promote Earned | **N/A with a reason**: `promote_earned = None` and `NOT_A_PROMOTE_PARTICIPANT` (never `0.0`); `promote_attribution_by_tier = None` |

Also ratified, as recorded in Section 19.1 and the body:

- SIMPLE distribution order is explicit, with no default.
- A catch-up recipient may be a partner or an investor class, never an
  economic account.
- `PRO_RATA_BY_CONTRIBUTION` executes in v1. A zero denominator is a
  deterministic refusal.
- Catch-up capacity is zero while partnership profit is non-positive.
- The catch-up rate is derived from the explicit split and reported, never
  stored.
- `ANNUAL_COMPOUND` hurdle balances are not floored.
- Common Equity Total Profit is derived from the cash-flow series, with no
  input field.
- Promote participants are named explicitly by `promote_participant_ids`,
  with no role inference, and they are fingerprinted.
- Result names: `benchmark_capital_subordination` and
  `promote_attribution_by_tier`.

### 19.3 Scope of the ratification

- **Engine scope.** The ratification records the engine-scope approval of
  Section 1.1 (Q16), for the P7.9 Partnership Waterfall and Investor Return
  layer only.
- **Nothing reopened.** It changes no ratified P7.0, P7.7 or P7.8 convention
  and introduces no deferred scope (Section 18).
- **Implementation.** Stage 1 is complete and accepted in PR #34 (`70b92e2`).
  Stage 2 and Stage 3 (Section 17) have not started; each requires an explicit
  start, and finishing one never starts the next.
