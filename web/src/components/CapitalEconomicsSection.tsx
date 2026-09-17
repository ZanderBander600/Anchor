/**
 * Phase 6 Gate D6.7 -- Capital Economics: what the plan costs at closing, what
 * equity goes in and comes back, what the owner's cash does each year, and when
 * the Business Plan's capital falls.
 *
 * **One section, three modes.** Quick, Detailed and Lease-Level render this
 * component over the same `AcquisitionResults` contract, so Sources & Uses,
 * Project Returns, Owner Cash Flow, the Net Additional Equity Requirement and
 * every IRR explanation read identically wherever an analyst meets them. The one
 * mode-shaped choice is `showLeasingCapital`: only Lease-Level models TI / LC, so
 * only Lease-Level gives them columns in the capital schedule. It chooses
 * columns, never a definition.
 *
 * **It computes nothing.** Every figure is one field of the engine's result,
 * passed through the shared `format.ts` helpers. The totals are the engine's
 * `total_closing_uses` and `total_closing_sources`, not a sum of the rows above
 * them, so a Sources & Uses that did not reconcile would show it rather than hide
 * it behind a browser total. Purchase Price is the one figure that is not a
 * result field -- it is an input -- and the caller passes the Purchase Price of
 * the request that produced these results.
 *
 * **Closing, hold and post-hold stay apart.** Closing Project Capital is a
 * closing use: it appears in Sources & Uses and on its own Closing (T0) row, never
 * as Year 1. Project Capital scheduled after the hold is disclosed beneath the
 * schedule and never enters a hold-year row, because it is excluded from seller
 * cash flows and returns (D6 conventions Section 19).
 *
 * **The capital channels stay separate.** The Recurring CapEx Reserve and
 * Lease-Level TI / LC sit under Property-Level Capital; Project Capital and Owner
 * Expenses sit under Business Plan. Each is its own column, read from its own
 * field, and none is ever added to another.
 */

import { useId } from 'react';
import { formatCurrency, formatMultiple, formatPercent } from '../format';
import {
  holdYearLabel,
  holdYearsAboveZero,
  irrNotReportedExplanation,
  isEveryEntryZero,
  signClass,
} from '../capitalEconomics';
import type { AcquisitionResults } from '../types';

export interface CapitalEconomicsSectionProps {
  /** The authoritative analysis. Every figure below is one of its fields. */
  results: AcquisitionResults;
  /** The Purchase Price of the request that produced `results`. An input, not
   * a result field, so the caller supplies it; `null` renders as N/A rather
   * than as a number the section made up. */
  purchasePrice: number | null;
  /** True only for Lease-Level, the one mode that models TI / LC. */
  showLeasingCapital: boolean;
}

interface LedgerRowProps {
  label: string;
  value: string;
  /** A sentence explaining the figure, set on its own line beneath it. */
  note?: string | null;
  /** A subtotal or total line: stronger weight and a rule above. */
  total?: boolean;
  valueClassName?: string;
}

function LedgerRow({ label, value, note = null, total = false, valueClassName }: LedgerRowProps) {
  const noteId = useId();
  return (
    <>
      <tr className={total ? 'capital-economics-ledger-total' : undefined}>
        <th scope="row">{label}</th>
        <td className={valueClassName} aria-describedby={note === null ? undefined : noteId}>
          {value}
        </td>
      </tr>
      {note !== null && (
        <tr className="capital-economics-ledger-note">
          <td colSpan={2} id={noteId}>
            {note}
          </td>
        </tr>
      )}
    </>
  );
}

function LedgerGroup({ label }: { label: string }) {
  return (
    <tr className="capital-economics-ledger-group">
      <th scope="rowgroup" colSpan={2}>
        {label}
      </th>
    </tr>
  );
}

/** One signed currency figure in a table. */
function MoneyCell({ value }: { value: number }) {
  return <td className={signClass(value)}>{formatCurrency(value)}</td>;
}

/** A cell with no amount by definition -- no reserve, TI / LC or owner expense
 * falls at closing. Not a zero, so it is not written as one. */
function NotApplicableCell() {
  return (
    <td className="capital-economics-na">
      <span aria-hidden="true">—</span>
      <span className="visually-hidden">Not applicable</span>
    </td>
  );
}

