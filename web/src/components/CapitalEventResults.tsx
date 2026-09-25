/**
 * Refinance & Capital Events V1 Stage 3 -- what each refinance did.
 *
 * For every configured refinance of the analysed variant: the primary economic
 * answer (cash returned to Common Equity, or the contribution it requires),
 * the sizing panel (each enabled capacity, the operands behind it, the binding
 * constraint or tie, achieved coverage and leverage), the audit bridge, and
 * then the Common Equity cash flow with the refinance cash shown apart from the
 * recurring cash, and the primary return view
 * (`docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md` Sections 11, 12.5, 16.3).
 *
 * **It computes nothing.** Every figure is one field of the accepted engine
 * result, formatted by the shared helpers. The net event cash is
 * `RefinanceBridge.net_event_cash`, never re-derived from the lines above it;
 * the recurring and event series are the engine's own decomposition; the
 * capacities, minimum and binding set are the engine's (Section 12.5 rule 7).
 *
 * **Unavailable is not zero.** A refinance that did not execute shows its
 * state and why, and every figure it would have produced reads N/A -- never
 * `$0`. A computed zero reads `$0`, because it is one (INV-12).
 *
 * **Common Equity is primary.** It is shown whether or not a Common Equity
 * marker is authored, and the acquisition-financing figures elsewhere in the
 * product are named as a reference that excludes this refinance.
 */

import { useId } from 'react';
import { irrNotReportedExplanation } from '../capitalEconomics';
import { formatCurrency, formatMultiple, formatPercent } from '../format';
import {
  ACQUISITION_REFERENCE_LABEL,
  CONSTRAINT_LABELS,
  DIRECTION_HEADINGS,
  DIRECTION_NOTES,
  DSCR_BASIS_TEXT,
  REFINANCE_STATUS_LABELS,
  capacityReasonText,
  commonEquityUnavailableText,
  eventDateText,
  magnitudeText,
  refinanceReasonText,
  retiringName,
  scopeText,
} from '../refinanceCatalog';
import type { RefinanceTextContext } from '../refinanceCatalog';
import type {
  CommonEquityReturns,
  ConstraintCapacity,
  FixedCapOperands,
  MaxLtvOperands,
  MinDscrOperands,
  PrimaryReturnView,
  RefinanceResult,
  StructuredCapitalResult,
} from '../capitalTypes';

export interface CapitalEventResultsProps {
  result: StructuredCapitalResult;
  primaryReturn: PrimaryReturnView | undefined;
  unitNames: Record<string, string>;
  /** The labels of the Investment's valuations, for the LTV operand. */
  valuationLabels: Record<string, string>;
}

const NOT_AVAILABLE = 'N/A';

function NotAvailable({ reason }: { reason: string | null }) {
  return (
    <>
      <span>{NOT_AVAILABLE}</span>
      {reason !== null && <span className="capital-result-reason">{reason}</span>}
    </>
  );
}

function money(value: number | null | undefined): string {
  return value === null || value === undefined ? NOT_AVAILABLE : formatCurrency(value);
}

// =============================================================================
// The primary answer
// =============================================================================

