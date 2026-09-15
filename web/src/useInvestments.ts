/**
 * Phase 7 Gate P7.6 -- the list of visible Investments.
 *
 * One read of `GET /investments`, shared by the sidebar's Recent Investments,
 * the Investment Library and the Deal workspace's "this Deal is a Unit"
 * notice, so they never disagree. Hidden one-unit wrappers are never listed:
 * they stay a Deal's own decision set. State is set only when a read settles.
 */

import { useEffect, useState } from 'react';
import { deleteVisibleInvestment, listVisibleInvestments } from './api';
import type { VisibleInvestment } from './investmentTypes';

export interface InvestmentsState {
  investments: VisibleInvestment[];
  isLoading: boolean;
  error: string | null;
  reload: () => void;
  /** Deletes one Investment -- its Units are released as standalone Deals --
   * then re-reads the list. Rejects with the backend's reason. */
  remove: (investmentId: string) => Promise<void>;
}

type ListState =
  | { status: 'loading'; investments: VisibleInvestment[] }
  | { status: 'ready'; investments: VisibleInvestment[] }
  | { status: 'error'; investments: VisibleInvestment[]; message: string };

function load(setState: (update: (current: ListState) => ListState) => void): void {
  listVisibleInvestments().then(
    (investments) => setState(() => ({ status: 'ready', investments })),
    (error: unknown) =>
      setState((current) => ({
        status: 'error',
        investments: current.investments,
        message: error instanceof Error ? error.message : 'The investments could not be loaded.',
      })),
  );
}

export function useInvestments(): InvestmentsState {
  const [state, setState] = useState<ListState>({ status: 'loading', investments: [] });

  useEffect(() => {
    load(setState);
  }, []);

  return {
    investments: state.investments,
    isLoading: state.status === 'loading',
    error: state.status === 'error' ? state.message : null,
    reload: () => {
      setState((current) => ({ status: 'loading', investments: current.investments }));
      load(setState);
    },
    remove: async (investmentId) => {
      await deleteVisibleInvestment(investmentId);
      setState((current) => ({ status: 'loading', investments: current.investments }));
      load(setState);
    },
  };
}
