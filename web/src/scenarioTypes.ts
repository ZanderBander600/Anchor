/**
 * Phase 7 Gate P7.3 -- the typed wire contracts of the Scenario API.
 *
 * Mirrors, field for field, what `src/anchor/api.py` returns for the persisted
 * Scenario routes (P7.2) and for the read-only target catalog (P7.3). Nothing
 * here computes, validates or resolves anything. The P7.1 registry and validator
 * decide what a Scenario may say, and the P7.2 variant service produces every
 * number a Scenario shows.
 *
 * `target` is a plain string on purpose. Which targets exist, in which operating
 * mode, with which operations, is the backend registry's decision. The UI reads
 * it at run time from `GET /scenario-targets` and never holds an enumeration of
 * its own that could drift from it.
 *
 * Every result a Scenario analysis returns is the mode's existing result
 * contract, unchanged: `AcquisitionResults`, `DetailedAcquisitionResults` or
 * `LeaseLevelAcquisitionResults`. There is no second representation of it.
 */

import type { LeaseLevelAcquisitionResults } from './leaseLevelTypes';
import type { AcquisitionResults, DetailedAcquisitionResults, OperatingMode } from './types';

/** Mirrors `ScenarioOperation` (P7.1): the four ratified operations, as sent. */
export type ScenarioOperation = 'set' | 'add' | 'scale' | 'cap_at';

/** One override, exactly as persisted. `value` is on the wire scale: the
 * decimal a rate is stored as, dollars for a rent, the multiplier for a SCALE. */
export interface ScenarioOverride {
  unit_id: string;
  target: string;
  operation: ScenarioOperation;
  value: number;
}

/** Mirrors the P7.1 `ScenarioDefinition`. Overrides arrive in the backend's
 * canonical order. */
export interface ScenarioDefinition {
  scenario_id: string;
  name: string;
  description: string | null;
  overrides: ScenarioOverride[];
}

/** Mirrors the P7.2 `InvestmentScenario`: one persisted Scenario and the hidden
 * Investment that owns it. */
export interface InvestmentScenario {
  investment_id: string;
  scenario: ScenarioDefinition;
  created_at: string;
  updated_at: string;
}

/** `GET /deals/{id}/scenarios`. A standalone Deal reports no Investment and no
 * Scenarios, and reading it creates neither. */
export interface DealScenarios {
  deal_id: string;
  investment_id: string | null;
  scenarios: InvestmentScenario[];
}

/** The body of a Scenario create or update: exactly the three keys the backend
 * accepts, and no others. */
export interface ScenarioDraft {
  name: string;
  description: string | null;
  overrides: ScenarioOverride[];
}

/** Mirrors `VariantCacheStatus` (P7.2). Operational metadata, never investment
 * information: the UI carries it for diagnostics and does not feature it. */
export type VariantCacheStatus = 'hit' | 'miss' | 'bypassed';

/** `GET /investments/{id}/scenarios/{id}/fingerprint`. */
export interface ScenarioVariantFingerprint {
  investment_id: string;
  scenario_id: string;
  unit_id: string;
  operating_mode: OperatingMode;
  source_fingerprint: string;
}

/** `POST /investments/{id}/scenarios/{id}/analysis`. `results` is the unit's
 * own mode's result contract, exactly as `POST /analyze` returns it. */
export interface ScenarioVariantAnalysis {
  investment_id: string;
  scenario_id: string;
  unit_id: string;
  operating_mode: OperatingMode;
  source_fingerprint: string;
  cache_status: VariantCacheStatus;
  results: AcquisitionResults | DetailedAcquisitionResults | LeaseLevelAcquisitionResults;
}

/** One entry of a structured Scenario 422: mirrors the P7.1 `ScenarioIssue` as
 * `api.py` serializes it. `message` is the validator's own wording. */
export interface ScenarioIssue {
  stage: 'scenario' | 'resolved_inputs';
  code: string;
  message: string;
  target: string | null;
  unit_id: string | null;
  field: string | null;
  source_code: string | null;
}

/** One target the registry offers in one operating mode (`GET
 * /scenario-targets`): its token, its operation whitelist in the registry's
 * order, and the registry's own statement of its units. */
export interface ScenarioTargetEntry {
  target: string;
  allowed_operations: ScenarioOperation[];
  units: string;
}

/** The whole catalog, keyed by operating mode. */
export type ScenarioTargetCatalog = Record<OperatingMode, ScenarioTargetEntry[]>;
