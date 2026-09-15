/**
 * Phase 7 Gate P7.5 -- the Decision Matrix state of one open Deal, and (P7.6)
 * of one visible Investment.
 *
 * The one comparison surface: every Strategy x Scenario variant, from one
 * backend request -- `POST /investments/{id}/decision-matrix` for a Deal's
 * hidden Investment, `POST /investments/{id}/investment-decision-matrix` for a
 * visible Investment, whose cells are consolidated. This hook asks for the
 * package and holds it. It computes no figure, compares no two cells and keeps
 * no second copy of anything the backend decides -- cross-cell figures
 * included (Q22, DC-5).
 *
 * **Explicit.** Nothing runs until the analyst presses Run Decision Matrix (or
 * Refresh Matrix after a run). A scope with no saved Strategy and no saved
 * Scenario has nothing to compare, and asks for nothing.
 *
 * **Never stale as current (DC-7).** A package records a token of the saved
 * economic state it ran against: the Deal and the save it was run on (or the
 * visible Investment's saved economic state, every Unit's save included), and
 * each Strategy's overlays and each Scenario's overrides by id. It is current
 * only while that token still matches and the base has no unsaved edits. A
 * rename or a new description leaves the token unchanged, so labels update
 * without a re-run. The token only detects that saved state moved; the backend
 * fingerprint remains the financial identity.
 */

import { useMemo, useRef, useState } from 'react';
import { analyzeDecisionMatrix, analyzeInvestmentDecisionMatrix } from './api';
import type { DecisionMatrixReport } from './decisionTypes';
import type { InvestmentDecisionScope } from './investmentCatalog';
import type { InvestmentDecisionMatrixReport } from './investmentTypes';
import type { InvestmentScenario } from './scenarioTypes';
import type { InvestmentStrategy } from './strategyTypes';

export interface UseDecisionMatrixOptions {
  dealId: string | null;
  isDirty: boolean;
  savedAt: string | null;
  strategies: InvestmentStrategy[];
  scenarios: InvestmentScenario[];
  /** Both lists have loaded, so the matrix knows what there is to compare. */
  isReady: boolean;
  /** P7.6: a visible Investment's scope. When present, the consolidated
   * Investment matrix runs, never the one-unit route. */
  investment?: InvestmentDecisionScope | null;
}

/** Either package: the matrix itself is the one P7.5 contract. */
export type AnyDecisionMatrixReport = DecisionMatrixReport | InvestmentDecisionMatrixReport;

type RunState =
  | { status: 'idle' }
  | { status: 'running'; token: string }
  | { status: 'ready'; token: string; report: AnyDecisionMatrixReport }
  | { status: 'error'; token: string; message: string };

export interface DecisionMatrixState {
  /** At least one saved Strategy or Scenario exists. */
  hasComparison: boolean;
  status: RunState['status'];
  report: AnyDecisionMatrixReport | null;
  error: string | null;
  /** The package was produced from exactly the saved state on screen. */
  isCurrent: boolean;
  hasRun: boolean;
  isRunning: boolean;
  canRun: boolean;
  run: () => Promise<void>;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'The decision matrix could not be completed.';
}

export function useDecisionMatrix({
  dealId,
  isDirty,
  savedAt,
  strategies,
  scenarios,
  isReady,
  investment = null,
}: UseDecisionMatrixOptions): DecisionMatrixState {
  const [state, setState] = useState<RunState>({ status: 'idle' });
  /** The latest run, so a slower earlier run can never overwrite a later one.
   * Compared by identity only. */
  const activeRun = useRef<object | null>(null);

  const token = useMemo(
    () =>
      JSON.stringify([
        investment === null ? dealId : investment.investmentId,
        investment === null ? savedAt : investment.stateToken,
        strategies.map((record) => [record.strategy.strategy_id, record.strategy.overlays]),
        scenarios.map((record) => [record.scenario.scenario_id, record.scenario.overrides]),
      ]),
    [investment, dealId, savedAt, strategies, scenarios],
  );

  const investmentId =
    investment?.investmentId ?? strategies[0]?.investment_id ?? scenarios[0]?.investment_id ?? null;
  const hasComparison = strategies.length > 0 || scenarios.length > 0;
  const isRunning = state.status === 'running';
  const canRun =
    (investment !== null || dealId !== null) && !isDirty && isReady && investmentId !== null && !isRunning;
  const isCurrent = state.status === 'ready' && state.token === token && !isDirty;

  async function run() {
    if (!canRun || investmentId === null) {
      return;
    }
    const current = {};
    activeRun.current = current;
    const ranAgainst = token;
    setState({ status: 'running', token: ranAgainst });
    try {
      const report =
        investment !== null
          ? await analyzeInvestmentDecisionMatrix(investment.investmentId)
          : await analyzeDecisionMatrix(investmentId);
      if (activeRun.current === current) {
        setState({ status: 'ready', token: ranAgainst, report });
      }
    } catch (error) {
      if (activeRun.current === current) {
        setState({ status: 'error', token: ranAgainst, message: messageOf(error) });
      }
    }
  }

  return {
    hasComparison,
    status: state.status,
    report: state.status === 'ready' ? state.report : null,
    error: state.status === 'error' ? state.message : null,
    isCurrent,
    hasRun: state.status !== 'idle',
    isRunning,
    canRun,
    run,
  };
}
