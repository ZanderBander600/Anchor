/**
 * Asset Types 1 -- the frontend classification contract.
 *
 * `docs/architecture/ASSET_TYPES_1_CLASSIFICATION.md`. The vocabulary and
 * subtype rules, the field's labels and announced validation, the Underwrite
 * strip, the Deal Library, the Investment Library's honest multi-type
 * presentation, the Asset Management filters, and the narrow-width CSS.
 * Filtering is presentation only, so every filter test also proves nothing was
 * written.
 */

import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import {
  ASSET_SUBTYPE_MAX_LENGTH,
  ASSET_TYPES,
  ASSET_TYPE_FILTER_OPTIONS,
  ASSET_TYPE_LABELS,
  BLANK_CLASSIFICATION_DRAFT,
  classificationDraftOf,
  classificationIssues,
  classificationRequest,
  distinctAssetTypes,
  isSameClassificationDraft,
  matchesAssetTypeFilter,
} from './assetTypes';
import type { AssetClassificationDraft, AssetClassificationIssues } from './assetTypes';
import {
  AssetClassificationField,
  DealClassificationStrip,
  DealClassificationSummary,
} from './components/AssetClassification';
import { DealLibraryPanel } from './components/DealLibraryPanel';
import { InvestmentLibraryPanel } from './components/InvestmentLibraryPanel';
import { AssetManagementShell } from './components/AssetManagementShell';
import { DEMO_ASSET } from './assetManagementFixture';
import type { ManagedAsset } from './assetManagementTypes';
import type { VisibleInvestment } from './investmentTypes';
import type { Deal } from './types';
import { withLfLineEndings } from './testSourceText';

afterEach(cleanup);

// =============================================================================
// 1. The vocabulary and the subtype rules
// =============================================================================

describe('the controlled vocabulary', () => {
  it('is exactly the ten ratified wire values, with their product labels', () => {
    expect(ASSET_TYPES.map((assetType) => [assetType, ASSET_TYPE_LABELS[assetType]])).toEqual([
      ['multifamily', 'Multifamily'],
      ['office', 'Office'],
      ['industrial', 'Industrial'],
      ['retail', 'Retail'],
      ['hospitality', 'Hospitality'],
      ['self_storage', 'Self-Storage'],
      ['manufactured_housing', 'Manufactured Housing'],
      ['mixed_use', 'Mixed-Use'],
      ['land_development', 'Land/Development'],
      ['other', 'Other'],
    ]);
  });

  it('offers All, every type and Not specified as filter choices', () => {
    expect(ASSET_TYPE_FILTER_OPTIONS.map((option) => option.label)).toEqual([
      'All asset types',
      ...ASSET_TYPES.map((assetType) => ASSET_TYPE_LABELS[assetType]),
      'Not specified',
    ]);
  });
});

describe('the subtype and requirement rules', () => {
  const draft = (assetType: AssetClassificationDraft['assetType'], assetSubtype = '') => ({
    assetType,
    assetSubtype,
  });

  it('requires a type for a new Deal only', () => {
    expect(classificationIssues(draft(''), { requireType: true })).toEqual({
      assetType: 'Choose an Asset Type.',
    });
    expect(classificationIssues(draft(''), { requireType: false })).toEqual({});
  });

  it('requires a description when the type is Other, and whitespace is not one', () => {
    expect(classificationIssues(draft('other', '   '), { requireType: true }).assetSubtype).toMatch(
      /required when the Asset Type is Other/,
    );
    expect(classificationIssues(draft('other', 'Cold storage'), { requireType: true })).toEqual({});
    expect(classificationIssues(draft('office'), { requireType: true })).toEqual({});
  });

  it('refuses a subtype with no type rather than inventing one', () => {
    expect(classificationIssues(draft('', 'Garden apartments'), { requireType: false }).assetType).toMatch(
      /before describing a subtype/,
    );
  });

  it('limits the trimmed subtype, counting characters rather than code units', () => {
    const limit = 'é'.repeat(ASSET_SUBTYPE_MAX_LENGTH);
    expect(classificationIssues(draft('office', `  ${limit}  `), { requireType: true })).toEqual({});
    const emoji = '🏢'.repeat(ASSET_SUBTYPE_MAX_LENGTH);
    expect(emoji.length).toBe(2 * ASSET_SUBTYPE_MAX_LENGTH);
    expect(classificationIssues(draft('office', emoji), { requireType: true })).toEqual({});
    expect(
      classificationIssues(draft('office', `${limit}x`), { requireType: true }).assetSubtype,
    ).toMatch(/80 characters or fewer/);
  });

  it('sends the subtype trimmed and otherwise exactly as written', () => {
    expect(classificationRequest(draft('multifamily', '  gARDEN Apartments  '))).toEqual({
      asset_type: 'multifamily',
      asset_subtype: 'gARDEN Apartments',
    });
    expect(classificationRequest(draft('retail', '   '))).toEqual({ asset_type: 'retail', asset_subtype: null });
    expect(classificationRequest(BLANK_CLASSIFICATION_DRAFT)).toEqual({ asset_type: null, asset_subtype: null });
  });

  it('reads a legacy record as the blank draft and compares drafts by trimmed text', () => {
    expect(classificationDraftOf({ asset_type: null, asset_subtype: null })).toEqual(BLANK_CLASSIFICATION_DRAFT);
    expect(isSameClassificationDraft(draft('office', 'Flex '), draft('office', 'Flex'))).toBe(true);
    expect(isSameClassificationDraft(draft('office', 'Flex'), draft('industrial', 'Flex'))).toBe(false);
  });
});

