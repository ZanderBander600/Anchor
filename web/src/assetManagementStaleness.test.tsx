/** Gate AM1 -- deferred-request regression tests for `useAssetPerformance`.
 *
 * These drive the real hook with requests the test resolves by hand, so the
 * window between "the analyst changed something" and "the response arrived" is
 * a state the test can inspect rather than a race it has to hope for.
 *
 * The claim under test is not "stale data is cleared quickly". It is that
 * results are *tied to the asset and month that produced them*, so a previous
 * asset's financials cannot render beneath a different asset's header, and a
 * previous month's figures cannot render while another month is selected --
 * not even for one frame.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';

import { ManagedAssetWorkspace } from './components/ManagedAssetWorkspace';
import { DEMO_ASSET, DEMO_PERFORMANCE, DEMO_REPORT } from './assetManagementFixture';
import type {
  AssetPerformanceResponse,
  ManagedAsset,
  MonthlyAssetReport,
} from './assetManagementTypes';
import { useAssetPerformance } from './useManagedAssets';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    listMonthlyReports: vi.fn(),
    readAssetPerformance: vi.fn(),
    createMonthlyReport: vi.fn(),
    updateMonthlyReportActuals: vi.fn(),
  };
});

const api = await import('./api');
const listMonthlyReports = vi.mocked(api.listMonthlyReports);
const readAssetPerformance = vi.mocked(api.readAssetPerformance);

afterEach(cleanup);

/** A promise the test resolves when it chooses. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const ASSET_A: ManagedAsset = { ...DEMO_ASSET, id: 'asset-a', name: 'Harbor Point Apartments' };
const ASSET_B: ManagedAsset = { ...DEMO_ASSET, id: 'asset-b', name: 'Westlake Industrial' };

const MARCH = '2027-03-01';
const FEBRUARY = '2027-02-01';

const REPORT_MARCH: MonthlyAssetReport = { ...DEMO_REPORT, managed_asset_id: 'asset-a' };
const REPORT_FEBRUARY: MonthlyAssetReport = {
  ...DEMO_REPORT,
  managed_asset_id: 'asset-a',
  reporting_month: FEBRUARY,
};

/** March's result: NOI $61,500. */
const MARCH_PERFORMANCE: AssetPerformanceResponse = {
  ...DEMO_PERFORMANCE,
  managed_asset: ASSET_A,
};

/** The same shape with a different actual NOI, everywhere that figure appears
 * -- the summary card *and* the statement row -- so "March is gone" can be
 * asserted over the whole screen rather than one card. */
function withActualNoi(
  source: AssetPerformanceResponse,
  actualNoi: number,
  overrides: { managed_asset?: ManagedAsset; reporting_month?: string } = {},
): AssetPerformanceResponse {
  const monthly = source.result.monthly;
  return {
    ...source,
    managed_asset: overrides.managed_asset ?? source.managed_asset,
    result: {
      ...source.result,
      reporting_month: overrides.reporting_month ?? source.result.reporting_month,
      // The trend renders the same figure in its accessible table, so it has to
      // move too or "March is gone" would be false there.
      noi_trend: source.result.noi_trend.map((point) => ({
        ...point,
        actual_net_operating_income: actualNoi,
      })),
      monthly: {
        ...monthly,
        actual: { ...monthly.actual, net_operating_income: actualNoi },
        lines: monthly.lines.map((line) =>
          line.line === 'net_operating_income'
            ? { ...line, actual: actualNoi, variance: actualNoi - line.budget }
            : line,
        ),
      },
    },
  };
}

/** February's result, distinguishable on screen by its NOI. */
const FEBRUARY_PERFORMANCE = withActualNoi(DEMO_PERFORMANCE, 66000, {
  managed_asset: ASSET_A,
  reporting_month: FEBRUARY,
});

/** Asset B's result, distinguishable by its NOI. */
const ASSET_B_PERFORMANCE = withActualNoi(DEMO_PERFORMANCE, 12345, { managed_asset: ASSET_B });

/** Renders the real workspace over the real hook for `asset`. */
function Harness({ asset }: { asset: ManagedAsset }) {
  const state = useAssetPerformance(asset.id);
  return (
    <ManagedAssetWorkspace asset={asset} state={state} onViewAcquisitionBasis={vi.fn()} />
  );
}

/** The Net Operating Income summary card's headline figure, or null. */
function noiOnScreen(): string | null {
  const card = screen.queryByRole('region', { name: 'Net Operating Income' });
  return card?.querySelector('.am-card-value')?.textContent ?? null;
}

