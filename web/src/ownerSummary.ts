/**
 * Sprint B Gate B2 -- Owner Summary data contract + presentation adapter.
 *
 * `buildOwnerSummaryData` is a pure, side-effect-free function that selects,
 * renames, and groups already-authoritative Anchor data (validated
 * assumptions, engine-computed `AcquisitionResults`, and already-computed
 * break-even output) into `OwnerSummaryData` -- the one typed view-model the
 * future `OwnerSummaryPanel` (Gate B3) will render. It performs NO
 * financial calculation of its own: every field below is either a direct
 * field read, a first/last array index (trivial presentation indexing, not
 * arithmetic), or a straight passthrough. If a value is not already
 * authoritative somewhere in Anchor's existing contracts, it is not
 * represented here.
 *
 * `AcquisitionResults` is identical for Quick and Detailed (confirmed by
 * inspection of `src/anchor/engine/contracts.py` -- Detailed's
 * `DetailedAcquisitionResults.results` is the exact same shape); callers
 * unwrap it before calling this module (`detailedResults.results`), exactly
 * as `App.tsx` already does for `ResultsPanel`. This module therefore never
 * imports or reads `DetailedAcquisitionResults`/`OperatingProjection` --
 * Quick/Detailed only diverge here where the underlying *input* contracts
 * genuinely differ: `AcquisitionRequest` (Quick, carries `noi_growth`) vs.
 * `AcquisitionTermsRequest` + `DetailedOperatingInputsRequest` (Detailed,
 * carries `revenue_growth`/`expense_growth` instead).
 *
 * Per Gate B2's locked product decisions: hurdle targets are not
 * represented at all (omission preferred over complexity -- see the module
 * docstring section below), the optional annual Levered CoC sparkline is
 * out of scope, and break-even highlights are optional -- `null` when the
 * workspace has not computed break-even this session (it is never
 * persisted/restored, see `docs/one_page_owner_summary_v3_spec.md` Section
 * 10), never recomputed here.
 *
 * Availability: this module does not decide whether an Owner Summary
 * *can* be shown for the current deal -- exactly like `ResultsPanel`, the
 * caller only invokes `buildOwnerSummaryData` once it already has a valid,
 * non-null `AcquisitionResults` (a fresh `/analyze` response or a restored
 * `analysis_snapshot` -- this function cannot tell the difference and does
 * not need to; see Gate B1 Section 21 / Gate B2 Section 21). There is no
 * "unavailable" variant of `OwnerSummaryData` here on purpose -- an absent
 * summary is the caller simply not rendering one, the same gate every other
 * results panel already uses.
 */

import type {
  AcquisitionRequest,
  AcquisitionTermsRequest,
  AcquisitionResults,
  BreakEvenResult,
  DetailedOperatingInputsRequest,
  OperatingMode,
  StandardBreakEvenAnalysis,
  StandardDetailedBreakEvenAnalysis,
} from './types';

// =============================================================================
// Output contract
// =============================================================================

export interface OwnerSummaryIdentity {
  dealName: string;
  operatingMode: OperatingMode;
}

/** Section D (B1) / "Key Returns" (B2 Section 8) -- the hero-tier return
 * metrics plus the one supporting metric (Unlevered IRR) B2 explicitly asks
 * to make available alongside them. Every field is a direct
 * `AcquisitionResults` read; `null` is preserved exactly where the engine
 * itself returns `None` (e.g. `headlineDscr`/`minDscr` under zero leverage,
 * a non-convergent IRR) -- never coerced to `0`. */
export interface OwnerSummaryKeyReturns {
  leveredIrr: number | null;
  unleveredIrr: number | null;
  equityMultiple: number | null;
  yearOneLeveredCashOnCash: number | null;
  headlineDscr: number | null;
  minDscr: number | null;
}

/** Section E (B1) / "Owner Returns" (B2 Section 9). The three headline
 * figures plus the three complete annual schedules, passed through
 * unmodified for B3 to choose whether to render (e.g. a future trend
 * strip) -- no new schedule or total is computed here; the "cumulative
 * through hold" figure is the schedule's own last entry, not a re-summed
 * value. */
export interface OwnerSummaryOwnerReturns {
  yearOneLeveredCashOnCash: number | null;
  yearOneDebtYield: number | null;
  cumulativeOperatingDistributionsThroughHold: number;
  leveredCashOnCashByYear: readonly (number | null)[];
  unleveredCashYieldByYear: readonly (number | null)[];
  cumulativeOperatingDistributionsByYear: readonly number[];
}

