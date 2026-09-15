/**
 * Phase 7 Gate P7.5 -- the Strategy editor's draft, and its one boundary to
 * the wire contract.
 *
 * **Whole domains, visibly.** Each of the five domains is either *Inherit
 * Base* (no overlay) or *Strategy-specific* (an overlay stating every field of
 * the domain). A disabled domain sends nothing; an enabled one is refused
 * rather than partly sent when a field is blank. The Business Plan domain has
 * three explicit states -- Inherit Base, No Business Plan (an explicit empty
 * plan) and Custom -- held as a choice, never inferred from whether the custom
 * rows happen to be empty.
 *
 * **One section per Unit (P7.6).** A Strategy's overlays each name one Unit.
 * A Deal's Strategy has exactly one Unit -- the Deal -- and the draft holds it
 * as the one section, so the wire body is exactly the P7.5 body. A visible
 * Investment's Strategy holds one section per member Unit, every Unit in every
 * Strategy (there is no Unit selection), and each section's domains are that
 * Unit's own: inherited from *its* saved Base, or replaced whole.
 *
 * **Prefill is convenience, not linkage.** Enabling a domain for the first
 * time copies that Unit's saved Deal's Base values into the draft. Once saved
 * they are the Strategy's own: a later change to Base never reaches them.
 *
 * **Conversions have one home.** Base values reach the draft through the same
 * `convert.ts` function the Underwrite form uses, rates are parsed with the
 * shipped `parsePercent`, and operating outcomes are typed and sent exactly as a
 * Scenario SET on the same target (`scenarioCatalog.ts`). The one arithmetic
 * expression here is `percentText`, the display conversion of a stored decimal
 * rate, which `decisionArchitecture.test.ts` pins.
 *
 * **Presence and parsing only.** Every rule about what a Strategy may say is the
 * backend's (P7.4, P7.6); this module only refuses what cannot be sent.
 */

import { businessPlanDraftFromInput, blankBusinessPlanDraft, prepareBusinessPlanInput } from './businessPlan';
import type { BusinessPlanDraft, BusinessPlanFieldIssue, BusinessPlanInput } from './businessPlan';
import {
  buildDetailedTermsFormValuesFromRequest,
  formatDisplayNumber,
  FormValidationError,
  parseNumber,
  parsePercent,
  parseWholeNumber,
} from './convert';
import { scenarioTargetLabel, scenarioValueToText, scenarioValueToWire } from './scenarioCatalog';
import { describeStrategyOverlay } from './strategyCatalog';
import type {
  InvestmentStrategy,
  OperatingOutcome,
  StrategyDomain,
  StrategyDraft,
  StrategyOverlay,
} from './strategyTypes';
import type { Deal } from './types';

export type BusinessPlanChoice = 'inherit' | 'none' | 'custom';

export type AcquisitionField = 'purchasePrice' | 'acquisitionCostPct';
export type FinancingField = 'ltv' | 'interestRate' | 'amortization' | 'ioPeriod' | 'financingFeePct';

export interface AcquisitionDraft extends Record<AcquisitionField, string> {
  enabled: boolean;
}

export interface FinancingDraft extends Record<FinancingField, string> {
  enabled: boolean;
}

/** One operating-outcome row as typed. `key` identifies the row for React only
 * and never reaches the backend. The operation is always SET, so it is not a
 * field. */
export interface OutcomeRowDraft {
  key: string;
  target: string;
  value: string;
}

/** One Unit's five decision domains, as typed. `unitId` is the Unit (Deal)
 * every overlay of this section names. */
export interface StrategyUnitDraft {
  unitId: string;
  acquisition: AcquisitionDraft;
  financing: FinancingDraft;
  businessPlan: { choice: BusinessPlanChoice; plan: BusinessPlanDraft };
  operatingOutcome: { enabled: boolean; rows: OutcomeRowDraft[] };
  disposition: { enabled: boolean; holdPeriod: string };
}

export interface StrategyEditorDraft {
  /** `null` for a new Strategy: the backend assigns the id, never the browser. */
  strategyId: string | null;
  name: string;
  description: string;
  /** One section per Unit, in presentation order. A Deal's Strategy has one. */
  units: StrategyUnitDraft[];
}

/** The saved Deal's Base values, as the Underwrite form shows them, and each
 * inheritable domain summarized as a saved overlay would be. */
export interface StrategyBaseValues {
  acquisition: Record<AcquisitionField, string>;
  financing: Record<FinancingField, string>;
  holdPeriod: string;
  businessPlan: BusinessPlanInput;
  summaries: Partial<Record<StrategyDomain, string>>;
}

/** The analyst's field labels, with the units they are typed in. */
export const ACQUISITION_FIELDS: readonly { key: AcquisitionField; label: string; prefix?: string; suffix?: string }[] = [
  { key: 'purchasePrice', label: 'Purchase Price', prefix: '$' },
  { key: 'acquisitionCostPct', label: 'Acquisition Costs', suffix: '%' },
];