function EventHeadline({ event, context }: { event: RefinanceResult; context: RefinanceTextContext }) {
  const bridge = event.bridge;
  const reason = refinanceReasonText(event, context);
  return (
    <div
      className={
        bridge === null
          ? 'refinance-headline refinance-headline-unavailable'
          : `refinance-headline refinance-headline-${bridge.direction}`
      }
    >
      <div className="refinance-headline-figure">
        <span className="refinance-headline-label">
          {bridge === null ? DIRECTION_HEADINGS.distribution : DIRECTION_HEADINGS[bridge.direction]}
        </span>
        <span className="refinance-headline-value" data-testid="refinance-net-cash">
          {bridge === null ? NOT_AVAILABLE : magnitudeText(bridge.net_event_cash)}
        </span>
        <span className="refinance-headline-note">
          {bridge === null ? REFINANCE_STATUS_LABELS[event.status] : DIRECTION_NOTES[bridge.direction]}
        </span>
      </div>
      <dl className="refinance-headline-facts">
        <div>
          <dt>Date</dt>
          <dd>{eventDateText(event)}</dd>
        </div>
        <div>
          <dt>Scope</dt>
          <dd>
            {event.scope.kind === 'investment' ? 'Whole Investment' : scopeText(event.scope, context.unitNames)}
          </dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>
            <span className={event.status === 'executed' ? 'refinance-status' : 'refinance-status refinance-status-open'}>
              {REFINANCE_STATUS_LABELS[event.status]}
            </span>
          </dd>
        </div>
        <div>
          <dt>New loan</dt>
          <dd>{money(event.funding?.gross_proceeds)}</dd>
        </div>
      </dl>
      {reason !== null && (
        <p className="refinance-headline-reason" role="status">
          {reason}
        </p>
      )}
    </div>
  );
}

// =============================================================================
// Sizing
// =============================================================================

function operandsText(capacity: ConstraintCapacity, event: RefinanceResult, context: RefinanceTextContext): string[] {
  if (capacity.kind === 'fixed_cap') {
    const operands = capacity.operands as FixedCapOperands;
    return [`Authored cap: ${formatCurrency(operands.amount)}`];
  }
  if (capacity.kind === 'max_ltv') {
    const operands = capacity.operands as MaxLtvOperands;
    const timepoint = event.value_dependency?.timepoint_id;
    const label = timepoint === undefined ? null : (context.valuationLabels[timepoint] ?? null);
    const analystSupplied = event.value_dependency?.analyst_supplied === true;
    return [
      `Maximum LTV: ${formatPercent(operands.max_ltv)}`,
      `Value${label === null ? '' : ` — ${label}`}${analystSupplied ? ' (Analyst-Supplied Value)' : ''}: ${money(operands.scope_value)}`,
      `Continuing senior debt: ${formatCurrency(operands.continuing_senior_balance)}`,
    ];
  }
  const operands = capacity.operands as MinDscrOperands;
  const forwardYear = event.noi_dependency?.forward_year;
  return [
    `Minimum DSCR: ${formatMultiple(operands.min_dscr)}`,
    `Forward NOI${forwardYear === undefined ? '' : ` (Year ${forwardYear})`}: ${money(operands.forward_noi)}`,
    `Continuing senior service: ${formatCurrency(operands.continuing_senior_service)}`,
    `Service capacity: ${money(operands.service_capacity)}`,
    `First-year service per $1 of loan: ${formatPercent(operands.first_year_service_per_dollar, 4)}`,
  ];
}

