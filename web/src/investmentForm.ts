/**
 * Phase 7 Gate P7.6 -- the Investment editor's drafts, and their one boundary
 * to the wire contract.
 *
 * **Presence and parsing only.** A Transaction Price, a resulting price and a
 * cost amount are parsed with the shipped `parseNumber`; the Investment
 * Business Plan goes through the one D6 boundary (`prepareBusinessPlanInput`).
 * Every rule about what an Investment may say -- the $0.01 reconciliation, the
 * common hold, the Lease-Level calendar, cost validity -- is the backend's, and
 * its refusals are shown in its own words.
 *
 * **Nothing is derived.** No price is summed, subtracted or proposed. The
 * analyst states the Transaction Price, and states the resulting price when a
 * Unit is added or removed.
 *
 * **Staleness, not arithmetic.** `investmentStateToken` names the saved
 * economic state a consolidated analysis ran against: the transaction price,
 * the Investment Business Plan, the costs' economics, and each member Deal's
 * saved underwriting. It reads no name, label, Unit Kind or presentation
 * order, so display edits never make an analysis stale.
 */

import {
  blankBusinessPlanDraft,
  businessPlanDraftFromInput,
  isSameBusinessPlanDraft,
  newBusinessPlanItemId,
  placeBusinessPlanApiIssues,
  prepareBusinessPlanInput,
} from './businessPlan';
import type { BusinessPlanApiIssue, BusinessPlanDraft, BusinessPlanFieldIssue, BusinessPlanInput } from './businessPlan';
import { formatDisplayNumber, FormValidationError, parseNumber } from './convert';
import type {
  InvestmentDetailsRequest,
  InvestmentIssue,
  InvestmentTransactionCost,
  TransactionCostCategory,
  VisibleInvestment,
} from './investmentTypes';
import type { Deal } from './types';

// =============================================================================
// The details draft
// =============================================================================

/** One transaction cost as typed. `costId` is minted once, by the one id
 * source (`businessPlan.ts`), or carried exactly as stored. */
export interface TransactionCostDraft {
  readonly costId: string;
  description: string;
  category: TransactionCostCategory;
  amount: string;
}

export interface InvestmentDetailsDraft {
  name: string;
  transactionPrice: string;
  businessPlan: BusinessPlanDraft;
  costs: TransactionCostDraft[];
}

export const TRANSACTION_PRICE_LABEL = 'Transaction Price';
export const RESULTING_PRICE_LABEL = 'Resulting Transaction Price';

export function detailsDraftFrom(investment: VisibleInvestment): InvestmentDetailsDraft {
  return {
    name: investment.name,
    transactionPrice: formatDisplayNumber(investment.transaction_price),
    businessPlan: businessPlanDraftFromInput(investment.business_plan),
    costs: investment.transaction_costs.map((cost) => ({
      costId: cost.cost_id,
      description: cost.description,
      category: cost.category,
      amount: formatDisplayNumber(cost.amount),
    })),
  };
}

export function blankDetailsDraft(): InvestmentDetailsDraft {
  return { name: '', transactionPrice: '', businessPlan: blankBusinessPlanDraft(), costs: [] };
}

export function blankCostDraft(): TransactionCostDraft {
  return { costId: newBusinessPlanItemId(), description: '', category: 'acquisition_fee', amount: '' };
}

function sameCosts(a: readonly TransactionCostDraft[], b: readonly TransactionCostDraft[]): boolean {
  return (
    a.length === b.length &&
    a.every(
      (cost, index) =>
        cost.costId === b[index].costId &&
        cost.description === b[index].description &&
        cost.category === b[index].category &&
        cost.amount === b[index].amount,
    )
  );
}

/** Whether the draft changes anything the Investment's economics read: the
 * Transaction Price, the Investment Business Plan or the transaction costs. */
export function isEconomicDraftChange(draft: InvestmentDetailsDraft, saved: InvestmentDetailsDraft): boolean {
  return (
    draft.transactionPrice !== saved.transactionPrice ||
    !isSameBusinessPlanDraft(draft.businessPlan, saved.businessPlan) ||
    !sameCosts(draft.costs, saved.costs)
  );
}

/** Whether the draft differs from what is saved at all -- the name included. */
export function isDraftChange(draft: InvestmentDetailsDraft, saved: InvestmentDetailsDraft): boolean {
  return draft.name !== saved.name || isEconomicDraftChange(draft, saved);
}

// =============================================================================
// Feedback
// =============================================================================

/** Why a details save did not happen, each finding placed where it belongs:
 * on the name, the Transaction Price, a cost row (by cost id) or a Business
 * Plan row. `general` holds what no field owns -- Unit findings included, in
 * the backend's own words. */
export interface InvestmentDetailsFeedback {
  message: string;
  general: InvestmentIssue[];
  name: string[];
  price: InvestmentIssue[];
  costs: Record<string, string[]>;
  planIssues: BusinessPlanFieldIssue[];
}