function headingOnScreen(): string {
  return screen.getByRole('heading', { level: 2 }).textContent ?? '';
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useAssetPerformance staleness', () => {
  it('never renders one asset’s results beneath another asset’s identity', async () => {
    const reportsA = deferred<MonthlyAssetReport[]>();
    const performanceA = deferred<AssetPerformanceResponse>();
    const reportsB = deferred<MonthlyAssetReport[]>();
    const performanceB = deferred<AssetPerformanceResponse>();

    listMonthlyReports.mockImplementation((id: string) =>
      id === 'asset-a' ? reportsA.promise : reportsB.promise,
    );
    readAssetPerformance.mockImplementation((id: string) =>
      id === 'asset-a' ? performanceA.promise : performanceB.promise,
    );

    const view = render(<Harness asset={ASSET_A} />);
    await act(async () => {
      reportsA.resolve([REPORT_MARCH]);
      performanceA.resolve(MARCH_PERFORMANCE);
    });
    expect(headingOnScreen()).toBe('Harbor Point Apartments');
    expect(noiOnScreen()).toBe('$61,500');

    // Switch to Asset B. B's requests are still in flight.
    view.rerender(<Harness asset={ASSET_B} />);

    // The header is already B's. Nothing of A's may be under it.
    expect(headingOnScreen()).toBe('Westlake Industrial');
    expect(noiOnScreen()).toBeNull();
    expect(screen.queryByText('$61,500')).toBeNull();

    await act(async () => {
      reportsB.resolve([{ ...REPORT_MARCH, managed_asset_id: 'asset-b' }]);
      performanceB.resolve(ASSET_B_PERFORMANCE);
    });
    expect(headingOnScreen()).toBe('Westlake Industrial');
    expect(noiOnScreen()).toBe('$12,345');
  });

  it('never renders one month’s results while another month is selected', async () => {
    listMonthlyReports.mockResolvedValue([REPORT_FEBRUARY, REPORT_MARCH]);

    const marchPerformance = deferred<AssetPerformanceResponse>();
    const februaryPerformance = deferred<AssetPerformanceResponse>();
    readAssetPerformance.mockImplementation((_id: string, month: string) =>
      month === MARCH ? marchPerformance.promise : februaryPerformance.promise,
    );

    render(<Harness asset={ASSET_A} />);
    await act(async () => {
      marchPerformance.resolve(MARCH_PERFORMANCE);
    });
    expect(noiOnScreen()).toBe('$61,500');

    // Select February. Its response has not arrived.
    const picker = screen.getByLabelText('Reporting Month') as HTMLSelectElement;
    await act(async () => {
      picker.value = FEBRUARY;
      picker.dispatchEvent(new Event('change', { bubbles: true }));
    });

    // March's figures must be gone the moment February is selected.
    expect(picker.value).toBe(FEBRUARY);
    expect(screen.queryByText('$61,500')).toBeNull();
    expect(noiOnScreen()).toBeNull();

    await act(async () => {
      februaryPerformance.resolve(FEBRUARY_PERFORMANCE);
    });
    expect(noiOnScreen()).toBe('$66,000');
  });

  it('does not claim "No reporting yet" before the reports request resolves', async () => {
    const reports = deferred<MonthlyAssetReport[]>();
    listMonthlyReports.mockReturnValue(reports.promise);
    readAssetPerformance.mockReturnValue(new Promise(() => {}));

    render(<Harness asset={ASSET_A} />);

    // Unresolved: the honest statement is that we are loading, not that this
    // asset has never been reported on.
    expect(screen.queryByText('No reporting yet')).toBeNull();
    expect(screen.getByText(/Loading this asset.s reporting history/i)).toBeTruthy();

    await act(async () => {
      reports.resolve([]);
    });

    // Resolved and genuinely empty: now the claim is true.
    expect(screen.getByText('No reporting yet')).toBeTruthy();
  });

  it('ignores a late response for an asset that is no longer open', async () => {
    const reportsA = deferred<MonthlyAssetReport[]>();
    const performanceA = deferred<AssetPerformanceResponse>();
    listMonthlyReports.mockImplementation((id: string) =>
      id === 'asset-a' ? reportsA.promise : Promise.resolve([]),
    );
    readAssetPerformance.mockImplementation((id: string) =>
      id === 'asset-a' ? performanceA.promise : new Promise(() => {}),
    );

    const view = render(<Harness asset={ASSET_A} />);
    view.rerender(<Harness asset={ASSET_B} />);

    // A's responses land *after* the analyst moved to B.
    await act(async () => {
      reportsA.resolve([REPORT_MARCH]);
      performanceA.resolve(MARCH_PERFORMANCE);
    });

    expect(headingOnScreen()).toBe('Westlake Industrial');
    expect(screen.queryByText('$61,500')).toBeNull();
    // B genuinely has no reports, and that is what is shown -- not A's.
    expect(screen.getByText('No reporting yet')).toBeTruthy();
  });

  it('ignores a late response for a month that is no longer selected', async () => {
    listMonthlyReports.mockResolvedValue([REPORT_FEBRUARY, REPORT_MARCH]);

    const marchPerformance = deferred<AssetPerformanceResponse>();
    const februaryPerformance = deferred<AssetPerformanceResponse>();
    readAssetPerformance.mockImplementation((_id: string, month: string) =>
      month === MARCH ? marchPerformance.promise : februaryPerformance.promise,
    );

    render(<Harness asset={ASSET_A} />);
    await act(async () => {});

    const picker = screen.getByLabelText('Reporting Month') as HTMLSelectElement;
    await act(async () => {
      picker.value = FEBRUARY;
      picker.dispatchEvent(new Event('change', { bubbles: true }));
    });

    // February is selected, then March's slow response finally lands.
    await act(async () => {
      februaryPerformance.resolve(FEBRUARY_PERFORMANCE);
      marchPerformance.resolve(MARCH_PERFORMANCE);
    });

    expect(picker.value).toBe(FEBRUARY);
    expect(noiOnScreen()).toBe('$66,000');
    expect(screen.queryByText('$61,500')).toBeNull();
  });

  it('does not let a resolved reports request declare performance loaded', async () => {
    listMonthlyReports.mockResolvedValue([REPORT_MARCH]);
    readAssetPerformance.mockReturnValue(new Promise(() => {}));

    render(<Harness asset={ASSET_A} />);
    await act(async () => {});

    // Reports resolved -- the month picker is up -- but performance has not, so
    // no figures may be claimed. A single shared `isLoading` flag let the
    // first request to finish clear it for both.
    expect(screen.getByLabelText('Reporting Month')).toBeTruthy();
    expect(noiOnScreen()).toBeNull();
    expect(screen.getByText(/Loading March 2027 performance/i)).toBeTruthy();
  });
});