function SizingPanel({ event, context }: { event: RefinanceResult; context: RefinanceTextContext }) {
  const titleId = useId();
  const sizing = event.sizing;
  if (sizing === null) {
    return null;
  }
  const binding = new Set(sizing.binding);
  return (
    <section className="card table-card capital-result-card" aria-labelledby={titleId}>
      <h5 className="card-title" id={titleId}>
        What sized the new loan
      </h5>
      <p className="capital-result-helper">
        The new loan is the least of every enabled constraint. Every enabled constraint must be known:
        one that is unavailable is never dropped from the comparison.
      </p>
      <div className="table-scroll" role="region" tabIndex={0} aria-labelledby={titleId}>
        <table className="capital-result-table refinance-sizing-table" aria-labelledby={titleId}>
          <thead>
            <tr>
              <th scope="col">Constraint</th>
              <th scope="col">Operands</th>
              <th scope="col">Capacity</th>
              <th scope="col">Result</th>
            </tr>
          </thead>
          <tbody>
            {sizing.capacities.map((capacity) => (
              <tr key={capacity.kind} className={binding.has(capacity.kind) ? 'refinance-binding-row' : undefined}>
                <th scope="row">{CONSTRAINT_LABELS[capacity.kind]}</th>
                <td>
                  <ul className="refinance-operands">
                    {operandsText(capacity, event, context).map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                  {capacity.kind === 'min_dscr' && <span className="capital-result-reason">{DSCR_BASIS_TEXT}</span>}
                </td>
                <td className={capacity.capacity === null ? 'capital-result-na' : undefined}>
                  {capacity.capacity === null ? (
                    <NotAvailable reason={capacityReasonText(capacity.unavailable_reason, event, context)} />
                  ) : (
                    formatCurrency(capacity.capacity)
                  )}
                </td>
                <td>
                  {binding.has(capacity.kind) ? (
                    <span className="refinance-binding">{sizing.tie ? 'Binding (tie)' : 'Binding'}</span>
                  ) : capacity.capacity === null ? (
                    <span className="refinance-status refinance-status-open">Unavailable</span>
                  ) : sizing.gross_proceeds === null ? (
                    // Another constraint is unavailable, so no minimum was taken.
                    <span className="capital-result-reason">Not compared</span>
                  ) : (
                    <span className="capital-result-reason">Not binding</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="refinance-facts">
        <div>
          <dt>Gross proceeds</dt>
          <dd>{money(sizing.gross_proceeds)}</dd>
        </div>
        <div>
          <dt>Binding constraint</dt>
          <dd>
            {sizing.binding.length === 0
              ? NOT_AVAILABLE
              : sizing.binding.map((kind) => CONSTRAINT_LABELS[kind]).join(', ')}
          </dd>
        </div>
        <div>
          <dt>Tie</dt>
          <dd>{sizing.binding.length === 0 ? NOT_AVAILABLE : sizing.tie ? 'Yes — every tied constraint binds' : 'No'}</dd>
        </div>
        <div>
          <dt>Achieved LTV</dt>
          <dd>
            {event.funding === null || event.funding.achieved_ltv === null
              ? NOT_AVAILABLE
              : formatPercent(event.funding.achieved_ltv)}
          </dd>
        </div>
        <div>
          <dt>Achieved DSCR</dt>
          <dd>
            {event.funding === null || event.funding.achieved_dscr === null
              ? NOT_AVAILABLE
              : formatMultiple(event.funding.achieved_dscr)}
          </dd>
        </div>
        <div>
          <dt>First payment</dt>
          <dd>{event.funding === null ? NOT_AVAILABLE : `Model Month ${event.funding.first_service_month}`}</dd>
        </div>
        <div>
          <dt>First-year debt service</dt>
          <dd>{money(event.funding?.first_year_service)}</dd>
        </div>
      </dl>
    </section>
  );
}

// =============================================================================
// The bridge
// =============================================================================

function BridgeTable({
  event,
  context,
  positionNames,
  multiUnit,
}: {
  event: RefinanceResult;
  context: RefinanceTextContext;
  positionNames: Record<string, string>;
  multiUnit: boolean;
}) {
  const titleId = useId();
  const bridge = event.bridge;
  const replacement = event.funding === null ? null : (positionNames[event.funding.position_id] ?? null);
  return (
    <section className="card table-card capital-result-card" aria-labelledby={titleId}>
      <h5 className="card-title" id={titleId}>
        Refinance bridge
      </h5>
      <p className="capital-result-helper">
        Each line is the engine’s own figure at the refinance date. The retiring loans’ scheduled payments
        for that month are ordinary debt service of the year and are not in the bridge.
      </p>
      <div className="table-scroll" role="region" tabIndex={0} aria-labelledby={titleId}>
        <table className="capital-result-table refinance-bridge-table" aria-labelledby={titleId}>
          <thead>
            <tr>
              <th scope="col">Line</th>
              <th scope="col">Amount</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">{replacement === null ? 'Gross replacement-loan proceeds' : `Gross proceeds — ${replacement}`}</th>
              <td>{bridge === null ? NOT_AVAILABLE : formatCurrency(bridge.gross_proceeds)}</td>
            </tr>
            {(event.payoffs ?? []).map((payoff) => (
              <tr key={`${payoff.ref.kind}:${payoff.ref.kind === 'legacy_acquisition_loan' ? payoff.ref.unit_id : payoff.ref.position_id}`}>
                <th scope="row" className="refinance-bridge-deduction">
                  {`Payoff — ${retiringName(payoff.ref, positionNames, context.unitNames, multiUnit)}`}
                </th>
                <td>{bridge === null ? NOT_AVAILABLE : formatCurrency(payoff.payoff)}</td>
              </tr>
            ))}
            {event.payoffs === null && (
              <tr>
                <th scope="row" className="refinance-bridge-deduction">Payoff of the loans repaid</th>
                <td>{NOT_AVAILABLE}</td>
              </tr>
            )}
            <tr>
              <th scope="row" className="refinance-bridge-deduction">Replacement-lender fees</th>
              <td>{bridge === null ? NOT_AVAILABLE : formatCurrency(bridge.replacement_lender_fees)}</td>
            </tr>
            <tr>
              <th scope="row" className="refinance-bridge-deduction">Retiring-lender fees</th>
              <td>{bridge === null ? NOT_AVAILABLE : formatCurrency(bridge.retiring_lender_fees)}</td>
            </tr>
            <tr>
              <th scope="row" className="refinance-bridge-deduction">Third-party costs</th>
              <td>{bridge === null ? NOT_AVAILABLE : formatCurrency(bridge.third_party_costs)}</td>
            </tr>
            <tr className="refinance-bridge-total">
              <th scope="row">Net refinance cash to Common Equity</th>
              <td>{bridge === null ? NOT_AVAILABLE : formatCurrency(bridge.net_event_cash)}</td>
            </tr>
            <tr>
              <th scope="row">Direction</th>
              <td>
                {bridge === null
                  ? NOT_AVAILABLE
                  : bridge.direction === 'distribution'
                    ? 'Distribution'
                    : bridge.direction === 'contribution'
                      ? 'Contribution'
                      : 'Zero'}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      {bridge !== null && (event.payoffs ?? []).length > 1 && (
        <p className="capital-result-reason">{`Total payoffs: ${formatCurrency(bridge.payoffs)}`}</p>
      )}
    </section>
  );
}

// =============================================================================
// Common Equity: the decomposition and the primary returns
// =============================================================================

function SeriesCell({ value }: { value: number }) {
  return <td>{formatCurrency(value)}</td>;
}

function CommonEquityDecomposition({ common, events }: { common: CommonEquityReturns; events: RefinanceResult[] }) {
  const titleId = useId();
  const total = common.cash_flows;
  const recurring = common.recurring_cash_flows ?? null;
  const eventCash = common.event_cash_flows ?? null;
  return (
    <section className="card table-card capital-result-card" aria-labelledby={titleId}>
      <h5 className="card-title" id={titleId}>
        Common Equity cash flow
      </h5>
      <p className="capital-result-helper">
        Refinance cash is shown apart from recurring Common Equity cash in the refinance year. Recurring
        measures read the recurring line only; the total is what every return below is measured on.
      </p>
      {total === null || recurring === null || eventCash === null ? (
        <p className="capital-result-empty capital-result-na">
          <NotAvailable reason={commonEquityUnavailableText(events)} />
        </p>
      ) : (
        <div className="table-scroll" role="region" tabIndex={0} aria-labelledby={titleId}>
          <table className="capital-result-table refinance-series-table" aria-labelledby={titleId}>
            <thead>
              <tr>
                <th scope="col">Line</th>
                {total.map((_, year) => (
                  <th scope="col" key={`year-${year}`}>{`Year ${year}`}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Recurring Common Equity cash flow</th>
                {recurring.map((value, year) => (
                  <SeriesCell key={`recurring-${year}`} value={value} />
                ))}
              </tr>
              <tr>
                <th scope="row">Refinance event cash</th>
                {eventCash.map((value, year) => (
                  <SeriesCell key={`event-${year}`} value={value} />
                ))}
              </tr>
              <tr className="refinance-bridge-total">
                <th scope="row">Total Common Equity cash flow</th>
                {total.map((value, year) => (
                  <SeriesCell key={`total-${year}`} value={value} />
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function PrimaryReturns({
  common,
  primaryReturn,
  events,
}: {
  common: CommonEquityReturns;
  primaryReturn: PrimaryReturnView | undefined;
  events: RefinanceResult[];
}) {
  const titleId = useId();
  const available = common.cash_flows !== null;
  const partner = primaryReturn?.primary_investor_namespace === 'partner';
  return (
    <section className="card capital-result-card refinance-primary" aria-labelledby={titleId}>
      <h5 className="card-title" id={titleId}>
        Primary return — Common Equity after Capital Structure
      </h5>
      <p className="capital-result-helper">
        Refinance-adjusted: every refinance of this analysis is included. It is reported whether or not a
        Common Equity position is authored.
      </p>
      {!available ? (
        <p className="capital-result-na" role="status">
          <NotAvailable reason={commonEquityUnavailableText(events)} />
        </p>
      ) : (
        <dl className="refinance-returns">
          <div className="refinance-return-primary">
            <dt>Common Equity IRR</dt>
            <dd>
              {common.irr === null ? (
                <NotAvailable
                  reason={
                    common.irr_status === null
                      ? null
                      : irrNotReportedExplanation('Common Equity IRR', common.irr_status)
                  }
                />
              ) : (
                formatPercent(common.irr)
              )}
            </dd>
          </div>
          <div className="refinance-return-primary">
            <dt>Equity Multiple</dt>
            <dd>{common.equity_multiple === null ? NOT_AVAILABLE : formatMultiple(common.equity_multiple)}</dd>
          </div>
          <div>
            <dt>Total Equity Invested</dt>
            <dd>{money(common.total_equity_invested)}</dd>
          </div>
          <div>
            <dt>Total Cash Returned</dt>
            <dd>{money(common.total_cash_returned)}</dd>
          </div>
          <div>
            <dt>Total Profit</dt>
            <dd>{money(common.total_profit)}</dd>
          </div>
        </dl>
      )}
      {partner && (
        <p className="refinance-namespace-note">
          Partner returns are the primary investor view for this analysis. They include every refinance
          through this Common Equity cash flow; see the Partnership workspace.
        </p>
      )}
      <p className="refinance-namespace-note">
        {`${ACQUISITION_REFERENCE_LABEL}: the levered IRR and equity multiple in Capital Economics hold the acquisition loan to the sale. They are a reference only, not this refinance-adjusted return.`}
      </p>
    </section>
  );
}

// =============================================================================
// The whole view
// =============================================================================

export function CapitalEventResults({ result, primaryReturn, unitNames, valuationLabels }: CapitalEventResultsProps) {
  const titleId = useId();
  const events = result.capital_events ?? [];
  if (events.length === 0) {
    return null;
  }
  const context: RefinanceTextContext = { unitNames, valuationLabels };
  const positionNames: Record<string, string> = Object.fromEntries([
    ...result.positions.map((position) => [position.position_id, position.name] as const),
    ...(result.unexecuted_positions ?? []).map((position) => [position.position_id, position.name] as const),
  ]);
  const multiUnit = result.unit_ids.length > 1;
  return (
    <section className="refinance-results" aria-labelledby={titleId}>
      <h4 className="capital-results-title" id={titleId}>
        Refinance
      </h4>
      {events.map((event) => (
        <article key={event.event_id} className="refinance-event" aria-label={event.label}>
          <h5 className="refinance-event-title">{event.label}</h5>
          <EventHeadline event={event} context={context} />
          <SizingPanel event={event} context={context} />
          <BridgeTable event={event} context={context} positionNames={positionNames} multiUnit={multiUnit} />
        </article>
      ))}
      <PrimaryReturns common={result.common_equity} primaryReturn={primaryReturn} events={events} />
      <CommonEquityDecomposition common={result.common_equity} events={events} />
    </section>
  );
}
