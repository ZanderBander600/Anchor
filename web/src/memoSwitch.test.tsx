/**
 * Phase 7 Gate P7.10 Stage 4 -- switching memos, through the real App.
 *
 * Ratified at the Stage 4 independent review (Correction 2). `window.confirm`
 * is gone from the memo workflow, and what replaced it has to be proved where
 * it actually runs: in `App`, which owns the open memo, the unsaved-work signal
 * and the navigation the confirmation guards.
 *
 * Four behaviours, all of them consequences rather than appearances:
 *
 * - no native dialog is opened, by anything, at any point;
 * - a switch that would discard unsaved work asks first, and cancelling
 *   navigates nowhere -- the analyst is still in the memo they were editing;
 * - confirming opens the memo they asked for;
 * - a switch that discards nothing asks nothing. A confirmation that appears
 *   when there is nothing at stake teaches people to dismiss confirmations.
 *
 * The dialog's own accessibility -- the modal role, the focused safe action,
 * Escape, the focus trap, the restored focus -- is proved in
 * `web/src/components/ConfirmDialog.test.tsx`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import {
  listDeals,
  listVisibleInvestments,
  listManagedAssets,
  readEvidenceReferences,
  readInvestmentMemo,
  readMemoLibrary,
  readMemoVersions,
  readPublicationReadiness,
  readValuationTimepoints,
  readValuationViews,
  listInvestmentScenarios,
  listInvestmentStrategies,
  listPositionPerspectives,
  listPartnerPerspectives,
  saveInvestmentMemo,
} from './api';
import type { InvestmentMemoDraft, MemoLibraryEntry } from './memoTypes';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    listDeals: vi.fn(),
    listVisibleInvestments: vi.fn(),
    listManagedAssets: vi.fn(),
    readMemoLibrary: vi.fn(),
    readInvestmentMemo: vi.fn(),
    readEvidenceReferences: vi.fn(),
    readMemoVersions: vi.fn(),
    readPublicationReadiness: vi.fn(),
    readValuationTimepoints: vi.fn(),
    readValuationViews: vi.fn(),
    listInvestmentScenarios: vi.fn(),
    listInvestmentStrategies: vi.fn(),
    listPositionPerspectives: vi.fn(),
    listPartnerPerspectives: vi.fn(),
    saveInvestmentMemo: vi.fn(),
  };
});

function entry(id: string, name: string): MemoLibraryEntry {
  return {
    investment_id: id,
    deal_id: id,
    name,
    unit_count: 1,
    asset_type: 'Multifamily',
    asset_subtype: null,
    has_draft: true,
    draft_updated_at: '2026-09-21',
    analyst_recommendation: 'approve_with_conditions',
    committee_decision: null,
    latest_version_id: null,
    latest_version_number: null,
    latest_published_at: null,
    version_count: 0,
  };
}

const RIVERSIDE = entry('inv-1', 'Riverside Commons');
const HARBOR = entry('inv-2', 'Harbor Point');

function draft(investmentId: string): InvestmentMemoDraft {
  return {
    memo_id: `memo-${investmentId}`,
    investment_id: investmentId,
    prepared_by: 'A. Analyst',
    decision_ask: '',
    analyst_recommendation: 'insufficient_information',
    executive_summary: '',
    execution_complexity: 'moderate',
    return_on_time_notes: '',
    selected_decision: null,
    items: [],
    risk_items: [],
    term_items: [],
    evidence_ids: [],
    selected_valuation_timepoint_ids: [],
    created_at: '2026-09-21',
    updated_at: '2026-09-21',
  };
}

let nativeDialogs: string[] = [];

beforeEach(() => {
  nativeDialogs = [];
  // Any native dialog anywhere in this flow is a failure, so they are recorded
  // rather than merely stubbed -- a stub that silently answered would hide one.
  for (const name of ['confirm', 'alert', 'prompt'] as const) {
    vi.spyOn(window, name).mockImplementation(((message?: string) => {
      nativeDialogs.push(`${name}: ${message ?? ''}`);
      return name === 'confirm' ? true : undefined;
    }) as never);
  }

  vi.mocked(listDeals).mockResolvedValue([]);
  vi.mocked(listVisibleInvestments).mockResolvedValue([]);
  vi.mocked(listManagedAssets).mockResolvedValue([]);
  vi.mocked(readMemoLibrary).mockResolvedValue([RIVERSIDE, HARBOR]);
  vi.mocked(readInvestmentMemo).mockImplementation((investmentId: string) =>
    Promise.resolve(draft(investmentId)),
  );
  vi.mocked(readEvidenceReferences).mockResolvedValue([]);
  vi.mocked(readMemoVersions).mockResolvedValue([]);
  vi.mocked(readPublicationReadiness).mockResolvedValue({
    investment_id: 'inv-1',
    publishable: false,
    refusals: [],
  });
  vi.mocked(readValuationTimepoints).mockResolvedValue([]);
  vi.mocked(readValuationViews).mockResolvedValue(null as never);
  vi.mocked(listInvestmentScenarios).mockResolvedValue([]);
  vi.mocked(listInvestmentStrategies).mockResolvedValue([]);
  vi.mocked(listPositionPerspectives).mockResolvedValue({ investment_id: 'inv-1', positions: [] });
  vi.mocked(listPartnerPerspectives).mockResolvedValue({ investment_id: 'inv-1', partners: [] });
  vi.mocked(saveInvestmentMemo).mockImplementation((investmentId: string) =>
    Promise.resolve(draft(investmentId)),
  );
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** Opens the Investment Committee library and the named memo. */
async function openMemo(name: string): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: 'Investment Committee' }));
  const row = (await screen.findByRole('row', { name: new RegExp(name) })) as HTMLElement;
  await userEvent.click(within(row).getByRole('button', { name: 'Open memo' }));
}