function SourcesAndUses({
  results,
  purchasePrice,
}: {
  results: AcquisitionResults;
  purchasePrice: number | null;
}) {
  const titleId = useId();
  const hasCapitalAfterClosing =
    results.post_hold_project_capital > 0 || !isEveryEntryZero(results.project_capital_by_year);

  return (
    <section className="card capital-economics-card" aria-labelledby={titleId}>
      <h4 className="card-title" id={titleId}>
        Sources &amp; Uses at Closing
      </h4>
      <table className="capital-economics-ledger" aria-labelledby={titleId}>
        <tbody>
          <LedgerGroup label="Uses" />
          <LedgerRow label="Purchase Price" value={formatCurrency(purchasePrice)} />
          <LedgerRow label="Acquisition Costs" value={formatCurrency(results.acquisition_costs)} />
          <LedgerRow label="Financing Fees" value={formatCurrency(results.financing_fee)} />
          <LedgerRow
            label="Closing Project Capital"
            value={formatCurrency(results.closing_project_capital)}
          />
          <LedgerRow
            label="Total Closing Uses"
            value={formatCurrency(results.total_closing_uses)}
            total
          />
        </tbody>
        <tbody>
          <LedgerGroup label="Sources" />
          <LedgerRow label="Acquisition Debt" value={formatCurrency(results.loan_amount)} />
          <LedgerRow label="Initial Equity" value={formatCurrency(results.initial_equity)} />
          <LedgerRow
            label="Total Closing Sources"
            value={formatCurrency(results.total_closing_sources)}
            total
          />
        </tbody>
      </table>
      {hasCapitalAfterClosing && (
        <p className="capital-economics-note">
          Project Capital scheduled during or after the hold is not a closing use. It appears in
          the Capital Schedule below.
        </p>
      )}
    </section>
  );
}

function ProjectReturns({ results }: { results: AcquisitionResults }) {
  const titleId = useId();
  const additionalEquityYears = holdYearsAboveZero(
    results.net_additional_equity_requirement_by_year,
  );

  return (
    <section className="card capital-economics-card" aria-labelledby={titleId}>
      <h4 className="card-title" id={titleId}>
        Project Returns
      </h4>
      <table className="capital-economics-ledger" aria-labelledby={titleId}>
        <tbody>
          <LedgerGroup label="Equity" />
          <LedgerRow
            label="Initial Equity Requirement"
            value={formatCurrency(results.initial_equity)}
          />
          <LedgerRow
            label="Total Equity Invested"
            value={formatCurrency(results.total_equity_invested)}
            note={
              additionalEquityYears.length === 0
                ? 'Equal to the Initial Equity Requirement: no Net Additional Equity Requirement during the hold.'
                : `The Initial Equity Requirement plus the Net Additional Equity Requirement in ${additionalEquityYears.join(', ')}.`
            }
          />
          <LedgerRow
            label="Total Cash Returned"
            value={formatCurrency(results.total_cash_returned)}
          />
          <LedgerRow
            label="Total Profit"
            value={formatCurrency(results.total_profit)}
            valueClassName={signClass(results.total_profit)}
            total
          />
        </tbody>
        <tbody>
          <LedgerGroup label="Returns" />
          <LedgerRow label="Equity Multiple" value={formatMultiple(results.equity_multiple)} />
          <LedgerRow
            label="Levered IRR"
            value={formatPercent(results.levered_irr)}
            note={irrNotReportedExplanation('Levered IRR', results.levered_irr_status)}
          />
          <LedgerRow
            label="Unlevered IRR"
            value={formatPercent(results.unlevered_irr)}
            note={irrNotReportedExplanation('Unlevered IRR', results.unlevered_irr_status)}
          />
        </tbody>
      </table>
    </section>
  );
}

