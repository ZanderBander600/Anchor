/**
 * D5.6 -- the Lease-Level operating statement, monthly or annual.
 *
 * **Monthly is canonical; annual is derived from it in Python.** This component
 * receives both surfaces and renders whichever the analyst asked for. It never
 * sums monthly values into a year and never divides an annual value by twelve:
 * the toggle changes which authoritative array is read, and nothing else. The
 * two agree because the backend derived one from the other, and the backend's
 * own tests prove they reconcile.
 *
 * TI and LC sit **below NOI**, where D4 puts them. They are not operating
 * expenses and folding them in would overstate every expense line and
 * understate NOI on a rent roll with real rollover.
 */

import type { ReactNode } from 'react';
import { formatCurrency, formatPercent } from '../format';
import { formatMonthLabel, formatSquareFeet } from '../leaseLevelFormat';
import type {
  AnnualOperatingProjection,
  LeaseLevelAcquisitionResults,
  MonthlyPropertyProjection,
} from '../leaseLevelTypes';

export type OperatingPeriodView = 'monthly' | 'annual';

export interface LeaseLevelOperatingStatementProps {
  analysis: LeaseLevelAcquisitionResults;
  view: OperatingPeriodView;
  onViewChange: (view: OperatingPeriodView) => void;
}

type RowKind = 'line' | 'deduction' | 'subtotal' | 'total' | 'state';

interface Row {
  label: string;
  values: number[];
  kind: RowKind;
}

interface Section {
  title: string;
  rows: Row[];
}

/** Column headers for the monthly view: `Jan 2027`, not `period_index 1`. */
function monthlyColumns(monthly: MonthlyPropertyProjection): string[] {
  return monthly.months.map((month) => formatMonthLabel(month.month_start));
}

/**
 * Column headers for the annual view.
 *
 * Taken from the projection's own `hold_year` values rather than counted out in
 * TypeScript. The hold months carry `1..H` and the twelve forward exit months
 * carry `H+1`, so filtering the forward window and de-duplicating yields
 * exactly the years the annual arrays cover, in order, with no arithmetic.
 */
function annualColumns(monthly: MonthlyPropertyProjection): string[] {
  const years: number[] = [];
  for (const month of monthly.months) {
    if (month.is_forward_exit_month) {
      continue;
    }
    if (!years.includes(month.hold_year)) {
      years.push(month.hold_year);
    }
  }
  return years.map((year) => `Year ${year}`);
}

function monthlySections(monthly: MonthlyPropertyProjection): Section[] {
  return [
    {
      title: 'Revenue',
      rows: [
        { label: 'Contractual Base Rent', values: monthly.contractual_base_rent, kind: 'line' },
        { label: 'Less: Free Rent', values: monthly.free_rent, kind: 'deduction' },
        { label: 'Cash Base Rent', values: monthly.cash_base_rent, kind: 'subtotal' },
        { label: 'Expense Recoveries', values: monthly.expense_recovery, kind: 'line' },
        { label: 'Other Income', values: monthly.other_income, kind: 'line' },
        { label: 'Less: Credit Loss', values: monthly.credit_loss, kind: 'deduction' },
        {
          label: 'Effective Gross Income',
          values: monthly.effective_gross_income,
          kind: 'subtotal',
        },
      ],
    },
    {
      title: 'Operating Expenses',
      rows: [
        { label: 'Property Taxes', values: monthly.property_taxes, kind: 'deduction' },
        { label: 'Insurance', values: monthly.insurance, kind: 'deduction' },
        { label: 'Utilities', values: monthly.utilities, kind: 'deduction' },
        { label: 'Repairs & Maintenance', values: monthly.repairs_maintenance, kind: 'deduction' },
        {
          label: 'Other Operating Expenses',
          values: monthly.other_operating_expenses,
          kind: 'deduction',
        },
        {
          label: 'Fixed Operating Expenses',
          values: monthly.fixed_operating_expenses,
          kind: 'subtotal',
        },
        { label: 'Management Fee', values: monthly.management_fee, kind: 'deduction' },
        {
          label: 'Total Operating Expenses',
          values: monthly.total_operating_expenses,
          kind: 'subtotal',
        },
      ],
    },
    {
      title: 'Net Operating Income',
      rows: [{ label: 'Net Operating Income', values: monthly.noi, kind: 'total' }],
    },
    {
      title: 'Below NOI',
      rows: [
        { label: 'Tenant Improvements', values: monthly.tenant_improvements, kind: 'deduction' },
        { label: 'Leasing Commissions', values: monthly.leasing_commissions, kind: 'deduction' },
      ],
    },
    {
      title: 'Occupancy',
      rows: [
        { label: 'Occupied Area', values: monthly.occupied_area_sf, kind: 'state' },
        { label: 'Vacant Area', values: monthly.vacant_area_sf, kind: 'state' },
        { label: 'Physical Occupancy', values: monthly.physical_occupancy, kind: 'state' },
      ],
    },
  ];
}

