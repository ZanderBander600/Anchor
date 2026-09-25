/**
 * Phase 7 Gate P7.8B -- the Capital Structure editor's form model.
 *
 * The analyst edits strings; the backend receives the P7.7 contract. This
 * module is the one conversion between them, in both directions, exactly as
 * `convert.ts` is for the assumption fields -- and it reuses `convert.ts`'s own
 * parsers, so "what a percentage means on screen" is answered once in this
 * product.
 *
 * **No financial arithmetic.** The only numbers touched here are display scale:
 * a rate is typed as `12.5` and sent as `0.125`, the same conversion every
 * assumption field already makes. Nothing is summed, sized, amortized or
 * derived; every funded amount, return and metric comes from the backend.
 *
 * **No default is invented.** A new claim-bearing position starts with its
 * shortfall resolution unselected, and a new preferred position starts with no
 * accrual convention: the analyst states them, because the engine refuses to
 * assume either (P-14, FR-4).
 *
 * **Identity is class and scope (P-8).** Changing either is a different
 * economic instrument, so `withClassOrScope` mints a new `position_id` rather
 * than quietly redefining the one the Decision Matrix addresses. Changing a
 * rate, an amount, a priority, a fee or a name keeps it.
 */

import { formatDisplayNumber, parseNumber, parsePercent, parseWholeNumber } from './convert';
import {
  capitalEventsOf,
  eventFormsOf,
  eventFundingOf,
  feeMonthOf,
  isEventProceeds,
} from './capitalEventForm';
import type { CapitalEventForm } from './capitalEventForm';
import type {
  CapitalPosition,
  CapitalStructure,
  FundingAmountRule,
  PositionClass,
  PositionScope,
  PositionTerms,
  ShortfallResolution,
} from './capitalTypes';

/** The funding shapes P7.8 executes. `pct_of_value` is not authored here: it
 * arrives with valuation timepoints, and the backend refuses it meanwhile.
 *
 * `capital_event` (Refinance V1 Stage 3) marks a position funded by a capital
 * event rather than at closing. It carries no amount: the event's own module,
 * `capitalEventForm.ts`, states its funding and its fee month. */
export type FundingRuleKind = 'fixed_amount' | 'pct_of_price' | 'capital_event';

/** One position as the editor holds it: every field a string, so a half-typed
 * number is never silently committed as a different one. */
export interface PositionForm {
  positionId: string;
  name: string;
  positionClass: PositionClass;
  /** `''` until the analyst selects one. Claim-bearing positions require it. */
  shortfallResolution: ShortfallResolution | '';
  scopeKind: 'unit' | 'investment';
  scopeUnitId: string | null;
  priority: string;
  fundingKind: FundingRuleKind;
  /** The dollars of a fixed funding, or the percentage of price. */
  fundingAmount: string;
  fundingPct: string;
  /** Debt only. */
  interestRate: string;
  amortization: string;
  ioPeriod: string;
  maturityMonth: string;
  /** One closing fee; blank means none. */
  feeAmount: string;
  feeDescription: string;
  /** Preferred only. */
  preferredRate: string;
  currentPayRate: string;
  accrualPermitted: boolean;
  accrualConvention: 'simple' | 'annual_compound' | '';
  redemptionMonth: string;
}

export interface CapitalStructureForm {
  positions: PositionForm[];
  /** Refinance V1 Stage 3: the structure's capital events, authored by
   * `capitalEventForm.ts` and read through its `formEvents`. Absent or empty
   * for a structure with none. */
  events?: CapitalEventForm[];
}

export const EMPTY_FORM: CapitalStructureForm = { positions: [], events: [] };

/** Whether the class carries a contractual claim -- and therefore funding,
 * terms and an explicit shortfall resolution. Common equity names the residual
 * and carries none of them. */
export function isClaimBearing(positionClass: PositionClass): boolean {
  return positionClass !== 'common_equity';
}

export function isDebt(positionClass: PositionClass): boolean {
  return positionClass === 'senior_debt' || positionClass === 'mezzanine_debt';
}

