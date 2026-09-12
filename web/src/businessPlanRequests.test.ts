/**
 * Phase 6 Gate D6.6 -- every request that carries deal state carries the plan.
 *
 * The D6.5 backend reads an absent `business_plan` as the EMPTY plan. So a
 * client function that silently dropped it would not fail loudly -- it would
 * clear a saved plan on the next write, or analyse, fingerprint or ground the
 * AI Analyst against a plan the deal does not hold. This file closes that door
 * twice over:
 *
 *   1. Behaviourally, every deal-state client function is called with a
 *      sentinel plan and the body it actually puts on the wire is read back.
 *   2. Structurally, an AST audit of `api.ts` finds every exported function
 *      whose body carries deal state and requires of each a required, typed
 *      `businessPlan` parameter and a `business_plan: businessPlan` in that same
 *      body -- and requires that set of functions to be exactly the set the
 *      behavioural table covers, so a future function cannot be added without
 *      joining both. Seeded mutants prove the audit has teeth.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import ts from 'typescript';
import * as api from './api';
import apiSourceText from './api.ts?raw';
import { referencePlan } from './businessPlanFixture';
import { withLfLineEndings } from './testSourceText';
import type { AcquisitionRequest, AcquisitionTermsRequest, DetailedOperatingInputsRequest } from './types';
import type { LeaseLevelInputsRequest } from './leaseLevelTypes';
import type {
  LeaseLevelOneWaySensitivityControls,
  LeaseLevelTwoWaySensitivityControls,
} from './leaseLevelSensitivityTypes';

const apiSource = withLfLineEndings(apiSourceText);

const PLAN = referencePlan();
const INPUTS = { purchase_price: 50_000_000 } as unknown as AcquisitionRequest;
const TERMS = { purchase_price: 30_000_000 } as unknown as AcquisitionTermsRequest;
const OPERATING = { gross_potential_rent: 800_000 } as unknown as DetailedOperatingInputsRequest;
const LEASE_LEVEL = {
  property_inputs: { analysis_start_date: '2027-01-01' },
  operating_inputs: {},
  market_leasing: {},
  suites: [],
  leases: [],
} as unknown as LeaseLevelInputsRequest;
const ONE_WAY = {
  assumption: 'exit_cap_rate',
  values: [0.06],
  metric: 'levered_irr',
} as unknown as LeaseLevelOneWaySensitivityControls;
const TWO_WAY = {
  row_assumption: 'exit_cap_rate',
  row_values: [0.06],
  column_assumption: 'purchase_price',
  column_values: [30_000_000],
  metric: 'levered_irr',
} as unknown as LeaseLevelTwoWaySensitivityControls;

/** Every client function whose request carries deal state, called with the
 * sentinel plan. Keyed by function name -- the structural audit below derives
 * the same set from `api.ts` and the two are required to match. */
