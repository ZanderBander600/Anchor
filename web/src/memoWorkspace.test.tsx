/**
 * Phase 7 Gate P7.10 Stage 4 -- the Investment Memo workstation's behaviour.
 *
 * Drives the real `MemoWorkspace` over the real `useInvestmentMemo` against a
 * mocked `api.ts`. The error classes stay real, so a refusal reaches the hook
 * exactly as the client would raise it.
 *
 * What is proved here is the analyst's workflow: authoring and saving a draft,
 * item identity surviving edits and reorders, claim-level evidence linking,
 * the two decision acts staying apart, publication refusals reaching the
 * analyst as actions, an immutable version, and the absence of any AI surface.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  EvidenceInUseError,
  MemoError,
  PublicationRefusedError,
  deleteEvidenceReference,
  listInvestmentScenarios,
  listInvestmentStrategies,
  listPartnerPerspectives,
  listPositionPerspectives,
  publishInvestmentMemo,
  readCommitteeDecision,
  readEvidenceReferences,
  readInvestmentMemo,
  readMemoReportPreview,
  readMemoVersionFreshness,
  readMemoVersionReport,
  readMemoVersions,
  readPublicationReadiness,
  readValuationTimepoints,
  readValuationViews,
  saveCommitteeDecision,

  saveInvestmentMemo,
} from './api';
import { MemoWorkspace } from './components/MemoWorkspace';
import type {
  InvestmentMemoDraft,
  MemoDraftRequest,
  InvestmentMemoVersion,
  MemoEvidenceReference,
  MemoReportPackage,
  ValuationSurface,
} from './memoTypes';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    deleteEvidenceReference: vi.fn(),
    listInvestmentScenarios: vi.fn(),
    listInvestmentStrategies: vi.fn(),
    listPartnerPerspectives: vi.fn(),
    listPositionPerspectives: vi.fn(),
    publishInvestmentMemo: vi.fn(),
    readCommitteeDecision: vi.fn(),
    readEvidenceReferences: vi.fn(),
    readInvestmentMemo: vi.fn(),
    readMemoReportPreview: vi.fn(),
    readMemoVersionFreshness: vi.fn(),
    readMemoVersionReport: vi.fn(),
    readMemoVersions: vi.fn(),
    readPublicationReadiness: vi.fn(),
    readValuationTimepoints: vi.fn(),
    readValuationViews: vi.fn(),
    saveCommitteeDecision: vi.fn(),
    saveEvidenceReference: vi.fn(),
    saveInvestmentMemo: vi.fn(),
  };
});

const mockSave = vi.mocked(saveInvestmentMemo);
const mockReadMemo = vi.mocked(readInvestmentMemo);
const mockEvidence = vi.mocked(readEvidenceReferences);

const mockDeleteEvidence = vi.mocked(deleteEvidenceReference);
const mockVersions = vi.mocked(readMemoVersions);
const mockReadiness = vi.mocked(readPublicationReadiness);
const mockPublish = vi.mocked(publishInvestmentMemo);
const mockViews = vi.mocked(readValuationViews);
const mockPreview = vi.mocked(readMemoReportPreview);
const mockVersionReport = vi.mocked(readMemoVersionReport);
const mockFreshness = vi.mocked(readMemoVersionFreshness);
const mockDecision = vi.mocked(readCommitteeDecision);
const mockSaveDecision = vi.mocked(saveCommitteeDecision);

// =============================================================================
// Fixtures
// =============================================================================

const SOURCE: MemoEvidenceReference = {
  evidence_id: 'ev-1',
  investment_id: 'inv-1',
  source_kind: 'sales_comp',
  title: 'Q3 sales comparables',
  reference: 'doc://comps/q3',
  as_of_date: null,
  approved: true,
  display_order: 0,
};

const UNAPPROVED: MemoEvidenceReference = {
  ...SOURCE,
  evidence_id: 'ev-2',
  title: 'Broker note',
  approved: false,
  display_order: 1,
};

const DRAFT: InvestmentMemoDraft = {
  memo_id: 'memo-1',
  investment_id: 'inv-1',
  prepared_by: 'A. Analyst',
  decision_ask: 'Approve the acquisition at $10.0m.',
  analyst_recommendation: 'approve_with_conditions',
  executive_summary: 'Core-plus asset, below replacement cost.',
  execution_complexity: 'moderate',
  return_on_time_notes: '',
  selected_decision: {
    strategy_id: 'base',
    scenario_id: 'base',
    perspective: 'project',
    position_id: null,
    partner_id: null,
  },
  items: [
    {
      item_id: 'thesis-1',
      section: 'thesis',
      display_order: 0,
      text: 'Acquired below replacement cost.',
      evidence_ids: ['ev-1'],
    },
    {
      item_id: 'thesis-2',
      section: 'thesis',
      display_order: 1,
      text: 'Rents sit below market.',
      evidence_ids: [],
    },
  ],
  risk_items: [
    {
      item_id: 'risk-1',
      display_order: 0,
      text: 'Concentrated Year-3 rollover.',
      severity: 'moderate',
      residual_risk: 'low',
      mitigant: 'Pre-leasing underway.',
      evidence_ids: [],
    },
  ],
  term_items: [],
  evidence_ids: ['ev-1'],
  selected_valuation_timepoint_ids: ['as-is'],
  created_at: '2026-09-21',
  updated_at: '2026-09-21',
};

const SURFACE: ValuationSurface = {
  investment_id: 'inv-1',
  strategy_id: 'base',
  scenario_id: 'base',
  unit_ids: ['unit-1'],
  hold_period: 5,
  views: [
    {
      timepoint_id: 'as-is',
      kind: 'as_is',
      label: 'As-Is',
      model_month: 0,
      scope_kind: 'investment',
      status: 'available',
      value: 10_909_091,
      unavailable: null,
      unit_views: [],
    },
    {
      timepoint_id: 'exploratory',
      kind: 'stabilized',
      label: 'Stabilized Year 6',
      model_month: 72,
      scope_kind: 'investment',
      status: 'unavailable',
      value: null,
      unavailable: {
        status: 'unavailable',
        reason_code: 'outside_hold_horizon',
        reason: 'Model month 72 is beyond this variant’s five-year hold.',
        scope_id: null,
        model_month: 72,
      },
      unit_views: [],
    },
  ],
  evidence_blocked: [],
  funding_states: [],
  consumed_timepoint_ids: [],
  project_source_fingerprint: 'fp-project',
  structured_source_fingerprint: 'fp-structured',
  valuation_definition_fingerprint: 'fp-def',
  valuation_result_fingerprint: 'fp-res',
};

const VERSION: InvestmentMemoVersion = {
  version_id: 'ver-1',
  investment_id: 'inv-1',
  version_number: 1,
  prepared_by: 'A. Analyst',
  decision_ask: DRAFT.decision_ask,
  analyst_recommendation: 'approve_with_conditions',
  executive_summary: DRAFT.executive_summary,
  execution_complexity: 'moderate',
  return_on_time_notes: '',
  selected_decision: DRAFT.selected_decision!,
  items: DRAFT.items,
  risk_items: DRAFT.risk_items,
  term_items: [],
  evidence: [SOURCE],
  claim_evidence: [
    { claim_kind: 'item', item_id: 'thesis-1', evidence_id: 'ev-1', ordinal: 0 },
  ],
  valuations: [],
  dependencies: [],
  memo_content_fingerprint: 'fp-content',
  published_fingerprint: 'fp-published',
  created_at: '2026-09-21',
};

function reportPackage(overrides: Partial<MemoReportPackage> = {}): MemoReportPackage {
  return {
    origin: 'draft_preview',
    investment_id: 'inv-1',
    investment_name: 'Maple Grove',
    asset_type: 'Multifamily',
    market: null,
    version_number: null,
    version_id: null,
    published_at: null,
    prepared_by: 'A. Analyst',
    generated_at: '2026-09-21 14:00 UTC',
    decision_ask: DRAFT.decision_ask,
    analyst_recommendation: 'Approve with Conditions',
    committee_decision: null,
    committee_note: null,
    executive_summary: DRAFT.executive_summary,
    strategy_label: 'Base Strategy',
    scenario_label: 'Base Scenario',
    perspective_label: 'Project',
    freshness: 'not_applicable',
    verification_code: null,
    key_metrics: [
      { label: 'Purchase Price', value: '$10,000,000', unavailable: null, note: null },
      {
        label: 'DSCR (Year 1)',
        value: null,
        unavailable: {
          reason_code: 'result_unavailable',
          reason: 'This analysis has no debt service.',
          label: 'Unavailable',
        },
        note: null,
      },
    ],
    valuations: [],
    sections: [],
    evidence: [],
    disclosures: [],
    concluding_statement: null,
    confidentiality: 'Confidential -- For Investment Committee Use Only',
    ...overrides,
  };
}

function renderWorkspace() {
  return render(
    <MemoWorkspace investmentId="inv-1" name="Maple Grove" isDeal={false} onClose={() => {}} />,
  );
}

/** Opens one tab once the workspace has finished loading.
 *
 * `findByRole` rather than `getByRole`: the memo loads its draft, sources,
 * definitions and versions before the tablist exists at all, and a test that
 * reached for a tab synchronously would be racing that load rather than
 * exercising the tab. */
