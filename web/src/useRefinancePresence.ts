/**
 * Refinance & Capital Events V1 Stage 3 -- which surfaces must name the
 * acquisition-financing reference.
 *
 * A Deal's underwriting results, Capital Economics, Owner Summary and an
 * Investment's overview report the Project levered IRR and equity multiple:
 * the acquisition loan held to the sale. When the Base Capital Structure
 * configures a refinance, those figures exclude it, so they may appear only as
 * the labelled reference "Acquisition financing — excludes later capital
 * events" and never as the refinance-adjusted headline (R-P rules 3 to 5).
 *
 * **Unknown is not "no refinance"** (Stage 3 correction round). Presence is a
 * typed state -- `loading`, `error` or `ready` -- and only `ready` answers the
 * question. Each read is kept with the exact identity, freshness token and
 * attempt it was made for, so a new analysis or a Retry reads `loading` at
 * once, during render: a previous answer is never shown for a new question,
 * and nothing is reset from an effect.
 *
 * The fact read here is the saved structure's own -- whether it states a
 * capital event -- and the Decision Matrix reads the server's typed
 * per-Strategy statement. Nothing is resolved, sized or computed.
 */

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import {
  readCapitalEventPresence,
  readDealCapitalStructure,
  readInvestmentCapitalStructure,
} from './api';

/** Whether a Base Capital Structure configures a refinance. */
export type RefinancePresence =
  | { status: 'loading' }
  | { status: 'error'; retry: () => void }
  | { status: 'ready'; configured: boolean };

/** A settled "no refinance": the value outside any refinance-aware provider,
 * where presentation is exactly as it always was, and with nothing open. */
export const NO_REFINANCE: RefinancePresence = { status: 'ready', configured: false };

export const AcquisitionReferenceContext = createContext<RefinancePresence>(NO_REFINANCE);

export function useAcquisitionReference(): RefinancePresence {
  return useContext(AcquisitionReferenceContext);
}

/** `true` only for a settled answer that a refinance is configured. */
export function isReference(presence: RefinancePresence): boolean {
  return presence.status === 'ready' && presence.configured;
}

/** `true` while the answer is unknown -- loading or failed. */
export function isUnresolved(presence: RefinancePresence): boolean {
  return presence.status !== 'ready';
}

/** What a withheld figure reads as, never a number. */
export const REFERENCE_CHECKING_VALUE = 'Checking…';
export const REFERENCE_WITHHELD_VALUE = 'Unavailable';

/** A refinance-sensitive figure as it may be shown: the formatted value only
 * once presence is settled; otherwise a word, never a number. */
export function referenceFigure(presence: RefinancePresence, value: string): string {
  if (presence.status === 'loading') {
    return REFERENCE_CHECKING_VALUE;
  }
  if (presence.status === 'error') {
    return REFERENCE_WITHHELD_VALUE;
  }
  return value;
}

/** A fresh attempt token. Its identity, not a count, distinguishes a Retry. */
function newAttempt(): object {
  return {};
}

/** Read whether the Base Capital Structure of a Deal or Investment configures
 * a capital event. `token` re-reads it when the caller's saved state or view
 * changes (a structure is saved from another workspace). */
export function useBaseCapitalEvents({
  dealId = null,
  investmentId = null,
  unitId = null,
  token,
}: {
  dealId?: string | null;
  investmentId?: string | null;
  /** With an Investment: count only refinances of this Unit or of the whole
   * Investment, so a Unit opened from its Investment is labeled only when a
   * refinance actually replaces its acquisition financing. */
  unitId?: string | null;
  token: string;
}): RefinancePresence {
  const [attempt, setAttempt] = useState<object>(newAttempt);
  const key = `${dealId ?? ''}|${investmentId ?? ''}|${unitId ?? ''}|${token}`;
  const [settled, setSettled] = useState<{ key: string; attempt: object; value: boolean | 'error' } | null>(null);
  const retry = useCallback(() => setAttempt(newAttempt()), []);

  useEffect(() => {
    if (dealId === null && investmentId === null) {
      return;
    }
    let live = true;
    const request =
      investmentId !== null
        ? readInvestmentCapitalStructure(investmentId)
        : readDealCapitalStructure(dealId as string);
    request
      .then((payload) => {
        if (live) {
          const events = payload.capital_structure.capital_events ?? [];
          setSettled({
            key,
            attempt,
            value: events.some(
              (event) => unitId === null || event.scope.kind === 'investment' || event.scope.unit_id === unitId,
            ),
          });
        }
      })
      .catch(() => {
        if (live) {
          setSettled({ key, attempt, value: 'error' });
        }
      });
    return () => {
      live = false;
    };
  }, [dealId, investmentId, unitId, key, attempt]);

  if (dealId === null && investmentId === null) {
    return NO_REFINANCE;
  }
  if (settled === null || settled.key !== key || settled.attempt !== attempt) {
    return { status: 'loading' };
  }
  return settled.value === 'error' ? { status: 'error', retry } : { status: 'ready', configured: settled.value };
}

export interface StrategyCapitalEvents {
  /** Strategy ids whose resolved Capital Structure configures a refinance. */
  strategies: ReadonlySet<string>;
  /** The Project matrix metrics those Strategies' figures qualify. */
  metrics: ReadonlySet<string>;
}

/** Which Strategies are refinance-bearing, as a typed state: an empty set is
 * only ever a settled answer, never a request still in flight or one that
 * failed. */
export type StrategyPresence =
  | { status: 'loading' }
  | { status: 'error'; retry: () => void }
  | ({ status: 'ready' } & StrategyCapitalEvents);

const NO_STRATEGY_PRESENCE: StrategyPresence = { status: 'ready', strategies: new Set(), metrics: new Set() };

/** The server's typed statement of which Strategies of an Investment are
 * refinance-bearing, and which Project metrics that makes the acquisition-
 * financing reference. */
export function useStrategyCapitalEvents(investmentId: string | null, token: string): StrategyPresence {
  const [attempt, setAttempt] = useState<object>(newAttempt);
  const key = `${investmentId ?? ''}|${token}`;
  const [settled, setSettled] = useState<{ key: string; attempt: object; value: StrategyCapitalEvents | 'error' } | null>(
    null,
  );
  const retry = useCallback(() => setAttempt(newAttempt()), []);

  useEffect(() => {
    if (investmentId === null) {
      return;
    }
    let live = true;
    readCapitalEventPresence(investmentId)
      .then((payload) => {
        if (live) {
          setSettled({
            key,
            attempt,
            value: {
              strategies: new Set(
                payload.strategies.filter((entry) => entry.capital_events_configured).map((entry) => entry.strategy_id),
              ),
              metrics: new Set(payload.acquisition_financing_metrics),
            },
          });
        }
      })
      .catch(() => {
        if (live) {
          setSettled({ key, attempt, value: 'error' });
        }
      });
    return () => {
      live = false;
    };
  }, [investmentId, key, attempt]);

  if (investmentId === null) {
    return NO_STRATEGY_PRESENCE;
  }
  if (settled === null || settled.key !== key || settled.attempt !== attempt) {
    return { status: 'loading' };
  }
  return settled.value === 'error' ? { status: 'error', retry } : { status: 'ready', ...settled.value };
}