export const POSITION_CLASS_LABELS: Readonly<Record<PositionClass, string>> = {
  senior_debt: 'Senior Debt',
  mezzanine_debt: 'Mezzanine Debt',
  preferred_equity: 'Preferred Equity',
  common_equity: 'Common Equity Marker',
};

export const SHORTFALL_RESOLUTION_LABELS: Readonly<Record<ShortfallResolution, string>> = {
  common_equity_contribution: 'Common Equity Contribution',
  unresolved: 'Unresolved',
};

export const ACCRUAL_CONVENTION_LABELS: Readonly<Record<'simple' | 'annual_compound', string>> = {
  simple: 'Simple',
  annual_compound: 'Annual Compound',
};

/** The next free id of a family: `mezzanine-1`, `mezzanine-2`, ... Stable and
 * readable, and never random, so a draft reloaded from the server keeps the
 * identity the analyst has already compared positions by. */
export function nextPositionId(form: CapitalStructureForm, prefix: string): string {
  const taken = new Set(form.positions.map((position) => position.positionId));
  for (let index = 1; ; index += 1) {
    const candidate = `${prefix}-${index}`;
    if (!taken.has(candidate)) {
      return candidate;
    }
  }
}

const ID_PREFIXES: Readonly<Record<PositionClass, string>> = {
  senior_debt: 'senior',
  mezzanine_debt: 'mezzanine',
  preferred_equity: 'preferred',
  common_equity: 'common-equity',
};

/** A new position of ``positionClass``, with nothing assumed: no resolution, no
 * accrual convention, and no funding amount. */
export function newPosition(
  form: CapitalStructureForm,
  positionClass: PositionClass,
  scope: { kind: 'unit' | 'investment'; unitId: string | null },
): PositionForm {
  return {
    positionId: nextPositionId(form, ID_PREFIXES[positionClass]),
    name: POSITION_CLASS_LABELS[positionClass],
    positionClass,
    shortfallResolution: '',
    scopeKind: scope.kind,
    scopeUnitId: scope.kind === 'unit' ? scope.unitId : null,
    priority: '',
    fundingKind: 'fixed_amount',
    fundingAmount: '',
    fundingPct: '',
    interestRate: '',
    amortization: '',
    ioPeriod: '',
    maturityMonth: '',
    feeAmount: '',
    feeDescription: 'Origination fee',
    preferredRate: '',
    currentPayRate: '',
    accrualPermitted: false,
    accrualConvention: '',
    redemptionMonth: '',
  };
}

/** A position whose class or scope changed: a different economic instrument, so
 * it takes a new `position_id` (P-8). Everything else the analyst typed is
 * kept, because retyping a rate is not what changing a scope means. */
export function withClassOrScope(
  form: CapitalStructureForm,
  position: PositionForm,
  change: {
    positionClass?: PositionClass;
    scopeKind?: 'unit' | 'investment';
    scopeUnitId?: string | null;
  },
): PositionForm {
  const positionClass = change.positionClass ?? position.positionClass;
  const scopeKind = change.scopeKind ?? position.scopeKind;
  const scopeUnitId = scopeKind === 'investment' ? null : (change.scopeUnitId ?? position.scopeUnitId);
  const identityMoved =
    positionClass !== position.positionClass ||
    scopeKind !== position.scopeKind ||
    scopeUnitId !== position.scopeUnitId;
  return {
    ...position,
    positionClass,
    scopeKind,
    scopeUnitId,
    positionId: identityMoved
      ? nextPositionId(form, ID_PREFIXES[positionClass])
      : position.positionId,
    name:
      position.name === POSITION_CLASS_LABELS[position.positionClass]
        ? POSITION_CLASS_LABELS[positionClass]
        : position.name,
  };
}

// =============================================================================
// The saved structure -> the form
// =============================================================================