async function openTab(name: RegExp): Promise<void> {
  await userEvent.click(await screen.findByRole('tab', { name }));
}

beforeEach(() => {
  vi.clearAllMocks();
  mockReadMemo.mockResolvedValue(DRAFT);
  mockEvidence.mockResolvedValue([SOURCE, UNAPPROVED]);
  vi.mocked(readValuationTimepoints).mockResolvedValue([]);
  mockVersions.mockResolvedValue([]);
  mockViews.mockResolvedValue(SURFACE);
  mockReadiness.mockResolvedValue({ investment_id: 'inv-1', publishable: true, refusals: [] });
  mockPreview.mockResolvedValue(reportPackage());
  mockFreshness.mockResolvedValue({
    investment_id: 'inv-1',
    version_id: 'ver-1',
    version_number: 1,
    freshness: 'current',
    stale_classes: [],
    stale_dependencies: [],
  });
  mockDecision.mockResolvedValue(null);
  vi.mocked(listInvestmentStrategies).mockResolvedValue([]);
  vi.mocked(listInvestmentScenarios).mockResolvedValue([]);
  vi.mocked(listPositionPerspectives).mockResolvedValue({
    investment_id: 'inv-1',
    positions: [],
  });
  vi.mocked(listPartnerPerspectives).mockResolvedValue({
    investment_id: 'inv-1',
    partners: [],
  });
  mockSave.mockImplementation(async (_id, request) => ({
    ...DRAFT,
    ...request,
    memo_id: 'memo-1',
    investment_id: 'inv-1',
    created_at: DRAFT.created_at,
    updated_at: '2026-09-22',
  }));
});

