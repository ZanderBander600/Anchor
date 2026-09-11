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
 * D5.6A adds two presentation distinctions that were previously left to the
 * reader:
 *
 * - **Leasing capital is not financing.** TI, LC and the CapEx reserve are
 *   costs of keeping the building let; debt service is a cost of how it was
 *   bought. Both sit below NOI, and D4 puts them there, but they answer
 *   different questions and no longer share a heading.
 * - **The hold period is not the forward valuation window.** The canonical
 *   projection runs twelve months past the sale, and those months exist only to
 *   establish the NOI capitalised at exit. They are real forecast months, not
 *   another year of ownership, and the monthly header now says so.
 *
 * Which months those are is read from `is_forward_exit_month` on the response.
 * It is never inferred from the hold period, from the length of the array, or
 * from a calendar year -- the backend owns that classification, and a second
 * opinion computed here could disagree with it.
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

/**
 * `contra` is the one that carries presentation weight.
 *
 * Free rent and credit loss sit inside the revenue block, surrounded by
 * positives, with nothing above them announcing that they come off. The
 * expense lines do not have that problem -- they live under a heading that
 * says Operating Expenses -- so they stay plain. A contra line is shown with a
 * leading minus and in red, and keeps its "Less:" label, so the direction
 * survives a monochrome print or a reader who does not see the colour.
 */
type RowKind = 'line' | 'contra' | 'deduction' | 'subtotal' | 'total' | 'state';

interface Row {
  label: string;
  values: number[];
  kind: RowKind;
}

interface Section {
  /** `null` for a section whose single row already names it. NOI had both a
   * band and a row reading "Net Operating Income"; one of them was noise. */
  title: string | null;
  rows: Row[];
}

interface Column {
  key: string;
  label: string;
  /** Straight from `is_forward_exit_month`. Never derived here. */
  isForward: boolean;
  /** The first forward month: where the sale falls. */
  isBoundary: boolean;
}

interface PeriodGroup {
  key: string;
  label: string;
  note: string;
  span: number;
  isForward: boolean;
}

/**
 * Column headers for the monthly view: `Jan 2027`, not `period_index 1`.
 *
 * Each column carries the response's own verdict on which period it belongs to.
 * `seenForward` finds the boundary by walking those flags in order rather than
 * by indexing, so a projection whose forward window were some other length --
 * or absent altogether -- would still be grouped correctly.
 */
function monthlyColumns(monthly: MonthlyPropertyProjection): Column[] {
  const columns: Column[] = [];
  let seenForward = false;
  for (const month of monthly.months) {
    const isForward = month.is_forward_exit_month;
    const isBoundary = isForward && !seenForward;
    if (isForward) {
      seenForward = true;
    }
    columns.push({
      key: month.month_start,
      label: formatMonthLabel(month.month_start),
      isForward,
      isBoundary,
    });
  }
  return columns;
}

/**
 * Column headers for the annual view.
 *
 * Taken from the projection's own `hold_year` values rather than counted out in
 * TypeScript. The hold months carry `1..H` and the twelve forward exit months
 * carry `H+1`, so skipping the forward window and de-duplicating yields exactly
 * the years the annual arrays cover, in order, with no arithmetic.
 *
 * The forward window is deliberately not a column here. It is a valuation
 * period, not a year of ownership, and showing it as "Year 8" of a seven-year
 * hold would invite precisely the reading D4 designed it to avoid. The monthly
 * view is where those months are inspected.
 */
function annualColumns(monthly: MonthlyPropertyProjection): Column[] {
  const years: number[] = [];
  for (const month of monthly.months) {
    if (month.is_forward_exit_month) {
      continue;
    }
    if (!years.includes(month.hold_year)) {
      years.push(month.hold_year);
    }
  }
  return years.map((year) => ({
    key: `year-${year}`,
    label: `Year ${year}`,
    isForward: false,
    isBoundary: false,
  }));
}

/**
 * The two period bands above the columns, or none at all.
 *
 * Partitioned by the authoritative flag each column already carries, so a span
 * is a count of what the backend classified rather than a calculation of where
 * the boundary ought to fall. The annual view has no forward columns and
 * therefore gets no band row: one group is not a grouping.
 */