const DEAL_STATE_CALLS: Record<string, () => Promise<unknown>> = {
  analyzeAcquisition: () => api.analyzeAcquisition(INPUTS, PLAN),
  analyzeDetailedAcquisition: () => api.analyzeDetailedAcquisition(TERMS, OPERATING, PLAN),
  analyzeLeaseLevelAcquisition: () => api.analyzeLeaseLevelAcquisition(TERMS, LEASE_LEVEL, PLAN),
  fetchSensitivityPresets: () => api.fetchSensitivityPresets(INPUTS, PLAN),
  fetchDetailedSensitivityPresets: () =>
    api.fetchDetailedSensitivityPresets(TERMS, OPERATING, PLAN),
  runLeaseLevelOneWaySensitivity: () =>
    api.runLeaseLevelOneWaySensitivity(TERMS, LEASE_LEVEL, PLAN, ONE_WAY),
  runLeaseLevelTwoWaySensitivity: () =>
    api.runLeaseLevelTwoWaySensitivity(TERMS, LEASE_LEVEL, PLAN, TWO_WAY),
  fetchBreakEvenAnalysis: () =>
    api.fetchBreakEvenAnalysis(INPUTS, PLAN, 0.1, 1.5, 1.2, 'levered_irr'),
  fetchDetailedBreakEvenAnalysis: () =>
    api.fetchDetailedBreakEvenAnalysis(TERMS, OPERATING, PLAN, 0.1, 1.5, 1.2, 'levered_irr'),
  fetchAIAnalysis: () => api.fetchAIAnalysis(INPUTS, PLAN, 0.1, 1.5, 1.2, 'levered_irr', null),
  fetchDetailedAIAnalysis: () =>
    api.fetchDetailedAIAnalysis(TERMS, OPERATING, PLAN, 0.1, 1.5, 1.2, 'levered_irr', null),
  fetchLeaseLevelAIAnalysis: () =>
    api.fetchLeaseLevelAIAnalysis(TERMS, LEASE_LEVEL, PLAN, 0.1, 1.5, 1.2, 'levered_irr', null),
  createDeal: () => api.createDeal('Deal', INPUTS, PLAN, null),
  updateDeal: () => api.updateDeal('deal-1', 'Deal', INPUTS, PLAN, null),
  createDetailedDeal: () => api.createDetailedDeal('Deal', TERMS, OPERATING, PLAN, null),
  updateDetailedDeal: () =>
    api.updateDetailedDeal('deal-1', 'Deal', TERMS, OPERATING, PLAN, null),
  createLeaseLevelDeal: () => api.createLeaseLevelDeal('Deal', TERMS, LEASE_LEVEL, PLAN, null),
  updateLeaseLevelDeal: () =>
    api.updateLeaseLevelDeal('deal-1', 'Deal', TERMS, LEASE_LEVEL, PLAN, null),
  fetchDealFingerprint: () => api.fetchDealFingerprint(INPUTS, PLAN, null),
  fetchDetailedDealFingerprint: () =>
    api.fetchDetailedDealFingerprint(TERMS, OPERATING, PLAN, null),
  fetchLeaseLevelDealFingerprint: () =>
    api.fetchLeaseLevelDealFingerprint(TERMS, LEASE_LEVEL, PLAN, null),
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function sentBody(call: () => Promise<unknown>): Promise<Record<string, unknown>> {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({}),
  } as Response);
  vi.stubGlobal('fetch', fetchMock);
  return call().then(() => {
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    return JSON.parse(init.body as string) as Record<string, unknown>;
  });
}

describe('every deal-state request puts the Business Plan on the wire', () => {
  it.each(Object.keys(DEAL_STATE_CALLS))('%s sends the exact plan, top-level', async (name) => {
    const body = await sentBody(DEAL_STATE_CALLS[name]);
    expect(body.business_plan).toEqual(PLAN);
    // Beside the deal's own inputs, never inside them.
    for (const container of ['inputs', 'terms', 'detailed_operating_inputs']) {
      const inner = body[container] as Record<string, unknown> | undefined;
      expect(inner?.business_plan, `${name} nested the plan in ${container}`).toBeUndefined();
    }
  });

  it('keeps Quick /analyze flat: the fourteen assumptions plus business_plan', async () => {
    const body = await sentBody(DEAL_STATE_CALLS.analyzeAcquisition);
    expect(body).toEqual({ purchase_price: 50_000_000, business_plan: PLAN });
  });

  it('sends an empty plan as two explicit empty arrays', async () => {
    const empty = { capital_items: [], owner_expense_items: [] };
    const body = await sentBody(() => api.updateDeal('deal-1', 'Deal', INPUTS, empty, null));
    expect(body.business_plan).toEqual(empty);
    expect(JSON.stringify(body)).toContain('"business_plan":{"capital_items":[],"owner_expense_items":[]}');
  });

  it('keeps last_year null and month 0 exactly as given', async () => {
    const body = await sentBody(DEAL_STATE_CALLS.updateLeaseLevelDeal);
    const plan = body.business_plan as typeof PLAN;
    expect(plan.capital_items[0].month).toBe(0);
    expect(plan.owner_expense_items[0].last_year).toBeNull();
  });
});

