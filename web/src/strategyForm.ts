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
 * **Prefill is convenience, not linkage.** Enabling a domain for the first
 * time copies the saved Deal's Base values into the draft. Once saved they are
 * the Strategy's own: a later change to Base never reaches them.
 *
 * **Conversions have one home.** Base values reach the draft through the same
 * `convert.ts` function the Underwrite form uses, rates are parsed with the
 * shipped `parsePercent`, and operating outcomes are typed and sent exactly as a
 * Scenario SET on the same target (`scenarioCatalog.ts`). The one arithmetic
 * expression here is `percentText`, the display conversion of a stored decimal
 * rate, which `decisionArchitecture.test.ts` pins.
 *
 * **Presence and parsing only.** Every rule about what a Strategy may say is the
 * backend's (P7.4); this module only refuses what cannot be sent.
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

export interface StrategyEditorDraft {
  /** `null` for a new Strategy: the backend assigns the id, never the browser. */
  strategyId: string | null;
  name: string;
  description: string;
  acquisition: AcquisitionDraft;
  financing: FinancingDraft;
  businessPlan: { choice: BusinessPlanChoice; plan: BusinessPlanDraft };
  operatingOutcome: { enabled: boolean; rows: OutcomeRowDraft[] };
  disposition: { enabled: boolean; holdPeriod: string };
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

export function blankStrategyDraft(): StrategyEditorDraft {
  return {
    strategyId: null,
    name: '',
    description: '',
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

/** A stored decimal rate as the percentage an analyst types. Display units,
 * the `convert.ts` convention; never a financial value. */
function percentText(value: number): string {
  return formatDisplayNumber(value * 100);
}

/** A saved Strategy as the editor's draft, every overlay restored exactly as
 * stated. A stored empty plan is the No Business Plan choice: the two are the
 * same contract. */
export function draftFromStrategy(record: InvestmentStrategy, nextRowKey: () => string): StrategyEditorDraft {
  const blank = blankStrategyDraft();
  let { acquisition, financing, businessPlan, operatingOutcome, disposition } = blank;
  for (const overlay of record.strategy.overlays) {
    switch (overlay.domain) {
      case 'acquisition':
        acquisition = {
          enabled: true,
          purchasePrice: formatDisplayNumber(overlay.content.purchase_price),
          acquisitionCostPct: percentText(overlay.content.acquisition_cost_pct),
        };
        break;
      case 'financing':
        financing = {
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
        businessPlan = {
          choice: isEmpty ? 'none' : 'custom',
          plan: businessPlanDraftFromInput(overlay.content),
        };
        break;
      }
      case 'operating_outcome':
        operatingOutcome = {
          enabled: true,
          rows: overlay.content.outcomes.map((outcome) => ({
            key: nextRowKey(),
            target: outcome.target,
            value: scenarioValueToText(outcome.target, 'set', outcome.value),
          })),
        };
        break;
      case 'disposition':
        disposition = { enabled: true, holdPeriod: formatDisplayNumber(overlay.content.hold_period) };
        break;
    }
  }
  return {
    strategyId: record.strategy.strategy_id,
    name: record.strategy.name,
    description: record.strategy.description ?? '',
    acquisition,
    financing,
    businessPlan,
    operatingOutcome,
    disposition,
  };
}

/** Whether the draft states any economic assumption. A Strategy that states
 * none is valid; it resolves to Base. */
export function draftHasEconomicContent(draft: StrategyEditorDraft): boolean {
  return (
    draft.acquisition.enabled ||
    draft.financing.enabled ||
    draft.businessPlan.choice !== 'inherit' ||
    draft.operatingOutcome.enabled ||
    draft.disposition.enabled
  );
}

/** Why a save did not happen. `general` holds what no domain owns;
 * `byDomain` what one domain owns; `byRow` what one outcome row owns;
 * `planIssues` the Business Plan rows, placed as the one Business Plan editor
 * places them. Backend messages keep the backend's words. */
export interface StrategyEditorFeedback {
  message: string;
  general: string[];
  byDomain: Partial<Record<StrategyDomain, string[]>>;
  byRow: Record<string, string[]>;
  planIssues: BusinessPlanFieldIssue[];
}

export interface BuiltStrategyRequest {
  draft: StrategyDraft;
  /** The plan the request carries, when it carries one: backend plan issues
   * are placed against exactly this. */
  submittedPlan: BusinessPlanInput | null;
}

/** The editor as a Strategy body, or every presence and parsing problem that
 * stops it being sent. */
export function buildStrategyRequest(
  editor: StrategyEditorDraft,
  unitId: string,
): BuiltStrategyRequest | { feedback: StrategyEditorFeedback } {
  const general: string[] = [];
  const byDomain: Partial<Record<StrategyDomain, string[]>> = {};
  const byRow: Record<string, string[]> = {};
  let planIssues: BusinessPlanFieldIssue[] = [];

  function report(domain: StrategyDomain, message: string) {
    (byDomain[domain] ??= []).push(message);
  }
  function read<T>(domain: StrategyDomain, parse: () => T): T | null {
    try {
      return parse();
    } catch (error) {
      if (!(error instanceof FormValidationError)) {
        throw error;
      }
      report(domain, error.message);
      return null;
    }
  }

  if (editor.name.trim() === '') {
    general.push('Enter a strategy name.');
  }

  const overlays: StrategyOverlay[] = [];
  let submittedPlan: BusinessPlanInput | null = null;

  if (editor.acquisition.enabled) {
    const purchasePrice = read('acquisition', () => parseNumber('Purchase Price', editor.acquisition.purchasePrice));
    const costs = read('acquisition', () => parsePercent('Acquisition Costs', editor.acquisition.acquisitionCostPct));
    if (purchasePrice !== null && costs !== null) {
      overlays.push({
        unit_id: unitId,
        domain: 'acquisition',
        content: { purchase_price: purchasePrice, acquisition_cost_pct: costs },
      });
    }
  }

  if (editor.financing.enabled) {
    const loan = editor.financing;
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

  switch (editor.businessPlan.choice) {
    case 'inherit':
      break;
    case 'none':
      submittedPlan = { capital_items: [], owner_expense_items: [] };
      overlays.push({ unit_id: unitId, domain: 'business_plan', content: submittedPlan });
      break;
    case 'custom': {
      const prepared = prepareBusinessPlanInput(editor.businessPlan.plan);
      if (prepared.ok) {
        submittedPlan = prepared.plan;
        overlays.push({ unit_id: unitId, domain: 'business_plan', content: prepared.plan });
      } else {
        planIssues = prepared.issues;
        report('business_plan', 'Complete the highlighted Business Plan rows.');
      }
      break;
    }
  }

  if (editor.operatingOutcome.enabled) {
    if (editor.operatingOutcome.rows.length === 0) {
      report('operating_outcome', 'Add an operating assumption, or return this domain to Inherit Base.');
    }
    const outcomes: OperatingOutcome[] = [];
    for (const row of editor.operatingOutcome.rows) {
      if (row.target === '') {
        byRow[row.key] = ['Choose an assumption.'];
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
        byRow[row.key] = [error.message];
      }
    }
    if (outcomes.length > 0 && outcomes.length === editor.operatingOutcome.rows.length) {
      overlays.push({ unit_id: unitId, domain: 'operating_outcome', content: { outcomes } });
    }
  }

  if (editor.disposition.enabled) {
    const hold = read('disposition', () => parseWholeNumber(HOLD_PERIOD_LABEL, editor.disposition.holdPeriod));
    if (hold !== null) {
      overlays.push({ unit_id: unitId, domain: 'disposition', content: { hold_period: hold } });
    }
  }

  if (
    general.length > 0 ||
    Object.keys(byDomain).length > 0 ||
    Object.keys(byRow).length > 0 ||
    planIssues.length > 0
  ) {
    return {
      feedback: {
        message: 'Complete the highlighted fields before saving.',
        general,
        byDomain,
        byRow,
        planIssues,
      },
    };
  }
  return {
    draft: {
      name: editor.name,
      description: editor.description.trim() === '' ? null : editor.description,
      overlays,
    },
    submittedPlan,
  };
}