function annualSections(
  annual: AnnualOperatingProjection,
  results: LeaseLevelAcquisitionResults['results'],
  holdYears: number,
): Section[] {
  return [
    {
      title: 'Revenue',
      rows: [
        {
          label: 'Contractual Base Rent',
          values: annual.contractual_base_rent_by_year,
          kind: 'line',
        },
        { label: 'Less: Free Rent', values: annual.free_rent_by_year, kind: 'deduction' },
        { label: 'Cash Base Rent', values: annual.cash_base_rent_by_year, kind: 'subtotal' },
        { label: 'Expense Recoveries', values: annual.expense_recovery_by_year, kind: 'line' },
        { label: 'Other Income', values: annual.other_income_by_year, kind: 'line' },
        { label: 'Less: Credit Loss', values: annual.credit_loss_by_year, kind: 'deduction' },
        {
          label: 'Effective Gross Income',
          values: annual.effective_gross_income_by_year,
          kind: 'subtotal',
        },
      ],
    },
    {
      title: 'Operating Expenses',
      rows: [
        { label: 'Property Taxes', values: annual.property_taxes_by_year, kind: 'deduction' },
        { label: 'Insurance', values: annual.insurance_by_year, kind: 'deduction' },
        { label: 'Utilities', values: annual.utilities_by_year, kind: 'deduction' },
        {
          label: 'Repairs & Maintenance',
          values: annual.repairs_maintenance_by_year,
          kind: 'deduction',
        },
        {
          label: 'Other Operating Expenses',
          values: annual.other_operating_expenses_by_year,
          kind: 'deduction',
        },
        {
          label: 'Fixed Operating Expenses',
          values: annual.fixed_operating_expenses_by_year,
          kind: 'subtotal',
        },
        { label: 'Management Fee', values: annual.management_fee_by_year, kind: 'deduction' },
        {
          label: 'Total Operating Expenses',
          values: annual.total_operating_expenses_by_year,
          kind: 'subtotal',
        },
      ],
    },
    {
      title: 'Net Operating Income',
      rows: [{ label: 'Net Operating Income', values: annual.noi_by_year, kind: 'total' }],
    },
    {
      title: 'Below NOI',
      rows: [
        {
          label: 'Tenant Improvements',
          values: annual.tenant_improvements_by_year,
          kind: 'deduction',
        },
        {
          label: 'Leasing Commissions',
          values: annual.leasing_commissions_by_year,
          kind: 'deduction',
        },
        // CapEx Reserve is an `AcquisitionTerms` annual assumption with no
        // monthly authority, which is why it appears here and not in the
        // monthly view. Sliced to the hold period the operating arrays cover.
        {
          label: 'CapEx Reserve',
          values: results.capex_by_year.slice(0, holdYears),
          kind: 'deduction',
        },
        {
          label: 'Debt Service',
          values: results.annual_debt_service.slice(0, holdYears),
          kind: 'deduction',
        },
      ],
    },
    {
      title: 'Occupancy',
      rows: [
        {
          label: 'Occupied Area at Year End',
          values: annual.occupied_area_at_year_end,
          kind: 'state',
        },
        { label: 'Vacant Area at Year End', values: annual.vacant_area_at_year_end, kind: 'state' },
        {
          label: 'Physical Occupancy at Year End',
          values: annual.physical_occupancy_at_year_end,
          kind: 'state',
        },
        {
          // Named for what it is. An average is not a year-end reading, and
          // labelling one as the other would misstate a rollover year badly.
          label: 'Average Physical Occupancy',
          values: annual.average_physical_occupancy_over_year,
          kind: 'state',
        },
      ],
    },
  ];
}

function renderValue(row: Row, value: number): ReactNode {
  if (row.kind !== 'state') {
    return formatCurrency(value);
  }
  if (row.label.startsWith('Physical Occupancy') || row.label.startsWith('Average')) {
    return formatPercent(value);
  }
  return formatSquareFeet(value);
}

export function LeaseLevelOperatingStatement({
  analysis,
  view,
  onViewChange,
}: LeaseLevelOperatingStatementProps) {
  const monthly = analysis.monthly_projection;
  const columns = view === 'monthly' ? monthlyColumns(monthly) : annualColumns(monthly);
  const sections =
    view === 'monthly'
      ? monthlySections(monthly)
      : annualSections(analysis.annual_projection, analysis.results, columns.length);
  // The label column plus one per period. Built as an array rather than
  // `columns.length + 1` so this module contains no arithmetic at all, which is
  // what lets the G-M7 audit cover it without an exception for table layout.
  const spanAllColumns = ['line-item', ...columns].length;

  return (
    <section className="card table-card lease-level-statement">
      <header className="lease-level-statement-head">
        <h3 className="card-title">Operating Statement</h3>
        <div className="sub-nav sub-nav-inline" role="tablist" aria-label="Statement period">
          {(
            [
              ['monthly', 'Monthly'],
              ['annual', 'Annual'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={view === id}
              className={view === id ? 'sub-nav-item sub-nav-item-active' : 'sub-nav-item'}
              onClick={() => onViewChange(id)}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      <p className="field-hint">
        {view === 'monthly'
          ? 'The canonical monthly model, including the twelve months after the hold period that set the exit. CapEx reserve and debt service are annual assumptions and appear on the annual view.'
          : 'Each year of the hold. Tenant improvements and leasing commissions sit below net operating income, where they belong.'}
      </p>

      <div className="table-scroll">
        <table className="cash-flow-table operating-statement-table lease-level-statement-table">
          <caption className="visually-hidden">
            Lease-Level operating statement, {view === 'monthly' ? 'monthly' : 'annual'}.
          </caption>
          <thead>
            <tr>
              <th scope="col">Line Item</th>
              {columns.map((column) => (
                <th scope="col" key={column}>
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sections.map((section) => (
              <>
                <tr className="lease-level-statement-section" key={`${section.title}-head`}>
                  <th scope="rowgroup" colSpan={spanAllColumns}>
                    {section.title}
                  </th>
                </tr>
                {section.rows.map((row) => (
                  <tr
                    key={`${section.title}-${row.label}`}
                    className={
                      row.kind === 'total'
                        ? 'operating-statement-emphasis lease-level-statement-noi'
                        : row.kind === 'subtotal'
                          ? 'operating-statement-emphasis'
                          : undefined
                    }
                  >
                    <th scope="row">{row.label}</th>
                    {row.values.map((value, index) => (
                      <td key={columns[index] ?? index}>{renderValue(row, value)}</td>
                    ))}
                  </tr>
                ))}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
