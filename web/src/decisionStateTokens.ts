/**
 * Phase 7 Gate P7.9 Stage 3 -- what each Decision Matrix perspective is current
 * against.
 *
 * A matrix report is "current" only while the saved economic state it ran
 * against is unchanged (DC-7). Which state that is differs by perspective,
 * because the three perspectives sit at different depths of one dependency
 * chain (§1.3):
 *
 * ```
 * PROJECT  ->  COMMON EQUITY (capital structure)  ->  PARTNERSHIP
 * ```
 *
 * Downstream edits never invalidate upstream results (P-4). So the Project
 * matrix reads neither of the root-overlay domains, the Position matrix reads
 * the Capital Structure and not the Partnership, and the Partner matrix reads
 * everything the Position matrix does plus the Partnership.
 *
 * **This module exists to make that boundary one thing rather than three.**
 * These are pure functions over already-saved contracts: they serialize, and
 * they compute nothing. They live outside the React component that uses them so
 * the boundary can be tested and guarded directly, without rendering a
 * workspace to find out what a token contains.
 */

import type { CapitalStructure } from './capitalTypes';
import type { Partnership } from './partnershipTypes';
import type { InvestmentScenario } from './scenarioTypes';
import type { InvestmentStrategy, InvestmentStrategyOverlay, StrategyDomain } from './strategyTypes';

/** One Strategy's root overlays in a single domain, exactly as it stated them.
 *
 * This filter is the **P-4 boundary between the two downstream matrices**. A
 * root-overlay set is not one economic input: it carries a Capital Structure
 * replacement and a Partnership replacement, and those sit at different depths
 * of the chain. Feeding the whole set to both matrices makes a
 * Partnership-only edit invalidate a Position report that cannot have moved,
 * because no Position cell identity includes a Partnership.
 *
 * The three Partnership states stay distinguishable through it, because each
 * produces a different array: an **absent** overlay gives `[]`, an **explicit
 * "no Partnership"** gives one entry whose `content` is `null`, and an
 * **authored replacement** gives one entry carrying the contract. Those three
 * serialize differently, so none is ever mistaken for another. */
export function rootOverlaysOfDomain(
  strategy: { root_overlays?: InvestmentStrategyOverlay[] },
  domain: StrategyDomain,
): InvestmentStrategyOverlay[] {
  return (strategy.root_overlays ?? []).filter((overlay) => overlay.domain === domain);
}

/** The saved economic state a **Position** matrix belongs to.
 *
 * A structured cell is invalidated by the Base Capital Structure it ran, by a
 * Strategy's Unit overlays, by the Strategy's own `capital_structure` root
 * overlay, and by a Scenario's overrides. It is deliberately **not** moved by a
 * Strategy's `partnership` root overlay, nor by the Base Partnership: a
 * Partnership allocates the Common Equity a structure leaves behind, so it
 * cannot change what any position funds, earns or is owed (P-4). A rename moves
 * none of them. */
export function positionStateTokenOf(input: {
  scopeId: string | null;
  scopeToken: string | null;
  strategies: readonly InvestmentStrategy[];
  scenarios: readonly InvestmentScenario[];
  baseCapitalStructure: CapitalStructure;
}): string {
  return JSON.stringify([
    input.scopeId,
    input.scopeToken,
    input.strategies.map((record) => [
      record.strategy.strategy_id,
      record.strategy.overlays,
      rootOverlaysOfDomain(record.strategy, 'capital_structure'),
    ]),
    input.scenarios.map((record) => [record.scenario.scenario_id, record.scenario.overrides]),
    input.baseCapitalStructure.positions,
  ]);
}

/** The saved economic state a **Partner** matrix belongs to: the complete
 * Position state, plus the two things that state a Partnership -- each
 * Strategy's own `partnership` root overlay, and the Investment's Base
 * Partnership. Everything that moves a Position cell moves a Partner cell too,
 * because a Partner cell is a Position cell's Common Equity allocated. */
export function partnerStateTokenOf(input: {
  positionStateToken: string;
  strategies: readonly InvestmentStrategy[];
  basePartnership: Partnership | null;
}): string {
  return JSON.stringify([
    input.positionStateToken,
    input.strategies.map((record) => [
      record.strategy.strategy_id,
      rootOverlaysOfDomain(record.strategy, 'partnership'),
    ]),
    input.basePartnership,
  ]);
}