// =============================================================================
// The structural audit
// =============================================================================

interface Audit {
  /** Exported functions that are handed deal state to send. */
  dealState: string[];
  /** Of those, the ones that do not carry the plan correctly, with why. */
  offenders: string[];
}

/** A function is a deal-state function because of what it is HANDED, not how
 * its body happens to be written: `JSON.stringify(request)` sends the deal
 * without a single object literal, and an audit keyed on literals alone would
 * not see that function at all. */
const DEAL_STATE_TYPES = new Set([
  'AcquisitionRequest',
  'AcquisitionTermsRequest',
  'DetailedOperatingInputsRequest',
  'LeaseLevelInputsRequest',
]);
const DEAL_STATE_KEYS = new Set(['inputs', 'terms', 'detailed_operating_inputs']);
const DEAL_STATE_SPREADS = new Set(['request', 'inputs']);

function propertyName(node: ts.ObjectLiteralElementLike): string | null {
  if (
    (ts.isPropertyAssignment(node) || ts.isShorthandPropertyAssignment(node)) &&
    ts.isIdentifier(node.name)
  ) {
    return node.name.text;
  }
  return null;
}

function carriesDealState(literal: ts.ObjectLiteralExpression): boolean {
  return literal.properties.some((property) => {
    const name = propertyName(property);
    if (name !== null && DEAL_STATE_KEYS.has(name)) {
      return true;
    }
    return (
      ts.isSpreadAssignment(property) &&
      ts.isIdentifier(property.expression) &&
      DEAL_STATE_SPREADS.has(property.expression.text)
    );
  });
}

function carriesPlan(literal: ts.ObjectLiteralExpression): boolean {
  return literal.properties.some(
    (property) =>
      ts.isPropertyAssignment(property) &&
      propertyName(property) === 'business_plan' &&
      property.initializer.getText() === 'businessPlan',
  );
}

function auditApi(text: string): Audit {
  const source = ts.createSourceFile('api.ts', text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const dealState: string[] = [];
  const offenders: string[] = [];
  for (const statement of source.statements) {
    if (
      !ts.isFunctionDeclaration(statement) ||
      statement.name === undefined ||
      statement.body === undefined ||
      !statement.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword)
    ) {
      continue;
    }
    const handedDealState = statement.parameters.some(
      (parameter) => parameter.type !== undefined && DEAL_STATE_TYPES.has(parameter.type.getText()),
    );
    const literals: ts.ObjectLiteralExpression[] = [];
    const planBodies: ts.ObjectLiteralExpression[] = [];
    const visit = (node: ts.Node): void => {
      if (ts.isObjectLiteralExpression(node)) {
        if (carriesDealState(node)) {
          literals.push(node);
        }
        if (carriesPlan(node)) {
          planBodies.push(node);
        }
      }
      node.forEachChild(visit);
    };
    visit(statement.body);
    if (!handedDealState && literals.length === 0) {
      continue;
    }
    const name = statement.name.text;
    dealState.push(name);
    const parameter = statement.parameters.find(
      (candidate) => ts.isIdentifier(candidate.name) && candidate.name.text === 'businessPlan',
    );
    if (parameter === undefined) {
      offenders.push(`${name}: no businessPlan parameter`);
    } else if (parameter.questionToken !== undefined || parameter.initializer !== undefined) {
      offenders.push(`${name}: businessPlan is optional or defaulted`);
    } else if (parameter.type?.getText() !== 'BusinessPlanInput') {
      offenders.push(`${name}: businessPlan is not a BusinessPlanInput`);
    }
    if (literals.some((literal) => !carriesPlan(literal))) {
      offenders.push(`${name}: a deal-state body omits business_plan: businessPlan`);
    } else if (planBodies.length === 0) {
      offenders.push(`${name}: no request body carries business_plan: businessPlan`);
    }
  }
  return { dealState: dealState.sort(), offenders };
}

