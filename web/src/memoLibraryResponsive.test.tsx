/**
 * Phase 7 Gate P7.10 Stage 4 -- the library at phone width, and scopes by name.
 *
 * The two corrections of the second independent review, proved where they
 * actually have to hold.
 *
 * **Correction 1.** The Investment Committee library is a navigation and status
 * surface. At 390px an analyst should be able to find a memo and open it
 * without scrolling sideways, so the same rows are presented as cards. What is
 * checked here is that the cards are not a *second* library: they carry every
 * fact the table carries, from the same description, and exactly one action per
 * memo is live at any width.
 *
 * **Correction 2.** A refusal's scope is shown by the name its own domain gives
 * it, and a scope whose record is gone says so -- never the stored id.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoLibraryPanel } from './components/MemoLibraryPanel';
import { describeEntry } from './memoLibraryRow';
import { NO_SCOPE_SOURCES, publicationScopeLabel } from './memoCatalog';
import type { MemoScopeSources } from './memoCatalog';
import type { MemoLibraryEntry } from './memoTypes';

afterEach(cleanup);

function entry(overrides: Partial<MemoLibraryEntry> = {}): MemoLibraryEntry {
  return {
    investment_id: 'inv-1',
    deal_id: 'deal-1',
    name: 'Harbor Point',
    unit_count: 1,
    asset_type: 'multifamily',
    asset_subtype: 'Garden apartments',
    has_draft: true,
    draft_updated_at: '2026-09-21T10:00:00+00:00',
    analyst_recommendation: 'approve_with_conditions',
    committee_decision: null,
    latest_version_id: 'ver-1',
    latest_version_number: 2,
    latest_published_at: '2026-09-20T10:00:00+00:00',
    version_count: 2,
    strategy_id: 'base',
    scenario_id: 'base',
    perspective: 'project',
    ...overrides,
  };
}

function renderLibrary(entries: MemoLibraryEntry[], onOpen = vi.fn()) {
  render(
    <MemoLibraryPanel
      entries={entries}
      isLoading={false}
      error={null}
      onOpen={onOpen}
      onRetry={vi.fn()}
    />,
  );
  return onOpen;
}

/** The card list, which is the presentation a phone gets. */
function cards(): HTMLElement {
  return screen.getByRole('list', { name: 'Memos in progress' });
}

describe('P7.10 Stage 4 -- the memo library reflows at phone width', () => {
  it('presents every row as a card as well as a table row', () => {
    renderLibrary([entry(), entry({ investment_id: 'inv-2', deal_id: null, name: 'Riverside' })]);

    const listed = within(cards()).getAllByRole('listitem');
    expect(listed).toHaveLength(2);
    // The table presentation of the same rows is still there for desktop.
    expect(
      within(screen.getByRole('group', { name: 'Memos in progress, as a table' })).getAllByRole(
        'row',
      ),
    ).toHaveLength(3); // header + two memos
  });

  it('a card carries every fact the table column carries', () => {
    renderLibrary([entry()]);
    const card = within(cards()).getByRole('listitem');

    expect(card.textContent).toContain('Harbor Point');
    expect(card.textContent).toContain('Deal');
    expect(card.textContent).toContain('Multifamily — Garden apartments');
    expect(card.textContent).toContain('1 Unit');
    expect(card.textContent).toContain('Published v2 · draft open');
    expect(card.textContent).toContain('Approve with Conditions');
    // The committee's own decision, separate from the analyst's (R-F).
    expect(card.textContent).toContain('Not yet recorded');
    expect(card.textContent).toContain('Base Strategy · Base Scenario · Project');
    expect(card.textContent).toContain('Sep 20, 2026');
  });

  it('the name is the heading and is never shortened', () => {
    const long =
      'The Riverside Commons and Harbor Point Consolidated Portfolio, Phase II (North Parcel)';
    renderLibrary([entry({ name: long })]);

    const heading = within(cards()).getByRole('heading', { level: 3 });
    expect(heading.textContent).toContain(long);
    // No ellipsis, no slicing: two neighbouring properties must stay distinct.
    expect(heading.textContent).not.toContain('…');
  });

  it('a card opens the memo it names, and says which one for a screen reader', async () => {
    const onOpen = renderLibrary([entry()]);
    const card = within(cards()).getByRole('listitem');

    const action = within(card).getByRole('button', { name: /Open memo/ });
    expect(action.textContent).toContain('Harbor Point');
    await userEvent.click(action);

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0][0].investment_id).toBe('inv-1');
  });

  it('an unstarted Investment is offered a start action, in both presentations', () => {
    renderLibrary([entry({ has_draft: false, version_count: 0, latest_version_number: null })]);

    // It belongs to the "Start a memo" list, which is already a card list.
    expect(screen.getByRole('button', { name: 'Start memo' })).toBeTruthy();
    expect(screen.queryByRole('list', { name: 'Memos in progress' })).toBeNull();
  });

  it('both presentations are described from one source', () => {
    // The guarantee the correction asked for: the table and the cards cannot
    // disagree about a memo, because neither decides anything.
    const row = describeEntry(entry({ committee_decision: 'approved' }));
    expect(row.status).toBe('Published v2 · draft open');
    expect(row.recommendation).toBe('Approve with Conditions');
    expect(row.decision).toBe('Approved');
    expect(row.action).toBe('Open memo');

    renderLibrary([entry({ committee_decision: 'approved' })]);
    const card = within(cards()).getByRole('listitem');
    const table = screen.getByRole('group', { name: 'Memos in progress, as a table' });
    for (const shown of [row.status, row.recommendation, row.decision]) {
      expect(card.textContent).toContain(shown);
      expect(table.textContent).toContain(shown);
    }
  });

  it('a row with no selected cell omits the line rather than inventing one', () => {
    renderLibrary([entry({ strategy_id: null, scenario_id: null, perspective: null })]);
    expect(within(cards()).getByRole('listitem').textContent).not.toContain('Decision cell');
  });

  it('an authored Strategy is described, never keyed', () => {
    const row = describeEntry(entry({ strategy_id: 'value-add-2', scenario_id: 'downside' }));
    expect(row.cell).toBe('Custom Strategy · Custom Scenario · Project');
    expect(row.cell).not.toContain('value-add-2');
    expect(row.cell).not.toContain('downside');
  });
});

