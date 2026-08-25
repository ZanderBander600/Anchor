import type { AcquisitionResults } from '../types';
import { formatCurrency, formatMultiple, formatPercent } from '../format';
import { CashFlowTable } from './CashFlowTable';

interface StatProps {
  label: string;
  value: string;
}

function StatCard({ label, value }: StatProps) {
  return (
    <div className="stat-card">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
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
      <section className="card">
        <h3 className="card-title">Key Returns</h3>
        <div className="stat-grid">
          <StatCard label="Levered IRR" value={formatPercent(results.levered_irr)} />
          <StatCard label="Unlevered IRR" value={formatPercent(results.unlevered_irr)} />
          <StatCard label="Equity Multiple" value={formatMultiple(results.equity_multiple)} />
          <StatCard label="Year 1 DSCR" value={formatMultiple(results.dscr_by_year[0])} />
        </div>
      </section>

      <div className="card-row">
        <section className="card">
          <h3 className="card-title">Property</h3>
          <InfoRow label="Going-In Cap Rate" value={formatPercent(results.going_in_cap_rate)} />
          <InfoRow label="Exit NOI" value={formatCurrency(results.exit_noi)} />
          <InfoRow label="Exit Value" value={formatCurrency(results.exit_value)} />
        </section>

        <section className="card">
          <h3 className="card-title">Capitalization</h3>
          <InfoRow label="Loan Amount" value={formatCurrency(results.loan_amount)} />
          <InfoRow label="Initial Equity" value={formatCurrency(results.initial_equity)} />
          <InfoRow
            label="Monthly Debt Service"
            value={formatCurrency(results.monthly_debt_service)}
          />
          <InfoRow
            label="Remaining Loan Balance"
            value={formatCurrency(results.remaining_loan_balance)}
          />
        </section>

        <section className="card">
          <h3 className="card-title">Exit</h3>
          <InfoRow label="Net Sale Proceeds" value={formatCurrency(results.net_sale_proceeds)} />
        </section>
      </div>

      <CashFlowTable results={results} />
    </div>
  );
}
