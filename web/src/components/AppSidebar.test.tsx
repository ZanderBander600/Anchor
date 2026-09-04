import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppSidebar } from './AppSidebar';
import type { AppSidebarProps } from './AppSidebar';
import type { Deal } from '../types';

afterEach(cleanup);

function makeDeal(overrides: Partial<Deal> = {}): Deal {
  return {
    id: 'deal-1',
    name: '111 Main St',
    operating_mode: 'quick',
    inputs: {
      purchase_price: 50_000_000,
      current_noi: 3_000_000,
      occupancy: 0.95,
      noi_growth: 0.03,
      hold_period: 5,
      exit_cap_rate: 0.055,
      ltv: 0.65,
      interest_rate: 0.055,
      amortization: 30,
      acquisition_cost_pct: 0,
      financing_fee_pct: 0,
      disposition_cost_pct: 0,
      annual_capex_reserve: 0,
      io_period: 0,
    },
    terms: null,
    detailed_operating_inputs: null,
    deal_context: null,
    analysis_snapshot: null,
    ai_snapshot: null,
    created_at: '2026-09-01T12:00:00+00:00',
    updated_at: '2026-09-01T12:00:00+00:00',
    ...overrides,
  };
}

function makeDetailedDeal(overrides: Partial<Deal> = {}): Deal {
  return makeDeal({
    id: 'detailed-1',
    name: 'Golden Detailed Deal',
    operating_mode: 'detailed',
    inputs: null,
    terms: {
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
    },
    ...overrides,
  });
}

function renderSidebar(overrides: Partial<AppSidebarProps> = {}) {
  const props: AppSidebarProps = {
    deals: [],
    isDealsLoading: false,
    activeDealId: null,
    view: 'workspace',
    onOpenLibrary: vi.fn(),
    onNewDeal: vi.fn(),
    onOpenDeal: vi.fn(),
    ...overrides,
  };
  render(<AppSidebar {...props} />);
  return props;
}

describe('AppSidebar', () => {
  it('renders the brand and the global navigation', () => {
    renderSidebar();

    expect(screen.getByText('Anchor')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Deal Library' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'New Deal' })).toBeTruthy();
  });

  it('calls the caller-supplied global actions', async () => {
    const user = userEvent.setup();
    const props = renderSidebar();

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));
    await user.click(screen.getByRole('button', { name: 'New Deal' }));

    expect(props.onOpenLibrary).toHaveBeenCalledTimes(1);
    expect(props.onNewDeal).toHaveBeenCalledTimes(1);
  });

  it('marks the Deal Library nav item current while the library view is showing', () => {
    renderSidebar({ view: 'library' });

    expect(
      screen.getByRole('button', { name: 'Deal Library' }).getAttribute('aria-current'),
    ).toBe('page');
  });

  it('lists saved deals with their mode and stored purchase price', () => {
    renderSidebar({ deals: [makeDeal(), makeDetailedDeal()] });

    expect(screen.getByText('111 Main St')).toBeTruthy();
    expect(screen.getByText('Quick · $50,000,000')).toBeTruthy();
    expect(screen.getByText('Golden Detailed Deal')).toBeTruthy();
    // Detailed deals carry `terms`, never a fabricated `inputs`.
    expect(screen.getByText('Detailed · $10,000,000')).toBeTruthy();
  });

  it('identifies the active deal, and only that deal', () => {
    renderSidebar({ deals: [makeDeal(), makeDetailedDeal()], activeDealId: 'detailed-1' });

    const active = screen.getByText('Golden Detailed Deal').closest('button');
    const inactive = screen.getByText('111 Main St').closest('button');
    expect(active?.getAttribute('aria-current')).toBe('true');
    expect(inactive?.getAttribute('aria-current')).toBeNull();
  });

  it('marks no deal active while the library view is showing', () => {
    renderSidebar({ deals: [makeDeal()], activeDealId: 'deal-1', view: 'library' });

    expect(screen.getByText('111 Main St').closest('button')?.getAttribute('aria-current')).toBe(
      null,
    );
  });

  it('opens a deal through the caller-supplied handler', async () => {
    const user = userEvent.setup();
    const deal = makeDeal();
    const props = renderSidebar({ deals: [deal] });

    await user.click(screen.getByText('111 Main St'));

    expect(props.onOpenDeal).toHaveBeenCalledWith(deal);
  });

  it('caps the Recent Deals list rather than growing without bound', () => {
    const deals = Array.from({ length: 12 }, (_, index) =>
      makeDeal({ id: `deal-${index}`, name: `Deal ${index}` }),
    );
    renderSidebar({ deals });

    const list = document.querySelector('.sidebar-deal-list') as HTMLElement;
    expect(within(list).getAllByRole('button').length).toBe(8);
    expect(screen.queryByText('Deal 8')).toBeNull();
  });

  it('shows an empty state when nothing is saved, and a loading state while fetching', () => {
    renderSidebar();
    expect(screen.getByText('No saved deals yet.')).toBeTruthy();

    cleanup();
    renderSidebar({ isDealsLoading: true });
    expect(screen.getByText('Loading…')).toBeTruthy();
  });

  it('keeps duplicate and delete out of the deal rows', () => {
    renderSidebar({ deals: [makeDeal()] });

    expect(screen.queryByRole('button', { name: 'Duplicate' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull();
  });

  it('renders Settings as a non-interactive placeholder', () => {
    renderSidebar();

    expect(screen.queryByRole('button', { name: 'Settings' })).toBeNull();
    const settings = screen.getByText('Settings').closest('.sidebar-nav-item');
    expect(settings?.getAttribute('aria-disabled')).toBe('true');
  });

  it('performs no financial calculation -- it renders the stored price verbatim', () => {
    // $50,000,000 is exactly `inputs.purchase_price`; nothing here derives,
    // scales, or recomputes a figure.
    renderSidebar({ deals: [makeDeal({ inputs: { ...makeDeal().inputs!, purchase_price: 1 } })] });

    expect(screen.getByText('Quick · $1')).toBeTruthy();
  });
});
