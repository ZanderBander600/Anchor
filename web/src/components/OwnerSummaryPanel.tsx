import type { BreakEvenMetric, BreakEvenResult } from '../types';
import type { OwnerSummaryData } from '../ownerSummary';
import { formatCurrency, formatMultiple, formatPercent } from '../format';

interface StatCardProps {
  label: string;
  value: string;
  caption?: string;
}

/** Mirrors `ResultsPanel`'s own `StatCard` exactly (same classes, same
 * shape) -- deliberately not imported from there, since `ResultsPanel` does
 * not export it; duplicating one tiny presentational helper is simpler and
 * safer than exporting a private component across files for one reuse. */
function StatCard({ label, value, caption }: StatCardProps) {
  return (
    <div className="stat-card stat-card-primary">
      <span className="stat-label">{label}</span>
      <span className="stat-value stat-value-primary">{value}</span>
      {caption && <span className="stat-caption">{caption}</span>}
    </div>
  );
}

interface InfoRowProps {
  label: string;
  value: string;
}

function InfoRow({ label, value }: InfoRowProps) {
  return (
    <div className="info-row">
      <span className="info-label">{label}</span>
      <span className="info-value">{value}</span>
    </div>
  );
}

const BREAK_EVEN_METRIC_LABEL: Record<BreakEvenMetric, string> = {
  levered_irr: 'Target Levered IRR',
  equity_multiple: 'Target Equity Multiple',
  headline_dscr: 'Target DSCR',
};

/** Formats one break-even highlight's solved value using whichever
 * existing formatter fits its *own* fixed assumption identity (Maximum
 * Purchase Price is always a dollar amount; Maximum Exit Cap Rate and
 * Maximum Interest Rate are always decimal-fraction rates) -- a
 * presentation dispatch, exactly like the backend's own field-name ->
 * formatter convention (`anchor.ai.presentation`), never a calculation.
 * `NO_SOLUTION_IN_RANGE` renders as a plain statement, never a fabricated
 * number -- mirroring the backend's own "this does not mean no solution
 * exists" framing. */
function formatBreakEvenSolvedValue(
  result: BreakEvenResult,
  formatSolvedValue: (value: number | null) => string,
): string {
  if (result.status === 'no_solution_in_range') {
    return 'No solution within tested range';
  }
  return formatSolvedValue(result.solved_assumption_value);
}

export interface OwnerSummaryPanelProps {
  data: OwnerSummaryData;
}

/**
 * Sprint B Gate B3 -- the One-Page Owner Summary. Presentation only: every
 * value rendered here is read directly off the already-computed
 * `OwnerSummaryData` (`../ownerSummary.ts`, Gate B2) and passed through one
 * of the app's existing `formatCurrency`/`formatPercent`/`formatMultiple`
 * helpers (`../format.ts`) -- this component performs no financial
 * calculation, and reads no engine/API contract directly (never
 * `AcquisitionResults`, `AcquisitionRequest`, or a break-even *analysis*
 * contract -- only the narrow, already-normalized `OwnerSummaryData`
 * shape). One shared component for both Quick and Detailed -- the only
 * mode-specific branch anywhere below is Operating Story's growth fields,
 * which `data.operatingStory` itself already discriminates.
 */