describe('the api.ts omission guard', () => {
  it('finds exactly the deal-state functions the behavioural table covers, all carrying the plan', () => {
    const audit = auditApi(apiSource);
    expect(audit.dealState).toEqual(Object.keys(DEAL_STATE_CALLS).sort());
    expect(audit.offenders).toEqual([]);
  });

  it('leaves the snapshot writes alone: they carry an artifact, not deal state', () => {
    const audit = auditApi(apiSource);
    for (const snapshotWrite of [
      'updateDealAnalysisSnapshot',
      'updateDealAiSnapshot',
      'updateDealOneWaySensitivitySnapshot',
      'updateDealTwoWaySensitivitySnapshot',
    ]) {
      expect(audit.dealState).not.toContain(snapshotWrite);
    }
  });

  /** Removes `business_plan: businessPlan` from one named function only. */
  function withoutPlanIn(functionName: string): string {
    const start = apiSource.indexOf(`export async function ${functionName}(`);
    expect(start, `${functionName} not found`).toBeGreaterThan(-1);
    const end = apiSource.indexOf('\n}\n', start);
    const body = apiSource.slice(start, end);
    const mutated = body.replace(/\n\s*business_plan: businessPlan,/, '').replace(
      '{ ...request, business_plan: businessPlan }',
      'request',
    ).replace('{ inputs, business_plan: businessPlan }', '{ inputs }');
    expect(mutated, `${functionName}: mutation changed nothing`).not.toBe(body);
    return apiSource.slice(0, start) + mutated + apiSource.slice(end);
  }

  it.each([
    'updateDeal',
    'createDeal',
    'fetchSensitivityPresets',
    'updateDetailedDeal',
    'updateLeaseLevelDeal',
    'analyzeLeaseLevelAcquisition',
    'fetchLeaseLevelAIAnalysis',
    'fetchDealFingerprint',
    'runLeaseLevelTwoWaySensitivity',
  ])('kills the mutant where %s drops the plan from its body', (name) => {
    expect(auditApi(withoutPlanIn(name)).offenders).toEqual([
      `${name}: a deal-state body omits business_plan: businessPlan`,
    ]);
  });

  it('kills the mutant where Quick /analyze goes back to sending the bare request (M2)', () => {
    // `JSON.stringify(request)` -- no object literal at all. Caught because the
    // function is identified by the deal state it is handed.
    expect(auditApi(withoutPlanIn('analyzeAcquisition')).offenders).toEqual([
      'analyzeAcquisition: no request body carries business_plan: businessPlan',
    ]);
  });

  it('kills the mutant where the plan parameter becomes optional', () => {
    const mutated = apiSource.replace(
      'export async function updateDeal(\n  dealId: string,\n  name: string,\n  inputs: AcquisitionRequest,\n  businessPlan: BusinessPlanInput,',
      'export async function updateDeal(\n  dealId: string,\n  name: string,\n  inputs: AcquisitionRequest,\n  businessPlan?: BusinessPlanInput,',
    );
    expect(mutated).not.toBe(apiSource);
    expect(auditApi(mutated).offenders).toEqual(['updateDeal: businessPlan is optional or defaulted']);
  });

  it('kills the mutant where a new deal-state function is added without the plan', () => {
    const mutated = `${apiSource}\nexport async function saveDealQuietly(inputs: AcquisitionRequest): Promise<void> {\n  await fetch('/deals', { method: 'PUT', body: JSON.stringify({ inputs }) });\n}\n`;
    const audit = auditApi(mutated);
    expect(audit.dealState).toContain('saveDealQuietly');
    expect(audit.offenders).toEqual(['saveDealQuietly: no businessPlan parameter', 'saveDealQuietly: a deal-state body omits business_plan: businessPlan']);
  });
});
