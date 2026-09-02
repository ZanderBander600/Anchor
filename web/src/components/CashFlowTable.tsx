import type { AcquisitionResults } from '../types';
import { formatCurrency, formatMultiple } from '../format';

interface CashFlowTableProps {
  results: AcquisitionResults;
}

export function CashFlowTable({ results }: CashFlowTableProps) {
  const holdPeriod = results.annual_debt_service.length;
  const years = Array.from({ length: holdPeriod }, (_, index) => index + 1);

  return (
    <section className="card table-card">
      <h3 className="card-title">Year-by-Year Analysis</h3>
      <div className="table-scroll">
        <table className="cash-flow-table">
          <thead>
            <tr>
              <th>Year</th>
              <th>NOI</th>
              <th>CapEx</th>
              <th>Annual Debt Service</th>
              <th>DSCR</th>
              <th>Unlevered Cash Flow</th>
              <th>Levered Cash Flow</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>0</td>
              <td className="muted">—</td>
              <td className="muted">—</td>
              <td className="muted">—</td>
              <td className="muted">—</td>
              <td>{formatCurrency(results.unlevered_cash_flows[0])}</td>
              <td>{formatCurrency(results.levered_cash_flows[0])}</td>
            </tr>
            {years.map((year) => {
              const index = year - 1;
              return (
                <tr key={year}>
                  <td>{year}</td>
                  <td>{formatCurrency(results.noi_by_year[index])}</td>
                  <td>{formatCurrency(results.capex_by_year[index])}</td>
                  <td>{formatCurrency(results.annual_debt_service[index])}</td>
                  <td>{formatMultiple(results.dscr_by_year[index])}</td>
                  <td>{formatCurrency(results.unlevered_cash_flows[year])}</td>
                  <td>{formatCurrency(results.levered_cash_flows[year])}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
