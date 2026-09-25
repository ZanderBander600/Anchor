/**
 * Refinance & Capital Events V1 Stage 3 -- the refinance editor's form model.
 *
 * The analyst edits strings; the backend receives the ratified capital-event
 * contract (`docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md` Sections 6.1 to
 * 6.7). This module is the one conversion between them, in both directions,
 * and it reuses `convert.ts`'s parsers so "what a percentage means on screen"
 * is answered once in this product.
 *
 * **No refinance arithmetic.** The only numbers touched here are display
 * scale: a maximum LTV typed as `65` is sent as `0.65` (the parser every
 * percentage field uses), and "End of Year 2" is sent as model month 24 -- the
 * contract's own `m = 12y` timing (Section 7.1), stated as a unit conversion in
 * one place, `eventMonthOfYear`. Nothing is sized, amortized, netted or
 * compared: every capacity, payoff, fee total and the net event cash come from
 * the backend (Section 12.5 rule 7).
 *
 * **No default is invented.** A new refinance starts with no year, no retiring
 * loan, no replacement, no sizing constraint and no valuation. The analyst
 * states each; the editor says what is still unstated before the round trip.
 *
 * **A valuation only while LTV is enabled.** The form keeps no valuation for a
 * DSCR-only, fixed-only or fixed-plus-DSCR event: disabling LTV drops the
 * reference, and the request never carries one without `max_ltv` (R-C; the
 * backend refuses `valuation_reference_unused`).
 *
 * **Identities are stable and never shown.** Event, cost-line and funding ids
 * are minted deterministically (`refinance-1`, `refinance-1-cost-1`) so a
 * reloaded draft keeps the identity P-8 compares by; none is ever a label.
 */

import { formatDisplayNumber, parseNumber, parsePercent, parseWholeNumber } from './convert';
import type { CapitalStructureForm, PositionForm } from './capitalStructureForm';
import type {
  CapitalEvent,
  CapitalEventProceeds,
  CapitalPosition,
  CapitalStructure,
  CapitalStructureIssue,
  FundingAmountRule,
  FundingEvent,
  PositionScope,
  RefinanceCostKind,
  RefinanceCostLine,
  RetiringPositionRef,
} from './capitalTypes';

// =============================================================================
// Timing: "End of Year N"
// =============================================================================

/** The contract's timing, `m = 12y` (Section 7.1): the one place a hold year
 * becomes a model month. A unit conversion, like a percentage's `/ 100`. */
export function eventMonthOfYear(year: number): number {
  return year * 12;
}

/** The hold years an analyst may place a refinance at the end of. Whether a
 * year is inside a particular variant's hold is decided at execution
 * (`event_outside_hold_horizon`), because a Strategy may shorten it. */
export const EVENT_YEARS: readonly number[] = Array.from({ length: 29 }, (_, index) => index + 1);

/** "End of Year N" for a model month the contract allows, or `null`. A lookup,
 * so a month is only ever named by the year it was built from. */
export function eventYearOfMonth(month: number): number | null {
  return EVENT_YEARS.find((year) => eventMonthOfYear(year) === month) ?? null;
}

export function endOfYearLabel(year: number): string {
  return `End of Year ${year}`;
}

/** "end of Year N" for a refinance the analyst has timed, or `null`. Read from
 * the typed choice as text; nothing is re-parsed. */
export function eventTimingLabel(event: { year: string }): string | null {
  return event.year === '' ? null : `end of Year ${event.year}`;
}

// =============================================================================
// The form
// =============================================================================

/** A retiring loan as the editor selects it: a Unit's acquisition loan, or an
 * authored debt position. The key is an option value, never shown. */
export type RetiringKey = `legacy:${string}` | `position:${string}`;

export function legacyKey(unitId: string): RetiringKey {
  return `legacy:${unitId}`;
}

export function positionKey(positionId: string): RetiringKey {
  return `position:${positionId}`;
}

function refOfKey(key: RetiringKey): RetiringPositionRef {
  return key.startsWith('legacy:')
    ? { kind: 'legacy_acquisition_loan', unit_id: key.slice('legacy:'.length) }
    : { kind: 'authored_position', position_id: key.slice('position:'.length) };
}

function keyOfRef(ref: RetiringPositionRef): RetiringKey {
  return ref.kind === 'legacy_acquisition_loan' ? legacyKey(ref.unit_id) : positionKey(ref.position_id);
}

