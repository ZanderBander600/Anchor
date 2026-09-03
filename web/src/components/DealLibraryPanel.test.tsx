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
  acquisition_cost_pct: 0,
  financing_fee_pct: 0,
  disposition_cost_pct: 0,
  annual_capex_reserve: 0,
  io_period: 0,
};

function dealFixture(overrides: Partial<Deal> = {}): Deal {
  return {
    id: 'deal-1',
    name: '111 Main St',
    operating_mode: 'quick',
    inputs: GOLDEN_INPUTS,
    terms: null,
    detailed_operating_inputs: null,
    created_at: '2026-09-01T12:00:00+00:00',
    updated_at: '2026-09-01T12:00:00+00:00',
    ...overrides,
  };
}

const GOLDEN_TERMS: NonNullable<Deal['terms']> = {
  purchase_price: 10_000_000,
  hold_period: 5,
  exit_cap_rate: 0.065,
  ltv: 0.6,
  interest_rate: 0.05,
  amortization: 30,
  acquisition_cost_pct: 0.02,
  financing_fee_pct: 0.01,
  disposition_cost_pct: 0.025,
  annual_capex_reserve: 50_000,
  io_period: 2,
};

const GOLDEN_DETAILED_OPERATING_INPUTS: NonNullable<Deal['detailed_operating_inputs']> = {
  gross_potential_rent: 800_000,
  other_income: 20_000,
  vacancy_credit_loss_pct: 0.05,
  property_taxes: 60_000,
  insurance: 20_000,
  utilities: 25_000,
  repairs_maintenance: 20_000,
  other_operating_expenses: 16_000,
  management_fee_pct: 0.05,
  revenue_growth: 0.03,
  expense_growth: 0.03,
};

/** Detailed Operating Model V2.1 Gate 11 -- a Detailed deal fixture:
 * `inputs` stays `null`, `terms`/`detailed_operating_inputs` populated. */
function detailedDealFixture(overrides: Partial<Deal> = {}): Deal {
  return {
    id: 'detailed-deal-1',
    name: 'Golden Detailed Deal',
    operating_mode: 'detailed',
    inputs: null,
    terms: GOLDEN_TERMS,
    detailed_operating_inputs: GOLDEN_DETAILED_OPERATING_INPUTS,
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
    onDuplicate: vi.fn(),
    onDelete: vi.fn(),
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

  it('identifies a Quick deal row with a "Quick" badge', () => {
    renderPanel({ deals: [dealFixture()] });

    expect(screen.getByText('Quick')).toBeTruthy();
    expect(screen.queryByText('Detailed')).toBeNull();
  });

  it('identifies a Detailed deal row with a "Detailed" badge, reading purchase price from terms', () => {
    renderPanel({ deals: [detailedDealFixture()] });

    expect(screen.getByText('Detailed')).toBeTruthy();
    expect(screen.getByText(/Purchase Price \$10,000,000/)).toBeTruthy();
  });

  it('lists Quick and Detailed deals together in one unified library', () => {
    renderPanel({
      deals: [dealFixture({ id: 'q1' }), detailedDealFixture({ id: 'd1' })],
    });

    expect(screen.getByText('111 Main St')).toBeTruthy();
    expect(screen.getByText('Golden Detailed Deal')).toBeTruthy();
    expect(screen.getByText('Quick')).toBeTruthy();
    expect(screen.getByText('Detailed')).toBeTruthy();
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

  describe('duplicate', () => {
    it('calls onDuplicate with the clicked deal', async () => {
      const user = userEvent.setup();
      const onDuplicate = vi.fn();
      const deal = dealFixture();
      renderPanel({ deals: [deal], onDuplicate });

      await user.click(screen.getByRole('button', { name: 'Duplicate' }));

      expect(onDuplicate).toHaveBeenCalledWith(deal);
    });

    it('never asks for confirmation (non-destructive)', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
      const user = userEvent.setup();
      renderPanel({ deals: [dealFixture()] });

      await user.click(screen.getByRole('button', { name: 'Duplicate' }));

      expect(confirmSpy).not.toHaveBeenCalled();
      confirmSpy.mockRestore();
    });
  });

  describe('delete', () => {
    it('requires confirmation before calling onDelete', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
      const user = userEvent.setup();
      const onDelete = vi.fn();
      const deal = dealFixture();
      renderPanel({ deals: [deal], onDelete });

      await user.click(screen.getByRole('button', { name: 'Delete' }));

      expect(confirmSpy).toHaveBeenCalledTimes(1);
      expect(confirmSpy.mock.calls[0][0]).toContain('111 Main St');
      expect(onDelete).toHaveBeenCalledWith(deal);
      confirmSpy.mockRestore();
    });

    it('does not call onDelete when the confirmation is cancelled', async () => {
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
      const user = userEvent.setup();
      const onDelete = vi.fn();
      renderPanel({ deals: [dealFixture()], onDelete });

      await user.click(screen.getByRole('button', { name: 'Delete' }));

      expect(confirmSpy).toHaveBeenCalledTimes(1);
      expect(onDelete).not.toHaveBeenCalled();
      confirmSpy.mockRestore();
    });
  });
});