/** Types into the memo's own narrative field, which is what makes it unsaved. */
async function makeUnsaved(): Promise<void> {
  const field = await screen.findByLabelText(/Decision ask/i);
  await userEvent.type(field, 'Approve at $12.0m.');
}

describe('P7.10 Stage 4 -- switching memos', () => {
  it('asks before discarding unsaved work, and cancelling navigates nowhere', async () => {
    render(<App />);
    await openMemo('Riverside Commons');
    await makeUnsaved();

    await openMemo('Harbor Point');

    // It asked, in the application, naming both memos and what is at stake.
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/Open Harbor Point\?/)).toBeTruthy();
    expect(dialog.textContent).toContain('Riverside Commons');
    expect(dialog.textContent).toContain('unsaved changes');
    expect(nativeDialogs).toEqual([]);

    await userEvent.click(screen.getByRole('button', { name: 'Keep editing' }));

    // Nowhere. The memo they nearly opened was never even read, so nothing of
    // it is on screen and nothing of theirs was replaced.
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(vi.mocked(readInvestmentMemo).mock.calls.map(([id]) => id)).not.toContain('inv-2');
    expect(screen.queryByRole('heading', { name: /Harbor Point/ })).toBeNull();

    // And the work is still there: going back into the memo they were editing
    // finds the sentence they had typed, unsaved and intact.
    await openMemo('Riverside Commons');
    expect(await screen.findByDisplayValue('Approve at $12.0m.')).toBeTruthy();
  });

  it('opens the other memo when the discard is confirmed', async () => {
    render(<App />);
    await openMemo('Riverside Commons');
    await makeUnsaved();
    await openMemo('Harbor Point');

    await userEvent.click(await screen.findByRole('button', { name: 'Discard and open' }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Harbor Point/ })).toBeTruthy();
    });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(nativeDialogs).toEqual([]);
  });

  it('asks nothing when there is nothing to discard', async () => {
    render(<App />);
    await openMemo('Riverside Commons');
    // No edit: everything the analyst has is already persisted.

    await openMemo('Harbor Point');

    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Harbor Point/ })).toBeTruthy();
    });
    expect(nativeDialogs).toEqual([]);
  });

  it('reopening the memo already open asks nothing, even with unsaved work', async () => {
    render(<App />);
    await openMemo('Riverside Commons');
    await makeUnsaved();

    await openMemo('Riverside Commons');

    // Nothing would be discarded, so nothing is asked -- and the draft is
    // still there.
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(nativeDialogs).toEqual([]);
    expect(await screen.findByDisplayValue('Approve at $12.0m.')).toBeTruthy();
  });
});
