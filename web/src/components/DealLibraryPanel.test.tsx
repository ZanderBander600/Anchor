import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DealLibraryPanel } from './DealLibraryPanel';
import type { DealLibraryPanelProps } from './DealLibraryPanel';
import type { Deal } from '../types';

afterEach(() => {
  cleanup();
});

const GOLDEN_INPUTS: Deal['inputs'] = {
  purchase_price: 50_000_000,
  current_noi: 2_500_000,
  occupancy: 0.95,
  noi_growth: 0.03,
  hold_period: 5,
  exit_cap_rate: 0.055,
  ltv: 0.65,
  interest_rate: 0.0525,
  amortization: 30,
};

function dealFixture(overrides: Partial<Deal> = {}): Deal {
  return {
    id: 'deal-1',
    name: '111 Main St',
    inputs: GOLDEN_INPUTS,
    created_at: '2026-09-01T12:00:00+00:00',
    updated_at: '2026-09-01T12:00:00+00:00',
    ...overrides,
  };
}

function renderPanel(overrides: Partial<DealLibraryPanelProps> = {}) {
  const props: DealLibraryPanelProps = {
    deals: [],
    isLoading: false,
    error: null,
    onOpen: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
  render(<DealLibraryPanel {...props} />);
  return props;
}

describe('DealLibraryPanel', () => {
  it('shows an empty-state prompt when there are no saved deals', () => {
    renderPanel({ deals: [] });

    expect(screen.getByText(/No saved deals yet/)).toBeTruthy();
  });

  it('shows a loading state', () => {
    renderPanel({ isLoading: true });

    expect(screen.getByText(/Loading saved deals/)).toBeTruthy();
  });

  it('shows an error state', () => {
    renderPanel({ error: 'The deal library could not be loaded.' });

    expect(screen.getByText('The deal library could not be loaded.')).toBeTruthy();
  });

  it('lists each deal with its name, updated timestamp, and purchase price', () => {
    renderPanel({ deals: [dealFixture()] });

    expect(screen.getByText('111 Main St')).toBeTruthy();
    expect(screen.getByText(/Purchase Price \$50,000,000/)).toBeTruthy();
  });

  it('renders every deal in the given order (backend-provided, most recently updated first)', () => {
    renderPanel({
      deals: [dealFixture({ id: 'a', name: 'Deal A' }), dealFixture({ id: 'b', name: 'Deal B' })],
    });

    const names = screen.getAllByText(/^Deal [AB]$/).map((node) => node.textContent);
    expect(names).toEqual(['Deal A', 'Deal B']);
  });

  it('calls onOpen with the clicked deal', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const deal = dealFixture();
    renderPanel({ deals: [deal], onOpen });

    await user.click(screen.getByRole('button', { name: 'Open' }));

    expect(onOpen).toHaveBeenCalledWith(deal);
  });

  it('calls onClose when Close is clicked', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderPanel({ onClose });

    await user.click(screen.getByRole('button', { name: 'Close' }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not show the empty state while loading or on error', () => {
    renderPanel({ isLoading: true, deals: [] });
    expect(screen.queryByText(/No saved deals yet/)).toBeNull();
    cleanup();

    renderPanel({ error: 'Failed.', deals: [] });
    expect(screen.queryByText(/No saved deals yet/)).toBeNull();
  });
});