afterEach(cleanup);

// =============================================================================
// Loading and saving a draft
// =============================================================================

describe('the memo draft', () => {
  it('loads the saved draft and reports nothing unsaved', async () => {
    renderWorkspace();
    expect(await screen.findByDisplayValue(DRAFT.decision_ask)).toBeTruthy();
    expect(screen.queryByText('Unsaved changes')).toBeNull();
  });

  it('reports unsaved changes as soon as the analyst types, and clears them on save', async () => {
    renderWorkspace();
    const ask = await screen.findByDisplayValue(DRAFT.decision_ask);

    await userEvent.type(ask, ' Revised.');
    expect(await screen.findByText('Unsaved changes')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText('Unsaved changes')).toBeNull());
  });

  it('keeps the analyst’s edits on screen when a save is refused', async () => {
    // Nothing is rolled back to the server's copy behind their back.
    mockSave.mockRejectedValueOnce(
      new MemoError('The memo could not be saved.', [
        { code: 'blank_decision_ask', message: 'State the decision ask.', item_id: null, field: 'decision_ask' },
      ]),
    );
    renderWorkspace();
    const ask = await screen.findByDisplayValue(DRAFT.decision_ask);
    await userEvent.clear(ask);
    await userEvent.type(ask, 'Edited but refused');

    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));

    expect(await screen.findByText('State the decision ask.')).toBeTruthy();
    expect(screen.getByDisplayValue('Edited but refused')).toBeTruthy();
    expect(screen.getByText('Unsaved changes')).toBeTruthy();
  });

  it('sends display order from the item’s position, never a stored index', async () => {
    renderWorkspace();
    const ask = await screen.findByDisplayValue(DRAFT.decision_ask);
    await userEvent.type(ask, '.');
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));

    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    const request = mockSave.mock.calls[0][1] as MemoDraftRequest;
    expect(request.items.map((item) => item.display_order)).toEqual([0, 1]);
    expect(request.items.map((item) => item.item_id)).toEqual(['thesis-1', 'thesis-2']);
  });
});

