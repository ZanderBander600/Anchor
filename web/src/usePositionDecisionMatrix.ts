/**
 * Phase 7 Gate P7.8B -- the `POSITION(position_id)` Decision Matrix state.
 *
 * The Project matrix answers "how does this deal do under each strategy and
 * scenario". This one answers a different question about the same variants:
 * **how does *this position* do** -- what it funds, what it earns, where it
 * attaches and detaches, and whether its claim was met.
 *
 * It is a second perspective, never a second authority. The backend runs every
 * cell through the same approved executor and computes every cross-cell figure;
 * this hook asks which positions are addressable, asks for one position's
 * matrix, and holds what comes back. It compares no two cells and computes no
 * figure (P-5, Q22, DC-5).
 *
 * **Explicit.** Nothing runs until the analyst selects a position and presses
 * Run. A scope with no addressable position has nothing to compare and asks for
 * nothing.
 *
 * **Never stale as current (DC-7).** A report records the saved economic state
 * it ran against -- the same token the Project matrix uses, plus the selected
 * position -- and is current only while that token still matches and the base
 * has no unsaved edits. Editing the Capital Structure moves it; renaming a
 * position does not.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { analyzePositionDecisionMatrix, listPositionPerspectives } from './api';
import type { PositionDecisionMatrixReport, PositionPerspective } from './capitalTypes';

export interface UsePositionDecisionMatrixOptions {
  /** The Investment that owns the positions: a visible one, or the Deal's
   * hidden wrapper once it exists. `null` before either does. */
  investmentId: string | null;
  isDirty: boolean;
  /** The saved economic state token the Project matrix is keyed by. */
  stateToken: string;
  /** Whether this perspective is on screen and selected. Nothing is requested
   * before it is: the owner of the perspective choice decides, because more
   * than one perspective now shares the surface. */
  isActive: boolean;
}

type RunState =
  | { status: 'idle' }
  | { status: 'running'; token: string }
  | { status: 'ready'; token: string; report: PositionDecisionMatrixReport }
  | { status: 'error'; token: string; message: string };

export interface PositionDecisionMatrixState {
  /** The addressable positions, once read. */
  positions: PositionPerspective[];
  listStatus: 'idle' | 'loading' | 'ready' | 'error';
  listError: string | null;
  retryList: () => void;
  selectedPositionId: string | null;
  selectPosition: (positionId: string) => void;
  report: PositionDecisionMatrixReport | null;
  error: string | null;
  /** The report was produced from exactly the saved state on screen. */
  isCurrent: boolean;
  hasRun: boolean;
  isRunning: boolean;
  canRun: boolean;
  run: () => Promise<void>;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'The position decision matrix could not be completed.';
}

export function usePositionDecisionMatrix({
  investmentId,
  isDirty,
  stateToken,
  isActive,
}: UsePositionDecisionMatrixOptions): PositionDecisionMatrixState {
  const [positions, setPositions] = useState<PositionPerspective[]>([]);
  const [listStatus, setListStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [listError, setListError] = useState<string | null>(null);
  const [selectedPositionId, setSelectedPositionId] = useState<string | null>(null);
  const [state, setState] = useState<RunState>({ status: 'idle' });
  const [reloadKey, setReloadKey] = useState(0);
  const activeRun = useRef<object | null>(null);
  const activeList = useRef<object | null>(null);

  const token = useMemo(
    () => JSON.stringify([investmentId, stateToken, selectedPositionId]),
    [investmentId, stateToken, selectedPositionId],
  );

  // The addressable positions are read only once the analyst asks for this
  // perspective -- which `isActive` already says -- so a Deal that never opted
  // into structured capital pays for nothing.
  const wantsList = isActive && investmentId !== null;

  // An effect, not a memo: this reads from the network and sets state, which is
  // synchronising with an external system rather than computing a value. Stated
  // as a memo it re-fired on any dependency change, set state during render and
  // touched a ref there too -- the shape that produces repeated requests and
  // missed updates.
  useEffect(() => {
    if (!wantsList) {
      return;
    }
    const current = {};
    activeList.current = current;
    setListStatus('loading');
    setListError(null);
    listPositionPerspectives(investmentId as string)
      .then((payload) => {
        if (activeList.current !== current) {
          return;
        }
        setPositions(payload.positions);
        setListStatus('ready');
        setSelectedPositionId((chosen) =>
          chosen === null ? (payload.positions[0]?.position_id ?? null) : chosen,
        );
      })
      .catch((error: unknown) => {
        if (activeList.current !== current) {
          return;
        }
        setListError(messageOf(error));
        setListStatus('error');
      });
    // The reload key is part of the identity of this request, so a Retry
    // re-reads rather than being ignored as an unchanged dependency.
  }, [wantsList, investmentId, reloadKey]);

  const isRunning = state.status === 'running';
  const canRun = investmentId !== null && selectedPositionId !== null && !isDirty && !isRunning;
  const isCurrent = state.status === 'ready' && state.token === token && !isDirty;

  async function run() {
    if (!canRun || investmentId === null || selectedPositionId === null) {
      return;
    }
    const current = {};
    activeRun.current = current;
    const ranAgainst = token;
    setState({ status: 'running', token: ranAgainst });
    try {
      const report = await analyzePositionDecisionMatrix(investmentId, selectedPositionId);
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
    positions,
    listStatus,
    listError,
    retryList: () => setReloadKey((key) => key + 1),
    selectedPositionId,
    selectPosition: (positionId) => {
      setSelectedPositionId(positionId);
      // A different position is a different comparison, so the report on screen
      // is no longer this selection's: it is dropped rather than relabelled.
      setState({ status: 'idle' });
    },
    report: state.status === 'ready' ? state.report : null,
    error: state.status === 'error' ? state.message : null,
    isCurrent,
    hasRun: state.status !== 'idle',
    isRunning,
    canRun,
    run,
  };
}
