/**
 * Phase 7 Gate P7.10 Stage 4 -- the Investment Committee library's state.
 *
 * One read of `GET /memo-library`, which is read-only and never materializes a
 * hidden Investment: opening the library gives no Deal a memo it did not have.
 *
 * Deliberately thin. The library reports stored facts; freshness is a
 * per-version question and is answered in the memo workspace, for the one
 * version it is showing, rather than by running an analysis for every row.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { readMemoLibrary } from './api';
import type { MemoLibraryEntry } from './memoTypes';

export interface UseMemoLibraryResult {
  entries: MemoLibraryEntry[];
  isLoading: boolean;
  error: string | null;
  reload: () => void;
}

export function useMemoLibrary(refreshSignal?: object): UseMemoLibraryResult {
  const [entries, setEntries] = useState<MemoLibraryEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState({});
  const liveRef = useRef(true);

  useEffect(() => {
    liveRef.current = true;
    return () => {
      liveRef.current = false;
    };
  }, []);

  useEffect(() => {
    setIsLoading(true);
    setError(null);
    void readMemoLibrary()
      .then((result) => {
        if (liveRef.current) {
          setEntries(result);
        }
      })
      .catch((cause: unknown) => {
        if (liveRef.current) {
          setEntries([]);
          setError(
            cause instanceof Error && cause.message !== ''
              ? cause.message
              : 'The investment memos could not be loaded.',
          );
        }
      })
      .finally(() => {
        if (liveRef.current) {
          setIsLoading(false);
        }
      });
  }, [refreshSignal, reloadToken]);

  const reload = useCallback(() => setReloadToken({}), []);

  return { entries, isLoading, error, reload };
}
