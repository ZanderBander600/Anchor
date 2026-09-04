import type { AcquisitionResults } from '../types';
import { formatCurrency, formatMultiple, formatPercent } from '../format';
import { CashFlowTable } from './CashFlowTable';
import { OwnerReturnSchedule } from './OwnerReturnSchedule';

interface StatProps {
  label: string;
  value: string;
}

interface StatCardProps extends StatProps {
  /** An optional secondary line under the primary value -- used to pair
   * Year 1 DSCR with Minimum DSCR (Underwriting V2 Gate 4) without adding a
   * fifth card to the headline strip. */
  caption?: string;
}

function StatCard({ label, value, caption }: StatCardProps) {
  return (
    <div className="stat-card stat-card-primary">
      <span className="stat-label">{label}</span>
      <span className="stat-value stat-value-primary">{value}</span>
      {caption && <span className="stat-caption">{caption}</span>}
    </div>
  );
}

function InfoRow({ label, value }: StatProps) {
  return (
    <div className="info-row">
      <span className="info-label">{label}</span>
      <span className="info-value">{value}</span>
    </div>
  );
}

interface ResultsPanelProps {
  results: AcquisitionResults;
}

export function ResultsPanel({ results }: ResultsPanelProps) {
  return (
    <div className="results-panel">
      <section className="headline-stats">
        <h3 className="card-title">Key Returns</h3>
        <div className="stat-grid">
          <StatCard label="Levered IRR" value={formatPercent(results.levered_irr)} />
          <StatCard label="Equity Multiple" value={formatMultiple(results.equity_multiple)} />
          <StatCard label="Going-In Cap Rate" value={formatPercent(results.going_in_cap_rate)} />
          <StatCard
            label="Year 1 DSCR"
            value={formatMultiple(results.dscr_by_year[0])}
            caption={`Min ${formatMultiple(results.min_dscr)}`}
          />
        </div>
      </section>

      <section className="headline-stats">
        <h3 className="card-title">Owner Returns</h3>
        <div className="stat-grid">
          <StatCard
            label="Year 1 Levered CoC"
            value={formatPercent(results.levered_cash_on_cash_by_year[0])}
          />
          <StatCard label="Year 1 Debt Yield" value={formatPercent(results.year_1_debt_yield)} />
          <StatCard
            label="Cumulative Operating Distributions"
            value={formatCurrency(
              results.cumulative_operating_distributions_by_year[
                results.cumulative_operating_distributions_by_year.length - 1
              ],
            )}
          />
        </div>
      </section>

      <div className="card-row">
        <section className="card">
          <h3 className="card-title">Property</h3>
          <InfoRow label="Unlevered IRR" value={formatPercent(results.unlevered_irr)} />
          <InfoRow label="Exit NOI" value={formatCurrency(results.exit_noi)} />
          <InfoRow label="Exit Value" value={formatCurrency(results.exit_value)} />
        </section>

        <section className="card">
          <h3 className="card-title">Capitalization</h3>
          <InfoRow label="Loan Amount" value={formatCurrency(results.loan_amount)} />
          <InfoRow label="Acquisition Costs" value={formatCurrency(results.acquisition_costs)} />
          <InfoRow label="Financing Fee" value={formatCurrency(results.financing_fee)} />
          <InfoRow label="Initial Equity" value={formatCurrency(results.initial_equity)} />
          <InfoRow
            label="Post-IO Monthly Payment"
            value={formatCurrency(results.monthly_debt_service)}
          />
          <InfoRow
            label="Remaining Loan Balance"
            value={formatCurrency(results.remaining_loan_balance)}
          />
          <InfoRow label="Minimum DSCR" value={formatMultiple(results.min_dscr)} />
        </section>

        <section className="card">
          <h3 className="card-title">Exit</h3>
          <InfoRow label="Disposition Costs" value={formatCurrency(results.disposition_costs)} />
          <InfoRow label="Net Sale Proceeds" value={formatCurrency(results.net_sale_proceeds)} />
        </section>
      </div>

      <CashFlowTable results={results} />
      <OwnerReturnSchedule results={results} />
    </div>
  );
}
