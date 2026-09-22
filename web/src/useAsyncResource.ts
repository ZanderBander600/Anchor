/**
 * Phase 7 Gate P7.10 Stage 4 -- one asynchronous read, done once, correctly.
 *
 * Ratified at the Stage 4 independent review (Correction 3). Six Stage 4
 * loading flows each opened their effect by synchronously setting a loading
 * flag and clearing an error, which `react(set-state-in-effect)` reports: a
 * synchronous `setState` inside an effect starts a second render pass before
 * the first has painted, and the value it sets was derivable all along.
 *
 * **Loading is derived, never set.** The settled result carries the `key` it
 * was loaded for. When the key changes, the settled result no longer describes
 * what the caller is asking about, so the resource *is* loading -- computed
 * during render, with no state written. The effect then writes state exactly
 * once, from the promise's own callback, which is asynchronous by construction
 * and is the state update React is asking for.
 *
 * **Stale responses cannot win.** Each run holds its own cancellation flag and
 * the cleanup sets it, so a response that arrives after the key moved, or after
 * the component unmounted, is discarded rather than written into state that no
 * longer belongs to it.
 *
 * **A null key means there is nothing to read**, which is a real state rather
 * than an error: a memo with no selected decision cell has no valuation views
 * to resolve, and saying so is more honest than showing a spinner forever.
 *
 * `web/src/useAsyncResource.test.ts` proves each of these, including that a
 * superseded response is dropped.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

export type AsyncStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface AsyncResource<T> {
  status: AsyncStatus;
  /** The loaded value, or `null` while loading, idle, or after a failure. */
  data: T | null;
  error: string | null;
  /** Re-runs the read for the current key. */
  reload: () => void;
  isLoading: boolean;
}

interface Settled<T> {
  key: string | null;
  /** Which attempt produced this. A retry is a new read of the same key, and
   * until it lands the resource is loading again -- otherwise a Retry button
   * would look inert while the request it started was in flight. */
  attempt: number;
  status: 'ready' | 'error';
  data: T | null;
  error: string | null;
}

const NOTHING: Settled<never> = {
  key: null,
  attempt: -1,
  status: 'ready',
  data: null,
  error: null,
};

/** The message a thrown value becomes, without swallowing what it said. */
export function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error && error.message !== '' ? error.message : fallback;
}

/**
 * Read `load()` whenever `key` changes, and report the result.
 *
 * `key` identifies *what* is being read: pass `null` when there is nothing to
 * read yet. `load` is called with no arguments and must return the value; it is
 * re-created freely by the caller, because only `key` drives the read.
 */
export function useAsyncResource<T>(
  key: string | null,
  load: () => Promise<T>,
  fallbackMessage: string,
): AsyncResource<T> {
  const [settled, setSettled] = useState<Settled<T>>(NOTHING as Settled<T>);
  const [attempt, setAttempt] = useState(0);

  /** The latest `load`, held in a ref so changing it never re-runs the read.
   * A caller that rebuilds its closure every render -- which is every caller --
   * would otherwise reload on every render.
   *
   * Updated in an effect rather than during render: a ref written while
   * rendering is a side effect in the render phase, and React may render
   * speculatively. This effect is declared first, so it has already run by the
   * time the read below fires and the closure it calls is the current one. */
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });

  useEffect(() => {
    if (key === null) {
      return;
    }
    let cancelled = false;
    void loadRef
      .current()
      .then((value) => {
        if (!cancelled) {
          setSettled({ key, attempt, status: 'ready', data: value, error: null });
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setSettled({
            key,
            attempt,
            status: 'error',
            data: null,
            error: messageOf(cause, fallbackMessage),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [key, attempt, fallbackMessage]);

  const reload = useCallback(() => setAttempt((count) => count + 1), []);

  // Derived during render: no effect writes a loading flag, because none needs
  // to. A settled result for another key is not this key's answer.
  if (key === null) {
    return { status: 'idle', data: null, error: null, reload, isLoading: false };
  }
  if (settled.key !== key || settled.attempt !== attempt) {
    return { status: 'loading', data: null, error: null, reload, isLoading: true };
  }
  return {
    status: settled.status,
    data: settled.data,
    error: settled.error,
    reload,
    isLoading: false,
  };
}
