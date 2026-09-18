/**
 * Phase 7 Gate P7.8B -- what the structured capital did.
 *
 * One position per row, the Funding Requirements beneath them, the Common
 * Equity residual, and each Unit's existing acquisition loan shown read-only.
 *
 * **It computes nothing.** Every figure below is one field of
 * `StructuredCapitalResult`, formatted by the shared helpers. Nothing here is
 * summed, netted, sized, amortized or derived, and no IRR, multiple,
 * attachment, coverage or Funding Requirement is recomputed in the browser
 * (P-3, P-5).
 *
 * **Returns and structural metrics are different things.** A position's
 * returns -- IRR, MOIC, profit, cash received -- are reported only when its
 * settlement is `complete`; otherwise they are `N/A` with the backend's own
 * reason. Its **structural metrics** -- attachment, detachment, last-dollar
 * basis, debt yield, coverage -- are contractual underwriting facts and stand
 * whatever the cash settlement did. The table keeps them apart, because an
 * analyst who reads "no IRR" must not conclude "no attachment point" (DC-2).
 *
 * **An unresolved Funding Requirement is not an error.** It is a successful
 * analysis of a structure whose claim the eligible cash could not meet, stated
 * as the deterministic fact it is (P-14).
 *
 * **Common Equity here is the residual after structured capital**, never the
 * project's levered return, which still exists and still differs (NS-1).
 */

import { useId } from 'react';
import { irrNotReportedExplanation, signClass } from '../capitalEconomics';
import { formatCurrency, formatMultiple, formatPercent } from '../format';
import { POSITION_CLASS_LABELS } from '../capitalStructureForm';
import type {
  CommonEquityReturns,
  FundingRequirement,
  LegacyAcquisitionLoan,
  PositionReturns,
  StructuredCapitalResult,
} from '../capitalTypes';

export interface CapitalStructureResultsProps {
  result: StructuredCapitalResult;
  /** Which Units this analysis covered, named as the analyst knows them. */
  unitNames?: Record<string, string>;
}

/** Each message is one string literal, never joined with `+`: this module is
 * asserted to contain no binary arithmetic operator, and the audit that forbids
 * browser math cannot tell a concatenated sentence from a sum. */
// prettier-ignore
export const UNRESOLVED_STRUCTURE_MESSAGE =
  'One or more claims could not be met from eligible cash. The structure is reported as analysed; the positions it blocked report no return, and why.';

// prettier-ignore
export const NO_FUNDING_REQUIREMENT_MESSAGE =
  'Every contractual claim was met from eligible cash. No Funding Requirement arose.';

// prettier-ignore
export const LEGACY_LOAN_MESSAGE =
  'Each Unit’s acquisition loan, as it is already underwritten. It is not authored here and is never recreated: the structured positions sit alongside it.';

// prettier-ignore
export const NO_POSITION_MESSAGE =
  'This analysis has no structured position. Each Unit keeps its acquisition loan and the residual.';

const NOT_AVAILABLE = 'N/A';

/** A figure the backend did not report, with the backend's own reason. Never a
 * zero, and never a dash that could read as one. */
function Unavailable({ message }: { message: string | null }) {
  return (
    <>
      <span>{NOT_AVAILABLE}</span>
      {message !== null && <span className="capital-result-reason">{message}</span>}
    </>
  );
}

/** One return figure: the value when it is reported, else N/A and why. */
function ReturnCell({
  label,
  value,
  format,
  position,
}: {
  label: string;
  value: number | null;
  format: (value: number) => string;
  position: PositionReturns;
}) {
  if (value !== null) {
    return <td>{format(value)}</td>;
  }
  const irr = position.irr_status === null ? null : irrNotReportedExplanation(label, position.irr_status);
  return (
    <td className="capital-result-na">
      <Unavailable message={irr ?? position.unavailable_message} />
    </td>
  );
}

