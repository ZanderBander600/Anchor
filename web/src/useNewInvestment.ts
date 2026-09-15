/**
 * Phase 7 Gate P7.6 -- the New Investment builder.
 *
 * The analyst names the Investment, states its Transaction Price and chooses
 * one or more saved Deals as its Units, each with an optional label and a Unit
 * Kind. Nothing is proposed: the Transaction Price is never pre-filled or
 * summed from the Deals' prices; the backend's $0.01 reconciliation decides,
 * and its refusal is shown near the price.
 *
 * **One parent per Deal.** A Deal that already has Strategies or Scenarios owns
 * a hidden one-unit Investment. Choosing it makes that hidden Investment the
 * visible one, by promotion -- the same Investment id, its Strategies and
 * Scenarios kept exactly -- never a second parent and never a copy. Whether a
 * Deal has one is read from the Deal's own Strategy and Scenario lists (read
 * only; nothing is created). A Deal the backend says belongs elsewhere is
 * refused by the backend, and its words are shown; nothing is worked around.
 */

import { useState } from 'react';
import {
  createVisibleInvestment,
  InvestmentApiError,
  listDealScenarios,
  listDealStrategies,
  promoteHiddenInvestment,
} from './api';
import { emptyBusinessPlanInput } from './businessPlan';
import { FormValidationError } from './convert';
import { parseStatedPrice, TRANSACTION_PRICE_LABEL } from './investmentForm';
import type { InvestmentCreateRequest, InvestmentIssue, UnitKind, VisibleInvestment } from './investmentTypes';
import type { Deal } from './types';

export interface NewUnitSelection {
  dealId: string;
  label: string;
  kind: UnitKind;
}

/** What is known about a chosen Deal's existing decision set. */
export type DealDiscovery =
  | { status: 'checking' }
  | { status: 'standalone' }
  | { status: 'hidden'; investmentId: string; strategyCount: number; scenarioCount: number }
  | { status: 'unavailable'; message: string };

export interface NewInvestmentFeedback {
  message: string;
  name: string[];
  price: InvestmentIssue[];
  units: InvestmentIssue[];
  general: InvestmentIssue[];
}

function localIssue(message: string): InvestmentIssue {
  return { code: 'incomplete', message, unit_id: null, field: null, source_code: null };
}

function emptyFeedback(message: string): NewInvestmentFeedback {
  return { message, name: [], price: [], units: [], general: [] };
}