export const FINANCING_FIELDS: readonly { key: FinancingField; label: string; suffix: string }[] = [
  { key: 'ltv', label: 'LTV', suffix: '%' },
  { key: 'interestRate', label: 'Interest Rate', suffix: '%' },
  { key: 'amortization', label: 'Amortization', suffix: 'yrs' },
  { key: 'ioPeriod', label: 'Interest-Only Period', suffix: 'yrs' },
  { key: 'financingFeePct', label: 'Financing Fee', suffix: '%' },
];

export const HOLD_PERIOD_LABEL = 'Hold Period';

/** The saved Deal's Base values for prefill, through the one wire-to-form
 * conversion the Underwrite form uses. Quick inputs and Detailed / Lease-Level
 * terms carry these fields under the same names. */
export function strategyBaseValues(deal: Deal): StrategyBaseValues | null {
  const terms = deal.terms ?? deal.inputs;
  if (terms === null) {
    return null;
  }
  const form = buildDetailedTermsFormValuesFromRequest(terms);
  const summary = (overlay: StrategyOverlay) => describeStrategyOverlay(overlay);
  return {
    summaries: {
      acquisition: summary({
        unit_id: deal.id,
        domain: 'acquisition',
        content: { purchase_price: terms.purchase_price, acquisition_cost_pct: terms.acquisition_cost_pct },
      }),
      financing: summary({
        unit_id: deal.id,
        domain: 'financing',
        content: {
          ltv: terms.ltv,
          interest_rate: terms.interest_rate,
          amortization: terms.amortization,
          io_period: terms.io_period,
          financing_fee_pct: terms.financing_fee_pct,
        },
      }),
      business_plan: summary({ unit_id: deal.id, domain: 'business_plan', content: deal.business_plan }),
      disposition: summary({ unit_id: deal.id, domain: 'disposition', content: { hold_period: terms.hold_period } }),
    },
    acquisition: { purchasePrice: form.purchasePrice, acquisitionCostPct: form.acquisitionCostPct },
    financing: {
      ltv: form.ltv,
      interestRate: form.interestRate,
      amortization: form.amortization,
      ioPeriod: form.ioPeriod,
      financingFeePct: form.financingFeePct,
    },
    holdPeriod: form.holdPeriod,
    businessPlan: deal.business_plan,
  };
}

/** One Unit whose every domain inherits Base. */
export function blankUnitDraft(unitId: string): StrategyUnitDraft {
  return {
    unitId,
    acquisition: { enabled: false, purchasePrice: '', acquisitionCostPct: '' },
    financing: {
      enabled: false,
      ltv: '',
      interestRate: '',
      amortization: '',
      ioPeriod: '',
      financingFeePct: '',
    },
    businessPlan: { choice: 'inherit', plan: blankBusinessPlanDraft() },
    operatingOutcome: { enabled: false, rows: [] },
    disposition: { enabled: false, holdPeriod: '' },
  };
}

/** A new Strategy over these Units, every domain inheriting Base. */
export function blankStrategyDraft(unitIds: readonly string[]): StrategyEditorDraft {
  return { strategyId: null, name: '', description: '', units: unitIds.map(blankUnitDraft) };
}

/** A stored decimal rate as the percentage an analyst types. Display units,
 * the `convert.ts` convention; never a financial value. */
function percentText(value: number): string {
  return formatDisplayNumber(value * 100);
}

/** One Unit's saved overlays as its section of the draft, every overlay
 * restored exactly as stated. */
function unitDraftFrom(
  unitId: string,
  overlays: readonly StrategyOverlay[],
  nextRowKey: () => string,
): StrategyUnitDraft {
  const unit = blankUnitDraft(unitId);
  for (const overlay of overlays) {
    switch (overlay.domain) {
      case 'acquisition':
        unit.acquisition = {
          enabled: true,
          purchasePrice: formatDisplayNumber(overlay.content.purchase_price),
          acquisitionCostPct: percentText(overlay.content.acquisition_cost_pct),
        };
        break;
      case 'financing':
        unit.financing = {
          enabled: true,
          ltv: percentText(overlay.content.ltv),
          interestRate: percentText(overlay.content.interest_rate),
          amortization: formatDisplayNumber(overlay.content.amortization),
          ioPeriod: formatDisplayNumber(overlay.content.io_period),
          financingFeePct: percentText(overlay.content.financing_fee_pct),
        };
        break;
      case 'business_plan': {
        const isEmpty =
          overlay.content.capital_items.length === 0 && overlay.content.owner_expense_items.length === 0;
        unit.businessPlan = {
          choice: isEmpty ? 'none' : 'custom',
          plan: businessPlanDraftFromInput(overlay.content),
        };
        break;
      }
      case 'operating_outcome':
        unit.operatingOutcome = {
          enabled: true,
          rows: overlay.content.outcomes.map((outcome) => ({
            key: nextRowKey(),
            target: outcome.target,
            value: scenarioValueToText(outcome.target, 'set', outcome.value),
          })),
        };
        break;
      case 'disposition':
        unit.disposition = { enabled: true, holdPeriod: formatDisplayNumber(overlay.content.hold_period) };
        break;
    }
  }
  return unit;
}