function periodGroups(columns: Column[]): PeriodGroup[] {
  const hold: Column[] = [];
  const forward: Column[] = [];
  for (const column of columns) {
    if (column.isForward) {
      forward.push(column);
    } else {
      hold.push(column);
    }
  }
  if (forward.length === 0) {
    return [];
  }
  return [
    { key: 'hold', label: 'Hold Period', note: 'Ownership', span: hold.length, isForward: false },
    {
      key: 'forward',
      label: 'Forward 12 Months',
      note: 'Used for Exit Valuation',
      span: forward.length,
      isForward: true,
    },
  ];
}

function columnClass(column: Column | undefined): string | undefined {
  if (column === undefined) {
    return undefined;
  }
  if (column.isBoundary) {
    return 'lease-level-statement-forward lease-level-statement-boundary';
  }
  if (column.isForward) {
    return 'lease-level-statement-forward';
  }
  return undefined;
}

function monthlySections(monthly: MonthlyPropertyProjection): Section[] {
  return [
    {
      title: 'Revenue',
      rows: [
        { label: 'Contractual Base Rent', values: monthly.contractual_base_rent, kind: 'line' },
        { label: 'Less: Free Rent', values: monthly.free_rent, kind: 'contra' },
        { label: 'Cash Base Rent', values: monthly.cash_base_rent, kind: 'subtotal' },
        { label: 'Expense Recoveries', values: monthly.expense_recovery, kind: 'line' },
        { label: 'Other Income', values: monthly.other_income, kind: 'line' },
        { label: 'Less: Credit Loss', values: monthly.credit_loss, kind: 'contra' },
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
      title: null,
      rows: [{ label: 'Net Operating Income', values: monthly.noi, kind: 'total' }],
    },
    {
      // No Financing band monthly: there is no canonical monthly debt service,
      // and none is manufactured. Debt service appears on the annual view,
      // where the engine actually computed it.
      title: 'Leasing & Capital Costs',
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
        { label: 'Less: Free Rent', values: annual.free_rent_by_year, kind: 'contra' },
        { label: 'Cash Base Rent', values: annual.cash_base_rent_by_year, kind: 'subtotal' },
        { label: 'Expense Recoveries', values: annual.expense_recovery_by_year, kind: 'line' },
        { label: 'Other Income', values: annual.other_income_by_year, kind: 'line' },
        { label: 'Less: Credit Loss', values: annual.credit_loss_by_year, kind: 'contra' },
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
      title: null,
      rows: [{ label: 'Net Operating Income', values: annual.noi_by_year, kind: 'total' }],
    },
    {
      // The cost of keeping the building let. All three are property-level
      // capital and all three sit below NOI, which is where D4 puts them.
      title: 'Leasing & Capital Costs',
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
      ],
    },
    {
      // Financing is a cost of how the building was bought, not of keeping it
      // let. Sharing a heading with leasing capital made an unlevered read of
      // the property harder than it needed to be. Nothing moved financially:
      // this row reads the same array it always did, in the same place.
      title: 'Financing',
      rows: [
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

function rowClass(row: Row): string | undefined {
  switch (row.kind) {
    case 'total':
      return 'operating-statement-emphasis lease-level-statement-noi';
    case 'subtotal':
      return 'operating-statement-emphasis';
    case 'contra':
      return 'lease-level-statement-contra';
    default:
      return undefined;
  }
}

function renderValue(row: Row, value: number): ReactNode {
  if (row.kind === 'state') {
    if (row.label.startsWith('Physical Occupancy') || row.label.startsWith('Average')) {
      return formatPercent(value);
    }
    return formatSquareFeet(value);
  }
  const amount = formatCurrency(value);
  if (row.kind === 'contra' && value > 0) {
    // A display sign, not a calculation. The wire carries a positive magnitude
    // -- free rent of 20,000 is 20,000 of free rent -- and this puts a
    // character in front of the formatted string. Nothing is negated, so the
    // module still contains no arithmetic, and a zero stays `$0` rather than
    // becoming the nonsense `-$0`.
    return `-${amount}`;
  }
  return amount;
}

export function LeaseLevelOperatingStatement({
  analysis,
  view,
  onViewChange,
}: LeaseLevelOperatingStatementProps) {
  const monthly = analysis.monthly_projection;
  const columns = view === 'monthly' ? monthlyColumns(monthly) : annualColumns(monthly);
  const groups = periodGroups(columns);
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
          ? 'The canonical monthly model. The property is notionally sold at the end of the hold period; the Forward 12 months that follow are used to determine the Exit NOI capitalised at that sale, and are not another year of ownership. CapEx reserve and debt service are annual assumptions and appear on the annual view.'
          : 'Each year of the hold period. The Forward 12 valuation months are not a year of ownership and are inspected on the monthly view. Leasing capital and debt service sit below net operating income, where they belong.'}
      </p>

      <div className="table-scroll">
        <table className="cash-flow-table operating-statement-table lease-level-statement-table">
          <caption className="visually-hidden">
            Lease-Level operating statement, {view === 'monthly' ? 'monthly' : 'annual'}.
            {view === 'monthly'
              ? ' Columns are grouped into the hold period and the Forward 12 months used for exit valuation.'
              : ' Columns are the years of the hold period.'}
          </caption>
          <thead>
            {groups.length > 0 && (
              <tr className="lease-level-statement-periods">
                <th scope="col" rowSpan={2} className="lease-level-statement-corner">
                  Line Item
                </th>
                {groups.map((group) => (
                  <th
                    key={group.key}
                    scope="colgroup"
                    colSpan={group.span}
                    className={
                      group.isForward
                        ? 'lease-level-statement-period lease-level-statement-forward lease-level-statement-boundary'
                        : 'lease-level-statement-period'
                    }
                  >
                    <span className="lease-level-statement-period-label">
                      <span className="lease-level-statement-period-name">{group.label}</span>
                      <span className="lease-level-statement-period-note">{group.note}</span>
                    </span>
                    {/* The sale falls at the right-hand edge of the hold band,
                        which is exactly the boundary between the two groups, so
                        the marker lands on the boundary without a column of its
                        own. It is a label: no value, no data, no fake month. */}
                    {!group.isForward && (
                      <span className="lease-level-statement-sale">Sale / Hold End</span>
                    )}
                  </th>
                ))}
              </tr>
            )}
            <tr>
              {groups.length === 0 && (
                <th scope="col" className="lease-level-statement-corner">
                  Line Item
                </th>
              )}
              {columns.map((column) => (
                <th scope="col" key={column.key} className={columnClass(column)}>
                  {column.label}
                  {column.isBoundary && (
                    <span className="visually-hidden">
                      {' '}
                      — sale and hold end; the Forward 12 months used for exit valuation begin here
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          {/* One `tbody` per section, which is what a row group is for.
              It matters most for net operating income: with a single `tbody`,
              NOI trailed the expense rows and belonged to the Operating
              Expenses group in the markup as well as to the eye. It is not part
              of that group -- it is what the group resolves to -- so it gets a
              row group of its own, with nothing else in it. */}
          {sections.map((section) => (
            <tbody
              key={section.title ?? section.rows[0].label}
              className={
                section.title === null
                  ? 'lease-level-statement-group lease-level-statement-standalone'
                  : 'lease-level-statement-group'
              }
            >
              {section.title !== null && (
                <tr className="lease-level-statement-section">
                  {/* The title is its own element inside the band, and that is
                      the whole point. The band cell spans every column, so a
                      sticky *cell* has nowhere to slide -- its containing block
                      is exactly as wide as it is -- and the title simply
                      scrolled out of view, leaving an unexplained empty stripe
                      across the table. A sticky span inside the cell does move,
                      and stays legible at the left edge for as long as its rows
                      are on screen. One label, in one place: never repeated
                      into the month cells. */}
                  <th scope="rowgroup" colSpan={spanAllColumns}>
                    <span className="lease-level-statement-section-label">{section.title}</span>
                  </th>
                </tr>
              )}
              {section.rows.map((row) => (
                <tr key={row.label} className={rowClass(row)}>
                  <th scope="row">{row.label}</th>
                  {row.values.map((value, index) => (
                    <td key={columns[index]?.key ?? index} className={columnClass(columns[index])}>
                      {renderValue(row, value)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </section>
  );
}