describe('filtering a record that may hold several assets', () => {
  it('matches when any contained asset matches, and never picks one to stand for all', () => {
    expect(matchesAssetTypeFilter(['multifamily', 'retail'], 'retail')).toBe(true);
    expect(matchesAssetTypeFilter(['multifamily', 'retail'], 'office')).toBe(false);
    expect(matchesAssetTypeFilter(['multifamily', null], 'not_specified')).toBe(true);
    expect(matchesAssetTypeFilter(['multifamily'], 'not_specified')).toBe(false);
    expect(matchesAssetTypeFilter([], 'all')).toBe(true);
  });

  it('lists distinct types in vocabulary order with Not specified last', () => {
    expect(distinctAssetTypes(['retail', null, 'multifamily', 'retail'])).toEqual([
      'multifamily',
      'retail',
      null,
    ]);
  });
});

// =============================================================================
// 2. The field: labels, the Other requirement, announced validation
// =============================================================================

function Field({
  initial = BLANK_CLASSIFICATION_DRAFT,
  issues = {},
  isTypeRequired = true,
}: {
  initial?: AssetClassificationDraft;
  issues?: AssetClassificationIssues;
  isTypeRequired?: boolean;
}) {
  const [draft, setDraft] = useState(initial);
  return (
    <AssetClassificationField draft={draft} onChange={setDraft} issues={issues} isTypeRequired={isTypeRequired} />
  );
}

describe('the classification field', () => {
  it('labels the controlled select and the optional subtype, with examples', () => {
    render(<Field />);
    const select = screen.getByRole('combobox', { name: 'Asset Type (required)' });
    expect(select.getAttribute('aria-required')).toBe('true');
    expect(within(select).getAllByRole('option')).toHaveLength(ASSET_TYPES.length + 1);
    const subtype = screen.getByRole('textbox', { name: 'Asset Subtype (optional)' });
    expect(subtype.getAttribute('placeholder')).toMatch(/Garden apartments, Medical office, Last-mile warehouse/);
  });

  it('turns the subtype into a required description when Other is chosen', async () => {
    const user = userEvent.setup();
    render(<Field />);
    await user.selectOptions(screen.getByRole('combobox', { name: /^Asset Type/ }), 'other');
    const described = screen.getByRole('textbox', { name: 'Describe the Asset Type (required)' });
    expect(described.getAttribute('aria-required')).toBe('true');
    expect(screen.getByText(/Required when the Asset Type is Other/)).toBeTruthy();
  });

  it('marks each invalid control, ties it to its message and announces the message', () => {
    render(
      <Field
        initial={{ assetType: 'other', assetSubtype: '' }}
        issues={{ assetType: 'Type problem.', assetSubtype: 'Describe the asset type.' }}
      />,
    );
    const select = screen.getByRole('combobox', { name: /^Asset Type/ });
    const subtype = screen.getByRole('textbox', { name: /Describe the Asset Type/ });
    expect(select.getAttribute('aria-invalid')).toBe('true');
    expect(subtype.getAttribute('aria-invalid')).toBe('true');
    const alerts = screen.getAllByRole('alert').map((alert) => alert.textContent);
    expect(alerts).toEqual(['Type problem.', 'Describe the asset type.']);
    const typeError = document.getElementById(select.getAttribute('aria-describedby') ?? '');
    expect(typeError?.textContent).toBe('Type problem.');
    expect(subtype.getAttribute('aria-describedby')?.split(' ')).toHaveLength(2);
  });

  it('lets a legacy Deal stay Not specified', () => {
    render(<Field isTypeRequired={false} />);
    const select = screen.getByRole('combobox', { name: 'Asset Type' }) as HTMLSelectElement;
    expect(select.value).toBe('');
    expect(within(select).getByRole('option', { name: 'Not specified' })).toBeTruthy();
    expect(select.getAttribute('aria-required')).toBeNull();
  });
});

