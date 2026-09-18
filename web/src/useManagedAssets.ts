/** Gate AM1 -- Asset Management state.
 *
 * Owns loading and refresh for the managed-asset list and for one asset's
 * reports and performance. It holds no financial state of its own: the
 * performance result it stores is exactly what the API returned, never a
 * locally derived or merged version of it.
 */

import { useCallback, useEffect, useState } from 'react';

import {
  AssetManagementError,
  createManagedAsset,
  createMonthlyReport,
  listManagedAssets,
  listMonthlyReports,
  readAssetPerformance,
  updateMonthlyReportActuals,
} from './api';
import type {
  AssetPerformanceResponse,
  ManagedAsset,
  MonthlyAssetReport,
  OperatingFigures,
} from './assetManagementTypes';

export interface ManagedAssetsState {
  assets: ManagedAsset[];
  isLoading: boolean;
  error: string | null;
  reload: () => void;
  create: (request: {
    source_deal_id: string;
    name: string | null;
    acquisition_date: string;
    property_type: string | null;
    market: string | null;
  }) => Promise<ManagedAsset>;
}

/** The managed-asset list, loaded once and refreshed on demand. */
export function useManagedAssets(): ManagedAssetsState {
  const [assets, setAssets] = useState<ManagedAsset[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState<object>({});

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    listManagedAssets()
      .then((loaded) => {
        if (!cancelled) {
          setAssets(loaded);
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : 'The managed assets could not be loaded');
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  const reload = useCallback(() => setRefresh({}), []);

  const create = useCallback(
    async (request: {
      source_deal_id: string;
      name: string | null;
      acquisition_date: string;
      property_type: string | null;
      market: string | null;
    }) => {
      const created = await createManagedAsset(request);
      setRefresh({});
      return created;
    },
    [],
  );

  return { assets, isLoading, error, reload, create };
}

/** How a keyed request stands for the asset and month currently on screen. */
export type LoadStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface AssetPerformanceState {
  /** The saved reports **of the asset currently open**, in month order. Empty
   * while they are still loading, so read `reportsStatus` to tell "none yet"
   * apart from "not known yet". */
  reports: MonthlyAssetReport[];
  reportsStatus: LoadStatus;
  /** The selected month's authoritative result, or `null` whenever one is not
   * available for the asset **and** month currently selected. */
  performance: AssetPerformanceResponse | null;
  performanceStatus: LoadStatus;
  selectedMonth: string | null;
  error: string | null;
  selectMonth: (month: string) => void;
  reload: () => void;
  saveReport: (request: {
    reporting_month: string;
    budget: OperatingFigures;
    actual: OperatingFigures;
    commentary: string | null;
  }) => Promise<void>;
  saveActuals: (
    month: string,
    request: { actual: OperatingFigures; commentary: string | null },
  ) => Promise<void>;
}

/** One request's settled outcome, tagged with the key that produced it. */
interface Outcome<T> {
  key: string;
  value: T;
  error: string | null;
}

function message(caught: unknown, fallback: string): string {
  return caught instanceof Error ? caught.message : fallback;
}

/**
 * One asset's reports, the selected month, and that month's authoritative
 * result.
 *
 * **Every returned value is derived from the key that produced it.** Each
 * request stores its outcome tagged with the asset -- and, for performance, the
 * month -- it was made for, and the hook returns that outcome only while the
 * tag still matches what is on screen. A previous asset's reports or a previous
 * month's figures are therefore not "cleared" when the selection changes; they
 * simply stop being what this hook returns, in the same render, before anything
 * can paint. Showing Asset A's financials under Asset B's header, or March's
 * while February is selected, is not a race this guards against -- it is a
 * state the model cannot represent.
 *
 * That makes a late response harmless twice over: the in-flight effect is
 * cancelled, and even if it were not, the outcome it writes carries its own key
 * and is ignored.
 *
 * **Loading is derived, not stored.** "Loading" means no settled outcome exists
 * for the current key, which is true synchronously from the moment that key
 * changes. There is deliberately no shared `isLoading` flag: the two requests
 * are independent, and one of them finishing must never be able to declare the
 * other finished -- which is exactly what a single boolean did.
 */
export function useAssetPerformance(managedAssetId: string | null): AssetPerformanceState {
  const [refreshId, setRefreshId] = useState(0);
  const [reportsOutcome, setReportsOutcome] = useState<Outcome<MonthlyAssetReport[]> | null>(null);
  const [performanceOutcome, setPerformanceOutcome] = useState<Outcome<
    AssetPerformanceResponse | null
  > | null>(null);
  // The analyst's explicit month choice, tagged with the asset it was made for
  // so it cannot survive into a different asset.
  const [selection, setSelection] = useState<{ assetId: string; month: string } | null>(null);

  const reportsKey = managedAssetId === null ? null : `${managedAssetId}#${refreshId}`;
  const settledReports =
    reportsKey !== null && reportsOutcome?.key === reportsKey ? reportsOutcome : null;

  const reports =
    settledReports !== null && settledReports.error === null ? settledReports.value : [];
  const reportsStatus: LoadStatus =
    managedAssetId === null
      ? 'idle'
      : settledReports === null
        ? 'loading'
        : settledReports.error !== null
          ? 'error'
          : 'ready';

  // The analyst's choice wins for this asset; otherwise the most recent
  // reported month, which is what an asset manager almost always wants on
  // opening. Both are `null` until this asset's own reports have arrived, so no
  // month is ever selected on the strength of a different asset's reports.
  const chosenMonth =
    selection !== null && selection.assetId === managedAssetId ? selection.month : null;
  const latestMonth = reports.length === 0 ? null : reports[reports.length - 1].reporting_month;
  const selectedMonth = chosenMonth ?? latestMonth;

  const performanceKey =
    managedAssetId === null || selectedMonth === null
      ? null
      : `${managedAssetId}#${selectedMonth}#${refreshId}`;
  const settledPerformance =
    performanceKey !== null && performanceOutcome?.key === performanceKey
      ? performanceOutcome
      : null;

  const performance =
    settledPerformance !== null && settledPerformance.error === null
      ? settledPerformance.value
      : null;
  const performanceStatus: LoadStatus =
    performanceKey === null
      ? 'idle'
      : settledPerformance === null
        ? 'loading'
        : settledPerformance.error !== null
          ? 'error'
          : 'ready';

  const error = settledReports?.error ?? settledPerformance?.error ?? null;

  useEffect(() => {
    if (reportsKey === null || managedAssetId === null) {
      return;
    }
    let cancelled = false;
    listMonthlyReports(managedAssetId)
      .then((loaded) => {
        if (!cancelled) {
          setReportsOutcome({ key: reportsKey, value: loaded, error: null });
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setReportsOutcome({
            key: reportsKey,
            value: [],
            error: message(caught, 'The monthly reports could not be loaded'),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [reportsKey, managedAssetId]);

  useEffect(() => {
    if (performanceKey === null || managedAssetId === null || selectedMonth === null) {
      return;
    }
    let cancelled = false;
    readAssetPerformance(managedAssetId, selectedMonth)
      .then((loaded) => {
        if (!cancelled) {
          setPerformanceOutcome({ key: performanceKey, value: loaded, error: null });
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setPerformanceOutcome({
            key: performanceKey,
            value: null,
            error: message(caught, 'The monthly performance could not be loaded'),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [performanceKey, managedAssetId, selectedMonth]);

  const selectMonth = useCallback(
    (month: string) => {
      if (managedAssetId !== null) {
        setSelection({ assetId: managedAssetId, month });
      }
    },
    [managedAssetId],
  );

  const reload = useCallback(() => setRefreshId((current) => current + 1), []);

  const saveReport = useCallback(
    async (request: {
      reporting_month: string;
      budget: OperatingFigures;
      actual: OperatingFigures;
      commentary: string | null;
    }) => {
      if (managedAssetId === null) {
        throw new AssetManagementError('No managed asset is open.');
      }
      await createMonthlyReport(managedAssetId, request);
      setSelection({ assetId: managedAssetId, month: request.reporting_month });
      setRefreshId((current) => current + 1);
    },
    [managedAssetId],
  );

  const saveActuals = useCallback(
    async (month: string, request: { actual: OperatingFigures; commentary: string | null }) => {
      if (managedAssetId === null) {
        throw new AssetManagementError('No managed asset is open.');
      }
      // `budget: null` asserts nothing about the frozen budget, which is the
      // ordinary path -- this call is not the one that may change it.
      await updateMonthlyReportActuals(managedAssetId, month, { ...request, budget: null });
      setRefreshId((current) => current + 1);
    },
    [managedAssetId],
  );

  return {
    reports,
    reportsStatus,
    performance,
    performanceStatus,
    selectedMonth,
    error,
    selectMonth,
    reload,
    saveReport,
    saveActuals,
  };
}