function localIssue(message: string): InvestmentIssue {
  return { code: 'incomplete', message, unit_id: null, field: null, source_code: null };
}

function emptyFeedback(message: string): InvestmentDetailsFeedback {
  return { message, general: [], name: [], price: [], costs: {}, planIssues: [] };
}

export interface BuiltDetailsRequest {
  request: InvestmentDetailsRequest;
  submittedPlan: BusinessPlanInput;
  submittedCosts: InvestmentTransactionCost[];
}

/** The draft as a details body, or every presence and parsing problem that
 * stops it being sent. */
export function buildDetailsRequest(
  draft: InvestmentDetailsDraft,
): BuiltDetailsRequest | { feedback: InvestmentDetailsFeedback } {
  const feedback = emptyFeedback('Complete the highlighted fields before saving.');
  if (draft.name.trim() === '') {
    feedback.name.push('Enter an investment name.');
  }
  let price: number | null = null;
  try {
    price = parseNumber(TRANSACTION_PRICE_LABEL, draft.transactionPrice);
  } catch (error) {
    if (!(error instanceof FormValidationError)) {
      throw error;
    }
    feedback.price.push(localIssue(error.message));
  }
  const costs: InvestmentTransactionCost[] = [];
  for (const cost of draft.costs) {
    const problems: string[] = [];
    if (cost.description.trim() === '') {
      problems.push('Enter a description.');
    }
    let amount: number | null = null;
    try {
      amount = parseNumber('Amount', cost.amount);
    } catch (error) {
      if (!(error instanceof FormValidationError)) {
        throw error;
      }
      problems.push(error.message);
    }
    if (problems.length > 0 || amount === null) {
      feedback.costs[cost.costId] = problems;
      continue;
    }
    costs.push({
      cost_id: cost.costId,
      description: cost.description.trim(),
      category: cost.category,
      amount,
      model_month: 0,
    });
  }
  const plan = prepareBusinessPlanInput(draft.businessPlan);
  if (!plan.ok) {
    feedback.planIssues = plan.issues;
  }
  if (
    price === null ||
    !plan.ok ||
    feedback.name.length > 0 ||
    Object.keys(feedback.costs).length > 0
  ) {
    return { feedback };
  }
  return {
    request: {
      name: draft.name.trim(),
      transaction_price: price,
      business_plan: plan.plan,
      transaction_costs: costs,
    },
    submittedPlan: plan.plan,
    submittedCosts: costs,
  };
}

const COST_FIELD = /^transaction_costs\[(\d+)\]/;

/** A backend refusal of a details save, placed on the fields it names. */
export function placeDetailsRefusal(
  status: number,
  investmentIssues: readonly InvestmentIssue[],
  planIssues: readonly BusinessPlanApiIssue[],
  reasons: readonly string[],
  submitted: BuiltDetailsRequest,
): InvestmentDetailsFeedback {
  const feedback = emptyFeedback(
    status === 422
      ? 'The Investment was not saved. The backend refused it for these reasons:'
      : 'The Investment was not saved.',
  );
  for (const issue of investmentIssues) {
    const costMatch = issue.field === null ? null : COST_FIELD.exec(issue.field);
    const cost =
      costMatch === null
        ? undefined
        : submitted.submittedCosts.find((_, position) => String(position) === costMatch[1]);
    if (issue.field === 'name') {
      feedback.name.push(issue.message);
    } else if (issue.field === 'transaction_price' || issue.code === 'allocation_mismatch') {
      feedback.price.push(issue);
    } else if (cost !== undefined) {
      (feedback.costs[cost.cost_id] ??= []).push(issue.message);
    } else {
      feedback.general.push(issue);
    }
  }
  feedback.planIssues = placeBusinessPlanApiIssues(planIssues, submitted.submittedPlan);
  if (investmentIssues.length === 0 && planIssues.length === 0) {
    feedback.general.push(...reasons.map(localIssue));
  }
  return feedback;
}

/** A price the analyst states -- the Investment's resulting Transaction Price
 * when a Unit is added or removed. Parsing only. */
export function parseStatedPrice(text: string, label: string = RESULTING_PRICE_LABEL): number {
  return parseNumber(label, text);
}

// =============================================================================
// The saved economic state
// =============================================================================

/** The saved economic state a consolidated analysis runs against. Unit ids
 * are strings, sorted so presentation order never reaches the token; no
 * figure is compared, ordered or computed. */
export function investmentStateToken(investment: VisibleInvestment, unitDeals: readonly Deal[]): string {
  const saves = new Map(unitDeals.map((deal) => [deal.id, deal.updated_at]));
  const units = investment.units.map((unit) => `${unit.unit_id}@${saves.get(unit.unit_id) ?? ''}`).sort();
  return JSON.stringify([
    investment.id,
    investment.transaction_price,
    investment.business_plan,
    investment.transaction_costs.map((cost) => [cost.cost_id, cost.amount, cost.model_month]),
    units,
  ]);
}