/** One fixed-dollar event cost, every field a string. */
export interface CostLineForm {
  costId: string;
  kind: RefinanceCostKind;
  amount: string;
  /** The retiring loan a retiring-lender fee is paid to; `''` until chosen,
   * and always `''` for a third-party cost. */
  recipient: RetiringKey | '';
  description: string;
}

/** One refinance as the editor holds it. */
export interface CapitalEventForm {
  eventId: string;
  label: string;
  scopeKind: 'unit' | 'investment';
  scopeUnitId: string | null;
  /** The hold year it occurs at the end of; `''` until chosen. */
  year: string;
  retiring: RetiringKey[];
  /** The authored replacement debt position; `''` until chosen. */
  replacementPositionId: string;
  fixedCapEnabled: boolean;
  fixedCap: string;
  ltvEnabled: boolean;
  /** A percentage, typed as `65` for 65%. */
  maxLtv: string;
  /** The valuation an LTV constraint consumes; `''` until chosen, and dropped
   * whenever LTV is disabled. */
  timepointId: string;
  dscrEnabled: boolean;
  /** A coverage ratio, typed as `1.25`. */
  minDscr: string;
  costs: CostLineForm[];
}

/** The form's capital events. A form built before Refinance V1 carries none,
 * and reads as the empty set. */
export function formEvents(form: CapitalStructureForm): CapitalEventForm[] {
  return form.events ?? [];
}

export function isEventProceeds(rule: FundingAmountRule | undefined): rule is CapitalEventProceeds {
  return rule !== undefined && rule.kind === 'refinance_proceeds';
}

/** The next free refinance identity: `refinance-1`, `refinance-2`, ... */
export function nextEventId(events: readonly CapitalEventForm[]): string {
  const taken = new Set(events.map((event) => event.eventId));
  let index = 1;
  while (taken.has(`refinance-${index}`)) {
    index += 1;
  }
  return `refinance-${index}`;
}

function nextCostId(event: CapitalEventForm): string {
  const taken = new Set(event.costs.map((line) => line.costId));
  let index = 1;
  while (taken.has(`${event.eventId}-cost-${index}`)) {
    index += 1;
  }
  return `${event.eventId}-cost-${index}`;
}

/** A new refinance of `scope`, with nothing assumed. */
export function newCapitalEvent(
  events: readonly CapitalEventForm[],
  scope: { kind: 'unit' | 'investment'; unitId: string | null },
): CapitalEventForm {
  return {
    eventId: nextEventId(events),
    label: 'Refinance',
    scopeKind: scope.kind,
    scopeUnitId: scope.kind === 'unit' ? scope.unitId : null,
    year: '',
    retiring: [],
    replacementPositionId: '',
    fixedCapEnabled: false,
    fixedCap: '',
    ltvEnabled: false,
    maxLtv: '',
    timepointId: '',
    dscrEnabled: false,
    minDscr: '',
    costs: [],
  };
}

export function newCostLine(event: CapitalEventForm, kind: RefinanceCostKind): CostLineForm {
  return {
    costId: nextCostId(event),
    kind,
    amount: '',
    recipient: '',
    description: kind === 'retiring_lender_fee' ? 'Prepayment fee' : 'Legal and title',
  };
}

/** The event with LTV switched. Disabling it drops the valuation reference as
 * well as the target: a non-LTV event consumes no valuation (R-C). */
export function withLtvEnabled(event: CapitalEventForm, enabled: boolean): CapitalEventForm {
  return enabled
    ? { ...event, ltvEnabled: true }
    : { ...event, ltvEnabled: false, maxLtv: '', timepointId: '' };
}

/** The event with its retiring loans changed. A retiring-lender fee whose
 * recipient is no longer retired loses its recipient, rather than silently
 * paying a lender the event no longer repays. */
export function withRetiring(event: CapitalEventForm, retiring: RetiringKey[]): CapitalEventForm {
  const kept = new Set(retiring);
  return {
    ...event,
    retiring,
    costs: event.costs.map((line) =>
      line.recipient !== '' && !kept.has(line.recipient) ? { ...line, recipient: '' } : line,
    ),
  };
}

// =============================================================================
// The saved structure -> the form
// =============================================================================

function costFormOf(line: RefinanceCostLine): CostLineForm {
  return {
    costId: line.cost_id,
    kind: line.kind,
    amount: formatDisplayNumber(line.amount),
    recipient: line.recipient === null ? '' : keyOfRef(line.recipient),
    description: line.description,
  };
}