describe('P7.10 Stage 4 -- a refusal names its scope', () => {
  const sources: MemoScopeSources = {
    timepoints: [{ id: 'as-is-3b93ed', label: 'As-Is at closing' }],
    strategies: [{ id: 'base', label: 'Base Strategy' }],
    scenarios: [{ id: 'base', label: 'Base Scenario' }],
    perspectives: [{ id: 'senior', label: 'Senior Loan' }],
    evidence: [{ id: 'ev-1', label: 'Q3 sales comparables' }],
    items: [{ id: 'thesis-1', label: 'Acquired below replacement cost.' }],
  };

  it('uses the label its own register carries', () => {
    expect(
      publicationScopeLabel('valuation_unavailable_for_required_view', 'as-is-3b93ed', sources),
    ).toBe('As-Is at closing');
    expect(publicationScopeLabel('selected_perspective_missing', 'senior', sources)).toBe(
      'Senior Loan',
    );
    expect(publicationScopeLabel('evidence_not_approved', 'ev-1', sources)).toBe(
      'Q3 sales comparables',
    );
    expect(publicationScopeLabel('memo_invalid', 'thesis-1', sources)).toBe(
      'Acquired below replacement cost.',
    );
  });

  it('a record that is gone says so, and never falls back to its id', () => {
    const answers = [
      publicationScopeLabel('valuation_unavailable_for_required_view', 'as-is-gone', sources),
      publicationScopeLabel('selected_perspective_missing', 'mezz', sources),
      publicationScopeLabel('evidence_not_found', 'ev-gone', sources),
      publicationScopeLabel('memo_invalid', 'thesis-gone', sources),
      publicationScopeLabel('selected_strategy_missing', 'strategy-gone', sources),
      publicationScopeLabel('selected_scenario_missing', 'scenario-gone', sources),
      // A code no register claims still refuses to print the id.
      publicationScopeLabel('something_new', 'whatever-id', sources),
    ];

    for (const answer of answers) {
      expect(answer).toContain('no longer available');
    }
    expect(answers.join(' ')).not.toMatch(/as-is-gone|mezz|ev-gone|thesis-gone|whatever-id/);
  });

  it('no scope at all renders nothing rather than an empty line', () => {
    expect(publicationScopeLabel('memo_invalid', null, sources)).toBeNull();
    expect(publicationScopeLabel('memo_invalid', '', sources)).toBeNull();
    expect(publicationScopeLabel('memo_invalid', undefined, sources)).toBeNull();
  });

  it('empty registers degrade honestly rather than to an id', () => {
    expect(
      publicationScopeLabel('valuation_unavailable_for_required_view', 'as-is-1', NO_SCOPE_SOURCES),
    ).toBe('Selected valuation view (no longer available)');
  });
});
