/**
 * Phase 7 Gate P7.6 -- how a visible Investment reads to an analyst.
 *
 * Presentation only: the words for each Unit Kind and transaction cost
 * category, how a Unit is identified on screen, the analyst's reading of a
 * backend refusal, and the Investment's own copy. Nothing here computes a
 * figure. A Deal's stored purchase price and hold are *read* off the contract
 * its mode populates -- never summed, never derived.
 *
 * **A Deal is one Underwriting Unit; an Investment is one transaction over one
 * or more of them.** The Deal keeps its underwriting; the Investment adds
 * structure. The copy here says so wherever the two meet.
 *
 * Unit Kind is reporting metadata. It is shown, and never decides anything.
 */

import type { DecisionMatrixCopy } from './decisionMatrix';
import type { InvestmentIssue, InvestmentVariantIssue, TransactionCostCategory, UnitKind } from './investmentTypes';
import { readableIssueMessage } from './issueText';
import { assertNeverMode, operatingModeLabel } from './operatingMode';
import type { Deal, OperatingMode } from './types';

// =============================================================================
// Reporting vocabulary
// =============================================================================

export const UNIT_KIND_OPTIONS: readonly { value: UnitKind; label: string }[] = [
  { value: 'property', label: 'Property' },
  { value: 'component', label: 'Component' },
  { value: 'phase', label: 'Phase' },
];

export function unitKindLabel(kind: string): string {
  return UNIT_KIND_OPTIONS.find((option) => option.value === kind)?.label ?? kind;
}

// prettier-ignore
export const UNIT_KIND_NOTE =
  'Unit Kind is an organizational and reporting classification only. It changes no calculation; Phase does not start a development model.';

export const TRANSACTION_COST_CATEGORY_OPTIONS: readonly { value: TransactionCostCategory; label: string }[] = [
  { value: 'acquisition_fee', label: 'Acquisition Fee' },
  { value: 'due_diligence', label: 'Due Diligence' },
  { value: 'legal', label: 'Legal' },
  { value: 'portfolio_transaction_cost', label: 'Portfolio Transaction Cost' },
  { value: 'other', label: 'Other' },
];

export function transactionCostCategoryLabel(category: string): string {
  return TRANSACTION_COST_CATEGORY_OPTIONS.find((option) => option.value === category)?.label ?? category;
}

/** P7.6 supports one transaction-cost timing: closing (model month 0). */
export const CLOSING_TIMING_LABEL = 'Closing';

// =============================================================================
// A Deal's stored assumptions -- read, never derived
// =============================================================================

/** The Deal's own stored purchase price, from whichever contract its mode
 * populates -- the `DealLibraryPanel` rule. Never a sum, never a fallback. */
export function storedPurchasePrice(deal: Deal): number | null {
  switch (deal.operating_mode) {
    case 'quick':
      return deal.inputs?.purchase_price ?? null;
    case 'detailed':
      return deal.terms?.purchase_price ?? null;
    case 'lease_level':
      return deal.terms?.purchase_price ?? null;
    default:
      return assertNeverMode(deal.operating_mode);
  }
}

/** The Deal's own stored hold period, read the same way. */
export function storedHoldPeriod(deal: Deal): number | null {
  switch (deal.operating_mode) {
    case 'quick':
      return deal.inputs?.hold_period ?? null;
    case 'detailed':
      return deal.terms?.hold_period ?? null;
    case 'lease_level':
      return deal.terms?.hold_period ?? null;
    default:
      return assertNeverMode(deal.operating_mode);
  }
}

// =============================================================================
// The decision scope of a visible Investment
// =============================================================================

/** One Unit as the Strategy, Scenario and Matrix tools see it: the Deal's id,
 * its name, the Investment's label for it, its operating mode, and the save
 * its underwriting is at (its `updated_at`), which keys that Unit's Base
 * prefill. */
export interface DecisionUnit {
  unitId: string;
  dealName: string;
  label: string | null;
  operatingMode: OperatingMode;
  savedAt: string | null;
}

/** A visible Investment's decision scope. Its Strategies and Scenarios live on
 * the Investment-scoped routes; `stateToken` names the saved economic state the
 * Units and the Investment are at, so a Decision Matrix run against an older
 * state is never shown as current. */
export interface InvestmentDecisionScope {
  investmentId: string;
  units: readonly DecisionUnit[];
  stateToken: string;
}