function eventFormOf(event: CapitalEvent): CapitalEventForm {
  const year = eventYearOfMonth(event.timing.model_month);
  return {
    eventId: event.event_id,
    label: event.label,
    scopeKind: event.scope.kind,
    scopeUnitId: event.scope.kind === 'unit' ? event.scope.unit_id : null,
    year: year === null ? '' : String(year),
    retiring: event.retiring.map(keyOfRef),
    replacementPositionId: event.replacement_position_id,
    fixedCapEnabled: event.sizing.fixed_cap !== null,
    fixedCap: event.sizing.fixed_cap === null ? '' : formatDisplayNumber(event.sizing.fixed_cap.amount),
    ltvEnabled: event.sizing.max_ltv !== null,
    maxLtv:
      event.sizing.max_ltv === null ? '' : formatDisplayNumber(event.sizing.max_ltv.max_ltv * 100),
    timepointId: event.sizing.max_ltv === null || event.valuation === null ? '' : event.valuation.timepoint_id,
    dscrEnabled: event.sizing.min_dscr !== null,
    minDscr: event.sizing.min_dscr === null ? '' : formatDisplayNumber(event.sizing.min_dscr.min_dscr),
    costs: event.costs.map(costFormOf),
  };
}

/** The saved structure's events as the editor holds them. */
export function eventFormsOf(structure: CapitalStructure): CapitalEventForm[] {
  return (structure.capital_events ?? []).map(eventFormOf);
}

/** Whether a saved position is a replacement, funded by a capital event. */
export function isEventFunded(position: CapitalPosition): boolean {
  return isEventProceeds(position.funding[0]?.amount_rule);
}

// =============================================================================
// The form -> the request
// =============================================================================

/** The refinance that funds `positionId`, if any. */
export function eventFunding(form: CapitalStructureForm, positionId: string): CapitalEventForm | undefined {
  return formEvents(form).find((event) => event.replacementPositionId === positionId);
}

function eventName(event: CapitalEventForm): string {
  return event.label.trim() === '' ? 'Refinance' : event.label.trim();
}

/** The model month of a refinance, parsed by name. */
function eventMonth(event: CapitalEventForm): number {
  return eventMonthOfYear(parseWholeNumber(`${eventName(event)} year`, event.year));
}

/** The replacement's one funding event: `RefinanceProceeds` at the event
 * month (Section 6.6). A position no refinance names states none, and the
 * backend refuses it (`orphaned_refinance_proceeds` never arises: it never
 * carries the rule). */
export function eventFundingOf(form: CapitalStructureForm, position: PositionForm): FundingEvent[] {
  const event = eventFunding(form, position.positionId);
  if (event === undefined) {
    return [];
  }
  return [
    {
      event_id: `${position.positionId}-funding`,
      model_month: eventMonth(event),
      sequence: 1,
      amount_rule: { kind: 'refinance_proceeds', capital_event_id: event.eventId },
    },
  ];
}

/** The model month a position's lender fee is paid at: the event month for a
 * replacement (its fees are replacement lender fees, Section 6.7), closing for
 * every other position. */
export function feeMonthOf(form: CapitalStructureForm, position: PositionForm): number {
  const event = eventFunding(form, position.positionId);
  return event === undefined ? 0 : eventMonth(event);
}

function scopeOf(event: CapitalEventForm): PositionScope {
  return event.scopeKind === 'investment'
    ? { kind: 'investment', unit_id: null }
    : { kind: 'unit', unit_id: event.scopeUnitId };
}

function costLineOf(event: CapitalEventForm, line: CostLineForm): RefinanceCostLine {
  const where = `${eventName(event)} ${line.kind === 'retiring_lender_fee' ? 'retiring-lender fee' : 'third-party cost'}`;
  return {
    cost_id: line.costId,
    kind: line.kind,
    amount: parseNumber(`${where} amount`, line.amount),
    recipient: line.kind === 'retiring_lender_fee' && line.recipient !== '' ? refOfKey(line.recipient) : null,
    description: line.description,
  };
}