// =============================================================================
// 3. The Underwrite strip and the Overview summary
// =============================================================================

describe('the Underwrite strip', () => {
  function Strip({ initial, revealSignal = null }: { initial: AssetClassificationDraft; revealSignal?: object | null }) {
    const [draft, setDraft] = useState(initial);
    return (
      <DealClassificationStrip
        draft={draft}
        onChange={setDraft}
        issues={{}}
        isTypeRequired={false}
        revealSignal={revealSignal}
      />
    );
  }

  it('reads one line for a classified deal and opens the editor on demand', async () => {
    const user = userEvent.setup();
    render(<Strip initial={{ assetType: 'industrial', assetSubtype: 'Last-mile warehouse' }} />);
    expect(screen.getByText('Industrial · Last-mile warehouse')).toBeTruthy();
    const toggle = screen.getByRole('button', { name: 'Edit' });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('combobox', { name: /^Asset Type/ })).toBeNull();

    await user.click(toggle);
    expect(screen.getByRole('button', { name: 'Done' }).getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByRole('combobox', { name: /^Asset Type/ })).toBeTruthy();
  });

  it('starts open for an unclassified deal', () => {
    render(<Strip initial={BLANK_CLASSIFICATION_DRAFT} />);
    expect(screen.getByRole('combobox', { name: /^Asset Type/ })).toBeTruthy();
  });

  it('opens and moves focus to the type select when a save is stopped', async () => {
    const view = render(<Strip initial={{ assetType: 'office', assetSubtype: '' }} />);
    expect(screen.queryByRole('combobox', { name: /^Asset Type/ })).toBeNull();
    view.rerender(<Strip initial={{ assetType: 'office', assetSubtype: '' }} revealSignal={{}} />);
    const select = await screen.findByRole('combobox', { name: /^Asset Type/ });
    await vi.waitFor(() => expect(document.activeElement).toBe(select));
  });

  it('does not replay a reveal it was mounted with (the strip remounts on first Save)', async () => {
    // Found in browser QA: after a blocked Save and then a successful one, the
    // strip remounted under the new deal id and re-opened itself and stole
    // focus, answering a request that had already been answered.
    const answered = {};
    const view = render(
      <Strip initial={{ assetType: 'office', assetSubtype: '' }} revealSignal={answered} />,
    );
    await new Promise((resolve) => window.requestAnimationFrame(() => resolve(null)));
    expect(screen.queryByRole('combobox', { name: /^Asset Type/ })).toBeNull();
    expect(screen.getByRole('button', { name: 'Edit' }).getAttribute('aria-expanded')).toBe('false');

    view.rerender(<Strip initial={{ assetType: 'office', assetSubtype: '' }} revealSignal={{}} />);
    expect(await screen.findByRole('combobox', { name: /^Asset Type/ })).toBeTruthy();
  });

  it('keeps the editor open while a problem is showing', () => {
    render(
      <DealClassificationStrip
        draft={{ assetType: 'other', assetSubtype: '' }}
        onChange={vi.fn()}
        issues={{ assetSubtype: 'Describe the asset type.' }}
        isTypeRequired
        revealSignal={null}
      />,
    );
    expect((screen.getByRole('button', { name: 'Edit' }) as HTMLButtonElement).disabled).toBe(false);
  });
});

describe('the Overview summary', () => {
  it('shows the type and the analyst’s subtype, or Not specified', () => {
    const view = render(<DealClassificationSummary draft={{ assetType: 'office', assetSubtype: 'Medical office' }} />);
    const summary = screen.getByRole('region', { name: 'Asset classification' });
    expect(within(summary).getByText('Office')).toBeTruthy();
    expect(within(summary).getByText('Medical office')).toBeTruthy();

    view.rerender(<DealClassificationSummary draft={BLANK_CLASSIFICATION_DRAFT} />);
    expect(within(screen.getByRole('region', { name: 'Asset classification' })).getByText('Not specified')).toBeTruthy();
  });

  it('calls an Other subtype what it is -- the description', () => {
    render(<DealClassificationSummary draft={{ assetType: 'other', assetSubtype: 'Marina' }} />);
    expect(screen.getByText('Description')).toBeTruthy();
    expect(screen.getByText('Marina')).toBeTruthy();
  });
});

