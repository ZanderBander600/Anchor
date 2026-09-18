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

export interface AssetPerformanceState {
  reports: MonthlyAssetReport[];
  performance: AssetPerformanceResponse | null;
  selectedMonth: string | null;
  isLoading: boolean;
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

/** One asset's reports, the selected month, and that month's authoritative
 * performance result.
 *
 * The month list comes from the saved reports, so the picker can only ever
 * offer a month that has one -- there is no way to ask for performance that
 * does not exist.
 */
export function useAssetPerformance(managedAssetId: string | null): AssetPerformanceState {
  const [reports, setReports] = useState<MonthlyAssetReport[]>([]);
  const [performance, setPerformance] = useState<AssetPerformanceResponse | null>(null);
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState<object>({});

  useEffect(() => {
    if (managedAssetId === null) {
      setReports([]);
      setPerformance(null);
      setSelectedMonth(null);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    listMonthlyReports(managedAssetId)
      .then((loaded) => {
        if (cancelled) {
          return;
        }
        setReports(loaded);
        setError(null);
        // Default to the most recent reported month: the one an asset manager
        // is almost always looking for when they open the asset.
        setSelectedMonth((current) => {
          if (current !== null && loaded.some((report) => report.reporting_month === current)) {
            return current;
          }
          return loaded.length === 0 ? null : loaded[loaded.length - 1].reporting_month;
        });
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : 'The monthly reports could not be loaded');
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
  }, [managedAssetId, refresh]);

  useEffect(() => {
    if (managedAssetId === null || selectedMonth === null) {
      setPerformance(null);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    readAssetPerformance(managedAssetId, selectedMonth)
      .then((loaded) => {
        if (!cancelled) {
          setPerformance(loaded);
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setPerformance(null);
          setError(
            caught instanceof Error ? caught.message : 'The monthly performance could not be loaded',
          );
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
  }, [managedAssetId, selectedMonth, refresh]);

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
      setSelectedMonth(request.reporting_month);
      setRefresh({});
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
      setRefresh({});
    },
    [managedAssetId],
  );

  return {
    reports,
    performance,
    selectedMonth,
    isLoading,
    error,
    selectMonth: setSelectedMonth,
    reload: () => setRefresh({}),
    saveReport,
    saveActuals,
  };
}