// =============================================================================
// Item identity, ordering and removal
// =============================================================================

describe('authoring claims', () => {
  it('editing an item’s text keeps its identity and its sources', async () => {
    renderWorkspace();
    await openTab(/Thesis & Risk/);

    const thesis = await screen.findByDisplayValue('Acquired below replacement cost.');
    await userEvent.type(thesis, ' Confirmed.');
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));

    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    const request = mockSave.mock.calls[0][1] as MemoDraftRequest;
    const edited = request.items.find((item) => item.item_id === 'thesis-1');
    expect(edited?.text).toContain('Confirmed.');
    // The claim keeps the source it rested on.
    expect(edited?.evidence_ids).toEqual(['ev-1']);
  });

  it('reordering swaps two items and leaves their ids intact', async () => {
    renderWorkspace();
    await openTab(/Thesis & Risk/);

    const moveDown = await screen.findAllByRole('button', { name: /Move Investment Thesis down/ });
    await userEvent.click(moveDown[0]);
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));

    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    const request = mockSave.mock.calls[0][1] as MemoDraftRequest;
    const thesisIds = request.items
      .filter((item) => item.section === 'thesis')
      .map((item) => item.item_id);
    expect(thesisIds).toEqual(['thesis-2', 'thesis-1']);
  });

  it('disables the move control at the end of a section rather than doing nothing', async () => {
    renderWorkspace();
    await openTab(/Thesis & Risk/);

    const moveUp = await screen.findAllByRole('button', { name: /Move Investment Thesis up/ });
    expect((moveUp[0] as HTMLButtonElement).disabled).toBe(true);
  });

  it('confirms a removal inline, with Cancel focused, and never a native dialog', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm');
    renderWorkspace();
    await openTab(/Thesis & Risk/);

    const remove = await screen.findAllByRole('button', { name: /Remove Investment Thesis/ });
    await userEvent.click(remove[0]);

    const group = await screen.findByRole('group', { name: /Confirm removing Investment Thesis/ });
    expect(group).toBeTruthy();
    expect(document.activeElement).toBe(within(group).getByRole('button', { name: 'Cancel' }));
    expect(confirmSpy).not.toHaveBeenCalled();

    // Cancelling keeps the item and returns focus to the row's own control.
    await userEvent.click(within(group).getByRole('button', { name: 'Cancel' }));
    expect(screen.getByDisplayValue('Acquired below replacement cost.')).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(remove[0]));
  });

  it('removes the item only after the confirmation is accepted', async () => {
    renderWorkspace();
    await openTab(/Thesis & Risk/);

    const remove = await screen.findAllByRole('button', { name: /Remove Investment Thesis/ });
    await userEvent.click(remove[0]);
    const group = await screen.findByRole('group', { name: /Confirm removing/ });
    await userEvent.click(within(group).getByRole('button', { name: 'Remove' }));

    await waitFor(() =>
      expect(screen.queryByDisplayValue('Acquired below replacement cost.')).toBeNull(),
    );
  });

  it('a new risk is Not Assessed rather than Low', async () => {
    renderWorkspace();
    await openTab(/Thesis & Risk/);
    await userEvent.click(await screen.findByRole('button', { name: 'Add risk' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));

    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    const request = mockSave.mock.calls[0][1] as MemoDraftRequest;
    const added = request.risk_items[request.risk_items.length - 1];
    expect(added.severity).toBe('not_assessed');
    expect(added.residual_risk).toBe('not_assessed');
  });
});

// =============================================================================
// Claim-level evidence (R-G)
// =============================================================================

