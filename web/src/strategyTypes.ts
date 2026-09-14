/**
 * Phase 7 Gate P7.5 -- the typed wire contracts of the Strategy API.
 *
 * Mirrors, field for field, what `src/anchor/api.py` returns for the persisted
 * Strategy routes (P7.4) and the read-only Strategy target catalog (P7.5).
 * Nothing here computes, validates or resolves anything: the P7.4 validator
 * decides what a Strategy may say, and the P7.4 variant service produces every
 * number a Strategy leads to.
 *
 * **Whole domains.** Each overlay is one whole decision domain. An omitted
 * domain inherits Base; an overlay states every field of its domain. The
 * Business Plan overlay carries the D6 `BusinessPlanInput` itself -- the same
 * contract the Deal's own plan uses, never a second one -- and the empty plan
 * is a real choice ("no Business Plan"), distinct from having no overlay.
 *
 * `target` is a plain string, as in `scenarioTypes.ts`: which outcome targets
 * each mode offers is the backend's decision, read from `GET /strategy-targets`.
 */

import type { BusinessPlanInput } from './businessPlan';
import type { OperatingMode } from './types';

/** Mirrors `StrategyDomain` (P7.4), in its declaration order. */
export type StrategyDomain =
  | 'acquisition'
  | 'financing'
  | 'business_plan'
  | 'operating_outcome'
  | 'disposition';

/** Mirrors `AcquisitionChoice`: the bid package, whole. */
export interface AcquisitionChoice {
  purchase_price: number;
  acquisition_cost_pct: number;
}

/** Mirrors `FinancingChoice`: the acquisition loan, whole. */
export interface FinancingChoice {
  ltv: number;
  interest_rate: number;
  amortization: number;
  io_period: number;
  financing_fee_pct: number;
}

/** Mirrors `OperatingOutcome`. A Strategy outcome is always `set`. */
export interface OperatingOutcome {
  target: string;
  operation: 'set';
  value: number;
}

export interface OperatingOutcomeSet {
  outcomes: OperatingOutcome[];
}

/** Mirrors `DispositionChoice`. */
export interface DispositionChoice {
  hold_period: number;
}

/** Mirrors `StrategyOverlay`: one whole domain on one Unit (the Deal). */
export type StrategyOverlay =
  | { unit_id: string; domain: 'acquisition'; content: AcquisitionChoice }
  | { unit_id: string; domain: 'financing'; content: FinancingChoice }
  | { unit_id: string; domain: 'business_plan'; content: BusinessPlanInput }
  | { unit_id: string; domain: 'operating_outcome'; content: OperatingOutcomeSet }
  | { unit_id: string; domain: 'disposition'; content: DispositionChoice };

/** Mirrors the P7.4 `StrategyDefinition`. Overlays arrive in canonical order. */
export interface StrategyDefinition {
  strategy_id: string;
  name: string;
  description: string | null;
  overlays: StrategyOverlay[];
}

/** Mirrors the P7.4 `InvestmentStrategy`: one persisted Strategy and the
 * hidden Investment that owns it. */
export interface InvestmentStrategy {
  investment_id: string;
  strategy: StrategyDefinition;
  created_at: string;
  updated_at: string;
}

/** `GET /deals/{id}/strategies`. A standalone Deal reports no Investment and no
 * Strategies, and reading it creates neither. */
export interface DealStrategies {
  deal_id: string;
  investment_id: string | null;
  strategies: InvestmentStrategy[];
}

/** The body of a Strategy create or update: exactly the three keys the backend
 * accepts. */
export interface StrategyDraft {
  name: string;
  description: string | null;
  overlays: StrategyOverlay[];
}

/** One entry of a structured Strategy 422: mirrors the P7.4 `StrategyIssue` as
 * `api.py` serializes it. `message` is the validator's own wording. */
export interface StrategyIssue {
  stage: 'strategy' | 'resolved_inputs';
  code: string;
  message: string;
  domain: StrategyDomain | null;
  unit_id: string | null;
  field: string | null;
  target: string | null;
  source_code: string | null;
}

/** One operating-outcome target a mode offers (`GET /strategy-targets`), with
 * the registry's own statement of its units. */
export interface StrategyTargetEntry {
  target: string;
  units: string;
}

/** The whole catalog, keyed by operating mode. */
export type StrategyTargetCatalog = Record<OperatingMode, StrategyTargetEntry[]>;
