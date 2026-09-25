/**
 * Refinance & Capital Events V1 Stage 3 -- which Deal, Investment or Unit
 * surface names the acquisition-financing reference.
 *
 * Browser QA finding: a Unit opened from its visible Investment has no Base
 * Capital Structure of its own -- the Deal route answers 409, because the
 * Investment owns the structure -- so the Unit's results were never labeled,
 * and every visit logged a failed request. The Unit is now read through its
 * Investment, counting only refinances of that Unit or of the whole Investment.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { readDealCapitalStructure, readInvestmentCapitalStructure } from './api';
import { useBaseCapitalEvents } from './useRefinancePresence';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    readDealCapitalStructure: vi.fn(),
    readInvestmentCapitalStructure: vi.fn(),
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

describe('a Unit opened from its Investment', () => {
  it('reads the Investment, never the Deal route that refuses it', async () => {
    vi.mocked(readInvestmentCapitalStructure).mockResolvedValue(structureWith({ kind: 'unit', unit_id: 'unit-a' }));
    const { result } = renderHook(() =>
      useBaseCapitalEvents({ investmentId: 'inv-1', unitId: 'unit-a', token: 't' }),
    );

    await waitFor(() => expect(result.current).toBe(true));
    expect(readDealCapitalStructure).not.toHaveBeenCalled();
    expect(readInvestmentCapitalStructure).toHaveBeenCalledWith('inv-1');
  });

  it('is not labeled by another Unit’s refinance', async () => {
    vi.mocked(readInvestmentCapitalStructure).mockResolvedValue(structureWith({ kind: 'unit', unit_id: 'unit-b' }));
    const { result } = renderHook(() =>
      useBaseCapitalEvents({ investmentId: 'inv-1', unitId: 'unit-a', token: 't' }),
    );

    await waitFor(() => expect(readInvestmentCapitalStructure).toHaveBeenCalled());
    await Promise.resolve();
    expect(result.current).toBe(false);
  });

  it('is labeled by a whole-Investment refinance', async () => {
    vi.mocked(readInvestmentCapitalStructure).mockResolvedValue(structureWith({ kind: 'investment', unit_id: null }));
    const { result } = renderHook(() =>
      useBaseCapitalEvents({ investmentId: 'inv-1', unitId: 'unit-a', token: 't' }),
    );

    await waitFor(() => expect(result.current).toBe(true));
  });
});

describe('a Deal or an Investment on its own', () => {
  it('a standalone Deal reads its own structure', async () => {
    vi.mocked(readDealCapitalStructure).mockResolvedValue(structureWith({ kind: 'unit', unit_id: 'deal-1' }));
    const { result } = renderHook(() => useBaseCapitalEvents({ dealId: 'deal-1', token: 't' }));

    await waitFor(() => expect(result.current).toBe(true));
    expect(readInvestmentCapitalStructure).not.toHaveBeenCalled();
  });

  it('an Investment counts any of its refinances', async () => {
    vi.mocked(readInvestmentCapitalStructure).mockResolvedValue(structureWith({ kind: 'unit', unit_id: 'unit-b' }));
    const { result } = renderHook(() => useBaseCapitalEvents({ investmentId: 'inv-1', token: 't' }));

    await waitFor(() => expect(result.current).toBe(true));
  });

  it('reads nothing with nothing open, and reports no refinance', () => {
    const { result } = renderHook(() => useBaseCapitalEvents({ token: 't' }));

    expect(result.current).toBe(false);
    expect(readDealCapitalStructure).not.toHaveBeenCalled();
    expect(readInvestmentCapitalStructure).not.toHaveBeenCalled();
  });
});