/** A saved Strategy as the editor's draft: one section per Unit, each Unit's
 * overlays restored onto its own section. A stored empty plan is the No
 * Business Plan choice: the two are the same contract. An overlay naming a Unit
 * the caller did not list keeps a section of its own rather than being dropped
 * on the next save. */
export function draftFromStrategy(
  record: InvestmentStrategy,
  unitIds: readonly string[],
  nextRowKey: () => string,
): StrategyEditorDraft {
  const ids = [...unitIds];
  for (const overlay of record.strategy.overlays) {
    if (!ids.includes(overlay.unit_id)) {
      ids.push(overlay.unit_id);
    }
  }
  return {
    strategyId: record.strategy.strategy_id,
    name: record.strategy.name,
    description: record.strategy.description ?? '',
    units: ids.map((unitId) =>
      unitDraftFrom(
        unitId,
        record.strategy.overlays.filter((overlay) => overlay.unit_id === unitId),
        nextRowKey,
      ),
    ),
  };
}

/** Whether one Unit's section states any economic assumption. */
export function unitHasEconomicContent(unit: StrategyUnitDraft): boolean {
  return (
    unit.acquisition.enabled ||
    unit.financing.enabled ||
    unit.businessPlan.choice !== 'inherit' ||
    unit.operatingOutcome.enabled ||
    unit.disposition.enabled
  );
}

/** Whether the draft states any economic assumption on any Unit. A Strategy
 * that states none is valid; it resolves to Base. */
export function draftHasEconomicContent(draft: StrategyEditorDraft): boolean {
  return draft.units.some(unitHasEconomicContent);
}

/** Whether making ``domain`` strategy-specific on this Unit must first copy in
 * the Unit's saved Base values: the domain is inherited now and holds nothing
 * typed. A domain that already holds explicit values -- a reopened Strategy, or
 * values kept from an earlier enable -- needs no Base. For the Business Plan
 * this is the Inherit Base -> Custom transition, which starts from a copy of the
 * Base plan; No Business Plan is an explicit empty plan and needs no Base. */
export function domainNeedsBase(unit: StrategyUnitDraft, domain: StrategyDomain): boolean {
  switch (domain) {
    case 'acquisition':
      return (
        !unit.acquisition.enabled &&
        unit.acquisition.purchasePrice === '' &&
        unit.acquisition.acquisitionCostPct === ''
      );
    case 'financing': {
      const loan = unit.financing;
      return (
        !loan.enabled &&
        loan.ltv === '' &&
        loan.interestRate === '' &&
        loan.amortization === '' &&
        loan.ioPeriod === '' &&
        loan.financingFeePct === ''
      );
    }
    case 'business_plan':
      return unit.businessPlan.choice === 'inherit';
    case 'operating_outcome':
      return false;
    case 'disposition':
      return !unit.disposition.enabled && unit.disposition.holdPeriod === '';
  }
}

/** What one Unit's section owns of a refusal: the domains it names, and its
 * Business Plan rows, placed as the one Business Plan editor places them. */
export interface StrategyUnitFeedback {
  byDomain: Partial<Record<StrategyDomain, string[]>>;
  planIssues: BusinessPlanFieldIssue[];
}

/** Why a save did not happen. `general` holds what no Unit domain owns;
 * `byUnit` what one Unit's section owns; `byRow` what one outcome row owns
 * (row keys are unique across Units). Backend messages keep the backend's
 * words. */
export interface StrategyEditorFeedback {
  message: string;
  general: string[];
  byUnit: Record<string, StrategyUnitFeedback>;
  byRow: Record<string, string[]>;
}

/** One Unit's share of the feedback, created on first use. */
export function unitFeedbackOf(feedback: StrategyEditorFeedback, unitId: string): StrategyUnitFeedback {
  return (feedback.byUnit[unitId] ??= { byDomain: {}, planIssues: [] });
}

export interface BuiltStrategyRequest {
  draft: StrategyDraft;
  /** Each Unit's plan the request carries, when it carries one: backend plan
   * issues are placed against exactly these. */
  submittedPlans: Record<string, BusinessPlanInput>;
}

/** The editor as a Strategy body, or every presence and parsing problem that
 * stops it being sent. Each Unit's overlays name that Unit. */
