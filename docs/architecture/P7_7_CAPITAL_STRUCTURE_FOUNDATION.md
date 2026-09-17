# P7.7 Capital Structure Foundation + Legacy Debt Adapter

Status: human-reviewed, accepted, and merged in `a9f9b09` (PR #27).
Base: `main` @ `fbaa07b` (the P7.6 merge).
Historical branch: `feature/p7-7-capital-structure-foundation`.
Risk: Tier 1 (financial / contract critical).

Current-state note: this is the completed P7.7 implementation decision record,
not an open review request. See `docs/CURRENT_STATE.md`.

`docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md` is the authority
(Sections 3, 12, 14, 15 and 21). This record states only what P7.7 decided and
shipped under it. It reopens no ratified decision.

---

## 1. Engine-scope approval (Q16)

P7.7's one Tier 1 approval covers:

- new downstream Capital Structure contracts;
- deterministic scope and priority validation;
- model-month-capable capital-event contracts;
- deterministic claim settlement and Funding Requirement reporting;
- a read-only adapter for each Unit's existing acquisition loan;
- a neutral facade whose Common Equity Cash Flow is today's levered cash flow;
- the explicit handoff between Property / Business Plan economics and Capital
  Structure economics.

It does not cover any change to:

- acquisition debt, loan sizing, amortization, interest-only or fee formulas;
- D6 owner cash flow;
- the IRR;
- consolidation;
- any frontend financial calculation.

It also does not cover building any of the following:

- new position cash flows or position returns;
- refinancing or recapitalization;
- partnership economics;
- AI.

`debt.py`, `acquisition.py`, `noi.py`, `returns.py` and `consolidation/engine.py`
are byte-identical to `fbaa07b`.

## 2. What shipped

One new package, `src/anchor/capital_structure/`. It changes no existing
production file, schema, route or frontend file.

| Module | Contents |
|---|---|
| `contracts.py` | Shapes only. `PositionClass`, `ScopeKind` / `PositionScope`, `ShortfallResolution`, `AccrualConvention`; the funding amount rules `FixedAmount`, `PctOfPrice` and `PctOfValue`; `FundingEvent`, `PositionFee`, `DebtTerms`, `PreferredEquityTerms`, `CapitalPosition` and `CapitalStructure`; issues and errors; `ModelMonthPeriod` / `HoldYearPeriod`, `ContractualClaim`, `FundingRequirement` and `ClaimSettlement`; `LegacyAcquisitionLoan`; the cash authorities; and the facade results. |
| `validation.py` | `validate_capital_structure`, `economic_order` and `scope_order_key`. Structural rules only, with no arithmetic. |
| `legacy.py` | `adapt_legacy_acquisition_loan`, `legacy_acquisition_loan_claims` and `legacy_acquisition_loan_id`. |
| `foundation.py` | `annual_period_of_model_month`, `settle_claim`, `common_equity_outcome`, the cash authorities, and the two facades `analyze_unit_capital_structure` and `analyze_investment_capital_structure`. |

Every contract is a frozen, slotted, keyword-only dataclass.

Wire values are lower-case: `senior_debt`, `mezzanine_debt`,
`preferred_equity`, `common_equity`; `unit`, `investment`;
`common_equity_contribution`, `unresolved`; `simple`, `annual_compound`.

## 3. Executable scope

The executor runs exactly two things:

- each Unit's existing acquisition loan;
- the implicit residual common equity.

`None` and the empty `CapitalStructure` mean "no authored position", which is
today's behavior (P-11). Any authored position of any class is refused:

- an invalid structure raises `CapitalStructureValidationError`;
- a valid structure raises `UnsupportedCapitalPositionError`, with one
  `unsupported_position` issue per position, in economic order.

An authored position is never ignored and never partially executed.

## 4. The pre-capital-structure cash authority

| Layer | Authority | Contract field |
|---|---|---|
| Unit, before its acquisition loan | `AcquisitionResults.unlevered_cash_flows` | `UnitCashAuthority.pre_acquisition_debt_cash_flows` |
| Unit, after its acquisition loan | `AcquisitionResults.levered_cash_flows` (plus the Levered Owner Cash Flow and Net Sale Proceeds) | `UnitCashAuthority.post_acquisition_debt_cash_flows` |
| Investment, after every Unit position and the Investment-level channels | `ConsolidatedResults.levered_cash_flows` (plus the consolidated Levered Owner Cash Flow and Net Sale Proceeds) | `InvestmentScopeCashAuthority.cash_flows_after_unit_positions` |

- The acquisition loan already bridges the Unit's pre- and post-debt
  authorities inside the engine. The facade passes the post-debt series
  through untouched; it never subtracts the loan's debt service, balance or
  fee again.
- A later Unit-scoped junior position reads the post-debt figures (CS-6).
- An Investment-scoped position reads only the Investment authority.
  `InvestmentScopeCashAuthority` has no unlevered field, so no position can
  start from `ConsolidatedResults.unlevered_cash_flows` while Unit loans exist
  (CS-4).

## 5. The legacy acquisition-loan adapter

- **Owners unchanged.** `AcquisitionTerms`, `anchor.engine.debt` and
  `AcquisitionResults` still own the loan. The adapter imports no debt function.
- **Read from `AcquisitionResults`, never recomputed:** `loan_amount` (also the
  closing `FundingEvent`), `financing_fee` (a closing `PositionFee`),
  `annual_debt_service` and `remaining_loan_balance`.
- **Read from `AcquisitionTerms`, descriptive only:** `interest_rate`,
  `amortization`, `io_period` and `hold_period`.
- **Identity:** `legacy-acquisition-loan:<unit_id>`. It is scoped to the Unit,
  has priority 1 and is `senior_debt`. The prefix is reserved: an authored
  position, funding event or fee that uses it is refused (`reserved_identity`).
  It is never stored.
- **Zero debt:** `loan_amount == 0` means no position at all. A result with
  zero loan but a fee, debt service or balance is refused as incoherent.
- **Payoff:** `modeled_payoff_month = 12 x hold_period`. This is the modeled
  sale, when Anchor repays whatever balance remains. It is not a legal
  maturity. The acquisition model records no maturity, current-pay rate or PIK
  rate, so none is fabricated, and `LegacyAcquisitionLoan` has no such field.
- **Resolution:** `COMMON_EQUITY_CONTRIBUTION`. This is the loan's own frozen
  D6 treatment (FR-5): debt service is always paid, and negative Levered Owner
  Cash Flow is common equity's.

## 6. Funding Requirements (Section 21.3 decisions)

### 6.1 The first resolutions

Exactly two resolutions ship: `COMMON_EQUITY_CONTRIBUTION` and `UNRESOLVED`.
There is no default:

- no dataclass field or parameter defaults a resolution;
- a claim-bearing position without one is invalid
  (`missing_shortfall_resolution`);
- `settle_claim` refuses a claim without one.

Common equity carries no resolution, because it has no contractual claim.

Reserve draws, protective advances, PIK cures, cash traps and default remedies
are not shipped. Common-equity contribution is not a global rule: in P7.7 only
the legacy adapter states it.

### 6.2 Settlement (`settle_claim`)

The inputs arrive already stated: the claim due, the eligible cash (finite and
`>= 0`), the position, the scope, the period and the explicit resolution.

| Case | Funding Requirement | Paid | Equity contribution | Unpaid |
|---|---|---|---|---|
| claim `<=` cash | none | the claim, from cash | 0 | 0 |
| shortfall, `COMMON_EQUITY_CONTRIBUTION` | `RESOLVED`, amount = claim - cash | the whole claim | the shortfall | 0 |
| shortfall, `UNRESOLVED` | `UNRESOLVED`, amount = claim - cash | the cash only | 0 | the shortfall |

### 6.3 Legacy reporting

For each hold year `y` of a Unit with an acquisition loan:

- **Claim:** the debt service for year `y`, plus `remaining_loan_balance` in
  the final year `H`.
- **Eligible cash:** the nonnegative part of that Unit's
  `unlevered_cash_flows[y]`. This is its Unlevered Owner Cash Flow; in year `H`
  it also includes the pre-debt sale cash, Gross Exit Value less Disposition
  Costs.
- **Requirement:** reported whenever the claim exceeds the eligible cash, in a
  `HoldYearPeriod`. Its resolution is `COMMON_EQUITY_CONTRIBUTION`, so the
  claim is paid in full, and the Common Equity Cash Flow is unchanged.

### 6.4 A Funding Requirement is not the NAER

A Funding Requirement reports a claim shortfall only.

- When the pre-debt cash is positive but short, the requirement equals the D6
  Net Additional Equity Requirement for that year.
- When the pre-debt cash is negative, the requirement is only the debt claim.
  The negative Property / Business Plan cash stays common equity's, inside the
  NAER.

### 6.5 The unresolved-funding rule

While any Funding Requirement is `UNRESOLVED`:

- the status is `UNRESOLVED_FUNDING` (incomplete);
- `common_equity_cash_flows` is `None`, with reason
  `unresolved_funding_requirement` and a message that names every unresolved
  requirement;
- nothing is zero-filled, partial, cured by equity or written off;
- upstream Property, Business Plan and consolidated project results are
  untouched.

P7.8's position returns downstream of an unresolved point report N/A with the
same reason.

### 6.6 Scope isolation

A Unit-scoped claim is met only from its own Unit's cash: the claims builder
refuses a cash authority of another Unit. A shortfall in one Unit is never
netted against another Unit's surplus, and cross-collateralization is never
inferred.

## 7. Timing

- **Capital contracts are model-month capable.** `FundingEvent`, `PositionFee`,
  `DebtTerms.maturity_month` and `PreferredEquityTerms.redemption_month` carry
  D6 Section 4 model months.
- **The convention.** `annual_period_of_model_month` restates the D6
  convention: month 0 is closing, and month `m` falls in hold year
  `((m - 1) // 12) + 1`. Tests check it against the D6 Business Plan
  resolver's own bucketing.
- **Honest periods.** Cash availability from `AcquisitionResults` is annual.
  So a legacy requirement uses a `HoldYearPeriod`, which never claims an exact
  month. An authored event's requirement can use a `ModelMonthPeriod`. The
  two are distinct types, each with its own `TimingBasis`.

## 8. Structural rules

- **Scope.** `UNIT` has exactly one nonblank `unit_id`, and `INVESTMENT` has
  none. When the analysis' Unit set is supplied, a foreign Unit is refused.
- **Priority.** Priority is a whole number `>= 1` (`bool` is refused); lower
  is more senior.
  - It is unique within a scope, and may repeat across scopes.
  - Priority 1 of a Unit that carries an acquisition loan is that loan's.
- **Economic order.** Every Unit scope comes first, by `unit_id`, then the
  Investment scope; within a scope, positions follow priority. List order
  never participates, and `position_id` only makes the order total.
- **Pairing.** The debt classes carry `DebtTerms`, preferred equity carries
  `PreferredEquityTerms`, and common equity carries no terms and no funding.
- **Preferred equity.** `accrual_permitted` is an explicit `bool`.
  - When accrual is permitted, the convention is required.
  - When accrual is not permitted, no convention may be stated, and none is
    inferred.
- **Identity.**
  - Every position id is unique.
  - Funding events and fees share one capital-event namespace across the
    structure.
  - Within one position, each (model month, sequence) pair is used once.
- **Domains.** Rates must be finite and `>= 0`, the `interest_rate` domain.
  Funding percentages must lie in `(0, 1]`, the `ltv` domain less zero. A
  fixed funding must be `> 0`, because a zero-dollar position does not exist.
  Fees must be finite and `>= 0`.
- **CS-5.** Investment-scoped senior debt is refused
  (`investment_senior_debt_with_acquisition_loan`) while any Unit carries an
  acquisition loan. The caller must state which Units carry a loan; it is
  never assumed that none does.
- **Determinism.** Issue order never depends on how the positions were listed.

## 9. Deferred to P7.8 and later

- **P7.8** owns all of the following:
  - executing authored senior, mezzanine, preferred and common positions;
  - their cash flows, current pay, PIK and preferred accrual, and redemption
    and repayment;
  - position IRR, MOIC and profit;
  - attachment and detachment, last-dollar basis, and coverage and debt yield
    through a position;
  - how `current_pay_rate` and `pik_rate` combine;
  - Capital Structure persistence and its product surface;
  - activating the Strategy `CAPITAL_STRUCTURE` domain.
- **P7.10** owns valuation timepoints: `PctOfValue` is representable, but
  nothing values it yet.
- **Later gates** own:
  - refinancing and recapitalization, the focused sub-gate;
  - partnership economics;
  - further shortfall resolutions;
  - a monthly cash-availability cadence.

The Decision Matrix stays on the `PROJECT` perspective.

## 10. Evidence

| Proof | Where |
|---|---|
| Contracts, validation, model month, scope, priority, subordination, CS-5, fail-closed executor | `tests/test_p7_7_capital_structure_contracts.py` |
| Bit-for-bit parity (nine Quick / Detailed / Lease-Level cases: leverage, fees, IO, Business Plans, negative owner years); handoff identity; zero debt; the named double-counting oracle; the result-authority oracle (a distinguishable synthetic result, and every `debt.py` function monkeypatched to explode); the visible four-Unit mixed-mode Investment with Unit and Investment plans and a transaction cost | `tests/test_p7_7_legacy_adapter.py` |
| Settlement, legacy requirements, exit-year claim, FR vs NAER, multi-Unit isolation, the unresolved downstream oracle | `tests/test_p7_7_funding_requirements.py` |
| Ledger, byte identity of the mature modules, imports, arithmetic, neutrality pins, no implicit cure, no later-gate economics | `tests/test_p7_7_capital_structure_architecture.py` |
| Every representative existing response identical against the git-archived `fbaa07b` tree; no schema change; no read-triggered write | `tests/test_p7_7_compatibility_oracle.py` |

Focused mutants M1-M8 were killed; the gate report records the results. The
P7.6 production ledger is re-pinned to its committed range, `6cade62..fbaa07b`.