// =============================================================================
// 4. The Deal Library
// =============================================================================

function deal(id: string, name: string, overrides: Partial<Deal> = {}): Deal {
  return {
    id,
    name,
    operating_mode: 'quick',
    inputs: null,
    terms: null,
    detailed_operating_inputs: null,
    property_inputs: null,
    operating_inputs: null,
    market_leasing: null,
    suites: null,
    leases: null,
    business_plan: { capital_items: [], owner_expense_items: [] },
    asset_type: null,
    asset_subtype: null,
    deal_context: null,
    analysis_snapshot: null,
    ai_snapshot: null,
    one_way_sensitivity_snapshot: null,
    two_way_sensitivity_snapshot: null,
    created_at: '2026-09-01T00:00:00+00:00',
    updated_at: '2026-09-01T00:00:00+00:00',
    ...overrides,
  };
}

const DEALS = [
  deal('d1', 'Harbor Point', { asset_type: 'multifamily', asset_subtype: 'Garden apartments' }),
  deal('d2', 'Westlake Flex', { asset_type: 'industrial', asset_subtype: null }),
  deal('d3', 'Legacy Plaza'),
];

describe('the Deal Library', () => {
  function renderLibrary() {
    const callbacks = { onOpen: vi.fn(), onDuplicate: vi.fn(), onDelete: vi.fn(), onClose: vi.fn() };
    render(<DealLibraryPanel deals={DEALS} isLoading={false} error={null} {...callbacks} />);
    return callbacks;
  }

  const rowNames = () =>
    screen.queryAllByText(/Harbor Point|Westlake Flex|Legacy Plaza/).map((node) => node.textContent);

  it('shows each deal’s classification on its one meta line', () => {
    renderLibrary();
    const harbor = screen.getByText('Harbor Point').closest('li') as HTMLElement;
    const meta = harbor.querySelector('.deal-library-row-meta') as HTMLElement;
    expect(within(meta).getByText('Multifamily')).toBeTruthy();
    expect(within(meta).getByText('Garden apartments')).toBeTruthy();
    // Real text between the two, so the pair reads as two words to a screen reader.
    expect(meta.textContent).toContain('Multifamily · Garden apartments');
    const legacy = screen.getByText('Legacy Plaza').closest('li') as HTMLElement;
    expect(within(legacy).getByText('Not specified')).toBeTruthy();
  });

  it('filters by a controlled type and by Not specified, and writes nothing', async () => {
    const user = userEvent.setup();
    const callbacks = renderLibrary();
    const filter = screen.getByRole('combobox', { name: 'Asset Type' });
    expect(screen.getByRole('status').textContent).toBe('3 deals');

    await user.selectOptions(filter, 'industrial');
    expect(rowNames()).toEqual(['Westlake Flex']);
    expect(screen.getByRole('status').textContent).toBe('Showing 1 of 3 deals');

    await user.selectOptions(filter, 'not_specified');
    expect(rowNames()).toEqual(['Legacy Plaza']);

    await user.selectOptions(filter, 'all');
    expect(rowNames()).toEqual(['Harbor Point', 'Westlake Flex', 'Legacy Plaza']);
    for (const callback of Object.values(callbacks)) {
      expect(callback).not.toHaveBeenCalled();
    }
  });

  it('says when nothing matches and offers the way back', async () => {
    const user = userEvent.setup();
    renderLibrary();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Asset Type' }), 'hospitality');
    expect(rowNames()).toEqual([]);
    expect(screen.getByText(/No saved deals match this asset type/)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Show all asset types' }));
    expect(rowNames()).toHaveLength(3);
  });
});

// =============================================================================
// 5. The Investment Library -- honest about several asset types
// =============================================================================

function investment(id: string, name: string, unitIds: string[]): VisibleInvestment {
  return {
    id,
    name,
    transaction_price: 10_000_000,
    units: unitIds.map((unitId, ordinal) => ({
      unit_id: unitId,
      ordinal,
      label: null,
      unit_kind: 'property',
      acquisition_month: 0,
      disposition_month: null,
    })),
    business_plan: { capital_items: [], owner_expense_items: [] },
    transaction_costs: [],
    created_at: '2026-09-01T00:00:00+00:00',
    updated_at: '2026-09-01T00:00:00+00:00',
  } as VisibleInvestment;
}

describe('the Investment Library', () => {
  const INVESTMENTS = [
    investment('i1', 'Harbor Portfolio', ['d1', 'd2']),
    investment('i2', 'Single Asset', ['d1']),
    investment('i3', 'Legacy Pair', ['d3', 'missing-deal']),
  ];

  function renderInvestments() {
    render(
      <InvestmentLibraryPanel
        investments={INVESTMENTS}
        deals={DEALS}
        isLoading={false}
        error={null}
        onOpen={vi.fn()}
        onDelete={vi.fn()}
        onNew={vi.fn()}
        onClose={vi.fn()}
      />,
    );
  }

  const cellOf = (name: string) =>
    (screen.getByRole('rowheader', { name }).closest('tr') as HTMLElement).querySelector(
      '.investment-asset-types',
    ) as HTMLElement;

  it('lists every distinct type its Units hold rather than choosing one', () => {
    renderInvestments();
    expect(screen.getByRole('columnheader', { name: 'Asset Types' })).toBeTruthy();
    expect(cellOf('Harbor Portfolio').textContent).toBe('Mixed: Multifamily, Industrial');
    expect(cellOf('Single Asset').textContent).toBe('Multifamily');
    // An unclassified Unit, and a Unit not in the loaded Deal list, are both
    // "Not specified" -- never guessed.
    expect(cellOf('Legacy Pair').textContent).toBe('Not specified');
  });

  it('keeps an Investment when any of its Units matches the filter', async () => {
    const user = userEvent.setup();
    renderInvestments();
    const filter = screen.getByRole('combobox', { name: 'Asset Type' });
    await user.selectOptions(filter, 'industrial');
    expect(screen.getAllByRole('rowheader').map((cell) => cell.textContent)).toEqual(['Harbor Portfolio']);
    await user.selectOptions(filter, 'multifamily');
    expect(screen.getAllByRole('rowheader').map((cell) => cell.textContent)).toEqual([
      'Harbor Portfolio',
      'Single Asset',
    ]);
    await user.selectOptions(filter, 'not_specified');
    expect(screen.getAllByRole('rowheader').map((cell) => cell.textContent)).toEqual(['Legacy Pair']);
  });
});

// =============================================================================
// 6. Asset Management -- the snapshot, the legacy text, the filters
// =============================================================================

const LEGACY_ASSET: ManagedAsset = {
  ...DEMO_ASSET,
  id: 'asset-legacy',
  source_deal_id: 'deal-legacy',
  name: 'Legacy Tower',
  property_type: 'Class B office',
  asset_type: null,
  asset_subtype: null,
};
const OTHER_ASSET: ManagedAsset = {
  ...DEMO_ASSET,
  id: 'asset-other',
  source_deal_id: 'deal-other',
  name: 'Harbor Marina',
  asset_type: 'other',
  asset_subtype: 'Marina',
};

describe('Asset Management classification', () => {
  function renderShell() {
    const remove = vi.fn();
    render(
      <AssetManagementShell
        state={{
          assets: [DEMO_ASSET, LEGACY_ASSET, OTHER_ASSET],
          isLoading: false,
          error: null,
          reload: vi.fn(),
          create: vi.fn(),
          remove,
        }}
        dealCount={3}
        onViewAcquisitionBasis={vi.fn()}
        onOpenAcquisitions={vi.fn()}
      />,
    );
    return remove;
  }

  const listed = () =>
    within(screen.getByRole('table'))
      .getAllByRole('rowheader')
      .map((cell) => cell.textContent);

  it('replaces the Property Type column with one Asset Type column', () => {
    renderShell();
    const headers = within(screen.getByRole('table')).getAllByRole('columnheader').map((cell) => cell.textContent);
    expect(headers).toContain('Asset Type');
    expect(headers).not.toContain('Property Type');
    const legacyRow = screen.getByRole('rowheader', { name: 'Legacy Tower' }).closest('tr') as HTMLElement;
    expect(within(legacyRow).getByText('Not specified')).toBeTruthy();
    expect(within(legacyRow).getByText('Recorded as “Class B office”')).toBeTruthy();
    const demoRow = screen.getByRole('rowheader', { name: 'Harbor Point Apartments' }).closest('tr') as HTMLElement;
    expect(within(demoRow).getByText('Multifamily')).toBeTruthy();
    expect(within(demoRow).getByText('Garden apartments')).toBeTruthy();
    expect(demoRow.querySelector('.asset-classification-text')?.textContent).toBe('Multifamily, Garden apartments');
  });

  it('filters Managed Assets, including to the legacy Not specified ones', async () => {
    const user = userEvent.setup();
    const remove = renderShell();
    const filter = screen.getByRole('combobox', { name: 'Asset Type' });
    await user.selectOptions(filter, 'not_specified');
    expect(listed()).toEqual(['Legacy Tower']);
    await user.selectOptions(filter, 'other');
    expect(listed()).toEqual(['Harbor Marina']);
    expect(remove).not.toHaveBeenCalled();
  });

  it('filters Monthly Reporting independently and shows the type there too', async () => {
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getAllByRole('button', { name: 'Monthly Reporting' })[0]);
    expect(screen.getByRole('heading', { name: 'Monthly Reporting' })).toBeTruthy();
    expect(within(screen.getByRole('table')).getByText('Marina')).toBeTruthy();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Asset Type' }), 'multifamily');
    expect(listed()).toEqual(['Harbor Point Apartments']);
    expect(screen.getByRole('status').textContent).toBe('Showing 1 of 3 managed assets');
  });

  it('names the type in the sidebar list', () => {
    renderShell();
    const sidebar = screen.getByRole('list', { name: 'Managed Assets' });
    expect(within(sidebar).getByText(/^Multifamily ·/)).toBeTruthy();
    expect(within(sidebar).getByText(/^Owned asset ·/)).toBeTruthy();
  });
});