describe('claim-level evidence', () => {
  it('labels a claim that cites nothing as an analyst assertion', async () => {
    renderWorkspace();
    await openTab(/Thesis & Risk/);
    expect(
      (await screen.findAllByText('Analyst Assertion — Source Not Attached')).length,
    ).toBeGreaterThan(0);
  });

  it('attaches a source to one claim and sends it on that claim only', async () => {
    renderWorkspace();
    await openTab(/Thesis & Risk/);

    // The second thesis item cites nothing; attach the approved source to it.
    const attach = await screen.findAllByRole('button', { name: 'Attach sources' });
    await userEvent.click(attach[1]);
    const picker = await screen.findByRole('group', { name: /Sources supporting: Rents sit below market/ });
    await userEvent.click(within(picker).getByLabelText(/Q3 sales comparables/));

    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(mockSave).toHaveBeenCalled());

    const request = mockSave.mock.calls[0][1] as MemoDraftRequest;
    expect(request.items.find((item) => item.item_id === 'thesis-2')?.evidence_ids).toEqual(['ev-1']);
    // The other claim is untouched.
    expect(request.items.find((item) => item.item_id === 'thesis-1')?.evidence_ids).toEqual(['ev-1']);
  });

  it('shows a source’s approval state beside it, in words', async () => {
    renderWorkspace();
    await openTab(/Thesis & Risk/);
    const attach = await screen.findAllByRole('button', { name: 'Attach sources' });
    await userEvent.click(attach[0]);

    const picker = await screen.findByRole('group', { name: /Sources supporting/ });
    expect(within(picker).getByText(/Not approved/)).toBeTruthy();
  });

  it('explains why a source in use cannot be removed', async () => {
    mockDeleteEvidence.mockRejectedValueOnce(
      new EvidenceInUseError('The source is still cited.', 'ev-1', ['as-is'], true),
    );
    renderWorkspace();
    await openTab(/Evidence/);

    const remove = await screen.findAllByRole('button', { name: 'Remove' });
    await userEvent.click(remove[0]);
    const group = await screen.findByRole('group', { name: /Confirm removing/ });
    await userEvent.click(within(group).getByRole('button', { name: 'Remove' }));

    expect(await screen.findByText('This source is still in use')).toBeTruthy();
    expect(screen.getByText(/A claim in this memo cites it/)).toBeTruthy();
  });

  it('a new source is not approved by default', async () => {
    renderWorkspace();
    await openTab(/Evidence/);
    await userEvent.click(await screen.findByRole('button', { name: 'Add source' }));

    const editor = await screen.findByRole('group', { name: 'Source details' });
    const approve = within(editor).getByLabelText(/Approved — this source may support/);
    expect((approve as HTMLInputElement).checked).toBe(false);
  });
});

// =============================================================================
// Valuation selection
// =============================================================================

describe('valuation views', () => {
  it('shows an unavailable view with its own reason and no number', async () => {
    renderWorkspace();
    await openTab(/Valuation/);

    const row = (await screen.findByText('Stabilized Year 6')).closest('tr') as HTMLElement;
    expect(within(row).getByText('Unavailable')).toBeTruthy();
    // The *translated* sentence, not the backend's own: that one names the
    // Investment and the timepoint by their opaque ids, which is exactly what
    // must not reach an analyst view.
    expect(within(row).getByText(/beyond the selected analysis/)).toBeTruthy();
    expect(within(row).queryByText(/5898557bc6b149c9a4994097272d8aea/)).toBeNull();
    expect(within(row).queryByText('$0')).toBeNull();
  });

  it('marks an unselected view as exploratory rather than as a problem', async () => {
    renderWorkspace();
    await openTab(/Valuation/);
    const row = (await screen.findByText('Stabilized Year 6')).closest('tr') as HTMLElement;
    expect(within(row).getByText('Exploratory — not included')).toBeTruthy();
  });

  it('including a view is an explicit stored choice', async () => {
    renderWorkspace();
    await openTab(/Valuation/);

    await userEvent.click(
      await screen.findByLabelText('Include Stabilized Year 6 in this memo'),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));

    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    const request = mockSave.mock.calls[0][1] as MemoDraftRequest;
    expect(request.selected_valuation_timepoint_ids).toEqual(['as-is', 'exploratory']);
  });
});

// =============================================================================
// Publication
// =============================================================================