export function useNewInvestment({
  onCreated,
}: {
  onCreated: (investment: VisibleInvestment) => void;
}) {
  const [name, setName] = useState('');
  const [price, setPrice] = useState('');
  const [selection, setSelection] = useState<NewUnitSelection[]>([]);
  const [discovery, setDiscovery] = useState<Record<string, DealDiscovery>>({});
  const [feedback, setFeedback] = useState<NewInvestmentFeedback | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  /** Reads -- never creates -- the Deal's hidden Investment, if it has one. */
  function discover(deal: Deal) {
    setDiscovery((current) => ({ ...current, [deal.id]: { status: 'checking' } }));
    Promise.all([listDealStrategies(deal.id), listDealScenarios(deal.id)]).then(
      ([strategies, scenarios]) => {
        const investmentId = strategies.investment_id ?? scenarios.investment_id;
        setDiscovery((current) => ({
          ...current,
          [deal.id]:
            investmentId === null
              ? { status: 'standalone' }
              : {
                  status: 'hidden',
                  investmentId,
                  strategyCount: strategies.strategies.length,
                  scenarioCount: scenarios.scenarios.length,
                },
        }));
      },
      (error: unknown) =>
        setDiscovery((current) => ({
          ...current,
          [deal.id]: {
            status: 'unavailable',
            message: error instanceof Error ? error.message : 'This deal could not be checked.',
          },
        })),
    );
  }

  const isChecking = selection.some((chosen) => discovery[chosen.dealId]?.status === 'checking');

  async function create() {
    if (isCreating || isChecking) {
      return;
    }
    const local = emptyFeedback('Complete the highlighted fields before creating the investment.');
    if (name.trim() === '') {
      local.name.push('Enter an investment name.');
    }
    let transactionPrice: number | null = null;
    try {
      transactionPrice = parseStatedPrice(price, TRANSACTION_PRICE_LABEL);
    } catch (error) {
      if (!(error instanceof FormValidationError)) {
        throw error;
      }
      local.price.push(localIssue(error.message));
    }
    if (selection.length === 0) {
      local.units.push(localIssue('Choose at least one deal as a unit.'));
    }
    if (transactionPrice === null || local.name.length > 0 || local.units.length > 0) {
      setFeedback(local);
      return;
    }
    const request: InvestmentCreateRequest = {
      name: name.trim(),
      transaction_price: transactionPrice,
      units: selection.map((chosen) => ({
        unit_id: chosen.dealId,
        label: chosen.label.trim() === '' ? null : chosen.label.trim(),
        unit_kind: chosen.kind,
      })),
      business_plan: emptyBusinessPlanInput(),
      transaction_costs: [],
    };
    // A chosen Deal's hidden Investment becomes this one, by promotion. If
    // more than one chosen Deal has one, the backend refuses the others by
    // name: a Deal is never a Unit of two Investments.
    const wrapper = selection
      .map((chosen) => discovery[chosen.dealId])
      .find((found): found is Extract<DealDiscovery, { status: 'hidden' }> => found?.status === 'hidden');
    setIsCreating(true);
    setFeedback(null);
    try {
      const created =
        wrapper === undefined
          ? await createVisibleInvestment(request)
          : await promoteHiddenInvestment(wrapper.investmentId, request);
      onCreated(created);
    } catch (error) {
      const refused = emptyFeedback(
        'The investment was not created. The backend refused it for these reasons:',
      );
      if (error instanceof InvestmentApiError && error.investmentIssues.length > 0) {
        for (const issue of error.investmentIssues) {
          if (issue.field === 'transaction_price' || issue.code === 'allocation_mismatch') {
            refused.price.push(issue);
          } else if (issue.field === 'name') {
            refused.name.push(issue.message);
          } else if (issue.unit_id !== null || (issue.field ?? '').startsWith('units')) {
            refused.units.push(issue);
          } else {
            refused.general.push(issue);
          }
        }
      } else if (error instanceof InvestmentApiError) {
        refused.general.push(...error.reasons.map(localIssue));
      } else {
        refused.general.push(localIssue(error instanceof Error ? error.message : 'The investment was not created.'));
      }
      setFeedback(refused);
    } finally {
      setIsCreating(false);
    }
  }

  return {
    name,
    price,
    selection,
    discovery,
    feedback,
    isCreating,
    isChecking,
    setName,
    setPrice,
    isSelected: (dealId: string) => selection.some((chosen) => chosen.dealId === dealId),
    toggle: (deal: Deal) => {
      if (selection.some((chosen) => chosen.dealId === deal.id)) {
        setSelection((current) => current.filter((chosen) => chosen.dealId !== deal.id));
        return;
      }
      setSelection((current) => [...current, { dealId: deal.id, label: '', kind: 'property' }]);
      if (discovery[deal.id] === undefined || discovery[deal.id].status === 'unavailable') {
        discover(deal);
      }
    },
    setLabel: (dealId: string, label: string) =>
      setSelection((current) => current.map((chosen) => (chosen.dealId === dealId ? { ...chosen, label } : chosen))),
    setKind: (dealId: string, kind: UnitKind) =>
      setSelection((current) => current.map((chosen) => (chosen.dealId === dealId ? { ...chosen, kind } : chosen))),
    create,
  };
}

export type NewInvestmentState = ReturnType<typeof useNewInvestment>;