/** Section C (B1) / "Investment Snapshot" (B2 Section 10). Six of these
 * fields (`purchasePrice` through `ioPeriod`) come from the validated
 * assumption contract (`AcquisitionRequest` for Quick, `AcquisitionTermsRequest`
 * for Detailed) rather than from `AcquisitionResults` -- neither
 * `AcquisitionResults` nor `DetailedAcquisitionResults` carries
 * purchase price, hold period, exit cap rate, LTV, interest rate, or IO
 * period (confirmed by inspection of `engine/contracts.py`); these are
 * inputs, not engine output. `loanAmount`/`yearOneNoi`/`goingInCapRate`
 * *are* `AcquisitionResults` fields and are shared verbatim with
 * `OwnerSummaryDebtRisk`/`OwnerSummaryOperatingStory` below -- the same
 * authoritative value legitimately appears in more than one presentation
 * group (mirroring how the existing `ResultsPanel` already repeats Year 1
 * DSCR as both a hero card and a Capitalization detail row). */
export interface OwnerSummaryInvestmentSnapshot {
  purchasePrice: number;
  holdPeriod: number;
  exitCapRate: number;
  ltv: number;
  interestRate: number;
  ioPeriod: number;
  loanAmount: number;
  yearOneNoi: number;
  goingInCapRate: number;
}

/** Section F (B1) / "Debt / Risk" (B2 Section 11). Every field is already
 * present in `OwnerSummaryInvestmentSnapshot`/`OwnerSummaryKeyReturns` --
 * this group exists only so B3 can render the debt/coverage story as one
 * self-contained unit without reaching back into the other two groups. */
export interface OwnerSummaryDebtRisk {
  loanAmount: number;
  ltv: number;
  interestRate: number;
  ioPeriod: number;
  headlineDscr: number | null;
  minDscr: number | null;
  yearOneDebtYield: number | null;
}

/** Section G (B1)/(B2 Section 12). Discriminated on `operatingMode` because
 * Quick and Detailed genuinely have different, non-overlapping growth
 * *inputs* (a single blended `noiGrowth` vs. two independent
 * `revenueGrowth`/`expenseGrowth` rates) -- there is no shared field to
 * normalize them onto, and inventing one (a blended rate, a spread, a CAGR)
 * would be exactly the new calculation this gate forbids. `finalYearNoi` is
 * `noi_by_year`'s last entry -- whatever the deal's actual hold period is,
 * never a hardcoded "Year 5". */
export type OwnerSummaryOperatingStory =
  | {
      operatingMode: 'quick';
      yearOneNoi: number;
      finalYearNoi: number;
      noiGrowth: number;
    }
  | {
      operatingMode: 'detailed';
      yearOneNoi: number;
      finalYearNoi: number;
      revenueGrowth: number;
      expenseGrowth: number;
    };

/** Section H (B1)/(B2 Section 13) -- optional. `null` whenever the
 * workspace has not run break-even this session (it is never persisted or
 * restored on deal reopen -- see the B1 spec, Section 10); never a
 * placeholder or recomputed value. Each field is the complete, existing
 * `BreakEvenResult` (not a re-picked subset of it) so B3 has the solved
 * value, status, and search bounds all together, exactly as
 * `StandardBreakEvenAnalysis`/`StandardDetailedBreakEvenAnalysis` already
 * expose them. Deliberately narrower than the B1 spec's original four-
 * number proposal (no "Base Levered IRR") -- Gate B2's own field list
 * (Section 13) asks for exactly these three. */
export interface OwnerSummaryBreakEvenHighlights {
  maxPurchasePrice: BreakEvenResult;
  maxExitCapRate: BreakEvenResult;
  maxInterestRate: BreakEvenResult;
}

/**
 * The complete Owner Summary view-model. No "metadata" group is present
 * as its own top-level key -- `identity.operatingMode` is the only "label
 * mode" data any group needs (B2 Section 5 group I), and a second, empty
 * carrier for the same one value would violate the "no empty groups for
 * symmetry" rule.
 *
 * Hurdle/return targets are deliberately absent from this contract
 * entirely, per the Gate B2-locked product decision not to persist or
 * otherwise depend on them: they remain purely ephemeral `App.tsx` form
 * state, and `OwnerSummaryData` must be fully renderable without them.
 */