// =============================================================================
// 7. Narrow widths -- the stylesheet keeps both new layouts inside 390px
// =============================================================================

async function readCss(): Promise<string> {
  const load = (specifier: string) =>
    import(/* @vite-ignore */ specifier) as Promise<{
      readFileSync: (file: string, encoding: string) => string;
    }>;
  const fs = await load('node:fs');
  const runtime = globalThis as unknown as { process: { cwd: () => string } };
  return withLfLineEndings(fs.readFileSync(`${runtime.process.cwd()}/src/index.css`, 'utf8'));
}

let CSS = '';
beforeAll(async () => {
  CSS = await readCss();
});

function lastMediaBlock(query: string): string {
  const start = CSS.lastIndexOf(`@media ${query} {`);
  expect(start).toBeGreaterThan(-1);
  let depth = 0;
  for (let index = CSS.indexOf('{', start); index < CSS.length; index += 1) {
    if (CSS[index] === '{') depth += 1;
    if (CSS[index] === '}') {
      depth -= 1;
      if (depth === 0) return CSS.slice(start, index);
    }
  }
  return '';
}

describe('the classification layout at narrow widths', () => {
  it('stacks the two fields and lets the filter shrink to the column', () => {
    const narrow = lastMediaBlock('(max-width: 720px)');
    expect(narrow).toMatch(/\.asset-classification-field \{\s*grid-template-columns: minmax\(0, 1fr\);/);
    expect(narrow).toMatch(/\.asset-type-filter-select \{[^}]*min-width: 0;/);
  });

  it('wraps a long subtype instead of widening its row', () => {
    expect(CSS).toMatch(/\.asset-classification-subtype \{[^}]*overflow-wrap: anywhere;/);
    expect(CSS).toMatch(/\.deal-classification-summary-list dd \{[^}]*overflow-wrap: anywhere;/);
    expect(CSS).toMatch(/\.asset-type-filter-select \{[^}]*max-width: 100%;/);
    // Found in browser QA at 390: the Asset Management list's scroll container
    // must contain its absolutely positioned hidden text, or a wider Asset Type
    // column pushes it past the viewport and widens the page.
    expect(CSS).toMatch(/\.am-table-scroll \{[^}]*position: relative;/);
  });
});

// A classification change fires no request of its own: the field is a
// controlled input and nothing more.
describe('editing a classification', () => {
  it('only reports the new draft', () => {
    const onChange = vi.fn();
    render(
      <AssetClassificationField
        draft={{ assetType: 'office', assetSubtype: '' }}
        onChange={onChange}
        issues={{}}
        isTypeRequired
      />,
    );
    fireEvent.change(screen.getByRole('textbox', { name: /Asset Subtype/ }), {
      target: { value: 'Medical office' },
    });
    expect(onChange).toHaveBeenCalledWith({ assetType: 'office', assetSubtype: 'Medical office' });
  });
});