function OwnerCashFlow({ results }: { results: AcquisitionResults }) {
  const titleId = useId();
  const showsAdditionalEquity = !isEveryEntryZero(
    results.net_additional_equity_requirement_by_year,
  );

  return (
    <section className="card table-card capital-economics-card" aria-labelledby={titleId}>
      <h4 className="card-title" id={titleId}>
        Owner Cash Flow
      </h4>
      <p className="capital-economics-helper">
        Property Cash Flow reflects the Recurring CapEx Reserve and, for Lease-Level deals, TI /
        LC. Owner Cash Flow then reflects Project Capital and Owner Expenses; Levered Owner Cash
        Flow is after debt service.
      </p>
      <div className="table-scroll">
        <table className="capital-economics-table" aria-labelledby={titleId}>
          <thead>
            <tr>
              <th scope="col">Year</th>
              <th scope="col">NOI</th>
              <th scope="col">Property Cash Flow</th>
              <th scope="col">Unlevered Owner Cash Flow</th>
              <th scope="col">Levered Owner Cash Flow</th>
              {showsAdditionalEquity && <th scope="col">Net Additional Equity Requirement</th>}
            </tr>
          </thead>
          <tbody>
            {results.property_cash_flow_by_year.map((propertyCashFlow, index) => (
              <tr key={index}>
                <th scope="row">{holdYearLabel(index)}</th>
                <MoneyCell value={results.noi_by_year[index]} />
                <MoneyCell value={propertyCashFlow} />
                <MoneyCell value={results.unlevered_owner_cash_flow_by_year[index]} />
                <MoneyCell value={results.levered_owner_cash_flow_by_year[index]} />
                {showsAdditionalEquity && (
                  <MoneyCell value={results.net_additional_equity_requirement_by_year[index]} />
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="capital-economics-note">
        {showsAdditionalEquity
          ? 'Net Additional Equity Requirement is the equity a hold year needs after netting that year’s other cash flows, including sale proceeds in the final year. It is an annual net figure and does not indicate timing within the year.'
          : 'No Net Additional Equity Requirement during the hold.'}
      </p>
    </section>
  );
}

function CapitalSchedule({
  results,
  showLeasingCapital,
}: {
  results: AcquisitionResults;
  showLeasingCapital: boolean;
}) {
  const titleId = useId();
  const schedulesNothing =
    results.closing_project_capital === 0 &&
    results.post_hold_project_capital === 0 &&
    isEveryEntryZero(results.project_capital_by_year) &&
    isEveryEntryZero(results.owner_expenses_by_year);

  if (schedulesNothing) {
    return (
      <section className="card capital-economics-card" aria-labelledby={titleId}>
        <h4 className="card-title" id={titleId}>
          Capital Schedule
        </h4>
        <p className="capital-economics-empty">
          The Business Plan schedules no Project Capital or Owner Expenses.
        </p>
      </section>
    );
  }

  return (
    <section className="card table-card capital-economics-card" aria-labelledby={titleId}>
      <h4 className="card-title" id={titleId}>
        Capital Schedule
      </h4>
      <p className="capital-economics-helper">
        {showLeasingCapital
          ? 'Each channel is reported on its own. Project Capital is never included in Tenant Improvements, Leasing Commissions or the Recurring CapEx Reserve.'
          : 'Each channel is reported on its own. Project Capital is never included in the Recurring CapEx Reserve.'}
      </p>
      <div className="table-scroll">
        <table className="capital-economics-table capital-economics-schedule" aria-labelledby={titleId}>
          <thead>
            <tr className="capital-economics-colgroups">
              <td />
              <th scope="colgroup" colSpan={showLeasingCapital ? 3 : 1}>
                Property-Level Capital
                <span className="capital-economics-colgroup-hint">In Property Cash Flow</span>
              </th>
              <th scope="colgroup" colSpan={2}>
                Business Plan
                <span className="capital-economics-colgroup-hint">In Owner Cash Flow</span>
              </th>
            </tr>
            <tr>
              <th scope="col">Period</th>
              <th scope="col">Recurring CapEx Reserve</th>
              {showLeasingCapital && (
                <>
                  <th scope="col">Tenant Improvements</th>
                  <th scope="col">Leasing Commissions</th>
                </>
              )}
              <th scope="col">Project Capital</th>
              <th scope="col">Owner Expenses</th>
            </tr>
          </thead>
          <tbody>
            <tr className="capital-economics-closing-row">
              <th scope="row">Closing (T0)</th>
              <NotApplicableCell />
              {showLeasingCapital && (
                <>
                  <NotApplicableCell />
                  <NotApplicableCell />
                </>
              )}
              <MoneyCell value={results.closing_project_capital} />
              <NotApplicableCell />
            </tr>
            {results.project_capital_by_year.map((projectCapital, index) => (
              <tr key={index}>
                <th scope="row">{holdYearLabel(index)}</th>
                <MoneyCell value={results.capex_by_year[index]} />
                {showLeasingCapital && (
                  <>
                    <MoneyCell value={results.tenant_improvements_by_year[index]} />
                    <MoneyCell value={results.leasing_commissions_by_year[index]} />
                  </>
                )}
                <MoneyCell value={projectCapital} />
                <MoneyCell value={results.owner_expenses_by_year[index]} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {results.post_hold_project_capital > 0 && (
        <div className="capital-economics-disclosure" role="note" aria-label="Post-Hold Project Capital">
          <p className="capital-economics-disclosure-title">Post-Hold Project Capital</p>
          <p className="capital-economics-disclosure-text">
            {`${formatCurrency(results.post_hold_project_capital)} is modeled after the current hold and is excluded from seller returns.`}
          </p>
        </div>
      )}
    </section>
  );
}

export function CapitalEconomicsSection({
  results,
  purchasePrice,
  showLeasingCapital,
}: CapitalEconomicsSectionProps) {
  const titleId = useId();
  return (
    <section className="capital-economics" aria-labelledby={titleId}>
      <header className="capital-economics-head">
        <h3 className="capital-economics-title" id={titleId}>
          Capital Economics
        </h3>
        <p className="capital-economics-lede">
          Closing economics, equity returns and annual owner cash flow for this analysis.
        </p>
      </header>
      <div className="capital-economics-grid">
        <SourcesAndUses results={results} purchasePrice={purchasePrice} />
        <ProjectReturns results={results} />
      </div>
      <OwnerCashFlow results={results} />
      <CapitalSchedule results={results} showLeasingCapital={showLeasingCapital} />
    </section>
  );
}