export function OwnerSummaryPanel({ data }: OwnerSummaryPanelProps) {
  const { identity, dealContext, keyReturns, ownerReturns, investmentSnapshot, debtRisk, operatingStory, breakEvenHighlights } =
    data;

  return (
    <div className="owner-summary-panel">
      <header className="owner-summary-header">
        <h2 className="owner-summary-deal-name">{identity.dealName}</h2>
        <span className="owner-summary-mode-badge">
          {identity.operatingMode === 'quick' ? 'Quick Underwrite' : 'Detailed Underwrite'}
        </span>
      </header>

      {dealContext !== null && (
        <section className="card owner-summary-play">
          <h3 className="card-title">The Play</h3>
          <p className="owner-summary-play-text">{dealContext}</p>
        </section>
      )}

      <section className="headline-stats">
        <h3 className="card-title">Key Returns</h3>
        <div className="stat-grid">
          <StatCard label="Levered IRR" value={formatPercent(keyReturns.leveredIrr)} />
          <StatCard label="Equity Multiple" value={formatMultiple(keyReturns.equityMultiple)} />
          <StatCard
            label="Year 1 Levered CoC"
            value={formatPercent(keyReturns.yearOneLeveredCashOnCash)}
          />
          <StatCard
            label="Year 1 DSCR"
            value={formatMultiple(keyReturns.headlineDscr)}
            caption={`Minimum DSCR: ${formatMultiple(keyReturns.minDscr)}`}
          />
        </div>
        <div className="owner-summary-supporting-rows">
          <InfoRow label="Unlevered IRR" value={formatPercent(keyReturns.unleveredIrr)} />
          <InfoRow label="Year 1 Debt Yield" value={formatPercent(ownerReturns.yearOneDebtYield)} />
          <InfoRow
            label="Cumulative Operating Distributions"
            value={formatCurrency(ownerReturns.cumulativeOperatingDistributionsThroughHold)}
          />
          <InfoRow label="Year 1 NOI" value={formatCurrency(operatingStory.yearOneNoi)} />
        </div>
      </section>

      <div className="owner-summary-two-col">
        <section className="card">
          <h3 className="card-title">Investment Snapshot</h3>
          <InfoRow label="Purchase Price" value={formatCurrency(investmentSnapshot.purchasePrice)} />
          <InfoRow label="Hold Period" value={`${investmentSnapshot.holdPeriod} years`} />
          <InfoRow label="Exit Cap Rate" value={formatPercent(investmentSnapshot.exitCapRate)} />
          <InfoRow label="LTV" value={formatPercent(investmentSnapshot.ltv)} />
          <InfoRow label="Interest Rate" value={formatPercent(investmentSnapshot.interestRate)} />
          {investmentSnapshot.ioPeriod > 0 && (
            <InfoRow label="IO Period" value={`${investmentSnapshot.ioPeriod} years`} />
          )}
        </section>

        <section className="card">
          <h3 className="card-title">Debt / Risk</h3>
          <InfoRow label="Loan Amount" value={formatCurrency(debtRisk.loanAmount)} />
          <InfoRow label="LTV" value={formatPercent(debtRisk.ltv)} />
          <InfoRow label="Interest Rate" value={formatPercent(debtRisk.interestRate)} />
          {debtRisk.ioPeriod > 0 && (
            <InfoRow label="IO Period" value={`${debtRisk.ioPeriod} years`} />
          )}
          <InfoRow label="Minimum DSCR" value={formatMultiple(debtRisk.minDscr)} />
          <InfoRow label="Year 1 Debt Yield" value={formatPercent(debtRisk.yearOneDebtYield)} />
        </section>
      </div>

      <div className="owner-summary-two-col">
        <section className="card">
          <h3 className="card-title">Operating Story</h3>
          <InfoRow label="Year 1 NOI" value={formatCurrency(operatingStory.yearOneNoi)} />
          {investmentSnapshot.holdPeriod > 1 && (
            <InfoRow
              label={`Year ${investmentSnapshot.holdPeriod} NOI`}
              value={formatCurrency(operatingStory.finalYearNoi)}
            />
          )}
          {operatingStory.operatingMode === 'quick' ? (
            <InfoRow label="NOI Growth" value={formatPercent(operatingStory.noiGrowth)} />
          ) : (
            <>
              <InfoRow label="Revenue Growth" value={formatPercent(operatingStory.revenueGrowth)} />
              <InfoRow label="Expense Growth" value={formatPercent(operatingStory.expenseGrowth)} />
            </>
          )}
        </section>

        <section className="card">
          <h3 className="card-title">Owner Returns</h3>
          <InfoRow
            label="Year 1 Levered CoC"
            value={formatPercent(ownerReturns.yearOneLeveredCashOnCash)}
          />
          <InfoRow label="Year 1 Debt Yield" value={formatPercent(ownerReturns.yearOneDebtYield)} />
          <InfoRow
            label="Cumulative Operating Distributions"
            value={formatCurrency(ownerReturns.cumulativeOperatingDistributionsThroughHold)}
          />
        </section>
      </div>

      {breakEvenHighlights !== null && (
        <section className="card">
          <h3 className="card-title">Break-Even Highlights</h3>
          <InfoRow
            label={`Max Purchase Price (${BREAK_EVEN_METRIC_LABEL[breakEvenHighlights.maxPurchasePrice.metric]})`}
            value={formatBreakEvenSolvedValue(breakEvenHighlights.maxPurchasePrice, formatCurrency)}
          />
          <InfoRow
            label={`Max Exit Cap Rate (${BREAK_EVEN_METRIC_LABEL[breakEvenHighlights.maxExitCapRate.metric]})`}
            value={formatBreakEvenSolvedValue(breakEvenHighlights.maxExitCapRate, formatPercent)}
          />
          <InfoRow
            label={`Max Interest Rate (${BREAK_EVEN_METRIC_LABEL[breakEvenHighlights.maxInterestRate.metric]})`}
            value={formatBreakEvenSolvedValue(breakEvenHighlights.maxInterestRate, formatPercent)}
          />
        </section>
      )}
    </div>
  );
}
