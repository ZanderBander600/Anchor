import { useState } from 'react';
import type { BreakEvenMetric, BreakEvenResult, DealStory } from '../types';
import type { OwnerSummaryData } from '../ownerSummary';
import { formatCurrency, formatMultiple, formatPercent } from '../format';

interface StatCardProps {
  label: string;
  value: string;
  caption?: string;
}

/** Sprint C Gate C4: the owner-facing hero metric. A light card with a
 * subtle label and a strong numeral -- no heavy top rule, no grey container,
 * no nesting. Presentation only; the value arrives already formatted. */
function StatCard({ label, value, caption }: StatCardProps) {
  return (
    <div className="metric-card">
      <span className="metric-card-label">{label}</span>
      <span className="metric-card-value">{value}</span>
      {caption && <span className="metric-card-caption">{caption}</span>}
    </div>
  );
}

/** A compact owner-level figure used where a full card would be too loud --
 * the break-even highlights and the supporting return strip. */
function MiniMetric({ label, value, caption }: StatCardProps) {
  return (
    <div className="mini-metric">
      <span className="mini-metric-label">{label}</span>
      <span className="mini-metric-value">{value}</span>
      {caption && <span className="mini-metric-caption">{caption}</span>}
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

/**
 * Sprint B Gate B4 -- the AI Deal Story block, positioned by Gate B5
 * directly beneath the Key Returns metrics it interprets. Visually
 * subordinate to every deterministic metric: a muted, explicitly labeled
 * "AI Interpretation" panel, never a `.stat-card`, never a headline. It renders only what the backend
 * `DealStory` contract already contains -- no slicing, no re-ranking, no
 * truncation (the max-2 caps are enforced in `anchor.ai.contracts`), and
 * absolutely no financial calculation.
 *
 * Renders nothing at all when `dealStory` is `null` (no AI generated yet,
 * or a restored pre-B4 snapshot): the deterministic Owner Summary above
 * stands on its own, and the existing "Generate AI Analysis" action in
 * `AiAnalystPanel` remains the single, unduplicated way to produce one.
 */
function DealStorySection({ dealStory }: { dealStory: DealStory }) {
  const { investment_view, key_strengths, key_risks, model_gap } = dealStory;

  return (
    <section className="card owner-summary-story" aria-label="AI Interpretation">
      <div className="owner-summary-story-header">
        <h3 className="card-title">Deal Story</h3>
        <span className="owner-summary-story-badge">AI Interpretation</span>
      </div>

      <p className="owner-summary-story-view">{investment_view}</p>

      {(key_strengths.length > 0 || key_risks.length > 0) && (
        <div className="owner-summary-story-columns">
          {key_strengths.length > 0 && (
            <div className="owner-summary-story-column">
              <h4 className="owner-summary-story-subtitle">Strengths</h4>
              <ul className="owner-summary-story-list">
                {key_strengths.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </div>
          )}
          {key_risks.length > 0 && (
            <div className="owner-summary-story-column">
              <h4 className="owner-summary-story-subtitle">Risks</h4>
              <ul className="owner-summary-story-list">
                {key_risks.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {model_gap !== null && (
        <div className="owner-summary-story-gap">
          <h4 className="owner-summary-story-subtitle">Model Gap</h4>
          <p className="owner-summary-story-gap-text">{model_gap}</p>
        </div>
      )}
    </section>
  );
}

export interface OwnerSummaryPanelProps {
  data: OwnerSummaryData;
  /** The concise AI interpretation for this exact deal state, or `null`
   * when none has been generated (or a restored snapshot predates Gate
   * B4). Supplied as its own prop rather than folded into
   * `OwnerSummaryData` on purpose: `OwnerSummaryData` is the deterministic
   * view-model, and keeping AI output structurally outside it makes the
   * deterministic/AI boundary visible in this component's own signature.
   * It also means the Deal Story invalidates exactly when the AI analysis
   * does -- the caller passes `aiAnalysis?.deal_story ?? null`, so every
   * existing `clearAiAnalysis()` path clears the Deal Story for free. */
  dealStory?: DealStory | null;
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
export function OwnerSummaryPanel({ data, dealStory = null }: OwnerSummaryPanelProps) {
  const { identity, dealContext, keyReturns, ownerReturns, investmentSnapshot, debtRisk, operatingStory, breakEvenHighlights } =
    data;

  // Sprint C Gate C4: The Play is clamped to a couple of lines so a long
  // business plan cannot push the owner story below the fold. Local
  // presentation state only -- it touches no deal, analysis or AI state.
  const [isPlayExpanded, setIsPlayExpanded] = useState(false);
  const isPlayLong = dealContext !== null && dealContext.length > 170;

  return (
    <div className="owner-summary-panel">
      <header className="owner-summary-header">
        <h2 className="owner-summary-deal-name">{identity.dealName}</h2>
        <span className="owner-summary-mode-badge">
          {identity.operatingMode === 'quick' ? 'Quick Underwrite' : 'Detailed Underwrite'}
        </span>
      </header>

      {dealContext !== null && (
        <section className="owner-summary-play">
          <span className="owner-summary-play-label">The Play</span>
          <p
            className={
              isPlayLong && !isPlayExpanded
                ? 'owner-summary-play-text owner-summary-play-text-clamped'
                : 'owner-summary-play-text'
            }
          >
            {dealContext}
          </p>
          {isPlayLong && (
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              aria-expanded={isPlayExpanded}
              onClick={() => setIsPlayExpanded((open) => !open)}
            >
              {isPlayExpanded ? 'Less' : 'More'}
            </button>
          )}
        </section>
      )}

      <section className="owner-summary-returns" aria-label="Key Returns">
        <h3 className="section-heading">Key Returns</h3>
        <div className="metric-row">
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
        {/* Sprint B Gate B5 density pass, kept: the supporting strip carries
            only the two figures that appear nowhere else on the page. */}
        <div className="owner-summary-supporting-rows">
          <InfoRow label="Unlevered IRR" value={formatPercent(keyReturns.unleveredIrr)} />
          <InfoRow
            label="Cumulative Operating Distributions"
            value={formatCurrency(ownerReturns.cumulativeOperatingDistributionsThroughHold)}
          />
        </div>
      </section>

      {/* Gate B5 hierarchy pass, kept: the Deal Story sits immediately under
          the hero metrics it interprets, visually subordinate to every
          deterministic figure. */}
      {dealStory !== null && <DealStorySection dealStory={dealStory} />}

      {/* Sprint C Gate C4: the four supporting panels sit in one compact row
          rather than two stacked two-column rows, which is most of what kept
          Overview above one viewport. Identical fields and values. */}
      <div className="owner-summary-grid">
        <section className="card owner-summary-card">
          <h3 className="card-title">Investment Snapshot</h3>
          <InfoRow label="Purchase Price" value={formatCurrency(investmentSnapshot.purchasePrice)} />
          <InfoRow label="Year 1 NOI" value={formatCurrency(investmentSnapshot.yearOneNoi)} />
          <InfoRow
            label="Going-In Cap Rate"
            value={formatPercent(investmentSnapshot.goingInCapRate)}
          />
          <InfoRow label="Hold Period" value={`${investmentSnapshot.holdPeriod} years`} />
          <InfoRow label="Exit Cap Rate" value={formatPercent(investmentSnapshot.exitCapRate)} />
        </section>

        <section className="card owner-summary-card">
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

        <section className="card owner-summary-card">
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

        <section className="card owner-summary-card">
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

      {/* Sprint C Gate C4: three compact owner-level figures instead of a
          full-width table-style block. Same three break-evens, same
          formatters, same "no solution within tested range" honesty. */}
      {breakEvenHighlights !== null && (
        <section className="owner-summary-breakeven" aria-label="Break-Even Highlights">
          <h3 className="section-heading">Break-Even Highlights</h3>
          <div className="mini-metric-row">
            <MiniMetric
              label="Max Purchase Price"
              value={formatBreakEvenSolvedValue(breakEvenHighlights.maxPurchasePrice, formatCurrency)}
              caption={BREAK_EVEN_METRIC_LABEL[breakEvenHighlights.maxPurchasePrice.metric]}
            />
            <MiniMetric
              label="Max Exit Cap Rate"
              value={formatBreakEvenSolvedValue(breakEvenHighlights.maxExitCapRate, formatPercent)}
              caption={BREAK_EVEN_METRIC_LABEL[breakEvenHighlights.maxExitCapRate.metric]}
            />
            <MiniMetric
              label="Max Interest Rate"
              value={formatBreakEvenSolvedValue(breakEvenHighlights.maxInterestRate, formatPercent)}
              caption={BREAK_EVEN_METRIC_LABEL[breakEvenHighlights.maxInterestRate.metric]}
            />
          </div>
        </section>
      )}
    </div>
  );
}
