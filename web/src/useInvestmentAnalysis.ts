/**
 * Phase 7 Gate P7.6 -- the Base consolidated analysis of one visible
 * Investment.
 *
 * One request, `POST /investments/{id}/investment-variants/base/base/analysis`:
 * every Unit through the existing engine, then consolidation. This hook asks
 * for it and holds it. Every figure on screen is a field of the response's
 * `ConsolidatedResults`; nothing is derived here.
 *
 * **Explicit, and never stale as current.** Nothing runs until the analyst
 * presses Run Base Analysis. A result records the saved economic state it ran
 * against (`investmentStateToken`: the Transaction Price, the Investment
 * Business Plan, the costs' economics and each Unit Deal's save). It is current
 * only while that state is unchanged and nothing economic is unsaved; returning
 * from a Unit whose underwriting was saved makes it out of date until it is run
 * again. A label, a Unit Kind or an order never does.
 */

import { useRef, useState } from 'react';
import { analyzeInvestmentVariant, InvestmentApiError } from './api';
import type { InvestmentVariantAnalysis, InvestmentVariantIssue } from './investmentTypes';

/** The reserved Base key on both the Strategy and the Scenario axis (P7.4). */
export const BASE_VARIANT_KEY = 'base';

export interface InvestmentAnalysisError {
  message: string;
  issues: InvestmentVariantIssue[];
}

type RunState =
  | { status: 'idle' }
  | { status: 'running'; token: string }
  | { status: 'ready'; token: string; analysis: InvestmentVariantAnalysis }
  | { status: 'error'; token: string; error: InvestmentAnalysisError };

export interface InvestmentAnalysisState {
  analysis: InvestmentVariantAnalysis | null;
  error: InvestmentAnalysisError | null;
  /** The result was produced from exactly the saved state on screen. */
  isCurrent: boolean;
  hasRun: boolean;
  isRunning: boolean;
  canRun: boolean;
  run: () => Promise<void>;
}

export function useInvestmentAnalysis({
  investmentId,
  stateToken,
  isBlocked,
}: {
  investmentId: string;
  /** The saved economic state; `null` while the Investment is loading. */
  stateToken: string | null;
  /** Unsaved economic edits, or an open membership change. */
  isBlocked: boolean;
}): InvestmentAnalysisState {
  const [state, setState] = useState<RunState>({ status: 'idle' });
  const activeRun = useRef<object | null>(null);

  const isRunning = state.status === 'running';
  const canRun = stateToken !== null && !isBlocked && !isRunning;

  async function run() {
    if (!canRun || stateToken === null) {
      return;
    }
    const current = {};
    activeRun.current = current;
    const ranAgainst = stateToken;
    setState({ status: 'running', token: ranAgainst });
    try {
      const analysis = await analyzeInvestmentVariant(investmentId, BASE_VARIANT_KEY, BASE_VARIANT_KEY);
      if (activeRun.current === current) {
        setState({ status: 'ready', token: ranAgainst, analysis });
      }
    } catch (error) {
      if (activeRun.current === current) {
        setState({
          status: 'error',
          token: ranAgainst,
          error: {
            message: error instanceof Error ? error.message : 'The consolidated analysis could not be completed.',
            issues: error instanceof InvestmentApiError ? error.variantIssues : [],
          },
        });
      }
    }
  }

  return {
    analysis: state.status === 'ready' ? state.analysis : null,
    error: state.status === 'error' ? state.error : null,
    isCurrent: state.status === 'ready' && state.token === stateToken && !isBlocked,
    hasRun: state.status !== 'idle',
    isRunning,
    canRun,
    run,
  };
}
