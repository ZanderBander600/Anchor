/**
 * Refinance & Capital Events V1 Stage 3 -- which Deal, Investment or Unit
 * surface names the acquisition-financing reference.
 *
 * **Fail closed** (correction round): presence is `loading | error | ready`,
 * and only `ready` answers. A surface wired to the real hook never shows the
 * acquisition-loan levered figures as primary while the answer is unknown --
 * on first render, after a failed read, or while a new analysis is read -- and
 * a Retry recovers.
 *
 * Browser QA finding kept from Stage 3: a Unit opened from its visible
 * Investment is read through that Investment, counting only refinances of that
 * Unit or of the whole Investment.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { readCapitalEventPresence, readDealCapitalStructure, readInvestmentCapitalStructure } from './api';
import { ResultsSummaryPanel } from './components/ResultsSummaryPanel';
import { REFERENCE_CHECKING_VALUE, REFERENCE_ERROR_NOTICE } from './components/AcquisitionReference';
import { ACQUISITION_REFERENCE_LABEL } from './refinanceCatalog';
import { AcquisitionReferenceContext, useBaseCapitalEvents, useStrategyCapitalEvents } from './useRefinancePresence';
import type { AcquisitionResults } from './types';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    readDealCapitalStructure: vi.fn(),
    readInvestmentCapitalStructure: vi.fn(),
    readCapitalEventPresence: vi.fn(),
  };
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

function structureWith(...scopes: { kind: 'unit' | 'investment'; unit_id: string | null }[]) {
  return {
    investment_id: 'inv-1',
    capital_structure: {
      positions: [],
      capital_events: scopes.map((scope, index) => ({ event_id: `e${index}`, scope })),
    },
  } as never;
}

const NONE = structureWith();
const REFINANCED = structureWith({ kind: 'unit', unit_id: 'deal-1' });

/** A promise the test settles when it chooses. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function results(): AcquisitionResults {
  return {
    going_in_cap_rate: 0.08,
    levered_irr: 0.2522,
    unlevered_irr: 0.1194,
    equity_multiple: 2.62,
    dscr_by_year: [3.33],
    min_dscr: 3.33,
    levered_irr_status: 'defined',
    unlevered_irr_status: 'defined',
    levered_cash_on_cash_by_year: [0.14],
    year_1_debt_yield: 0.1333,
    cumulative_operating_distributions_by_year: [560_000],
    exit_noi: 800_000,
    exit_value: 12_500_000,
    loan_amount: 6_000_000,
    acquisition_costs: 0,
    financing_fee: 0,
    initial_equity: 4_000_000,
    monthly_debt_service: 20_000,
    remaining_loan_balance: 4_800_000,
    net_sale_proceeds: 7_700_000,
    disposition_costs: 0,
  } as unknown as AcquisitionResults;
}

/** A Deal surface wired exactly as App wires it: the real hook feeding the
 * provider that the results panel reads. */
function DealSurface({ token }: { token: string }) {
  const presence = useBaseCapitalEvents({ dealId: 'deal-1', token });
  return (
    <AcquisitionReferenceContext.Provider value={presence}>
      <ResultsSummaryPanel results={results()} />
    </AcquisitionReferenceContext.Provider>
  );
}

function leveredShown(): boolean {
  return screen.queryByText('25.22%') !== null || screen.queryByText('2.62x') !== null;
}

