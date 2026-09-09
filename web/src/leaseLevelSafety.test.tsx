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
 *
 * **D5.5A transition.** The workspace now exists, so (2) is inverted rather than
 * deleted: the selector must offer all three modes, and its successor invariant
 * -- that choosing Lease-Level reaches the Lease-Level workspace and not Quick's
 * -- is asserted in `leaseLevelWorkspace.test.tsx`. Rule (1) is unchanged and
 * still binding: a Lease-Level deal is labelled Lease-Level everywhere. The
 * safe-behaviour matrix below keeps every refusal that is still true, and the
 * two that stopped being true are restated as what replaced them.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { AppSidebar } from './components/AppSidebar';
import { DealLibraryPanel } from './components/DealLibraryPanel';
import { DealHeader } from './components/DealHeader';
import { resultsViewsFor } from './underwrite';
import { UnsupportedOperatingModeError, requireUnderwriteWorkspaceMode } from './operatingMode';
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
    // D5.5A: `terms` is the shared `AcquisitionTerms` contract, and a
    // Lease-Level deal genuinely carries one. `inputs` and
    // `detailed_operating_inputs` stay null, because it genuinely carries
    // neither.
    terms: {
      purchase_price: 31_000_000,
      hold_period: 7,
      exit_cap_rate: 0.0625,
      ltv: 0.6,
      interest_rate: 0.055,
      amortization: 30,
      acquisition_cost_pct: 0.015,
      financing_fee_pct: 0.01,
      disposition_cost_pct: 0.0125,
      annual_capex_reserve: 120_000,
      io_period: 2,
    },
    detailed_operating_inputs: null,
    property_inputs: null,
    operating_inputs: null,
    market_leasing: null,
    suites: null,
    leases: null,
    deal_context: null,
    analysis_snapshot: null,
    ai_snapshot: null,
    one_way_sensitivity_snapshot: null,
    two_way_sensitivity_snapshot: null,
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

  it('shows the deal’s own purchase price, never another mode’s', () => {
    // D5.5A transition. D5.1B asserted N/A here, and that was right at the
    // time: no Lease-Level deal could be persisted, so there was no `terms` to
    // read and the honest answer was "unavailable". D5.4 gave the deal `terms`,
    // so the successor invariant is that the row shows *that* number. What is
    // still forbidden is unchanged: reading Quick's `inputs`, which this deal
    // does not populate.
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

    expect(screen.getByText(/\$31,000,000/)).toBeTruthy();
  });

  it('shows an unavailable price for a Lease-Level deal with no terms', () => {
    // The library lists summaries, which carry no `terms`. `null` must still
    // render as the app's neutral unavailable state rather than as zero -- a
    // deal whose price is unknown is not a deal that cost nothing.
    render(
      <DealLibraryPanel
        deals={[{ ...leaseLevelDeal(), terms: null }]}
        isLoading={false}
        error={null}
        onOpen={vi.fn()}
        onDuplicate={vi.fn()}
        onDelete={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText(/N\/A/)).toBeTruthy();
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
// D5.5A: inverted. The workspace behind the choice now exists, so withholding
// the choice would be hiding a shipped workflow -- the opposite failure to the
// one D5.1B was preventing.
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

  it('offers exactly the three published modes', () => {
    renderHeader();
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'Quick Underwrite',
      'Detailed Underwrite',
      'Lease-Level Underwrite',
    ]);
  });

  it('offers Lease-Level, and keeps the two existing tab names byte-identical', () => {
    renderHeader();
    // The existing names are load-bearing: `App.test.tsx` switches modes by
    // clicking them throughout. Adding a third tab must not rename either.
    expect(screen.getByRole('tab', { name: 'Quick Underwrite' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Detailed Underwrite' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Lease-Level Underwrite' })).toBeTruthy();
  });
});

// =============================================================================
// 3. Mode-aware helpers refuse Lease-Level rather than substituting a mode
// =============================================================================

describe('the Lease-Level safe-behaviour matrix', () => {
  it('resultsViewsFor gives Lease-Level its own views, never another mode’s', () => {
    // D5.6 transition. This asserted a refusal, which was the honest answer
    // while nothing could render a Lease-Level result. The successor invariant
    // is the one the refusal was protecting: Lease-Level gets views of its own
    // and inherits neither Quick's nor Detailed's.
    const quickViews = resultsViewsFor('quick').map((view) => view.id);
    const detailedViews = resultsViewsFor('detailed').map((view) => view.id);
    const leaseLevelViews = resultsViewsFor('lease_level').map((view) => view.id);

    expect(quickViews).toEqual(['summary', 'cash-flow', 'owner-returns']);
    expect(detailedViews).toContain('operating-statement');

    expect(leaseLevelViews).toEqual(['summary', 'operating-statement', 'cash-flow']);
    // Not Quick's list, and not Detailed's -- a fallthrough to either would be
    // the exact hazard this file exists for.
    expect(leaseLevelViews).not.toEqual(quickViews);
    expect(leaseLevelViews).not.toEqual(detailedViews);
    // And no Owner Returns: that surface needs one growth rate per mode, which
    // Lease-Level does not have.
    expect(leaseLevelViews).not.toContain('owner-returns');
  });

  it('the shared Quick/Detailed workspace still refuses Lease-Level', () => {
    // D5.5A narrows what this guardrail claims rather than removing it.
    // Lease-Level is implemented -- in its own component. Routing it through
    // `UnderwriteWorkspace` would render a rent-roll deal as a column of scalar
    // assumptions, which is the substitution this refusal exists to prevent.
    expect(requireUnderwriteWorkspaceMode('quick', 'the Underwrite workspace')).toBe('quick');
    expect(requireUnderwriteWorkspaceMode('detailed', 'the Underwrite workspace')).toBe(
      'detailed',
    );
    expect(() =>
      requireUnderwriteWorkspaceMode('lease_level', 'the Underwrite workspace'),
    ).toThrow(UnsupportedOperatingModeError);
  });

  it('Open Deal now opens a Lease-Level deal, and opens it as Lease-Level', () => {
    // D5.1B asserted the opposite here, because no Lease-Level deal could be
    // persisted or rendered. D5.4 made one persistable and D5.5A makes one
    // openable, so the successor invariant is that opening one selects
    // `lease_level` -- never Quick. The behavioural proof lives in
    // `leaseLevelWorkspace.test.tsx`, which drives the real `handleOpenDeal`
    // against a mocked API; what is asserted here is the fixture's own claim,
    // so this file cannot silently start describing a Quick deal.
    expect(leaseLevelDeal().operating_mode).toBe('lease_level');
    expect(leaseLevelDeal().inputs).toBeNull();
    expect(leaseLevelDeal().detailed_operating_inputs).toBeNull();
  });
});