/** The name a Unit is shown by: its Deal's name, with the Investment's label
 * beside it when there is one. */
export function unitDisplayName(unit: { dealName: string; label: string | null }): string {
  return unit.label === null || unit.label.trim() === '' ? unit.dealName : `${unit.dealName} (${unit.label})`;
}

/** The line under a Unit's name: its label and its operating mode. */
export function unitMeta(unit: { label: string | null; operatingMode: OperatingMode }): string {
  const mode = operatingModeLabel(unit.operatingMode);
  return unit.label === null || unit.label.trim() === '' ? mode : `${unit.label} · ${mode}`;
}

/** Each Unit's id, mapped to the name an analyst knows it by. */
export function unitNames(units: readonly DecisionUnit[]): Record<string, string> {
  return Object.fromEntries(units.map((unit) => [unit.unitId, unitDisplayName(unit)]));
}

/** A backend message with every Unit id it quotes replaced by the Unit's name,
 * and its numbers shown as an analyst reads them (`readableIssueMessage`).
 * Presentation only: the backend's words are otherwise kept exactly. */
export function withUnitNames(message: string, names: Readonly<Record<string, string>>): string {
  let text = message;
  for (const [unitId, name] of Object.entries(names)) {
    if (unitId !== '') {
      text = text.split(unitId).join(name);
    }
  }
  return readableIssueMessage(text);
}

/** The element-id namespace of a decision workspace: its Risk views, its
 * Strategy and Scenario managers and editors, its Decision Matrix. A Deal's
 * keeps the ids it has always had; a visible Investment's are prefixed. The
 * Investment's decision tools stay mounted, hidden, while one of its Units --
 * or any other Deal -- is open, so an open draft survives the trip, and the
 * namespace keeps the two workspaces from sharing an id. Stable, never random. */
export function decisionIdScope(isInvestment: boolean): string {
  return isInvestment ? 'investment-' : '';
}

// =============================================================================
// Refusals, in the analyst's words
// =============================================================================

/** The analyst's reading of the Investment rules a backend refusal names. The
 * backend's own message is always shown beneath it. */
const ISSUE_LEADS: Readonly<Record<string, string>> = {
  allocation_mismatch:
    'Unit purchase-price allocations do not reconcile to the Investment transaction price.',
  hold_period_mismatch: 'All Units in one Investment variant must use the same hold period.',
  analysis_start_date_mismatch: 'Lease-Level Units must share the same analysis start date.',
};

export function investmentIssueLead(code: string): string | null {
  return ISSUE_LEADS[code] ?? null;
}

/** One refusal as it is shown: the Unit it concerns by name, the analyst's
 * reading of the rule, and the backend's message with Unit ids named. */
export interface InvestmentIssueText {
  unit: string | null;
  lead: string | null;
  message: string;
}

export function describeInvestmentIssue(
  issue: InvestmentIssue | InvestmentVariantIssue,
  names: Readonly<Record<string, string>>,
): InvestmentIssueText {
  return {
    unit: issue.unit_id === null ? null : (names[issue.unit_id] ?? null),
    lead: investmentIssueLead(issue.code),
    message: withUnitNames(issue.message, names),
  };
}

// =============================================================================
// The Investment's copy
// =============================================================================

export const INVESTMENT_LABEL = 'Investment';

/** Recent Investments in the sidebar: a short shortcut list; the Investment
 * Library holds them all. */
export const RECENT_INVESTMENT_LIMIT = 3;

// prettier-ignore
export const TRANSACTION_PRICE_NOTE =
  'Transaction Price is the negotiated price for the whole Investment. It is used to reconcile and report: each Unit is underwritten at its own purchase price, and the backend requires the Units to reconcile to this price within $0.01.';

// prettier-ignore
export const ALLOCATED_PRICE_NOTE =
  'Allocated Purchase Price is the Units’ own underwriting prices combined by the backend; it is the price the cash flows use. Transaction Price is reconciliation and reporting only.';

// prettier-ignore
export const INVESTMENT_BUSINESS_PLAN_NOTE =
  'Investment-level shared Project Capital and Owner Expenses, applied in addition to each Unit’s own Business Plan. They are owner uses of the Investment and never change any Unit’s NOI.';

// prettier-ignore
export const TRANSACTION_COST_NOTE =
  'Investment transaction costs are equity-funded closing uses of the whole transaction. They are not financing fees, Project Capital or Owner Expenses.';