describe('publication', () => {
  it('groups a refusal into the action that fixes it and keeps the backend’s reason', async () => {
    mockReadiness.mockResolvedValue({
      investment_id: 'inv-1',
      publishable: false,
      refusals: [
        {
          code: 'valuation_unavailable_for_required_view',
          message: 'The view “Stabilized Year 6” has no value at this timepoint.',
          scope_id: 'exploratory',
          field: null,
          unavailable_reason: 'outside_hold_horizon',
        },
      ],
    });
    renderWorkspace();
    await openTab(/Preview & Publish/);

    expect(await screen.findByText('Resolve the included valuations')).toBeTruthy();
    expect(
      screen.getByText('The view “Stabilized Year 6” has no value at this timepoint.'),
    ).toBeTruthy();
    expect(screen.getByText('Affects: exploratory')).toBeTruthy();
  });

  it('cannot publish while the draft has unsaved changes', async () => {
    renderWorkspace();
    const ask = await screen.findByDisplayValue(DRAFT.decision_ask);
    await userEvent.type(ask, ' edited');
    await openTab(/Preview & Publish/);

    const publish = await screen.findByRole('button', { name: 'Publish version' });
    expect((publish as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/This memo has unsaved changes/)).toBeTruthy();
  });

  it('publishing asks for an explicit confirmation first', async () => {
    mockPublish.mockResolvedValue(VERSION);
    mockVersionReport.mockResolvedValue({
      investment_id: 'inv-1',
      version_id: 'ver-1',
      report: reportPackage({
        origin: 'published_version',
        version_number: 1,
        version_id: 'ver-1',
      }),
      unavailable: null,
    });
    renderWorkspace();
    await openTab(/Preview & Publish/);

    await userEvent.click(await screen.findByRole('button', { name: 'Publish version' }));
    expect(mockPublish).not.toHaveBeenCalled();

    const confirm = await screen.findByRole('group', { name: 'Confirm publication' });
    await userEvent.click(within(confirm).getByRole('button', { name: 'Publish' }));
    await waitFor(() => expect(mockPublish).toHaveBeenCalledWith('inv-1'));
  });

  it('a refused publication keeps the analyst in context with the issue focused', async () => {
    mockPublish.mockRejectedValueOnce(
      new PublicationRefusedError('Refused', [
        {
          code: 'evidence_not_approved',
          message: 'The memo cites “Broker note”, which is not approved.',
          scope_id: 'ev-2',
          field: null,
          unavailable_reason: null,
        },
      ]),
    );
    renderWorkspace();
    await openTab(/Preview & Publish/);

    await userEvent.click(await screen.findByRole('button', { name: 'Publish version' }));
    const confirm = await screen.findByRole('group', { name: 'Confirm publication' });
    await userEvent.click(within(confirm).getByRole('button', { name: 'Publish' }));

    expect(await screen.findByText('Approve the cited sources')).toBeTruthy();
    const region = screen.getByRole('group', {
      name: 'Reasons this memo cannot be published',
    });
    await waitFor(() => expect(document.activeElement).toBe(region));
  });
});

// =============================================================================
// The published record and the committee's own decision
// =============================================================================

