/**
 * Phase 7 Gate P7.10 Stage 4 -- the Investment Committee library's state.
 *
 * One read of `GET /memo-library`, which is read-only and never materializes a
 * hidden Investment: opening the library gives no Deal a memo it did not have.
 *
 * Deliberately thin. The library reports stored facts; freshness is a
 * per-version question and is answered in the memo workspace, for the one
 * version it is showing, rather than by running an analysis for every row.
 *
 * Loading and cancellation belong to `useAsyncResource`, so this hook holds no
 * loading flag of its own and writes no state in an effect (Correction 3).
 * Re-reading is `reload()` rather than a changing signal object, because a
 * caller that mints a key to force a refresh is doing the hook's job for it.
 */

import { useCallback } from 'react';
import { readMemoLibrary } from './api';
import type { MemoLibraryEntry } from './memoTypes';
import { useAsyncResource } from './useAsyncResource';

export interface UseMemoLibraryResult {
  entries: MemoLibraryEntry[];
  isLoading: boolean;
  error: string | null;
  reload: () => void;
}

/** One shared empty list, so a loading render does not hand consumers a new
 * array identity every time and invalidate their memoisation. */
const NO_ENTRIES: MemoLibraryEntry[] = [];

export function useMemoLibrary(): UseMemoLibraryResult {
  const load = useCallback(() => readMemoLibrary(), []);
  const resource = useAsyncResource(
    'memo-library',
    load,
    'The investment memos could not be loaded.',
  );

  return {
    entries: resource.data ?? NO_ENTRIES,
    isLoading: resource.isLoading,
    error: resource.error,
    reload: resource.reload,
  };
}
