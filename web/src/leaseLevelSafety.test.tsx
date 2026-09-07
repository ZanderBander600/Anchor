/**
 * D5.1B -- what an analyst actually sees when a Lease-Level deal reaches a
 * surface that cannot underwrite it.
 *
 * The architecture test proves dispatch is total; this proves the *rendered*
 * outcome is honest. Two things must both hold at the end of D5.1B, and they
 * pull in opposite directions:
 *
 *   1. A Lease-Level deal is labelled **Lease-Level** wherever a mode is shown,
 *      and its unavailable figures read as unavailable -- never as Quick's.
 *   2. The analyst still **cannot select** Lease-Level. Knowing the name is not
 *      offering the workflow. D5.5A inverts this guardrail when the workspace
 *      behind it exists.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { AppSidebar } from './components/AppSidebar';
import { DealLibraryPanel } from './components/DealLibraryPanel';
import { DealHeader } from './components/DealHeader';
import { resultsViewsFor } from './underwrite';
import { UnsupportedOperatingModeError, requireImplementedMode } from './operatingMode';
import type { Deal } from './types';

afterEach(() => {
  cleanup();
});

const QUICK_INPUTS: Deal['inputs'] = {
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

/**
 * A Lease-Level deal as the *frontend* would meet one.
 *
 * Not reachable through the running app at D5.1B -- the backend refuses to
 * persist Lease-Level deals (D5.1A) and D5.4 owns the schema that will hold
 * them -- so this fixture is a future-proofing probe, exactly like the
 * unreachable third arms it exercises. It carries no Quick or Detailed
 * assumptions, because a Lease-Level deal genuinely has neither.
 */
function leaseLevelDeal(): Deal {
  return {
    id: 'deal-ll',
    name: 'Rolling Rent Roll',
    operating_mode: 'lease_level',
    inputs: null,
    terms: null,
    detailed_operating_inputs: null,
    deal_context: null,
    analysis_snapshot: null,
    ai_snapshot: null,
    created_at: '2027-01-01T12:00:00+00:00',
    updated_at: '2027-01-01T12:00:00+00:00',
  };
}

function quickDeal(): Deal {
  return { ...leaseLevelDeal(), id: 'deal-q', name: 'Quick Deal', operating_mode: 'quick', inputs: QUICK_INPUTS };
}

// =============================================================================
// 1. A Lease-Level deal is labelled Lease-Level, everywhere a mode is shown
// =============================================================================

describe('deal identity is never mislabelled', () => {
  it('the sidebar labels a Lease-Level deal Lease-Level, not Quick', () => {
    render(
      <AppSidebar
        deals={[leaseLevelDeal()]}
        isDealsLoading={false}
        activeDealId={null}
        view="workspace"
        onOpenLibrary={vi.fn()}
        onNewDeal={vi.fn()}
        onOpenDeal={vi.fn()}
      />,
    );

    expect(screen.getByText(/Lease-Level/)).toBeTruthy();
    expect(screen.queryByText(/·\s*Quick/)).toBeNull();
  });

  it('the Deal Library labels a Lease-Level deal Lease-Level, not Quick', () => {
    render(
      <DealLibraryPanel
        deals={[leaseLevelDeal()]}
        isLoading={false}
        error={null}
        onOpen={vi.fn()}
        onDuplicate={vi.fn()}
        onDelete={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('Lease-Level')).toBeTruthy();
    expect(screen.queryByText('Quick')).toBeNull();
    expect(screen.queryByText('Detailed')).toBeNull();
  });

  it('shows an unavailable purchase price rather than borrowing another mode’s', () => {
    render(
      <DealLibraryPanel
        deals={[leaseLevelDeal()]}
        isLoading={false}
        error={null}
        onOpen={vi.fn()}
        onDuplicate={vi.fn()}
        onDelete={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    // `formatCurrency(null)` is the app's existing neutral unavailable state.
    expect(screen.getByText(/N\/A/)).toBeTruthy();
    // Emphatically not "$0", which would read as a real, stated price of zero.
    expect(screen.queryByText(/\$0\b/)).toBeNull();
  });

  it('still labels Quick deals Quick', () => {
    render(
      <DealLibraryPanel
        deals={[quickDeal()]}
        isLoading={false}
        error={null}
        onOpen={vi.fn()}
        onDuplicate={vi.fn()}
        onDelete={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('Quick')).toBeTruthy();
    expect(screen.getByText(/\$50,000,000/)).toBeTruthy();
  });
});

// =============================================================================
// 2. The visible mode selector still offers only working modes
//
// Inverted by D5.5A, deliberately. Until the Lease-Level workspace exists,
// offering the choice would be offering a dead end.
// =============================================================================

describe('the visible mode selector', () => {
  function renderHeader() {
    render(
      <DealHeader
        dealName="A deal"
        onDealNameChange={vi.fn()}
        operatingMode="quick"
        onOperatingModeChange={vi.fn()}
        isSavedDeal={false}
        isSaving={false}
        saveStatus="saved"
        lastSavedAt={null}
        error={null}
        onSaveDeal={vi.fn()}
        onAnalyze={vi.fn()}
        isAnalyzing={false}
        onDuplicateDeal={vi.fn()}
        onDeleteDeal={vi.fn()}
      />,
    );
  }

  it('offers exactly the two implemented modes', () => {
    renderHeader();
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'Quick Underwrite',
      'Detailed Underwrite',
    ]);
  });

  it('does not offer Lease-Level', () => {
    renderHeader();
    expect(screen.queryByRole('tab', { name: /Lease-Level/i })).toBeNull();
  });
});

// =============================================================================
// 3. Mode-aware helpers refuse Lease-Level rather than substituting a mode
// =============================================================================

describe('the Lease-Level safe-behaviour matrix', () => {
  it('resultsViewsFor refuses Lease-Level instead of returning Quick views', () => {
    const quickViews = resultsViewsFor('quick');
    const detailedViews = resultsViewsFor('detailed');

    expect(quickViews.map((view) => view.id)).toEqual([
      'summary',
      'cash-flow',
      'owner-returns',
    ]);
    expect(detailedViews.map((view) => view.id)).toContain('operating-statement');

    let caught: unknown;
    try {
      resultsViewsFor('lease_level');
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(UnsupportedOperatingModeError);
    expect((caught as UnsupportedOperatingModeError).surface).toBe(
      'the Results sub-navigation',
    );
  });

  it('the Underwrite shell refuses Lease-Level rather than rendering Quick', () => {
    expect(requireImplementedMode('quick', 'the Underwrite shell')).toBe('quick');
    expect(requireImplementedMode('detailed', 'the Underwrite shell')).toBe('detailed');
    expect(() => requireImplementedMode('lease_level', 'the Underwrite shell')).toThrow(
      UnsupportedOperatingModeError,
    );
  });

  it('Open Deal refuses a Lease-Level deal rather than opening it as Quick', () => {
    // The narrowing `handleOpenDeal` performs before either branch. Asserted at
    // the seam rather than by driving the whole App, because the App-level path
    // is unreachable until D5.4 can persist such a deal at all.
    expect(() => requireImplementedMode(leaseLevelDeal().operating_mode, 'Open Deal')).toThrow(
      UnsupportedOperatingModeError,
    );
  });
});
