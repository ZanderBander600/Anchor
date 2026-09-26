/**
 * The saved Capital Structure at a glance: one row per authored position --
 * what it is, where it ranks, what it covers, how it is funded and on what
 * terms -- and one line per refinance saying what it repays and what it
 * funds.
 *
 * Presentation only. Every figure is an authored value read back from the
 * saved structure, formatted by the existing helpers or by the editor's own
 * form model (`formFromStructure`), so a term reads here exactly as it does
 * on the position's card. Nothing is sized, summed, sorted or derived: what a
 * refinance actually raises is the engine's, and is reported by the
 * structured analysis below. Positions keep their saved order and state their
 * priority.
 *
 * Kept with the Stage 3 modules because it names the refinance relationship,
 * which the P7.8B capital modules may not (`refinanceArchitecture.test.ts`
 * holds it to no computation).
 */

import { eventYearOfMonth, endOfYearLabel } from '../capitalEventForm';
import type { CapitalEvent, CapitalPosition, CapitalStructure, FundingEvent } from '../capitalTypes';
import { POSITION_CLASS_LABELS, formFromStructure, isDebt } from '../capitalStructureForm';
import type { PositionForm } from '../capitalStructureForm';
import { formatCurrency, formatPercent } from '../format';
import { retiringName, scopeText } from '../refinanceCatalog';

export interface CapitalStackSummaryProps {
  structure: CapitalStructure;
  /** The Units a position may be scoped to, by id. */
  unitNames: Record<string, string>;
  /** True when the structure spans more than one Unit. */
  multiUnit: boolean;
}

function eventName(event: CapitalEvent): string {
  return event.label.trim() === '' ? 'Refinance' : event.label.trim();
}

function whenText(month: number): string {
  if (month === 0) {
    return 'at closing';
  }
  const year = eventYearOfMonth(month);
  return year === null ? `in model month ${month}` : `at the end of Year ${year}`;
}

function fundingText(funding: FundingEvent, events: CapitalEvent[]): string {
  const rule = funding.amount_rule;
  switch (rule.kind) {
    case 'fixed_amount':
      return `${formatCurrency(rule.amount)} ${whenText(funding.model_month)}`;
    case 'pct_of_price':
      return `${formatPercent(rule.pct)} of purchase price ${whenText(funding.model_month)}`;
    case 'pct_of_value':
      return `${formatPercent(rule.pct)} of a valuation ${whenText(funding.model_month)}`;
    case 'refinance_proceeds': {
      const event = events.find((candidate) => candidate.event_id === rule.capital_event_id);
      return event === undefined
        ? 'Sized by a capital event'
        : `Sized by “${eventName(event)}” ${whenText(funding.model_month)}`;
    }
    default:
      return '—';
  }
}

function fundingSummary(position: CapitalPosition, events: CapitalEvent[]): string {
  const [first] = position.funding;
  if (first === undefined) {
    return '—';
  }
  const text = fundingText(first, events);
  return position.funding.length === 1 ? text : `${text}; ${position.funding.length} funding events`;
}

function stated(value: string, format: (text: string) => string): string | null {
  return value.trim() === '' ? null : format(value.trim());
}

/** The position's key terms, as its editor card states them. */
function termsText(form: PositionForm | undefined): string {
  if (form === undefined) {
    return '—';
  }
  const parts = isDebt(form.positionClass)
    ? [
        stated(form.interestRate, (text) => `${text}% rate`),
        stated(form.amortization, (text) => `${text}-yr amortization`),
        stated(form.ioPeriod, (text) => (text === '0' ? 'no interest-only' : `${text}-yr interest-only`)),
        stated(form.maturityMonth, (text) => `matures month ${text}`),
      ]
    : form.positionClass === 'preferred_equity'
      ? [
          stated(form.preferredRate, (text) => `${text}% preferred`),
          stated(form.currentPayRate, (text) => `${text}% current pay`),
          stated(form.redemptionMonth, (text) => `redeems month ${text}`),
        ]
      : [];
  const shown = parts.filter((part): part is string => part !== null);
  return shown.length === 0 ? '—' : shown.join(' · ');
}

function scopeLabel(position: CapitalPosition, unitNames: Record<string, string>): string {
  return position.scope.kind === 'investment'
    ? 'Whole Investment'
    : (unitNames[position.scope.unit_id ?? ''] ?? 'Unit');
}

export function CapitalStackSummary({ structure, unitNames, multiUnit }: CapitalStackSummaryProps) {
  const events = structure.capital_events ?? [];
  const forms = Object.fromEntries(
    formFromStructure(structure).positions.map((form) => [form.positionId, form] as const),
  );
  const positionNames = Object.fromEntries(
    structure.positions.map((position) => [position.position_id, position.name] as const),
  );

  return (
    <div className="capital-stack">
      <div className="capital-stack-scroll" role="region" aria-label="Saved capital structure" tabIndex={0}>
        <table className="capital-stack-table">
          <thead>
            <tr>
              <th scope="col" className="col-text">
                Position
              </th>
              <th scope="col" className="col-num">
                Priority
              </th>
              <th scope="col" className="col-text">
                Scope
              </th>
              <th scope="col" className="col-text">
                Funding
              </th>
              <th scope="col" className="col-text">
                Key terms
              </th>
            </tr>
          </thead>
          <tbody>
            {structure.positions.map((position) => (
              <tr key={position.position_id}>
                <th scope="row" className="col-text">
                  <span className="capital-stack-name">{position.name}</span>
                  <span className="capital-stack-class">{POSITION_CLASS_LABELS[position.position_class]}</span>
                </th>
                <td className="col-num" data-label="Priority">
                  {position.priority}
                </td>
                <td className="col-text" data-label="Scope">
                  {scopeLabel(position, unitNames)}
                </td>
                <td className="col-text" data-label="Funding">
                  {fundingSummary(position, events)}
                </td>
                <td className="col-text" data-label="Key terms">
                  {termsText(forms[position.position_id])}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {events.length > 0 && (
        <ul className="capital-stack-events" aria-label="Refinances">
          {events.map((event) => {
            const repays = event.retiring
              .map((ref) => retiringName(ref, positionNames, unitNames, multiUnit))
              .join(', ');
            const year = eventYearOfMonth(event.timing.model_month);
            return (
              <li key={event.event_id} className="capital-stack-event">
                <span className="ws-tag ws-tag-linked">Refinance</span>
                <span className="capital-stack-event-name">{eventName(event)}</span>
                <span className="capital-stack-event-facts">
                  {[
                    year === null ? null : endOfYearLabel(year),
                    repays === '' ? null : `repays ${repays}`,
                    `funds ${positionNames[event.replacement_position_id] ?? 'a loan no longer in this structure'}`,
                    scopeText(event.scope, unitNames),
                  ]
                    .filter((part): part is string => part !== null)
                    .join(' · ')}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