describe('presence fails closed on a real surface', () => {
  it('1. never shows the acquisition figures as primary on first render', () => {
    vi.mocked(readDealCapitalStructure).mockReturnValue(deferred<never>().promise);
    render(<DealSurface token="t1" />);

    expect(leveredShown()).toBe(false);
    expect(screen.getAllByText(REFERENCE_CHECKING_VALUE)).toHaveLength(2);
  });

  it('2. a rejected read shows an error and still withholds them', async () => {
    vi.mocked(readDealCapitalStructure).mockRejectedValue(new Error('network'));
    render(<DealSurface token="t1" />);

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(REFERENCE_ERROR_NOTICE);
    expect(leveredShown()).toBe(false);
  });

  it('3. Retry reads again and recovers', async () => {
    const user = userEvent.setup();
    vi.mocked(readDealCapitalStructure).mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(REFINANCED);
    render(<DealSurface token="t1" />);

    await user.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(screen.getAllByText(ACQUISITION_REFERENCE_LABEL)).toHaveLength(2));
    expect(screen.getByText('25.22%')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(readDealCapitalStructure).toHaveBeenCalledTimes(2);
  });

  it('4. a new analysis token returns to loading until its own answer arrives', async () => {
    const second = deferred<never>();
    vi.mocked(readDealCapitalStructure).mockResolvedValueOnce(NONE).mockReturnValueOnce(second.promise);
    const { rerender } = render(<DealSurface token="t1" />);
    await waitFor(() => expect(screen.getByText('25.22%')).toBeTruthy());

    rerender(<DealSurface token="t2" />);

    // The previous "no refinance" is not reused for the new analysis.
    expect(leveredShown()).toBe(false);
    expect(screen.getAllByText(REFERENCE_CHECKING_VALUE)).toHaveLength(2);
    await act(async () => second.resolve(REFINANCED as never));
    expect(screen.getAllByText(ACQUISITION_REFERENCE_LABEL)).toHaveLength(2);
  });

  it('4b. returning to an earlier token still waits for its own answer (A -> B -> A)', async () => {
    const third = deferred<never>();
    vi.mocked(readDealCapitalStructure)
      .mockResolvedValueOnce(NONE)
      .mockResolvedValueOnce(NONE)
      .mockReturnValueOnce(third.promise);
    const { rerender } = render(<DealSurface token="underwrite" />);
    await waitFor(() => expect(screen.getByText('25.22%')).toBeTruthy());
    rerender(<DealSurface token="overview" />);
    await waitFor(() => expect(screen.getByText('25.22%')).toBeTruthy());

    // Back to the first token: its earlier answer is not reused while the
    // structure is read again (a Capital Structure may have been saved since).
    rerender(<DealSurface token="underwrite" />);

    expect(leveredShown()).toBe(false);
    expect(screen.getAllByText(REFERENCE_CHECKING_VALUE)).toHaveLength(2);
    await act(async () => third.resolve(REFINANCED as never));
    expect(screen.getAllByText(ACQUISITION_REFERENCE_LABEL)).toHaveLength(2);
    expect(readDealCapitalStructure).toHaveBeenCalledTimes(3);
  });

  it('6. settled answers keep their presentations: no refinance, and a refinance', async () => {
    vi.mocked(readDealCapitalStructure).mockResolvedValueOnce(NONE);
    const { unmount } = render(<DealSurface token="t1" />);
    await waitFor(() => expect(screen.getByText('25.22%')).toBeTruthy());
    expect(screen.queryByText(ACQUISITION_REFERENCE_LABEL)).toBeNull();
    expect(screen.queryByRole('status')).toBeNull();
    unmount();

    vi.mocked(readDealCapitalStructure).mockResolvedValueOnce(REFINANCED);
    render(<DealSurface token="t1" />);
    await waitFor(() => expect(screen.getAllByText(ACQUISITION_REFERENCE_LABEL)).toHaveLength(2));
    expect(screen.getByText('25.22%')).toBeTruthy();
  });

  it('makes one request per question: no loop while it waits or after it settles', async () => {
    vi.mocked(readDealCapitalStructure).mockResolvedValue(NONE);
    const { rerender } = render(<DealSurface token="t1" />);
    await waitFor(() => expect(screen.getByText('25.22%')).toBeTruthy());
    rerender(<DealSurface token="t1" />);
    rerender(<DealSurface token="t1" />);

    expect(readDealCapitalStructure).toHaveBeenCalledTimes(1);
  });
});