export function buildStrategyRequest(
  editor: StrategyEditorDraft,
): BuiltStrategyRequest | { feedback: StrategyEditorFeedback } {
  const feedback: StrategyEditorFeedback = {
    message: 'Complete the highlighted fields before saving.',
    general: [],
    byUnit: {},
    byRow: {},
  };

  if (editor.name.trim() === '') {
    feedback.general.push('Enter a strategy name.');
  }

  const overlays: StrategyOverlay[] = [];
  const submittedPlans: Record<string, BusinessPlanInput> = {};

  for (const unit of editor.units) {
    const unitId = unit.unitId;
    const report = (domain: StrategyDomain, message: string) => {
      (unitFeedbackOf(feedback, unitId).byDomain[domain] ??= []).push(message);
    };
    const read = <T>(domain: StrategyDomain, parse: () => T): T | null => {
      try {
        return parse();
      } catch (error) {
        if (!(error instanceof FormValidationError)) {
          throw error;
        }
        report(domain, error.message);
        return null;
      }
    };

    if (unit.acquisition.enabled) {
      const purchasePrice = read('acquisition', () => parseNumber('Purchase Price', unit.acquisition.purchasePrice));
      const costs = read('acquisition', () => parsePercent('Acquisition Costs', unit.acquisition.acquisitionCostPct));
      if (purchasePrice !== null && costs !== null) {
        overlays.push({
          unit_id: unitId,
          domain: 'acquisition',
          content: { purchase_price: purchasePrice, acquisition_cost_pct: costs },
        });
      }
    }

    if (unit.financing.enabled) {
      const loan = unit.financing;
      const ltv = read('financing', () => parsePercent('LTV', loan.ltv));
      const rate = read('financing', () => parsePercent('Interest Rate', loan.interestRate));
      const amortization = read('financing', () => parseWholeNumber('Amortization', loan.amortization));
      const io = read('financing', () => parseWholeNumber('Interest-Only Period', loan.ioPeriod));
      const fee = read('financing', () => parsePercent('Financing Fee', loan.financingFeePct));
      if (ltv !== null && rate !== null && amortization !== null && io !== null && fee !== null) {
        overlays.push({
          unit_id: unitId,
          domain: 'financing',
          content: { ltv, interest_rate: rate, amortization, io_period: io, financing_fee_pct: fee },
        });
      }
    }

    switch (unit.businessPlan.choice) {
      case 'inherit':
        break;
      case 'none':
        submittedPlans[unitId] = { capital_items: [], owner_expense_items: [] };
        overlays.push({ unit_id: unitId, domain: 'business_plan', content: submittedPlans[unitId] });
        break;
      case 'custom': {
        const prepared = prepareBusinessPlanInput(unit.businessPlan.plan);
        if (prepared.ok) {
          submittedPlans[unitId] = prepared.plan;
          overlays.push({ unit_id: unitId, domain: 'business_plan', content: prepared.plan });
        } else {
          unitFeedbackOf(feedback, unitId).planIssues = prepared.issues;
          report('business_plan', 'Complete the highlighted Business Plan rows.');
        }
        break;
      }
    }

    if (unit.operatingOutcome.enabled) {
      if (unit.operatingOutcome.rows.length === 0) {
        report('operating_outcome', 'Add an operating assumption, or return this domain to Inherit Base.');
      }
      const outcomes: OperatingOutcome[] = [];
      for (const row of unit.operatingOutcome.rows) {
        if (row.target === '') {
          feedback.byRow[row.key] = ['Choose an assumption.'];
          continue;
        }
        try {
          outcomes.push({
            target: row.target,
            operation: 'set',
            value: scenarioValueToWire(row.target, 'set', row.value, `${scenarioTargetLabel(row.target)} value`),
          });
        } catch (error) {
          if (!(error instanceof FormValidationError)) {
            throw error;
          }
          feedback.byRow[row.key] = [error.message];
        }
      }
      if (outcomes.length > 0 && outcomes.length === unit.operatingOutcome.rows.length) {
        overlays.push({ unit_id: unitId, domain: 'operating_outcome', content: { outcomes } });
      }
    }

    if (unit.disposition.enabled) {
      const hold = read('disposition', () => parseWholeNumber(HOLD_PERIOD_LABEL, unit.disposition.holdPeriod));
      if (hold !== null) {
        overlays.push({ unit_id: unitId, domain: 'disposition', content: { hold_period: hold } });
      }
    }
  }

  if (
    feedback.general.length > 0 ||
    Object.keys(feedback.byUnit).length > 0 ||
    Object.keys(feedback.byRow).length > 0
  ) {
    return { feedback };
  }
  return {
    draft: {
      name: editor.name,
      description: editor.description.trim() === '' ? null : editor.description,
      overlays,
    },
    submittedPlans,
  };
}
