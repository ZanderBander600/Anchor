import type { AcquisitionResults, OperatingProjection } from '../types';
import { formatCurrency } from '../format';

interface OperatingStatementTableProps {
  operatingProjection: OperatingProjection;
  results: AcquisitionResults;
}

interface StatementRow {
  label: string;
  values: number[];
  /** Visually distinguishes a subtotal/total line (EGI, NOI) from an
   * ordinary line item, without a separate divider component. */
  emphasis?: boolean;
  /** A deduction line (Vacancy & Credit Loss, each expense line) is shown
   * parenthesized, matching standard operating-statement convention --
   * the underlying number is never negated, only its display. */
  isDeduction?: boolean;
}

/**
 * Detailed Operating Model V2.1 Gate 6 -- the institutional operating
 * statement: line items as rows, Years 1..H as columns, sourced entirely
 * from the backend-authoritative `OperatingProjection`/`AcquisitionResults`
 * -- no value here is computed in TypeScript. CapEx Reserve, Debt Service,
 * and Levered Cash Flow (below NOI, per the frozen engine convention) come
 * from `AcquisitionResults`, sliced to the same Years 1..H the operating
 * schedule covers -- the terminal Year H sale proceeds are not part of an
 * *operating* statement and are already shown in the Key Returns/Exit cards
 * `ResultsPanel` renders alongside this table.
 */
export function OperatingStatementTable({
  operatingProjection,
  results,
}: OperatingStatementTableProps) {
  const holdPeriod = operatingProjection.noi_by_year.length;
  const years = Array.from({ length: holdPeriod }, (_, index) => index + 1);

  const rows: StatementRow[] = [
    { label: 'Gross Potential Rent', values: operatingProjection.gross_potential_rent_by_year },
    {
      label: 'Less: Vacancy & Credit Loss',
      values: operatingProjection.vacancy_credit_loss_by_year,
      isDeduction: true,
    },
    { label: 'Other Income', values: operatingProjection.other_income_by_year },
    {
      label: 'Effective Gross Income',
      values: operatingProjection.effective_gross_income_by_year,
      emphasis: true,
    },
    { label: 'Property Taxes', values: operatingProjection.property_taxes_by_year, isDeduction: true },
    { label: 'Insurance', values: operatingProjection.insurance_by_year, isDeduction: true },
    { label: 'Utilities', values: operatingProjection.utilities_by_year, isDeduction: true },
    {
      label: 'Repairs & Maintenance',
      values: operatingProjection.repairs_maintenance_by_year,
      isDeduction: true,
    },
    {
      label: 'Other Operating Expenses',
      values: operatingProjection.other_operating_expenses_by_year,
      isDeduction: true,
    },
    { label: 'Management Fee', values: operatingProjection.management_fee_by_year, isDeduction: true },
    {
      label: 'Total Operating Expenses',
      values: operatingProjection.total_operating_expenses_by_year,
      emphasis: true,
      isDeduction: true,
    },
    { label: 'Net Operating Income', values: operatingProjection.noi_by_year, emphasis: true },
    {
      label: 'CapEx Reserve',
      values: results.capex_by_year.slice(0, holdPeriod),
      isDeduction: true,
    },
    {
      label: 'Debt Service',
      values: results.annual_debt_service.slice(0, holdPeriod),
      isDeduction: true,
    },
    {
      label: 'Levered Cash Flow',
      values: results.levered_cash_flows.slice(1, holdPeriod + 1),
      emphasis: true,
    },
  ];

  return (
    <section className="card table-card">
      <h3 className="card-title">Operating Statement</h3>
      <div className="table-scroll">
        <table className="cash-flow-table operating-statement-table">
          <thead>
            <tr>
              <th>Line Item</th>
              {years.map((year) => (
                <th key={year}>Year {year}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className={row.emphasis ? 'operating-statement-emphasis' : undefined}>
                <td>{row.label}</td>
                {row.values.map((value, index) => (
                  <td key={index}>
                    {row.isDeduction && value !== 0
                      ? `(${formatCurrency(Math.abs(value))})`
                      : formatCurrency(value)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="operating-statement-exit-note">
        Exit NOI (Year {holdPeriod + 1}, sale-only): {formatCurrency(operatingProjection.exit_noi)}
      </p>
    </section>
  );
}