describe('5. Strategy presence cannot masquerade as "no refinance"', () => {
  it('is loading, not an empty set, while the read is in flight', () => {
    vi.mocked(readCapitalEventPresence).mockReturnValue(deferred<never>().promise);
    const { result } = renderHook(() => useStrategyCapitalEvents('inv-1', 'm1'));

    expect(result.current.status).toBe('loading');
    expect('strategies' in result.current).toBe(false);
  });

  it('is an error with Retry, not an empty set, after a failed read', async () => {
    vi.mocked(readCapitalEventPresence)
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce({ investment_id: 'inv-1', strategies: [], acquisition_financing_metrics: [] });
    const { result } = renderHook(() => useStrategyCapitalEvents('inv-1', 'm1'));

    await waitFor(() => expect(result.current.status).toBe('error'));
    expect('strategies' in result.current).toBe(false);
    act(() => {
      if (result.current.status === 'error') {
        result.current.retry();
      }
    });
    await waitFor(() => expect(result.current.status).toBe('ready'));
  });

  it('returns to loading when a matrix run returns to an earlier fingerprint', async () => {
    const third = deferred<never>();
    const none = { investment_id: 'inv-1', strategies: [], acquisition_financing_metrics: [] };
    vi.mocked(readCapitalEventPresence)
      .mockResolvedValueOnce(none)
      .mockResolvedValueOnce(none)
      .mockReturnValueOnce(third.promise);
    const { result, rerender } = renderHook(({ token }) => useStrategyCapitalEvents('inv-1', token), {
      initialProps: { token: 'm1' },
    });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    rerender({ token: 'm2' });
    await waitFor(() => expect(result.current.status).toBe('ready'));

    rerender({ token: 'm1' });

    expect(result.current.status).toBe('loading');
  });

  it('returns to loading for a new matrix run', async () => {
    const second = deferred<never>();
    vi.mocked(readCapitalEventPresence)
      .mockResolvedValueOnce({ investment_id: 'inv-1', strategies: [], acquisition_financing_metrics: [] })
      .mockReturnValueOnce(second.promise);
    const { result, rerender } = renderHook(({ token }) => useStrategyCapitalEvents('inv-1', token), {
      initialProps: { token: 'm1' },
    });
    await waitFor(() => expect(result.current.status).toBe('ready'));

    rerender({ token: 'm2' });

    expect(result.current.status).toBe('loading');
  });
});

describe('a Unit opened from its Investment', () => {
  it('reads the Investment, never the Deal route that refuses it', async () => {
    vi.mocked(readInvestmentCapitalStructure).mockResolvedValue(structureWith({ kind: 'unit', unit_id: 'unit-a' }));
    const { result } = renderHook(() =>
      useBaseCapitalEvents({ investmentId: 'inv-1', unitId: 'unit-a', token: 't' }),
    );

    await waitFor(() => expect(result.current).toEqual({ status: 'ready', configured: true }));
    expect(readDealCapitalStructure).not.toHaveBeenCalled();
    expect(readInvestmentCapitalStructure).toHaveBeenCalledWith('inv-1');
  });

  it('is not labeled by another Unit’s refinance', async () => {
    vi.mocked(readInvestmentCapitalStructure).mockResolvedValue(structureWith({ kind: 'unit', unit_id: 'unit-b' }));
    const { result } = renderHook(() =>
      useBaseCapitalEvents({ investmentId: 'inv-1', unitId: 'unit-a', token: 't' }),
    );

    await waitFor(() => expect(result.current).toEqual({ status: 'ready', configured: false }));
  });

  it('is labeled by a whole-Investment refinance', async () => {
    vi.mocked(readInvestmentCapitalStructure).mockResolvedValue(structureWith({ kind: 'investment', unit_id: null }));
    const { result } = renderHook(() =>
      useBaseCapitalEvents({ investmentId: 'inv-1', unitId: 'unit-a', token: 't' }),
    );

    await waitFor(() => expect(result.current).toEqual({ status: 'ready', configured: true }));
  });
});

describe('a Deal or an Investment on its own', () => {
  it('a standalone Deal reads its own structure', async () => {
    vi.mocked(readDealCapitalStructure).mockResolvedValue(REFINANCED);
    const { result } = renderHook(() => useBaseCapitalEvents({ dealId: 'deal-1', token: 't' }));

    await waitFor(() => expect(result.current).toEqual({ status: 'ready', configured: true }));
    expect(readInvestmentCapitalStructure).not.toHaveBeenCalled();
  });

  it('an Investment counts any of its refinances', async () => {
    vi.mocked(readInvestmentCapitalStructure).mockResolvedValue(structureWith({ kind: 'unit', unit_id: 'unit-b' }));
    const { result } = renderHook(() => useBaseCapitalEvents({ investmentId: 'inv-1', token: 't' }));

    await waitFor(() => expect(result.current).toEqual({ status: 'ready', configured: true }));
  });

  it('with nothing open reads nothing and is a settled "no refinance"', () => {
    const { result } = renderHook(() => useBaseCapitalEvents({ token: 't' }));

    expect(result.current).toEqual({ status: 'ready', configured: false });
    expect(readDealCapitalStructure).not.toHaveBeenCalled();
    expect(readInvestmentCapitalStructure).not.toHaveBeenCalled();
  });
});