describe('published versions', () => {
  beforeEach(() => {
    mockVersions.mockResolvedValue([VERSION]);
    mockVersionReport.mockResolvedValue({
      investment_id: 'inv-1',
      version_id: 'ver-1',
      report: reportPackage({
        origin: 'published_version',
        version_number: 1,
        version_id: 'ver-1',
        published_at: '2026-09-21',
        freshness: 'current',
        verification_code: 'fp-published',
      }),
      unavailable: null,
    });
  });

  it('offers a PDF download for a published version and for nothing else', async () => {
    renderWorkspace();
    await openTab(/Published Versions/);

    const link = await screen.findByRole('link', { name: 'Download PDF' });
    expect(link.getAttribute('href')).toContain('/memo-versions/ver-1/exports/investment-memo.pdf');
    expect(screen.getAllByRole('link', { name: 'Download PDF' }).length).toBe(1);
  });

  it('opens a published version read-only, with a route back to the draft', async () => {
    renderWorkspace();
    await openTab(/Published Versions/);
    await userEvent.click(await screen.findByRole('button', { name: 'Open' }));

    expect(await screen.findByText('Published memo')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Back to draft' })).toBeTruthy();
    // No authoring control is on screen beside an immutable record.
    expect(screen.queryByRole('button', { name: 'Save draft' })).toBeNull();
    expect(screen.queryByRole('tab', { name: /Thesis & Risk/ })).toBeNull();
  });

  it('reports a stale version without presenting it as current', async () => {
    mockFreshness.mockResolvedValue({
      investment_id: 'inv-1',
      version_id: 'ver-1',
      version_number: 1,
      freshness: 'stale',
      stale_classes: ['business_plan'],
      stale_dependencies: [],
    });
    renderWorkspace();
    await openTab(/Published Versions/);

    expect(await screen.findByText('Analysis has changed')).toBeTruthy();
    expect(screen.getByText(/Changed since publication: Business Plan/)).toBeTruthy();
  });

  it('records the committee decision as its own act, never the recommendation', async () => {
    mockSaveDecision.mockResolvedValue({
      memo_version_id: 'ver-1',
      decision: 'deferred',
      decision_note: 'Revisit after the report.',
      decided_at: null,
      created_at: '2026-09-22',
      updated_at: '2026-09-22',
    });
    renderWorkspace();
    await openTab(/Published Versions/);

    expect(await screen.findByText('Not yet recorded')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Record decision' }));

    const form = await screen.findByRole('group', { name: 'Record the committee decision' });
    await userEvent.selectOptions(
      within(form).getByLabelText('Committee outcome'),
      'deferred',
    );
    await userEvent.click(within(form).getByRole('button', { name: 'Record decision' }));

    await waitFor(() =>
      expect(mockSaveDecision).toHaveBeenCalledWith('inv-1', 'ver-1', {
        decision: 'deferred',
        decision_note: null,
        decided_at: null,
      }),
    );
    // The analyst's recommendation is untouched by the committee's act.
    expect(mockSave).not.toHaveBeenCalled();
  });

  it('offers only committee outcomes, never analyst recommendations', async () => {
    renderWorkspace();
    await openTab(/Published Versions/);
    await userEvent.click(await screen.findByRole('button', { name: 'Record decision' }));

    const form = await screen.findByRole('group', { name: 'Record the committee decision' });
    const select = within(form).getByLabelText('Committee outcome');
    const options = within(select as HTMLElement)
      .getAllByRole('option')
      .map((option) => option.textContent);
    expect(options).toContain('Deferred');
    expect(options).not.toContain('Insufficient Information');
    expect(options).not.toContain('Revise and Resubmit');
  });
});

// =============================================================================
// The preview, and the absence of AI
// =============================================================================

describe('the report preview', () => {
  it('is unmistakably a draft', async () => {
    renderWorkspace();
    await openTab(/Preview & Publish/);

    expect(await screen.findByText('Draft — Not Published')).toBeTruthy();
    expect(screen.getByText(/Figures follow the current analysis/)).toBeTruthy();
  });

  it('prints an unavailable metric as its label rather than a zero', async () => {
    renderWorkspace();
    await openTab(/Preview & Publish/);

    const dscr = (await screen.findByText('DSCR (Year 1)')).closest('.memo-metric') as HTMLElement;
    expect(within(dscr).getByText('Unavailable')).toBeTruthy();
    expect(within(dscr).queryByText('$0')).toBeNull();
    expect(within(dscr).queryByText('$10,000,000')).toBeNull();
  });

  it('shows the two decision acts as different things', async () => {
    renderWorkspace();
    await openTab(/Preview & Publish/);

    // Scoped to the rendered report: every panel stays mounted, so the
    // Decision Summary tab's own heading is legitimately in the DOM too, and an
    // unscoped query would be asserting about the wrong surface.
    const report = (await screen.findByText('Investment Committee Memorandum')).closest(
      'article',
    ) as HTMLElement;
    expect(within(report).getByText('Analyst Recommendation')).toBeTruthy();
    expect(within(report).getByText('Investment Committee Decision')).toBeTruthy();
    expect(within(report).getByText('Approve with Conditions')).toBeTruthy();
    expect(within(report).getByText('Not yet recorded')).toBeTruthy();
  });
});

describe('no AI surface', () => {
  it('the workspace offers no AI tab, panel or control', async () => {
    renderWorkspace();
    await screen.findByDisplayValue(DRAFT.decision_ask);

    const tabs = screen.getAllByRole('tab').map((tab) => tab.textContent ?? '');
    expect(tabs).toEqual([
      'Decision Summary',
      'Valuation',
      'Thesis & Risk',
      'Evidence',
      'Preview & Publish',
      'Published Versions',
    ]);
    expect(screen.queryByText(/\bAI\b/)).toBeNull();
    expect(screen.queryByText(/coming soon/i)).toBeNull();
    // And no disabled placeholder, which the brief forbids as firmly.
    const disabled = screen
      .getAllByRole('button')
      .filter((button) => (button as HTMLButtonElement).disabled)
      .map((button) => button.textContent ?? '');
    expect(disabled.join(' ')).not.toMatch(/\bAI\b/);
  });
});
