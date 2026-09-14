/**
 * Phase 7 Gate P7.5 -- how a Strategy reads to an analyst.
 *
 * Presentation only. The P7.4 domains and the operating-outcome whitelist are
 * the backend's; this module names the five domains, says what each one
 * replaces, and summarizes a saved overlay in a line. Operating outcomes reuse
 * the Scenario target labels and value presentation (`scenarioCatalog.ts`), so
 * one assumption has one name wherever it appears.
 *
 * Nothing here computes a figure. Every number shown is an overlay value the
 * analyst stated, formatted by the shared formatters.
 */

import { formatCurrency, formatPercent } from './format';
import { scenarioTargetLabel, scenarioValueFormat, scenarioValueToText } from './scenarioCatalog';
import type { StrategyDefinition, StrategyDomain, StrategyOverlay } from './strategyTypes';

export interface StrategyDomainPresentation {
  domain: StrategyDomain;
  label: string;
  /** What an enabled domain replaces, whole. */
  replaces: string;
}

/** The five decision domains, in the backend's canonical order. */
export const STRATEGY_DOMAINS: readonly StrategyDomainPresentation[] = [
  {
    domain: 'acquisition',
    label: 'Acquisition',
    replaces: 'Purchase Price and Acquisition Costs.',
  },
  {
    domain: 'financing',
    label: 'Financing',
    replaces: 'The acquisition loan: LTV, Interest Rate, Amortization, Interest-Only Period and Financing Fee.',
  },
  {
    domain: 'business_plan',
    label: 'Business Plan',
    replaces: 'The whole Business Plan: every Project Capital and Owner Expense item.',
  },
  {
    domain: 'operating_outcome',
    label: 'Operating Outcome',
    replaces: 'Selected operating assumptions, each set to the value this strategy underwrites.',
  },
  {
    domain: 'disposition',
    label: 'Disposition',
    replaces: 'Hold Period.',
  },
];

export function strategyDomainLabel(domain: string): string {
  return STRATEGY_DOMAINS.find((entry) => entry.domain === domain)?.label ?? domain;
}

/** The domains a saved Strategy replaces, in canonical order. Empty means it
 * inherits Base everywhere. */
export function strategyDomainsReplaced(strategy: StrategyDefinition): string[] {
  const present = new Set(strategy.overlays.map((overlay) => overlay.domain));
  return STRATEGY_DOMAINS.filter((entry) => present.has(entry.domain)).map((entry) => entry.label);
}

function itemCount(count: number, singular: string, plural: string): string {
  return count === 1 ? `1 ${singular}` : `${count} ${plural}`;
}

/** One saved overlay as a short line, e.g. "$9,000,000 · 2.00% acquisition
 * costs". */
export function describeStrategyOverlay(overlay: StrategyOverlay): string {
  switch (overlay.domain) {
    case 'acquisition':
      return `${formatCurrency(overlay.content.purchase_price)} · ${formatPercent(overlay.content.acquisition_cost_pct)} acquisition costs`;
    case 'financing': {
      const loan = overlay.content;
      return [
        `${formatPercent(loan.ltv)} LTV`,
        `${formatPercent(loan.interest_rate)} rate`,
        `${loan.amortization}-yr amortization`,
        `${loan.io_period}-yr interest-only`,
        `${formatPercent(loan.financing_fee_pct)} fee`,
      ].join(' · ');
    }
    case 'business_plan': {
      const plan = overlay.content;
      if (plan.capital_items.length === 0 && plan.owner_expense_items.length === 0) {
        return 'No Business Plan';
      }
      return [
        'Custom Business Plan',
        itemCount(plan.capital_items.length, 'capital item', 'capital items'),
        itemCount(plan.owner_expense_items.length, 'owner expense', 'owner expenses'),
      ].join(' · ');
    }
    case 'operating_outcome':
      return overlay.content.outcomes
        .map((outcome) => {
          const { prefix, suffix } = scenarioValueFormat(outcome.target, 'set', undefined);
          const figure = scenarioValueToText(outcome.target, 'set', outcome.value);
          return `${scenarioTargetLabel(outcome.target)} ${prefix ?? ''}${figure}${suffix ?? ''}`;
        })
        .join(' · ');
    case 'disposition':
      return `${overlay.content.hold_period}-year hold`;
  }
}

/** Said beside a Strategy with no economic overlay. Not an error: such a
 * Strategy is valid, and its variants legitimately fingerprint as Base. */
export const STRATEGY_RESOLVES_TO_BASE_MESSAGE =
  'This Strategy currently resolves to the same economic assumptions as Base.';

/** Why Strategies cannot be changed while the deal is unsaved or dirty. */
export const SAVE_DEAL_BEFORE_STRATEGIES_MESSAGE = 'Save this deal before adding strategies.';

export const SAVE_BEFORE_STRATEGIES_MESSAGE =
  'Save base underwriting changes before editing strategies or running the decision matrix.';