export interface OwnerSummaryData {
  identity: OwnerSummaryIdentity;
  dealContext: string | null;
  keyReturns: OwnerSummaryKeyReturns;
  ownerReturns: OwnerSummaryOwnerReturns;
  investmentSnapshot: OwnerSummaryInvestmentSnapshot;
  debtRisk: OwnerSummaryDebtRisk;
  operatingStory: OwnerSummaryOperatingStory;
  breakEvenHighlights: OwnerSummaryBreakEvenHighlights | null;
}

// =============================================================================
// Input contract
// =============================================================================

/**
 * The authoritative source data `buildOwnerSummaryData` reads from --
 * already-validated/already-computed frontend state, never raw form
 * strings (`AcquisitionFormValues`/`DetailedFormValues`) and never a
 * `DetailedAcquisitionResults` envelope (callers unwrap `.results` first,
 * matching the existing `ResultsPanel` call convention). Discriminated on
 * `operatingMode` exactly like `Deal`/`AnalysisContext` already are on the
 * backend, so a Quick source can never carry Detailed-only fields or vice
 * versa -- TypeScript, not a runtime check, enforces this.
 *
 * `results`/`breakEven` are identical in *origin* whether they came from a
 * fresh `/analyze`/`/break-even` response this session or from a restored
 * `analysis_snapshot` -- this type carries no field that distinguishes the
 * two, by design (Gate B2 Section 21: the builder must behave identically
 * either way).
 */
export type OwnerSummarySource =
  | {
      operatingMode: 'quick';
      dealName: string;
      dealContext: string | null;
      inputs: AcquisitionRequest;
      results: AcquisitionResults;
      breakEven: StandardBreakEvenAnalysis | null;
    }
  | {
      operatingMode: 'detailed';
      dealName: string;
      dealContext: string | null;
      terms: AcquisitionTermsRequest;
      detailedOperatingInputs: DetailedOperatingInputsRequest;
      results: AcquisitionResults;
      breakEven: StandardDetailedBreakEvenAnalysis | null;
    };

// =============================================================================
// Builder
// =============================================================================

/** The one existing-frontend-behavior normalization this module applies:
 * blank/whitespace-only Deal Context reads as "no context supplied," never
 * as a spurious present-but-empty value. Mirrors `App.tsx`'s own
 * `dealContext.trim() || null` (used when building a Save request) --
 * not a new rule invented for this contract. */
function normalizeDealContext(dealContext: string | null): string | null {
  if (dealContext === null) {
    return null;
  }
  const trimmed = dealContext.trim();
  return trimmed === '' ? null : trimmed;
}

function buildKeyReturns(results: AcquisitionResults): OwnerSummaryKeyReturns {
  return {
    leveredIrr: results.levered_irr,
    unleveredIrr: results.unlevered_irr,
    equityMultiple: results.equity_multiple,
    yearOneLeveredCashOnCash: results.levered_cash_on_cash_by_year[0],
    headlineDscr: results.headline_dscr,
    minDscr: results.min_dscr,
  };
}

function buildOwnerReturns(results: AcquisitionResults): OwnerSummaryOwnerReturns {
  const cumulativeSchedule = results.cumulative_operating_distributions_by_year;
  return {
    yearOneLeveredCashOnCash: results.levered_cash_on_cash_by_year[0],
    yearOneDebtYield: results.year_1_debt_yield,
    cumulativeOperatingDistributionsThroughHold: cumulativeSchedule[cumulativeSchedule.length - 1],
    leveredCashOnCashByYear: results.levered_cash_on_cash_by_year,
    unleveredCashYieldByYear: results.unlevered_cash_yield_by_year,
    cumulativeOperatingDistributionsByYear: cumulativeSchedule,
  };
}

/** The six assumption fields `OwnerSummaryInvestmentSnapshot`/
 * `OwnerSummaryDebtRisk` need that exist identically, under identical
 * names, on both `AcquisitionRequest` (Quick) and `AcquisitionTermsRequest`
 * (Detailed) -- structurally, not by a mode branch: both request shapes
 * already satisfy this narrower type without a cast, since
 * `AcquisitionTermsRequest` is exactly `AcquisitionRequest` minus
 * `current_noi`/`occupancy`/`noi_growth` (confirmed against
 * `src/anchor/contracts.py`). */
