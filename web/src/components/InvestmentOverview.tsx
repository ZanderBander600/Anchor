/**
 * Phase 7 Gate P7.6 -- the Investment Overview: its structure and shared
 * assumptions, and its Base consolidated project economics.
 *
 * **Structure.** Investment Summary, the Investment Business Plan (the one D6
 * editor, on the one D6 contract) and the transaction costs are one draft with
 * one explicit Save Investment; Edit Investment opens it, Cancel restores what
 * is saved, and unsaved changes are always shown.
 *
 * **Economics.** Run Base Analysis asks the backend for the Base variant: every
 * Unit through its own engine, then consolidation. Every figure below is one
 * field of the returned `ConsolidatedResults`, formatted -- the Overview totals,
 * averages and derives nothing. An IRR the engine could not define is `N/A` with
 * its reason, never 0%. Aggregate DSCR is consolidated NOI over consolidated
 * debt service, and is named as such. Year-End Physical Occupancy appears only
 * when the backend reports it, and otherwise says why.
 *
 * **Never stale as current.** The results are shown only while they match the
 * saved state on screen; otherwise the out-of-date notice replaces them until
 * the analyst runs Base Analysis again.
 */

import type { ReactNode } from 'react';
import { holdYearLabel, irrNotReportedExplanation, signClass } from '../capitalEconomics';
import { formatCurrency, formatMultiple, formatPercent } from '../format';
import {
  ALLOCATED_PRICE_NOTE,
  INVESTMENT_ANALYSIS_DIRTY_MESSAGE,
  INVESTMENT_ANALYSIS_STALE_MESSAGE,
  INVESTMENT_BUSINESS_PLAN_NOTE,
  OCCUPANCY_NOT_REPORTED,
  storedHoldPeriod,
  TRANSACTION_PRICE_NOTE,
  unitDisplayName,
  withUnitNames,
} from '../investmentCatalog';
import type { ConsolidatedResults } from '../investmentTypes';
import { operatingModeLabel } from '../operatingMode';
import type { IrrStatus } from '../types';
import type { InvestmentAnalysisState } from '../useInvestmentAnalysis';
import type { InvestmentWorkspaceState } from '../useInvestmentWorkspace';
import { BusinessPlanEditor } from './BusinessPlanEditor';
import { InvestmentIssueList } from './InvestmentIssueList';
import { NumericInput } from './NumericInput';
import { StaleAnalysisNotice } from './StaleAnalysisNotice';
import { TransactionCostEditor } from './TransactionCostEditor';

export interface InvestmentOverviewProps {
  workspace: InvestmentWorkspaceState;
  analysis: InvestmentAnalysisState;
}

/** One ledger line: a label, a formatted backend value, and an optional note. */
interface LedgerLine {
  label: string;
  value: string;
  note?: string | null;
  negative?: boolean;
}

