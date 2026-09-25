/**
 * D5.6 -- the Lease-Level headline metrics.
 *
 * Every figure is read straight off the authoritative response. Nothing here is
 * computed: no cap rate from NOI over price, no DSCR from NOI over debt
 * service, no occupancy from occupied over rentable. The engine already
 * answered all of those, once, and this renders its answers.
 *
 * Deliberately *not* built on `OwnerSummaryPanel`. That component's
 * `operatingStory` requires a single growth figure per mode -- Quick's
 * `noi_growth`, Detailed's `revenue_growth`/`expense_growth`. Lease-Level has
 * neither: its growth emerges from per-lease escalation, rollover and market
 * leasing, and no single authoritative rate exists on any contract. Inventing
 * one to fill that shape would be precisely the calculation this gate forbids,
 * so Lease-Level gets its own summary rather than being cast into a shape it
 * does not have.
 */

import { formatCurrency, formatMultiple, formatPercent } from '../format';
import { irrNotReportedExplanation } from '../capitalEconomics';
import { formatRatio, formatSquareFeet } from '../leaseLevelFormat';
import type { LeaseLevelAcquisitionResults } from '../leaseLevelTypes';
import type { IrrStatus } from '../types';
import { ACQUISITION_REFERENCE_LABEL } from './AcquisitionReference';
import { useAcquisitionReference } from '../useRefinancePresence';

export interface LeaseLevelMetricSummaryProps {
  analysis: LeaseLevelAcquisitionResults;
}

interface Metric {
  label: string;
  value: string;
  /** Shown under the value where the number alone would mislead. */
  note?: string;
  emphasis?: boolean;
}

/**
 * An IRR, or N/A with the engine's own reason.
 *
 * D6.7 closeout: the reason is the engine's `IrrStatus`, put into words by the
 * one frontend mapping (`irrNotReportedExplanation` in `capitalEconomics.ts`) --
 * the same sentence the Capital Economics view shows, so the two views can
 * never disagree about why an IRR is unavailable. This card predates the
 * status and used to give the sign-pattern reason for every missing IRR, which
 * is only one of six reasons the engine can have. A reported IRR carries no
 * status note at all. `null` is still never shown as zero.
 */
function irrMetric(
  label: 'Levered IRR' | 'Unlevered IRR',
  value: number | null,
  status: IrrStatus,
): Metric {
  return {
    label,
    value: formatPercent(value),
    note: value === null ? (irrNotReportedExplanation(label, status) ?? undefined) : undefined,
    emphasis: true,
  };
}

export function LeaseLevelMetricSummary({ analysis }: LeaseLevelMetricSummaryProps) {
  const { results, annual_projection: annual, monthly_projection: monthly } = analysis;
  // Refinance V1 Stage 3: with a refinance in the Base Capital Structure the
  // levered figures are the acquisition-financing reference (R-P rules 3 to 5).
  const reference = useAcquisitionReference();
  const levered = irrMetric('Levered IRR', results.levered_irr, results.levered_irr_status);

  const returns: Metric[] = [
    reference
      ? { ...levered, note: levered.note === undefined ? ACQUISITION_REFERENCE_LABEL : `${ACQUISITION_REFERENCE_LABEL}. ${levered.note}` }
      : levered,
    irrMetric('Unlevered IRR', results.unlevered_irr, results.unlevered_irr_status),
    {
      label: 'Equity Multiple',
      value: formatMultiple(results.equity_multiple),
      emphasis: true,
      ...(reference ? { note: ACQUISITION_REFERENCE_LABEL } : {}),
    },
    { label: 'Going-In Cap Rate', value: formatPercent(results.going_in_cap_rate) },
  ];

  const debt: Metric[] = [
    { label: 'Headline DSCR', value: formatRatio(results.headline_dscr) },
    { label: 'Minimum DSCR', value: formatRatio(results.min_dscr) },
    { label: 'Year 1 Debt Yield', value: formatPercent(results.year_1_debt_yield) },
    { label: 'Loan Amount', value: formatCurrency(results.loan_amount) },
  ];

  const exit: Metric[] = [
    {
      label: 'Exit NOI',
      value: formatCurrency(results.exit_noi),
      // D4's forward window, named the same way the monthly statement names it
      // so the tile and the columns are recognisably the same period. Stated
      // explicitly because the obvious wrong reading -- the final hold year --
      // produces a plausible number.
      note: 'Forward 12-month NOI used for exit valuation.',
    },
    { label: 'Exit Value', value: formatCurrency(results.exit_value) },
    { label: 'Disposition Costs', value: formatCurrency(results.disposition_costs) },
    {
      // D5.6A: the value is after disposition costs *and* after repaying the
      // remaining loan balance, so "Net Sale Proceeds" understated how far
      // through the waterfall it already is. The label now says whose money it
      // is. The field, the source and the wire value are untouched.
      label: 'Net Sale Proceeds to Equity',
      value: formatCurrency(results.net_sale_proceeds),
    },
    {
      label: 'Exit Window Leasing Costs',
      value: formatCurrency(annual.exit_window_leasing_costs),
      note: 'TI and leasing commissions falling in the Forward 12 valuation period. Excluded from Exit NOI and from hold-period cash flow.',
    },
  ];

  const property: Metric[] = [
    { label: 'Rentable Area', value: formatSquareFeet(monthly.rentable_area_sf) },
    { label: 'Initial Equity', value: formatCurrency(results.initial_equity) },
    { label: 'Acquisition Costs', value: formatCurrency(results.acquisition_costs) },
    { label: 'Financing Fee', value: formatCurrency(results.financing_fee) },
  ];

  return (
    <div className="lease-level-summary">
      {(
        [
          ['Returns', returns],
          ['Debt & Coverage', debt],
          ['Exit', exit],
          ['Property & Capitalisation', property],
        ] as const
      ).map(([title, metrics]) => (
        <section className="card lease-level-metric-card" key={title}>
          <h3 className="card-title">{title}</h3>
          <dl className="lease-level-metric-grid">
            {metrics.map((metric) => (
              <div
                className={
                  metric.emphasis
                    ? 'lease-level-metric lease-level-metric-emphasis'
                    : 'lease-level-metric'
                }
                key={metric.label}
              >
                <dt>{metric.label}</dt>
                <dd>{metric.value}</dd>
                {metric.note && <p className="lease-level-metric-note">{metric.note}</p>}
              </div>
            ))}
          </dl>
        </section>
      ))}
    </div>
  );
}