function scopeLabel(
  position: { scope: { kind: string; unit_id: string | null } },
  unitNames: Record<string, string>,
): string {
  if (position.scope.kind === 'investment') {
    return 'Whole Investment';
  }
  const unitId = position.scope.unit_id;
  if (unitId === null) {
    return 'Unit';
  }
  return unitNames[unitId] ?? unitId;
}

function PositionReturnsTable({
  positions,
  unitNames,
}: {
  positions: PositionReturns[];
  unitNames: Record<string, string>;
}) {
  const titleId = useId();
  return (
    <section className="card table-card capital-result-card" aria-labelledby={titleId}>
      <h4 className="card-title" id={titleId}>
        Position Returns
      </h4>
      <div className="table-scroll">
        <table className="capital-result-table" aria-labelledby={titleId}>
          <thead>
            <tr>
              <th scope="col">Position</th>
              <th scope="col">Scope</th>
              <th scope="col">Priority</th>
              <th scope="col">Funded</th>
              <th scope="col">IRR</th>
              <th scope="col">MOIC</th>
              <th scope="col">Cash Received</th>
              <th scope="col">Profit</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((position) => (
              <tr key={position.position_id}>
                <th scope="row">
                  <span className="capital-result-name">{position.name}</span>
                  <span className="capital-result-class">
                    {POSITION_CLASS_LABELS[position.position_class]}
                  </span>
                </th>
                <td>{scopeLabel(position, unitNames)}</td>
                <td>{position.priority}</td>
                <td>{formatCurrency(position.funded_amount)}</td>
                <ReturnCell label="IRR" value={position.irr} format={formatPercent} position={position} />
                <ReturnCell label="MOIC" value={position.moic} format={formatMultiple} position={position} />
                <ReturnCell
                  label="Cash Received"
                  value={position.total_cash_received}
                  format={formatCurrency}
                  position={position}
                />
                <ReturnCell
                  label="Profit"
                  value={position.profit}
                  format={formatCurrency}
                  position={position}
                />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** The contractual underwriting facts, which stand whatever the settlement did.
 * They are in their own table for exactly that reason. */
function StructuralMetricsTable({
  positions,
  unitNames,
}: {
  positions: PositionReturns[];
  unitNames: Record<string, string>;
}) {
  const titleId = useId();
  const claimBearing = positions.filter((position) => position.position_class !== 'common_equity');
  if (claimBearing.length === 0) {
    return null;
  }
  return (
    <section className="card table-card capital-result-card" aria-labelledby={titleId}>
      <h4 className="card-title" id={titleId}>
        Structural Metrics
      </h4>
      <p className="capital-result-helper">
        Contractual underwriting facts. They describe where a position sits in the stack and stand
        whatever the cash settlement did.
      </p>
      <div className="table-scroll">
        <table className="capital-result-table" aria-labelledby={titleId}>
          <thead>
            <tr>
              <th scope="col">Position</th>
              <th scope="col">Scope</th>
              <th scope="col">Attachment</th>
              <th scope="col">Detachment</th>
              <th scope="col">Last-Dollar Basis</th>
              <th scope="col">Debt Yield Through</th>
              <th scope="col">Headline Coverage</th>
              <th scope="col">Minimum Coverage</th>
              <th scope="col">Balance at Maturity or Exit</th>
            </tr>
          </thead>
          <tbody>
            {claimBearing.map((position) => (
              <tr key={position.position_id}>
                <th scope="row">{position.name}</th>
                <td>{scopeLabel(position, unitNames)}</td>
                <td>{position.attachment_ltv === null ? NOT_AVAILABLE : formatPercent(position.attachment_ltv)}</td>
                <td>{position.detachment_ltv === null ? NOT_AVAILABLE : formatPercent(position.detachment_ltv)}</td>
                <td>{formatCurrency(position.last_dollar_basis)}</td>
                <td>
                  {position.debt_yield_through === null
                    ? NOT_AVAILABLE
                    : formatPercent(position.debt_yield_through)}
                </td>
                <td>
                  {position.headline_coverage === null
                    ? NOT_AVAILABLE
                    : formatMultiple(position.headline_coverage)}
                </td>
                <td>
                  {position.minimum_coverage === null
                    ? NOT_AVAILABLE
                    : formatMultiple(position.minimum_coverage)}
                </td>
                <td>{formatCurrency(position.balance_at_maturity_or_exit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function periodLabel(requirement: FundingRequirement): string {
  // `hold_year` is the hold year itself, and the backend validates it as
  // `>= 1` -- it is not a zero-based index, so it is written as it stands.
  // Passing it through `holdYearLabel`, which adds one to an *index*, reported
  // a claim arising in hold year 2 as "Year 3": the right amount against the
  // wrong year, in the one table whose purpose is saying when a claim went
  // unmet.
  return requirement.period.kind === 'model_month'
    ? `Month ${requirement.period.model_month}`
    : `Year ${requirement.period.hold_year}`;
}

function FundingRequirements({
  requirements,
  unitNames,
}: {
  requirements: FundingRequirement[];
  unitNames: Record<string, string>;
}) {
  const titleId = useId();
  return (
    <section className="card table-card capital-result-card" aria-labelledby={titleId}>
      <h4 className="card-title" id={titleId}>
        Funding Requirements
      </h4>
      <p className="capital-result-helper">
        A Funding Requirement is a contractual claim the eligible cash could not meet. It is not the
        Net Additional Equity Requirement, which is a project-level annual net figure.
      </p>
      {requirements.length === 0 ? (
        <p className="capital-result-empty">{NO_FUNDING_REQUIREMENT_MESSAGE}</p>
      ) : (
        <div className="table-scroll">
          <table className="capital-result-table" aria-labelledby={titleId}>
            <thead>
              <tr>
                <th scope="col">Position</th>
                <th scope="col">Scope</th>
                <th scope="col">Period</th>
                <th scope="col">Claim</th>
                <th scope="col">Cash Available</th>
                <th scope="col">Paid from Cash</th>
                <th scope="col">Requirement</th>
                <th scope="col">Equity Contribution</th>
                <th scope="col">Unpaid Claim</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {requirements.map((requirement) => (
                <tr key={requirement.requirement_id}>
                  <th scope="row">{requirement.position_id}</th>
                  <td>{scopeLabel(requirement, unitNames)}</td>
                  <td>{periodLabel(requirement)}</td>
                  <td>{formatCurrency(requirement.claim_amount)}</td>
                  <td>{formatCurrency(requirement.cash_available)}</td>
                  <td>{formatCurrency(requirement.claim_paid_from_cash)}</td>
                  <td>{formatCurrency(requirement.amount)}</td>
                  <td>{formatCurrency(requirement.equity_contribution)}</td>
                  <td>{formatCurrency(requirement.unpaid_claim_amount)}</td>
                  <td>
                    <span
                      className={
                        requirement.status === 'resolved'
                          ? 'capital-result-status'
                          : 'capital-result-status capital-result-status-unresolved'
                      }
                    >
                      {requirement.status === 'resolved' ? 'Resolved' : 'Unresolved'}
                    </span>
                    <span className="capital-result-reason">{requirement.explanation}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function CommonEquityPanel({ common }: { common: CommonEquityReturns }) {
  const titleId = useId();
  const unavailable = common.irr === null && common.unavailable_message !== null;
  return (
    <section className="card capital-result-card" aria-labelledby={titleId}>
      <h4 className="card-title" id={titleId}>
        Common Equity After Structured Capital
      </h4>
      <p className="capital-result-helper">
        The residual after every claim above it. This is not the project’s levered return, which is
        reported in Capital Economics and still differs.
      </p>
      <table className="capital-economics-ledger" aria-labelledby={titleId}>
        <tbody>
          <tr>
            <th scope="row">Common Equity IRR</th>
            <td className={unavailable ? 'capital-result-na' : undefined}>
              {common.irr === null ? (
                <Unavailable
                  message={
                    (common.irr_status === null
                      ? null
                      : irrNotReportedExplanation('Common Equity IRR', common.irr_status)) ??
                    common.unavailable_message
                  }
                />
              ) : (
                formatPercent(common.irr)
              )}
            </td>
          </tr>
          <tr>
            <th scope="row">Equity Multiple</th>
            <td>{common.equity_multiple === null ? NOT_AVAILABLE : formatMultiple(common.equity_multiple)}</td>
          </tr>
          <tr>
            <th scope="row">Total Equity Invested</th>
            <td>
              {common.total_equity_invested === null
                ? NOT_AVAILABLE
                : formatCurrency(common.total_equity_invested)}
            </td>
          </tr>
          <tr>
            <th scope="row">Total Cash Returned</th>
            <td>
              {common.total_cash_returned === null
                ? NOT_AVAILABLE
                : formatCurrency(common.total_cash_returned)}
            </td>
          </tr>
          <tr className="capital-economics-ledger-total">
            <th scope="row">Total Profit</th>
            <td className={common.total_profit === null ? undefined : signClass(common.total_profit)}>
              {common.total_profit === null ? NOT_AVAILABLE : formatCurrency(common.total_profit)}
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  );
}

function LegacyLoans({
  loans,
  unitNames,
}: {
  loans: LegacyAcquisitionLoan[];
  unitNames: Record<string, string>;
}) {
  const titleId = useId();
  if (loans.length === 0) {
    return null;
  }
  return (
    <section className="card table-card capital-result-card" aria-labelledby={titleId}>
      <h4 className="card-title" id={titleId}>
        Acquisition Loans
      </h4>
      <p className="capital-result-helper">{LEGACY_LOAN_MESSAGE}</p>
      <div className="table-scroll">
        {/* Every column but the Unit is a figure, so this table -- and only
          * this table -- right-aligns its column headers over the values they
          * describe. The other Capital Structure tables carry text columns
          * (Scope, Period, Status) whose headers belong on the left, which is
          * why the shared rule stays as it is and this is a scoped hook. */}
        <table className="capital-result-table capital-loan-table" aria-labelledby={titleId}>
          <thead>
            <tr>
              <th scope="col">Unit</th>
              <th scope="col">Priority</th>
              <th scope="col">Loan Amount</th>
              <th scope="col">Interest Rate</th>
              <th scope="col">Amortization</th>
              <th scope="col">Interest-Only</th>
              <th scope="col">Remaining Balance</th>
            </tr>
          </thead>
          <tbody>
            {loans.map((loan) => (
              <tr key={loan.position_id}>
                <th scope="row">{scopeLabel(loan, unitNames)}</th>
                <td>{loan.priority}</td>
                <td>{formatCurrency(loan.loan_amount)}</td>
                <td>{formatPercent(loan.interest_rate)}</td>
                <td>{`${loan.amortization} yrs`}</td>
                <td>{`${loan.io_period} yrs`}</td>
                <td>{formatCurrency(loan.remaining_loan_balance)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function CapitalStructureResults({ result, unitNames = {} }: CapitalStructureResultsProps) {
  const titleId = useId();
  return (
    <section className="capital-results" aria-labelledby={titleId}>
      <header className="capital-results-head">
        <h3 className="capital-results-title" id={titleId}>
          Structured Capital
        </h3>
        {result.status === 'unresolved_funding' && (
          <p className="capital-result-unresolved" role="status">
            {UNRESOLVED_STRUCTURE_MESSAGE}
          </p>
        )}
      </header>

      {result.positions.length === 0 ? (
        <p className="capital-result-empty">{NO_POSITION_MESSAGE}</p>
      ) : (
        <>
          <PositionReturnsTable positions={result.positions} unitNames={unitNames} />
          <StructuralMetricsTable positions={result.positions} unitNames={unitNames} />
        </>
      )}

      <FundingRequirements requirements={result.funding_requirements} unitNames={unitNames} />
      <CommonEquityPanel common={result.common_equity} />
      <LegacyLoans loans={result.legacy_acquisition_loans} unitNames={unitNames} />
    </section>
  );
}