function fundingFormOf(position: CapitalPosition): Pick<PositionForm, 'fundingKind' | 'fundingAmount' | 'fundingPct'> {
  const rule: FundingAmountRule | undefined = position.funding[0]?.amount_rule;
  if (isEventProceeds(rule)) {
    return { fundingKind: 'capital_event', fundingAmount: '', fundingPct: '' };
  }
  if (rule === undefined || rule.kind === 'pct_of_value') {
    // A valuation-based rule cannot be authored here. It is shown as blank and
    // the editor refuses to save over it, rather than silently rewriting it.
    return { fundingKind: 'fixed_amount', fundingAmount: '', fundingPct: '' };
  }
  if (rule.kind === 'pct_of_price') {
    return { fundingKind: 'pct_of_price', fundingAmount: '', fundingPct: formatDisplayNumber(rule.pct * 100) };
  }
  return { fundingKind: 'fixed_amount', fundingAmount: formatDisplayNumber(rule.amount), fundingPct: '' };
}

function termsFormOf(terms: PositionTerms | null): Partial<PositionForm> {
  if (terms === null) {
    return {};
  }
  if (terms.kind === 'debt') {
    const fee = terms.fees[0];
    return {
      interestRate: formatDisplayNumber(terms.interest_rate * 100),
      amortization: formatDisplayNumber(terms.amortization),
      ioPeriod: formatDisplayNumber(terms.io_period),
      maturityMonth: formatDisplayNumber(terms.maturity_month),
      feeAmount: fee === undefined ? '' : formatDisplayNumber(fee.amount),
      feeDescription: fee === undefined ? 'Origination fee' : fee.description,
    };
  }
  return {
    preferredRate: formatDisplayNumber(terms.preferred_rate * 100),
    currentPayRate: formatDisplayNumber(terms.current_pay_rate * 100),
    accrualPermitted: terms.accrual_permitted,
    accrualConvention: terms.accrual_convention ?? '',
    redemptionMonth: formatDisplayNumber(terms.redemption_month),
  };
}

/** The saved structure as the editor holds it. */
export function formFromStructure(structure: CapitalStructure): CapitalStructureForm {
  return {
    positions: structure.positions.map((position) => {
      const blank = newPosition(
        EMPTY_FORM,
        position.position_class,
        { kind: position.scope.kind, unitId: position.scope.unit_id },
      );
      return {
        ...blank,
        ...fundingFormOf(position),
        ...termsFormOf(position.terms),
        positionId: position.position_id,
        name: position.name,
        priority: formatDisplayNumber(position.priority),
        shortfallResolution: position.shortfall_resolution ?? '',
      };
    }),
    events: eventFormsOf(structure),
  };
}

// =============================================================================
// The form -> the request
// =============================================================================

function scopeOf(position: PositionForm): PositionScope {
  return position.scopeKind === 'investment'
    ? { kind: 'investment', unit_id: null }
    : { kind: 'unit', unit_id: position.scopeUnitId };
}

function fundingOf(form: CapitalStructureForm, position: PositionForm, where: string): CapitalPosition['funding'] {
  if (!isClaimBearing(position.positionClass)) {
    return [];
  }
  if (position.fundingKind === 'capital_event') {
    return eventFundingOf(form, position);
  }
  const amountRule: FundingAmountRule =
    position.fundingKind === 'pct_of_price'
      ? { kind: 'pct_of_price', pct: parsePercent(`${where} funding (% of price)`, position.fundingPct) }
      : { kind: 'fixed_amount', amount: parseNumber(`${where} funding amount`, position.fundingAmount) };
  return [
    {
      event_id: `${position.positionId}-funding`,
      model_month: 0,
      sequence: 1,
      amount_rule: amountRule,
    },
  ];
}