function Ledger({ caption, lines }: { caption: string; lines: LedgerLine[] }) {
  return (
    <table className="investment-ledger">
      <caption className="investment-ledger-caption">{caption}</caption>
      <tbody>
        {lines.map((line) => (
          <tr key={line.label}>
            <th scope="row">{line.label}</th>
            <td className={line.negative ? 'investment-num capital-economics-negative' : 'investment-num'}>
              {line.value}
              {line.note != null && <span className="investment-ledger-note">{line.note}</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** An IRR, or `N/A` with the engine's reason. Never 0%. */
function irrLine(label: string, value: number | null, status: IrrStatus): LedgerLine {
  if (value !== null) {
    return { label, value: formatPercent(value) };
  }
  return { label, value: 'N/A', note: irrNotReportedExplanation(label, status) };
}

/** The backend's reason occupancy is not reported, with each quoted Unit id
 * replaced by the Unit's name. */
function occupancyReason(results: ConsolidatedResults, names: Readonly<Record<string, string>>): string {
  return withUnitNames(results.physical_occupancy_message ?? OCCUPANCY_NOT_REPORTED, names);
}

function ReturnsSection({
  results,
  hold,
  names,
}: {
  results: ConsolidatedResults;
  hold: number;
  names: Readonly<Record<string, string>>;
}) {
  const occupancy = results.physical_occupancy_at_year_end;
  return (
    <div className="investment-returns">
      <p className="investment-note">
        Base Strategy under the Base Scenario · {hold}-year common hold · every Unit consolidated.
      </p>
      <div className="investment-ledgers">
        <Ledger
          caption="Returns"
          lines={[
            irrLine('Levered IRR', results.levered_irr, results.levered_irr_status),
            irrLine('Unlevered IRR', results.unlevered_irr, results.unlevered_irr_status),
            { label: 'Equity Multiple', value: formatMultiple(results.equity_multiple) },
            { label: 'Total Profit', value: formatCurrency(results.total_profit), negative: results.total_profit < 0 },
            { label: 'Total Equity Invested', value: formatCurrency(results.total_equity_invested) },
            { label: 'Initial Equity', value: formatCurrency(results.initial_equity) },
          ]}
        />
        <Ledger
          caption="Leverage and Valuation"
          lines={[
            { label: 'Loan Amount', value: formatCurrency(results.loan_amount) },
            { label: 'Going-In Cap Rate', value: formatPercent(results.going_in_cap_rate) },
            { label: 'Year-1 Debt Yield', value: formatPercent(results.year_1_debt_yield) },
            { label: 'Headline Aggregate DSCR', value: formatMultiple(results.headline_aggregate_dscr) },
            { label: 'Minimum Aggregate DSCR', value: formatMultiple(results.min_aggregate_dscr) },
            { label: 'Exit Value', value: formatCurrency(results.exit_value) },
            { label: 'Implied Exit Cap Rate', value: formatPercent(results.implied_exit_cap_rate) },
            occupancy === null
              ? {
                  label: 'Year-End Physical Occupancy',
                  value: 'N/A',
                  note: occupancyReason(results, names),
                }
              : { label: 'Year-End Physical Occupancy', value: 'By year, below' },
          ]}
        />
      </div>
      <p className="investment-note">
        Aggregate DSCR is consolidated NOI over consolidated acquisition-loan debt service: it is
        not an average of Unit DSCRs and not the lowest Unit DSCR.
      </p>
    </div>
  );
}

function ClosingSection({ results }: { results: ConsolidatedResults }) {
  const line = (label: string, value: number, note?: string): LedgerLine => ({
    label,
    value: formatCurrency(value),
    note,
    negative: value < 0,
  });
  return (
    <div className="investment-closing">
      <Ledger
        caption="Sources and Uses at Closing"
        lines={[
          line('Transaction Price', results.transaction_price, 'Reconciliation and reporting only.'),
          line('Allocated Purchase Price', results.allocated_purchase_price, 'The Units’ underwriting prices; used in the cash flows.'),
          line('Allocation Variance', results.allocation_variance),
          line('Acquisition Costs', results.acquisition_costs),
          line('Financing Fees', results.financing_fees),
          line('Investment Transaction Costs', results.investment_transaction_costs),
          line('Closing Project Capital', results.closing_project_capital),
          line('of which Investment-level', results.investment_closing_project_capital),
          line('Loan Amount', results.loan_amount),
          line('Initial Equity', results.initial_equity),
          line('Total Closing Uses', results.total_closing_uses),
          line('Total Closing Sources', results.total_closing_sources),
        ]}
      />
      <p className="investment-note">{ALLOCATED_PRICE_NOTE}</p>
    </div>
  );
}

/** One annual row: a label and a backend series, each year formatted. */
interface SeriesRow {
  label: string;
  values: readonly (number | null)[];
  format: (value: number | null) => string;
  strong?: boolean;
}

function CashFlowSection({ results, names }: { results: ConsolidatedResults; names: Readonly<Record<string, string>> }) {
  const years = results.noi_by_year.map((_, index) => holdYearLabel(index));
  const occupancy = results.physical_occupancy_at_year_end;
  const rows: SeriesRow[] = [
    { label: 'NOI', values: results.noi_by_year, format: formatCurrency, strong: true },
    { label: 'CapEx Reserve', values: results.capex_by_year, format: formatCurrency },
    { label: 'Tenant Improvements', values: results.tenant_improvements_by_year, format: formatCurrency },
    { label: 'Leasing Commissions', values: results.leasing_commissions_by_year, format: formatCurrency },
    { label: 'Property Cash Flow', values: results.property_cash_flow_by_year, format: formatCurrency, strong: true },
    { label: 'Project Capital (Investment-level)', values: results.investment_project_capital_by_year, format: formatCurrency },
    { label: 'Project Capital (total)', values: results.project_capital_by_year, format: formatCurrency },
    { label: 'Owner Expenses (Investment-level)', values: results.investment_owner_expenses_by_year, format: formatCurrency },
    { label: 'Owner Expenses (total)', values: results.owner_expenses_by_year, format: formatCurrency },
    { label: 'Unlevered Owner Cash Flow', values: results.unlevered_owner_cash_flow_by_year, format: formatCurrency, strong: true },
    { label: 'Debt Service', values: results.annual_debt_service, format: formatCurrency },
    { label: 'Levered Owner Cash Flow', values: results.levered_owner_cash_flow_by_year, format: formatCurrency, strong: true },
    {
      label: 'Net Additional Equity Requirement',
      values: results.net_additional_equity_requirement_by_year,
      format: formatCurrency,
    },
    { label: 'Aggregate DSCR', values: results.aggregate_dscr_by_year, format: formatMultiple },
  ];
  return (
    <div className="investment-table-scroll" role="region" aria-label="Annual consolidated cash flow" tabIndex={0}>
      <table className="investment-table investment-cash-flow">
        <caption className="visually-hidden">Annual consolidated cash flow, Years 1 to {results.hold_period}</caption>
        <thead>
          <tr>
            <th scope="col" className="investment-row-head">
              Line
            </th>
            {years.map((year) => (
              <th key={year} scope="col" className="investment-num">
                {year}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className={row.strong ? 'investment-row-strong' : undefined}>
              <th scope="row" className="investment-row-head">
                {row.label}
              </th>
              {row.values.map((value, index) => (
                <td
                  key={years[index] ?? index}
                  className={value !== null && signClass(value) !== undefined ? 'investment-num capital-economics-negative' : 'investment-num'}
                >
                  {row.format(value)}
                </td>
              ))}
            </tr>
          ))}
          <tr>
            <th scope="row" className="investment-row-head">
              Year-End Physical Occupancy
            </th>
            {occupancy === null ? (
              <td colSpan={years.length} className="investment-muted investment-wrap-cell">
                N/A: {occupancyReason(results, names)}
              </td>
            ) : (
              occupancy.map((value, index) => (
                <td key={years[index] ?? index} className="investment-num">
                  {formatPercent(value)}
                </td>
              ))
            )}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

interface SectionProps {
  id: string;
  title: string;
  action?: ReactNode;
  children: ReactNode;
}

function Section({ id, title, action, children }: SectionProps) {
  return (
    <section className="scenario-panel investment-section" aria-labelledby={id}>
      <div className="scenario-panel-header">
        <div className="scenario-panel-heading">
          <h3 id={id} className="scenario-panel-title">
            {title}
          </h3>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function InvestmentOverview({ workspace, analysis }: InvestmentOverviewProps) {
  const investment = workspace.investment;
  const shown = workspace.editing ?? workspace.savedDetails;
  if (investment === null || shown === null) {
    return null;
  }
  const editing = workspace.editing;
  const feedback = workspace.detailsFeedback;
  const locked = editing === null || workspace.isSavingDetails;
  const unitHolds = new Set(workspace.unitRows.map((row) => (row.deal === null ? null : storedHoldPeriod(row.deal))));
  const [onlyHold] = [...unitHolds];
  const commonHold = unitHolds.size === 1 && onlyHold !== null && onlyHold !== undefined ? String(onlyHold) : '';
  const results = analysis.analysis?.consolidated_results ?? null;
  const showResults = results !== null && analysis.isCurrent;
  const staleMessage = workspace.isEconomicBlocked ? INVESTMENT_ANALYSIS_DIRTY_MESSAGE : INVESTMENT_ANALYSIS_STALE_MESSAGE;

  const runButton = (
    <button
      type="button"
      className="btn btn-primary btn-sm"
      onClick={() => void analysis.run()}
      disabled={!analysis.canRun}
      aria-describedby={workspace.isEconomicBlocked ? 'investment-analysis-blocked' : undefined}
    >
      {analysis.isRunning ? 'Running…' : analysis.hasRun ? 'Refresh Base Analysis' : 'Run Base Analysis'}
    </button>
  );

  return (
    <div className="investment-overview">
      {editing !== null && (
        <div className="investment-edit-bar" role="region" aria-label="Investment changes">
          <span className={workspace.isDirty ? 'save-status save-status-unsaved-changes' : 'save-status save-status-saved'}>
            <span className="save-status-dot" aria-hidden="true" />
            {workspace.isDirty ? 'Unsaved changes' : 'No changes yet'}
          </span>
          <div className="investment-edit-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={workspace.cancelEdit}
              disabled={workspace.isSavingDetails}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => void workspace.saveDetails()}
              disabled={workspace.isSavingDetails}
            >
              {workspace.isSavingDetails ? 'Saving…' : 'Save Investment'}
            </button>
          </div>
        </div>
      )}

      {feedback !== null && (
        <div className="error-banner investment-feedback" role="alert">
          <p className="scenario-editor-feedback-message">{feedback.message}</p>
          <InvestmentIssueList issues={feedback.general} names={workspace.names} />
        </div>
      )}

      <Section id="investment-summary-title" title="Investment Summary">
        <div className="investment-summary">
          <div className="investment-summary-fields">
            <div className="field">
              <label className="field-label" htmlFor="investment-name">
                Investment Name
              </label>
              <input
                id="investment-name"
                className="field-input"
                type="text"
                value={shown.name}
                onChange={(event) => workspace.setName(event.target.value)}
                disabled={locked}
                autoComplete="off"
                aria-invalid={(feedback?.name.length ?? 0) > 0 ? true : undefined}
              />
              {feedback !== null && feedback.name.length > 0 && (
                <ul className="investment-issues" role="alert">
                  {feedback.name.map((message) => (
                    <li key={message}>{message}</li>
                  ))}
                </ul>
              )}
            </div>
            <div className="field">
              <label className="field-label" htmlFor="investment-transaction-price">
                Transaction Price
              </label>
              <div className="field-input-wrap">
                <span className="field-affix field-affix-left">$</span>
                <NumericInput
                  id="investment-transaction-price"
                  className="field-input"
                  value={shown.transactionPrice}
                  onChange={workspace.setTransactionPrice}
                  group
                  disabled={locked}
                  style={{ paddingLeft: '1.4rem' }}
                  aria-invalid={(feedback?.price.length ?? 0) > 0 ? true : undefined}
                  aria-describedby="investment-transaction-price-note"
                />
              </div>
              <InvestmentIssueList issues={feedback?.price ?? []} names={workspace.names} />
            </div>
          </div>
          <p className="investment-note" id="investment-transaction-price-note">
            {TRANSACTION_PRICE_NOTE}
          </p>
          <table className="investment-table investment-summary-units">
            <caption className="investment-ledger-caption">Units</caption>
            <thead>
              <tr>
                <th scope="col">Unit</th>
                <th scope="col">Mode</th>
              </tr>
            </thead>
            <tbody>
              {workspace.unitRows.map((row) => (
                <tr key={row.membership.unit_id}>
                  <th scope="row" className="investment-name-cell">
                    {unitDisplayName({ dealName: row.deal?.name ?? row.membership.unit_id, label: row.membership.label })}
                  </th>
                  <td>{row.deal === null ? 'N/A' : operatingModeLabel(row.deal.operating_mode)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section id="investment-returns-title" title="Consolidated Returns" action={runButton}>
        {workspace.isEconomicBlocked && (
          <p id="investment-analysis-blocked" className="scenario-blocked" role="status">
            {INVESTMENT_ANALYSIS_DIRTY_MESSAGE}
          </p>
        )}
        {!analysis.hasRun && (
          <p className="scenario-muted">
            Run Base Analysis to analyze every Unit and consolidate the Investment&apos;s project economics.
          </p>
        )}
        {analysis.isRunning && (
          <p className="scenario-muted" role="status" aria-live="polite">
            Analyzing every Unit and consolidating…
          </p>
        )}
        {analysis.error !== null && (
          <div className="error-banner investment-feedback" role="alert">
            <p className="scenario-editor-feedback-message">
              The consolidated analysis could not be completed.
            </p>
            {analysis.error.issues.length > 0 ? (
              <InvestmentIssueList issues={analysis.error.issues} names={workspace.names} />
            ) : (
              <p className="investment-issue-message">{analysis.error.message}</p>
            )}
          </div>
        )}
        {results !== null && !analysis.isCurrent && <StaleAnalysisNotice message={staleMessage} />}
        {showResults && analysis.analysis !== null && (
          <ReturnsSection results={results} hold={analysis.analysis.hold_period} names={workspace.names} />
        )}
      </Section>

      <Section id="investment-closing-title" title="Closing Economics">
        {showResults ? (
          <ClosingSection results={results} />
        ) : (
          <p className="scenario-muted">Closing sources and uses appear with a current Base Analysis.</p>
        )}
      </Section>

      <Section id="investment-business-plan-title" title="Investment Business Plan">
        <p className="investment-note">{INVESTMENT_BUSINESS_PLAN_NOTE}</p>
        <BusinessPlanEditor
          idPrefix="investment-business-plan"
          embedded
          plan={shown.businessPlan}
          onChange={workspace.setBusinessPlan}
          issues={feedback?.planIssues ?? []}
          holdPeriod={commonHold}
          disabled={locked}
        />
      </Section>

      <Section id="investment-costs-title" title="Transaction Costs">
        <TransactionCostEditor
          costs={shown.costs}
          issues={feedback?.costs ?? {}}
          disabled={locked}
          onAdd={workspace.addCost}
          onChange={workspace.updateCost}
          onRemove={workspace.removeCost}
        />
      </Section>

      <Section id="investment-cash-flow-title" title="Annual Consolidated Cash Flow">
        {showResults ? (
          <CashFlowSection results={results} names={workspace.names} />
        ) : (
          <p className="scenario-muted">The annual consolidated cash flow appears with a current Base Analysis.</p>
        )}
      </Section>
    </div>
  );
}