function capitalEventOf(event: CapitalEventForm): CapitalEvent {
  const where = eventName(event);
  return {
    event_id: event.eventId,
    kind: 'refinance',
    scope: scopeOf(event),
    timing: { model_month: eventMonth(event), sequence: 1 },
    label: event.label,
    retiring: event.retiring.map(refOfKey),
    replacement_position_id: event.replacementPositionId,
    sizing: {
      fixed_cap: event.fixedCapEnabled
        ? { amount: parseNumber(`${where} fixed maximum proceeds`, event.fixedCap) }
        : null,
      max_ltv: event.ltvEnabled ? { max_ltv: parsePercent(`${where} maximum LTV`, event.maxLtv) } : null,
      min_dscr: event.dscrEnabled
        ? { min_dscr: parseNumber(`${where} minimum DSCR`, event.minDscr) }
        : null,
    },
    valuation: event.ltvEnabled && event.timepointId !== '' ? { timepoint_id: event.timepointId } : null,
    costs: event.costs.map((line) => costLineOf(event, line)),
  };
}

/** The form's events as the request, or `undefined` when there are none -- so
 * a structure with no refinance is sent exactly as it always was. */
export function capitalEventsOf(form: CapitalStructureForm): CapitalEvent[] | undefined {
  return formEvents(form).length === 0 ? undefined : formEvents(form).map(capitalEventOf);
}

// =============================================================================
// Keeping references whole while the stack is edited
// =============================================================================

/** The form after a position's identity moved (P-8: a class or scope change
 * mints a new id). Every event reference follows it, so a refinance never
 * points at an id the structure no longer holds. */
export function renamePositionReferences(
  form: CapitalStructureForm,
  from: string,
  to: string,
): CapitalStructureForm {
  if (from === to) {
    return form;
  }
  const oldKey = positionKey(from);
  const newKey = positionKey(to);
  return {
    ...form,
    events: formEvents(form).map((event) => ({
      ...event,
      replacementPositionId: event.replacementPositionId === from ? to : event.replacementPositionId,
      retiring: event.retiring.map((key) => (key === oldKey ? newKey : key)),
      costs: event.costs.map((line) => (line.recipient === oldKey ? { ...line, recipient: newKey } : line)),
    })),
  };
}

/** The events once `positionId` is removed from the stack: it is no longer a
 * replacement, a retiring loan or a fee recipient anywhere. */
export function withoutPositionReferences(
  events: readonly CapitalEventForm[],
  positionId: string,
): CapitalEventForm[] {
  const removed = positionKey(positionId);
  return events.map((event) =>
    withRetiring(
      {
        ...event,
        replacementPositionId: event.replacementPositionId === positionId ? '' : event.replacementPositionId,
      },
      event.retiring.filter((key) => key !== removed),
    ),
  );
}

// =============================================================================
// What the analyst must still state
// =============================================================================

export interface UnstatedEventChoice {
  eventId: string;
  choice: string;
  message: string;
}

/** Everything a refinance still needs before the backend could accept it,
 * said in the analyst's terms. Presentation only: the backend refuses each
 * anyway, and this only lets the editor say so before the round trip. */
export function unstatedEventChoices(form: CapitalStructureForm): UnstatedEventChoice[] {
  const missing: UnstatedEventChoice[] = [];
  for (const event of formEvents(form)) {
    const name = eventName(event);
    const push = (choice: string, message: string) => missing.push({ eventId: event.eventId, choice, message });
    if (event.year === '') {
      push('year', `${name}: select the year it occurs at the end of.`);
    }
    if (event.retiring.length === 0) {
      push('retiring', `${name}: select at least one loan it repays.`);
    }
    if (event.replacementPositionId === '') {
      push('replacement', `${name}: select or add the replacement loan.`);
    }
    if (!event.fixedCapEnabled && !event.ltvEnabled && !event.dscrEnabled) {
      push('sizing', `${name}: enable at least one sizing constraint.`);
    }
    if (event.ltvEnabled && event.timepointId === '') {
      push('valuation', `${name}: select the valuation the maximum LTV is measured against.`);
    }
    for (const line of event.costs) {
      if (line.kind === 'retiring_lender_fee' && line.recipient === '') {
        push(`recipient:${line.costId}`, `${name}: select which retiring lender receives each retiring-lender fee.`);
      }
    }
  }
  return missing;
}

// =============================================================================
// The backend's refusals, in the analyst's terms
// =============================================================================

/** The refusal codes a capital event can draw, each as an analyst sentence
 * naming the refinance by its label. The backend's own message names records
 * by their opaque ids, so it is never shown for these codes (Section 15.3). */