function termsOf(form: CapitalStructureForm, position: PositionForm, where: string): PositionTerms | null {
  if (!isClaimBearing(position.positionClass)) {
    return null;
  }
  if (isDebt(position.positionClass)) {
    const rate = parsePercent(`${where} interest rate`, position.interestRate);
    const fees =
      position.feeAmount.trim() === ''
        ? []
        : [
            {
              fee_id: `${position.positionId}-fee`,
              description: position.feeDescription.trim() === '' ? 'Closing fee' : position.feeDescription,
              amount: parseNumber(`${where} closing fee`, position.feeAmount),
              model_month: feeMonthOf(form, position),
              sequence: 2,
            },
          ];
    return {
      kind: 'debt',
      interest_rate: rate,
      amortization: parseWholeNumber(`${where} amortization`, position.amortization),
      io_period: parseWholeNumber(`${where} interest-only period`, position.ioPeriod),
      maturity_month: parseWholeNumber(`${where} legal maturity`, position.maturityMonth),
      fees,
      // P7.8 debt is cash pay: the whole coupon is current pay and nothing
      // accrues. The editor states the approved contract; it invents no split.
      current_pay_rate: rate,
      pik_rate: 0,
    };
  }
  return {
    kind: 'preferred_equity',
    preferred_rate: parsePercent(`${where} preferred rate`, position.preferredRate),
    current_pay_rate: parsePercent(`${where} current pay rate`, position.currentPayRate),
    accrual_permitted: position.accrualPermitted,
    accrual_convention: position.accrualPermitted
      ? (position.accrualConvention === '' ? null : position.accrualConvention)
      : null,
    redemption_month: parseWholeNumber(`${where} redemption month`, position.redemptionMonth),
  };
}

/** The form as the request the backend validates.
 *
 * Client-side parsing only: a blank or unparsable number is refused here with
 * the field's name, exactly as the assumption form does. Every *domain* rule --
 * priority within a scope, one identity per position, a resolution that must be
 * stated, what the executor can schedule -- belongs to the backend, and its
 * refusals are shown as they arrive. */
export function structureFromForm(form: CapitalStructureForm): CapitalStructure {
  const capitalEvents = capitalEventsOf(form);
  const structure: CapitalStructure = {
    positions: form.positions.map((position) => {
      const where = position.name.trim() === '' ? position.positionId : position.name.trim();
      return {
        position_id: position.positionId,
        name: position.name,
        position_class: position.positionClass,
        priority: parseWholeNumber(`${where} priority`, position.priority),
        scope: scopeOf(position),
        funding: fundingOf(form, position, where),
        terms: termsOf(form, position, where),
        shortfall_resolution: isClaimBearing(position.positionClass)
          ? (position.shortfallResolution === '' ? null : position.shortfallResolution)
          : null,
      };
    }),
  };
  // A structure with no capital event is sent exactly as it always was: the
  // member is absent, never an empty array.
  return capitalEvents === undefined ? structure : { ...structure, capital_events: capitalEvents };
}

/** One choice the analyst must still state, and the position it belongs to.
 *
 * `positionId` and `choice` together identify it, because two positions may
 * carry the same display name -- two preferred positions both named "Preferred
 * Equity" is the ordinary case -- and one position may be missing both a
 * resolution and a convention at once. The message alone is not unique, so it
 * is not an identity. */
export interface UnstatedChoice {
  positionId: string;
  choice: 'shortfall_resolution' | 'accrual_convention';
  message: string;
}

/** Whether the form still holds something the analyst must state before the
 * backend can accept it: a claim-bearing position with no resolution, or a
 * preferred position that accrues with no convention named. Presentation only
 * -- the backend refuses both anyway, and this only lets the editor say so
 * before the round trip. */
export function unstatedChoices(form: CapitalStructureForm): UnstatedChoice[] {
  const missing: UnstatedChoice[] = [];
  for (const position of form.positions) {
    const name = position.name.trim() === '' ? position.positionId : position.name.trim();
    if (isClaimBearing(position.positionClass) && position.shortfallResolution === '') {
      missing.push({
        positionId: position.positionId,
        choice: 'shortfall_resolution',
        message: `${name}: select how a shortfall is resolved.`,
      });
    }
    if (
      position.positionClass === 'preferred_equity' &&
      position.accrualPermitted &&
      position.accrualConvention === ''
    ) {
      missing.push({
        positionId: position.positionId,
        choice: 'accrual_convention',
        message: `${name}: select an accrual convention.`,
      });
    }
  }
  return missing;
}