interface SharedAcquisitionTermsFields {
  purchase_price: number;
  hold_period: number;
  exit_cap_rate: number;
  ltv: number;
  interest_rate: number;
  io_period: number;
}

function buildInvestmentSnapshot(
  terms: SharedAcquisitionTermsFields,
  results: AcquisitionResults,
): OwnerSummaryInvestmentSnapshot {
  return {
    purchasePrice: terms.purchase_price,
    holdPeriod: terms.hold_period,
    exitCapRate: terms.exit_cap_rate,
    ltv: terms.ltv,
    interestRate: terms.interest_rate,
    ioPeriod: terms.io_period,
    loanAmount: results.loan_amount,
    yearOneNoi: results.noi_by_year[0],
    goingInCapRate: results.going_in_cap_rate,
  };
}

function buildDebtRisk(
  terms: SharedAcquisitionTermsFields,
  results: AcquisitionResults,
): OwnerSummaryDebtRisk {
  return {
    loanAmount: results.loan_amount,
    ltv: terms.ltv,
    interestRate: terms.interest_rate,
    ioPeriod: terms.io_period,
    headlineDscr: results.headline_dscr,
    minDscr: results.min_dscr,
    yearOneDebtYield: results.year_1_debt_yield,
  };
}

function buildOperatingStory(source: OwnerSummarySource): OwnerSummaryOperatingStory {
  const noiByYear = source.results.noi_by_year;
  const yearOneNoi = noiByYear[0];
  const finalYearNoi = noiByYear[noiByYear.length - 1];

  if (source.operatingMode === 'quick') {
    return {
      operatingMode: 'quick',
      yearOneNoi,
      finalYearNoi,
      noiGrowth: source.inputs.noi_growth,
    };
  }

  return {
    operatingMode: 'detailed',
    yearOneNoi,
    finalYearNoi,
    revenueGrowth: source.detailedOperatingInputs.revenue_growth,
    expenseGrowth: source.detailedOperatingInputs.expense_growth,
  };
}

/** Reads only the three fields `StandardBreakEvenAnalysis` (Quick, 5
 * members) and `StandardDetailedBreakEvenAnalysis` (Detailed, 3 members)
 * have in common, under identical names/types -- again structural, not a
 * mode branch. Returns `null` when no break-even has been computed this
 * session (see the `OwnerSummaryBreakEvenHighlights` docstring above) --
 * never recomputed or fabricated here. */
function buildBreakEvenHighlights(
  breakEven: StandardBreakEvenAnalysis | StandardDetailedBreakEvenAnalysis | null,
): OwnerSummaryBreakEvenHighlights | null {
  if (breakEven === null) {
    return null;
  }
  return {
    maxPurchasePrice: breakEven.max_purchase_price,
    maxExitCapRate: breakEven.max_exit_cap_rate,
    maxInterestRate: breakEven.max_interest_rate,
  };
}

/**
 * Build the Owner Summary view-model from already-authoritative Anchor
 * state. Deterministic and side-effect free: the same `source` always
 * produces the same `OwnerSummaryData`, whether `source.results` came from
 * a fresh `/analyze` call or a restored `analysis_snapshot` -- this
 * function has no way to tell the difference and does not need one.
 *
 * Callers must only invoke this once a valid `AcquisitionResults` already
 * exists for the current deal (mirroring `{results && <ResultsPanel .../>}`
 * -- see the module docstring's "Availability" note); there is no
 * "analysis not yet available" variant of `OwnerSummaryData`.
 */
export function buildOwnerSummaryData(source: OwnerSummarySource): OwnerSummaryData {
  const terms: SharedAcquisitionTermsFields =
    source.operatingMode === 'quick' ? source.inputs : source.terms;

  return {
    identity: {
      dealName: source.dealName,
      operatingMode: source.operatingMode,
    },
    dealContext: normalizeDealContext(source.dealContext),
    keyReturns: buildKeyReturns(source.results),
    ownerReturns: buildOwnerReturns(source.results),
    investmentSnapshot: buildInvestmentSnapshot(terms, source.results),
    debtRisk: buildDebtRisk(terms, source.results),
    operatingStory: buildOperatingStory(source),
    breakEvenHighlights: buildBreakEvenHighlights(source.breakEven),
  };
}
