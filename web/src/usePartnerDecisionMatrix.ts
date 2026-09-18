/**
 * Phase 7 Gate P7.9 Stage 3 -- the `PARTNER(partner_id)` Decision Matrix state.
 *
 * The Project matrix answers "how does this deal do under each strategy and
 * scenario". The Position matrix answers it for one capital position. This one
 * answers a third question about the same variants: **how does *this partner*
 * do** -- what it contributes, what it is distributed, what it earns, how that
 * compares with the no-promote benchmark, and whether it earned a promote at
 * all.
 *
 * It is a third perspective, never a third authority. The backend runs every
 * cell through the accepted Stage 1 engine and computes every cross-cell figure;
 * this hook asks which partners are addressable, asks for one partner's matrix,
 * and holds what comes back. It compares no two cells, scores nothing, ranks
 * nothing and computes no figure (P-5, Q22, DC-5).
 *
 * **Identity is the `partner_id` (P-8).** The selector shows one deterministic
 * name so the analyst never has to pick an opaque id, but that name is not an
 * invariant of the partner: each cell reports the name and role *its own*
 * resolved Partnership states, so one Strategy's terms never label another's.
 *
 * **Explicit.** Nothing runs until the analyst selects a partner and presses
 * Run. A scope with no addressable partner has nothing to compare and asks for
 * nothing.
 *
 * **Never stale as current (DC-7).** A report records the saved economic state
 * it ran against -- the Project and structured state, plus every stored
 * Partnership statement, plus the selected partner -- and is current only while
 * that token still matches and the base has no unsaved edits. A stale report
 * stays on screen, labelled out of date.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { analyzePartnerDecisionMatrix, listPartnerPerspectives } from './api';
import type { PartnerDecisionMatrixReport, PartnerPerspective } from './partnershipTypes';

export interface UsePartnerDecisionMatrixOptions {
  /** The Investment that owns the Partnerships: a visible one, or the Deal's
   * hidden wrapper once it exists. `null` before either does. */
  investmentId: string | null;
  isDirty: boolean;
  /** The saved economic state token, including every stored Partnership. */
  stateToken: string;
  /** Whether the surface is on screen. Nothing is requested before it is. */
  isActive: boolean;
}

type RunState =
  | { status: 'idle' }
  | { status: 'running'; token: string }
  | { status: 'ready'; token: string; report: PartnerDecisionMatrixReport }
  | { status: 'error'; token: string; message: string };

export interface PartnerDecisionMatrixState {
  /** The addressable partners, once read. */
  partners: PartnerPerspective[];
  listStatus: 'idle' | 'loading' | 'ready' | 'error';
  listError: string | null;
  retryList: () => void;
  selectedPartnerId: string | null;
  selectPartner: (partnerId: string) => void;
  report: PartnerDecisionMatrixReport | null;
  error: string | null;
  /** The report was produced from exactly the saved state on screen. */
  isCurrent: boolean;
  hasRun: boolean;
  isRunning: boolean;
  canRun: boolean;
  run: () => Promise<void>;
}

const MATRIX_FAILED = 'The partner decision matrix could not be completed.';

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : MATRIX_FAILED;
}

export function usePartnerDecisionMatrix({
  investmentId,
  isDirty,
  stateToken,
  isActive,
}: UsePartnerDecisionMatrixOptions): PartnerDecisionMatrixState {
  const [partners, setPartners] = useState<PartnerPerspective[]>([]);
  const [listStatus, setListStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [listError, setListError] = useState<string | null>(null);
  const [selectedPartnerId, setSelectedPartnerId] = useState<string | null>(null);
  const [state, setState] = useState<RunState>({ status: 'idle' });
  const [reloadKey, setReloadKey] = useState(0);
  const activeRun = useRef<object | null>(null);
  const activeList = useRef<object | null>(null);

  const token = useMemo(
    () => JSON.stringify([investmentId, stateToken, selectedPartnerId]),
    [investmentId, stateToken, selectedPartnerId],
  );

  // The addressable partners are read only once the surface asks for them: a
  // Deal that never opted into a Partnership pays for nothing.
  const wantsList = isActive && investmentId !== null;

  // An effect, not a memo: this reads from the network and sets state, which is
  // synchronising with an external system rather than computing a value.
  useEffect(() => {
    if (!wantsList) {
      return;
    }
    const current = {};
    activeList.current = current;
    setListStatus('loading');
    setListError(null);
    listPartnerPerspectives(investmentId as string)
      .then((payload) => {
        if (activeList.current !== current) {
          return;
        }
        setPartners(payload.partners);
        setListStatus('ready');
        setSelectedPartnerId((chosen) =>
          chosen === null ? (payload.partners[0]?.partner_id ?? null) : chosen,
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
  const canRun = investmentId !== null && selectedPartnerId !== null && !isDirty && !isRunning;
  const isCurrent = state.status === 'ready' && state.token === token && !isDirty;

  async function run() {
    if (!canRun || investmentId === null || selectedPartnerId === null) {
      return;
    }
    const current = {};
    activeRun.current = current;
    const ranAgainst = token;
    setState({ status: 'running', token: ranAgainst });
    try {
      const report = await analyzePartnerDecisionMatrix(investmentId, selectedPartnerId);
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
    partners,
    listStatus,
    listError,
    retryList: () => setReloadKey((key) => key + 1),
    selectedPartnerId,
    selectPartner: (partnerId) => {
      setSelectedPartnerId(partnerId);
      // A different partner is a different comparison, so the report on screen
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
