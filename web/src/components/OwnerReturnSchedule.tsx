import type { AcquisitionResults } from '../types';
import { formatCurrency, formatPercent } from '../format';

interface OwnerReturnScheduleProps {
  results: AcquisitionResults;
}

/** Owner Return Metrics V3 Gate A3 -- the annual Levered Cash-on-Cash
 * Return / Unlevered Cash Yield / Cumulative Operating Distributions
 * schedule, in its own compact table rather than three more columns on
 * ``CashFlowTable`` (which is already a 7-column, horizontally-scrolling
 * table). Every value is read directly off ``AcquisitionResults`` -- no
 * formula lives here, and every entry (including the final hold year)
 * already excludes sale/refinance proceeds at the engine layer. Shared,
 * unmodified, by both Quick and Detailed Underwrite -- like
 * ``ResultsPanel``, this component only knows about ``AcquisitionResults``,
 * never which mode produced it. */
export function OwnerReturnSchedule({ results }: OwnerReturnScheduleProps) {
  const holdPeriod = results.levered_cash_on_cash_by_year.length;
  const years = Array.from({ length: holdPeriod }, (_, index) => index + 1);

  return (
    <section className="card table-card">
      <h3 className="card-title">Owner Return Schedule</h3>
      <div className="table-scroll">
        <table className="cash-flow-table">
          <thead>
            <tr>
              <th>Year</th>
              <th>Levered CoC</th>
              <th>Unlevered Cash Yield</th>
              <th>Cumulative Operating Distributions</th>
            </tr>
          </thead>
          <tbody>
            {years.map((year) => {
              const index = year - 1;
              return (
                <tr key={year}>
                  <td>{year}</td>
                  <td>{formatPercent(results.levered_cash_on_cash_by_year[index])}</td>
                  <td>{formatPercent(results.unlevered_cash_yield_by_year[index])}</td>
                  <td>
                    {formatCurrency(results.cumulative_operating_distributions_by_year[index])}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