const EVENT_ISSUE_SENTENCES: Readonly<Record<string, (name: string) => string>> = {
  invalid_capital_event: (name) => `${name} is not complete: state its year, scope, sizing and loans.`,
  unsupported_capital_event_kind: (name) => `${name} is not a refinance; only refinances are supported.`,
  event_month_not_hold_year_end: (name) => `${name} must occur at the end of a hold year.`,
  unsupported_event_sequence: (name) => `${name}: only one refinance may occur in a scope at one time.`,
  duplicate_capital_event_id: () =>
    'Two refinance items share an identity. Remove and re-add the most recent refinance cost.',
  multiple_refinances_in_scope: () => 'Only one refinance is permitted per Unit or per Investment.',
  no_retiring_position: (name) => `${name}: select at least one loan it repays.`,
  retiring_position_not_found: (name) => `${name} repays a loan that is no longer in this capital structure.`,
  retiring_position_duplicated: (name) => `${name} lists the same retiring loan twice.`,
  retiring_position_scope_mismatch: (name) =>
    `${name} may repay only loans of its own scope: the same Unit, or the whole Investment.`,
  retiring_position_not_debt: (name) =>
    `${name} may repay only senior or mezzanine debt, and never its own replacement loan.`,
  replacement_position_not_found: (name) => `${name}: select or add the replacement loan.`,
  replacement_position_not_debt: (name) => `${name}: the replacement loan must be senior or mezzanine debt.`,
  replacement_scope_mismatch: (name) => `${name}: the replacement loan must be in the refinance's own scope.`,
  replacement_funding_mismatch: (name) =>
    `${name}: the replacement loan must be funded only by this refinance, at its event date.`,
  orphaned_refinance_proceeds: () =>
    'A loan is marked as funded by a refinance that does not name it as its replacement.',
  replacement_priority_not_successor: (name) =>
    `${name}: the replacement loan must take the priority of the most senior loan it repays (priority 1 when it repays the acquisition loan).`,
  replacement_maturity_too_early: (name) =>
    `${name}: the replacement loan must mature at least twelve months after the refinance.`,
  replacement_fee_timing: (name) => `${name}: replacement lender fees are paid at the refinance date.`,
  no_sizing_constraint: (name) => `${name}: enable at least one sizing constraint.`,
  invalid_fixed_cap: (name) => `${name}: fixed maximum proceeds must be greater than zero.`,
  invalid_max_ltv: (name) => `${name}: maximum LTV must be greater than 0% and at most 100%.`,
  invalid_min_dscr: (name) => `${name}: minimum DSCR must be greater than zero.`,
  valuation_reference_required: (name) =>
    `${name}: select the valuation the maximum LTV is measured against.`,
  valuation_reference_unused: (name) =>
    `${name} references a valuation without an LTV constraint. Only LTV sizing consumes a valuation.`,
  dscr_zero_first_year_service: (name) =>
    `${name}: DSCR sizing needs a replacement loan with first-year debt service; an interest-only loan at 0% has none.`,
  invalid_retiring_lender_fee_recipient: (name) =>
    `${name}: each retiring-lender fee must be paid to one of the loans it repays.`,
  invalid_cost_line: (name) =>
    `${name}: each cost must be a dollar amount of zero or more, and a third-party cost names no lender.`,
  investment_refinance_with_unit_debt: (name) =>
    `${name}: an Investment refinance is not supported while any Unit still carries its own debt after the refinance.`,
  unsupported_event_scope: (name) => `${name}: a whole-Investment refinance needs a visible Investment.`,
  capital_event_kind_conflict: () =>
    'This refinance conflicts with another capital structure of this Investment that uses the same identity.',
  capital_event_scope_conflict: () =>
    'This refinance conflicts with another capital structure of this Investment that uses the same identity for another scope.',
};

/** The codes this module translates. */
export function isCapitalEventIssue(issue: CapitalStructureIssue): boolean {
  return issue.code in EVENT_ISSUE_SENTENCES;
}

/** The issues with every capital-event refusal restated in the analyst's
 * terms, naming the refinance by its label -- never by an id. An issue about
 * a position rather than an event is returned exactly as it arrived. */
export function analystCapitalIssues(
  issues: CapitalStructureIssue[],
  form: CapitalStructureForm,
): CapitalStructureIssue[] {
  return issues.map((issue) => {
    const sentence = EVENT_ISSUE_SENTENCES[issue.code];
    if (sentence === undefined) {
      return issue;
    }
    const event =
      formEvents(form).find((candidate) => candidate.eventId === issue.position_id) ??
      formEvents(form).find((candidate) => candidate.replacementPositionId === issue.position_id);
    return { ...issue, message: sentence(event === undefined ? 'The refinance' : eventName(event)) };
  });
}