// prettier-ignore
export const OCCUPANCY_NOT_REPORTED =
  'Year-End Physical Occupancy is not reported for this Investment.';

// prettier-ignore
export const INVESTMENT_DIRTY_MESSAGE =
  'Save or cancel the Investment changes before running analysis or changing strategies and scenarios.';

// prettier-ignore
export const INVESTMENT_ANALYSIS_STALE_MESSAGE =
  'The Investment or one of its Units changed after this analysis ran. Run Base Analysis to update it.';

// prettier-ignore
export const INVESTMENT_ANALYSIS_DIRTY_MESSAGE =
  'The Investment has unsaved changes. Save them, then run Base Analysis.';

/** What leaving the open Investment for another would discard, worded for the
 * confirmation -- or `null` when nothing would be lost. An open Strategy or
 * Scenario editor is an unsaved draft. */
export function investmentLeaveWarning(unsaved: {
  details: boolean;
  strategyDraft: boolean;
  scenarioDraft: boolean;
  /** P7.8B: an open Capital Structure editor is an unsaved draft too. */
  capitalStructureDraft?: boolean;
}): string | null {
  const parts: string[] = [];
  if (unsaved.details) {
    parts.push('unsaved Investment changes');
  }
  if (unsaved.strategyDraft) {
    parts.push('an unsaved Strategy draft');
  }
  if (unsaved.scenarioDraft) {
    parts.push('an unsaved Scenario draft');
  }
  if (unsaved.capitalStructureDraft === true) {
    parts.push('an unsaved Capital Structure draft');
  }
  const last = parts.pop();
  if (last === undefined) {
    return null;
  }
  const what = parts.length === 0 ? last : `${parts.join(', ')} and ${last}`;
  const discarded = unsaved.details || parts.length > 0 ? 'them' : 'it';
  return `You have ${what}. Leaving will discard ${discarded}.`;
}

// prettier-ignore
export const DELETE_INVESTMENT_CONSEQUENCES =
  'Deleting this Investment releases its Units as standalone Deals. It does not delete the Deals or their underwriting. The Investment’s Business Plan, transaction costs, strategies and scenarios are deleted.';

// prettier-ignore
export const REMOVE_UNIT_CONSEQUENCES =
  'Removing this Unit releases its Deal as a standalone Deal, unchanged. State the Investment’s resulting transaction price: the remaining Units must reconcile to it. Nothing is subtracted for you.';

// prettier-ignore
export const LAST_UNIT_MESSAGE =
  'An Investment always holds at least one Unit. Delete the Investment to release its last Unit.';

// prettier-ignore
export const UNIT_UNDERWRITING_NOTE =
  'Each Unit is a Deal with its own underwriting. Open Underwriting to change it; the Investment holds the structure.';

// prettier-ignore
export const INVESTMENT_BASE_STRATEGY_DESCRIPTION =
  'The saved Investment and each Unit’s saved underwriting. Edit them on Overview and in each Unit.';

// prettier-ignore
export const INVESTMENT_STRATEGY_SUBTITLE =
  'Alternative decisions across the Units: bid, financing, business plan, operating outcome and hold. Each Unit’s domains inherit its Base or are replaced whole. Compare them in the Decision Matrix.';

// prettier-ignore
export const INVESTMENT_SCENARIO_SUBTITLE =
  'Named Downside, Upside or other views of the market, overriding selected assumptions of chosen Units. Compare them in the Decision Matrix.';

// prettier-ignore
export const UNIT_OF_INVESTMENT_NOTICE =
  'This deal is a Unit of a visible Investment. Its strategies, scenarios and decision matrix are managed on the Investment.';

/** The Decision Matrix's words for a visible Investment. */
export const INVESTMENT_MATRIX_COPY: DecisionMatrixCopy = {
  subtitle:
    'Each strategy (what you choose) under each scenario (what may happen). Every cell runs each Unit through the deterministic engine and consolidates the Investment.',
  unsaved: 'Save this Investment before comparing strategies and scenarios.',
  dirty: 'The Investment has unsaved changes. Save them, then Refresh Matrix.',
  stale:
    'The Investment, a Unit, or the strategies or scenarios changed after this matrix ran. Refresh Matrix to update it.',
  blocked: INVESTMENT_DIRTY_MESSAGE,
  caption:
    'Consolidated Project results of each strategy under each scenario, with the backend’s Delta vs Base, Worst Case and Range',
};
