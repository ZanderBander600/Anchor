/**
 * D5.5E -- the polish Human Pass #1 asked for, verified against the real app.
 *
 * Pass #1 accepted the workflow ("very good, intuitive") and named five faults:
 * unreadable large numbers, an ambiguous "Escalation" label, "Successor" leaking
 * engine vocabulary into the product, implementation words in user copy, and a
 * rent roll that scrolled horizontally while the desktop sat half empty.
 *
 * These tests hold each of those closed. They also hold closed the thing that
 * makes the numeric change safe: the value the analyst sees is grouped, and the
 * value Anchor receives is not.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { analyzeLeaseLevelAcquisition, getDeal, listDeals } from './api';
import { buildAcquisitionTermsRequest } from './convert';
import type { LeaseLevelAcquisitionResults } from './leaseLevelTypes';
import { savedDeal } from './hiddenIssuesFixture';

import workspaceSourceText from './components/LeaseLevelWorkspace.tsx?raw';
import tableSourceText from './components/RentRollTable.tsx?raw';
import editorSourceText from './components/SuiteLeaseEditor.tsx?raw';
import convertSourceText from './leaseLevelConvert.ts?raw';
import appSourceText from './App.tsx?raw';
import { withLfLineEndings } from './testSourceText';

// D5.9: source text is normalised to LF where it is loaded, so no assertion in
// this file depends on how the working tree happens to store a line break.
const workspaceSource = withLfLineEndings(workspaceSourceText);
const tableSource = withLfLineEndings(tableSourceText);
const editorSource = withLfLineEndings(editorSourceText);
const convertSource = withLfLineEndings(convertSourceText);
const appSource = withLfLineEndings(appSourceText);



vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    analyzeLeaseLevelAcquisition: vi.fn(),
    getDeal: vi.fn(),
    listDeals: vi.fn(),
  };
});

const mockAnalyze = vi.mocked(analyzeLeaseLevelAcquisition);
const mockGetDeal = vi.mocked(getDeal);
const mockListDeals = vi.mocked(listDeals);

beforeEach(() => {
  vi.clearAllMocks();
  mockListDeals.mockResolvedValue([]);
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function results(): LeaseLevelAcquisitionResults {
  return {
    monthly_projection: {} as LeaseLevelAcquisitionResults['monthly_projection'],
    annual_projection: {} as LeaseLevelAcquisitionResults['annual_projection'],
    results: {} as LeaseLevelAcquisitionResults['results'],
  };
}

function field(id: string): HTMLInputElement {
  const element = document.getElementById(id);
  if (element === null) {
    throw new Error(`No field with id ${id}`);
  }
  return element as HTMLInputElement;
}

async function enterLeaseLevel() {
  const user = userEvent.setup();
  render(<App />);
  await user.click(screen.getByRole('tab', { name: 'Lease-Level Underwrite' }));
  return user;
}

async function openSixSuiteDeal() {
  mockListDeals.mockResolvedValue([savedDeal()]);
  mockGetDeal.mockResolvedValue(savedDeal());
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('Fulton Exchange');
  await user.click(screen.getByText('Fulton Exchange'));
  await waitFor(() => {
    expect(screen.getByRole('tablist', { name: 'Lease-Level sections' })).toBeTruthy();
  });
  return user;
}

// =============================================================================
// A. Numeric readability -- and wire-value identity
// =============================================================================

describe('thousands grouping in the running app', () => {
  it('shows 30,000,000 after typing 30000000 (M1)', async () => {
    const user = await enterLeaseLevel();
    const purchasePrice = field('lease-level-terms-purchasePrice');

    await user.type(purchasePrice, '30000000');
    // Grouped the moment the analyst looks away.
    await user.tab();
    expect(purchasePrice.value).toBe('30,000,000');
  });

  it.each([
    ['100000', '100,000'],
    ['20000', '20,000'],
    ['1234567.89', '1,234,567.89'],
  ])('shows %s as %s', async (typed, shown) => {
    const user = await enterLeaseLevel();
    const purchasePrice = field('lease-level-terms-purchasePrice');
    await user.type(purchasePrice, typed);
    await user.tab();
    expect(purchasePrice.value).toBe(shown);
  });

  it('shows the raw digits again on focus, so editing is never fought (M1)', async () => {
    const user = await enterLeaseLevel();
    const purchasePrice = field('lease-level-terms-purchasePrice');

    await user.type(purchasePrice, '30000000');
    await user.tab();
    expect(purchasePrice.value).toBe('30,000,000');

    await user.click(purchasePrice);
    expect(purchasePrice.value).toBe('30000000');

    // And editing from there behaves normally.
    await user.type(purchasePrice, '0');
    expect(purchasePrice.value).toBe('300000000');
    await user.tab();
    expect(purchasePrice.value).toBe('300,000,000');
  });

  it('submits the ungrouped value (M2)', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSixSuiteDeal();
    const purchasePrice = field('lease-level-terms-purchasePrice');
    expect(purchasePrice.value).toBe('20,000,000');

    await user.click(screen.getByRole('button', { name: /^Analyz/i }));
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [terms] = mockAnalyze.mock.calls[0];
    expect(terms.purchase_price).toBe(20_000_000);
  });

  it('does not round a decimal on its way to the wire (M3)', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSixSuiteDeal();
    const rentable = field('lease-level-property-rentableAreaSf');
    await user.clear(rentable);
    await user.type(rentable, '1234567.89');
    await user.tab();
    expect(rentable.value).toBe('1,234,567.89');

    await user.click(screen.getByRole('button', { name: /^Analyz/i }));
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    expect(inputs.property_inputs.rentable_area_sf).toBe(1234567.89);
  });

  it('accepts a pasted grouped number without keeping the commas in state', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSixSuiteDeal();
    const rentable = field('lease-level-property-rentableAreaSf');
    await user.clear(rentable);
    await user.paste('1,250,000');
    await user.tab();
    expect(rentable.value).toBe('1,250,000');

    await user.click(screen.getByRole('button', { name: /^Analyz/i }));
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    expect(inputs.property_inputs.rentable_area_sf).toBe(1_250_000);
  });

  it('leaves percentages, months and years alone (M4)', async () => {
    const user = await enterLeaseLevel();

    const exitCap = field('lease-level-terms-exitCapRate');
    await user.type(exitCap, '6.25');
    await user.tab();
    expect(exitCap.value).toBe('6.25');
    expect(exitCap.getAttribute('type')).toBe('number');

    await user.click(screen.getByRole('tab', { name: 'Market Leasing' }));
    const term = field('lease-level-market-renewalTermMonths');
    await user.type(term, '1200');
    await user.tab();
    // A month count is not money; commas would imply a magnitude it never has.
    expect(term.value).toBe('1200');
  });

  it('leaves the Suite identifier alone (M5)', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    const panel = document.getElementById('lease-level-panel-rent-roll') as HTMLElement;
    const firstRow = within(panel).getAllByRole('row')[1];

    const suiteId = within(firstRow).getByLabelText(/^Suite, /) as HTMLInputElement;
    expect(suiteId.value).toBe('100');
    expect(suiteId.getAttribute('type')).not.toBe('number');
  });

  it('groups areas in the rent roll grid', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    const panel = document.getElementById('lease-level-panel-rent-roll') as HTMLElement;
    const firstRow = within(panel).getAllByRole('row')[1];
    expect((within(firstRow).getByLabelText(/^Area SF, /) as HTMLInputElement).value).toBe(
      '12,000',
    );
  });
});

describe('Quick and Detailed keep their wire values (M6)', () => {
  // Both modes start from a blank form, so Analyze legitimately refuses before
  // any request is built. What matters here is the same thing either way: the
  // analyst sees a grouped number, and the state behind it -- which is what the
  // existing conversion reads -- is unchanged.
  it('Quick groups the display and keeps the state ungrouped', async () => {
    const user = userEvent.setup();
    render(<App />);

    const purchasePrice = field('purchasePrice');
    await user.clear(purchasePrice);
    await user.type(purchasePrice, '48000000');
    await user.tab();
    expect(purchasePrice.value).toBe('48,000,000');

    // Focus reveals the state itself, which is what `convert.ts` parses.
    await user.click(purchasePrice);
    expect(purchasePrice.value).toBe('48000000');
  });

  it('Detailed groups the display and keeps the state ungrouped', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));

    const purchasePrice = field('purchasePrice');
    await user.clear(purchasePrice);
    await user.type(purchasePrice, '52000000');
    await user.tab();
    expect(purchasePrice.value).toBe('52,000,000');

    await user.click(purchasePrice);
    expect(purchasePrice.value).toBe('52000000');
  });

  it('the conversion both modes share is untouched by grouping', () => {
    // The decisive check: `buildAcquisitionTermsRequest` never sees a separator,
    // because state never holds one.
    expect(buildAcquisitionTermsRequest({
      purchasePrice: '48000000',
      holdPeriod: '5',
      exitCapRate: '6',
      ltv: '60',
      interestRate: '5',
      amortization: '30',
      acquisitionCostPct: '0',
      financingFeePct: '0',
      dispositionCostPct: '0',
      annualCapexReserve: '0',
      ioPeriod: '0',
    }).purchase_price).toBe(48_000_000);
  });
});

// =============================================================================
// B/C. Terminology
// =============================================================================

describe('escalation terminology (M7, M8)', () => {
  it('names what escalates and that it is a percentage', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    const panel = document.getElementById('lease-level-panel-rent-roll') as HTMLElement;
    await user.click(
      within(within(panel).getAllByRole('row')[1]).getByRole('button', {
        name: /Edit details for/,
      }),
    );

    const drawer = document.querySelector('.suite-editor') as HTMLElement;
    expect(within(drawer).getByLabelText('Rent Escalation (%)')).toBeTruthy();
    // The bare, ambiguous label is gone.
    expect(within(drawer).queryByLabelText('Escalation')).toBeNull();
  });

  it('names the timing control for what it decides', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    const panel = document.getElementById('lease-level-panel-rent-roll') as HTMLElement;
    await user.click(
      within(within(panel).getAllByRole('row')[1]).getByRole('button', {
        name: /Edit details for/,
      }),
    );

    const drawer = document.querySelector('.suite-editor') as HTMLElement;
    const timing = within(drawer).getByLabelText('Escalation Timing');
    expect(timing).toBeTruthy();
    expect(within(drawer).queryByLabelText('Escalation Basis')).toBeNull();

    // The choices really are about when, which is what earns the name.
    const options = Array.from((timing as HTMLSelectElement).options).map((o) => o.value);
    expect(options).toContain('lease_anniversary');
  });

  it('keeps the wire field name unchanged', () => {
    // Labels moved; the contract did not.
    expect(convertSource).toContain('escalation_basis');
    expect(convertSource).toContain('escalation_pct');
  });
});

describe('successor terminology (M9)', () => {
  it('shows no user-facing "Successor" anywhere in the Lease-Level workspace', async () => {
    const user = await openSixSuiteDeal();
    for (const tab of ['Acquisition & Debt', 'Property', 'Operating', 'Market Leasing']) {
      await user.click(screen.getByRole('tab', { name: tab }));
    }
    const workspace = document.querySelector('.underwrite') as HTMLElement;
    expect(workspace.textContent).not.toMatch(/successor/i);
  });

  it('renamed the escalation that applies to whatever lease comes next', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Market Leasing' }));
    expect(screen.getByLabelText(/^Future Lease Rent Escalation/)).toBeTruthy();
  });

  it('explains that market leasing describes the lease after the current one', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Market Leasing' }));
    const panel = document.getElementById('lease-level-panel-market') as HTMLElement;
    expect(panel.textContent).toMatch(/follows each current lease when it expires/);
  });

  it('keeps Renewal and New Tenant named precisely, not blurred into "future"', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Market Leasing' }));

    expect(screen.getByLabelText(/^Renewal Probability/)).toBeTruthy();
    expect(screen.getByLabelText(/^Renewal Term/)).toBeTruthy();
    expect(screen.getByLabelText(/^New Tenant Term/)).toBeTruthy();
    expect(screen.getByLabelText(/^New Tenant Downtime/)).toBeTruthy();
    expect(screen.getByLabelText(/^New Tenant Free Rent/)).toBeTruthy();
    expect(screen.getByLabelText('New Tenant Lease Type')).toBeTruthy();
  });

  it('keeps the internal wire vocabulary untouched', () => {
    // "successor" survives in code, where it is precise and correct.
    expect(convertSource).toContain('successor_escalation_pct');
    expect(convertSource).toContain('successorEscalationPct');
  });
});

// =============================================================================
// D. Product language
// =============================================================================

describe('user-facing copy (M10)', () => {
  const IMPLEMENTATION_WORDS = /\b(backend|frontend|parser|database|transport)\b|\bAPI\b/i;

  it('uses none of it anywhere in the Lease-Level workspace', async () => {
    const user = await openSixSuiteDeal();
    for (const tab of [
      'Acquisition & Debt',
      'Property',
      'Operating',
      'Market Leasing',
      'Rent Roll',
    ]) {
      await user.click(screen.getByRole('tab', { name: tab }));
      const workspace = document.querySelector('.underwrite') as HTMLElement;
      expect(workspace.textContent, `${tab} tab`).not.toMatch(IMPLEMENTATION_WORDS);
    }
  });

  it('uses none of it in the suite drawer', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    const panel = document.getElementById('lease-level-panel-rent-roll') as HTMLElement;
    await user.click(
      within(within(panel).getAllByRole('row')[1]).getByRole('button', {
        name: /Edit details for/,
      }),
    );
    const drawer = document.querySelector('.suite-editor') as HTMLElement;
    expect(drawer.textContent).not.toMatch(IMPLEMENTATION_WORDS);
  });

  it('describes an exact area match in the analyst’s terms', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    const strip = screen.getByLabelText('Area reconciliation');
    expect(within(strip).getByText('Suite areas match the property rentable area.')).toBeTruthy();
  });

  it('describes a shortfall and an excess in the analyst’s terms', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    const panel = document.getElementById('lease-level-panel-rent-roll') as HTMLElement;
    const firstRow = within(panel).getAllByRole('row')[1];
    const area = within(firstRow).getByLabelText(/^Area SF, /);

    await user.clear(area);
    await user.type(area, '2000');
    expect(
      within(screen.getByLabelText('Area reconciliation')).getByText(
        /Suite areas are 10,000 SF below the property rentable area/,
      ),
    ).toBeTruthy();

    await user.clear(area);
    await user.type(area, '22000');
    expect(
      within(screen.getByLabelText('Area reconciliation')).getByText(
        /Suite areas exceed the property rentable area by 10,000 SF/,
      ),
    ).toBeTruthy();
  });

  it('states no software structure vocabulary in the override copy', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    const panel = document.getElementById('lease-level-panel-rent-roll') as HTMLElement;
    await user.click(
      within(within(panel).getAllByRole('row')[1]).getByRole('button', {
        name: /Edit details for/,
      }),
    );
    const drawer = document.querySelector('.suite-editor') as HTMLElement;
    expect(drawer.textContent).not.toMatch(/entire record|per-field merge/i);
  });

  it('keeps real CRE vocabulary, which is not the same thing', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    const panel = document.getElementById('lease-level-panel-rent-roll') as HTMLElement;
    // "rent roll", "lease", "rollover" belong to the domain and stay.
    expect(panel.textContent).toMatch(/rollover/i);
    expect(panel.textContent).toMatch(/in-place lease/i);
  });
});

// =============================================================================
// E. Layout contracts
//
// jsdom computes no widths, so these assert the structural decisions that
// produce the width -- which class is applied where. Human Pass #2 judges the
// result on a real screen.
// =============================================================================

/**
 * jsdom applies no stylesheet, so no test here can prove a pixel width -- that
 * is Human Pass #2's job, on a real screen. What *is* machine-checkable, and
 * what actually decides the width, is which class lands on which element. These
 * pin exactly that, and nothing more, rather than pretending to measure.
 */
describe('desktop space utilisation', () => {
  it('the Lease-Level Underwrite panel opts into the wide layout (M11)', async () => {
    await openSixSuiteDeal();
    const panel = document
      .querySelector('#lease-level-panel-acquisition')
      ?.closest('.workspace-panel');
    expect(panel).not.toBeNull();
    expect(panel!.className).toContain('workspace-panel-wide');
  });

  it('does not widen Quick or Detailed (M12)', async () => {
    const user = userEvent.setup();
    render(<App />);

    // Quick, then Detailed: neither takes the wide variant, and the Lease-Level
    // panel is the only place in the app that asks for it.
    for (const tab of ['Quick Underwrite', 'Detailed Underwrite']) {
      await user.click(screen.getByRole('tab', { name: tab }));
      for (const panel of document.querySelectorAll('.workspace-panel')) {
        expect(panel.className, `${tab} panel`).not.toContain('workspace-panel-wide');
      }
    }
    // D5.7: two sites now, both Lease-Level -- the Underwrite panel for its rent
    // roll, and the Risk panel for its sensitivity matrix, which is the other
    // analyst-dense grid in the product. Quick and Detailed still ask for
    // neither, which the loop above is what actually proves.
    expect(appSource.match(/workspace-panel-wide/g)).toHaveLength(2);
    const leaseLevelTree = appSource.slice(appSource.indexOf('const leaseLevelWorkspace = ('));
    expect(leaseLevelTree.match(/workspace-panel-wide/g)).toHaveLength(2);
  });

  it('keeps the scalar tabs at the readable width', async () => {
    const user = await openSixSuiteDeal();
    for (const [tab, id] of [
      ['Acquisition & Debt', 'lease-level-panel-acquisition'],
      ['Property', 'lease-level-panel-property'],
      ['Operating', 'lease-level-panel-operating'],
      ['Market Leasing', 'lease-level-panel-market'],
    ] as const) {
      await user.click(screen.getByRole('tab', { name: tab }));
      expect(document.getElementById(id)?.className).toContain('lease-level-scalar-panel');
    }
    // The rent roll is the one section that does not take the constraint.
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    expect(document.getElementById('lease-level-panel-rent-roll')?.className).not.toContain(
      'lease-level-scalar-panel',
    );
  });

  it('declares a width for every column so none can crowd the rest (M13, M14)', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));

    const cols = Array.from(document.querySelectorAll('.rent-roll-table col'));
    expect(cols.map((col) => col.className)).toEqual([
      'rent-roll-col-suite',
      'rent-roll-col-area',
      'rent-roll-col-status',
      'rent-roll-col-tenant',
      'rent-roll-col-expiry',
      'rent-roll-col-rent',
      'rent-roll-col-type',
      'rent-roll-col-market-rent',
      'rent-roll-col-actions',
    ]);
    // One column declaration per header cell -- a mismatch would silently shift
    // every width one place to the left.
    expect(cols).toHaveLength(
      document.querySelectorAll('.rent-roll-table thead th').length,
    );
  });

  it('keeps Details and Delete as separate, named, visible actions (M13)', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    const panel = document.getElementById('lease-level-panel-rent-roll') as HTMLElement;

    for (const row of within(panel).getAllByRole('row').slice(1)) {
      expect(within(row).getByRole('button', { name: /Edit details for/ })).toBeTruthy();
      const remove = within(row).getByRole('button', { name: /^Delete /i });
      // Not abbreviated, and not hidden behind a menu, to make the layout fit.
      expect(remove.textContent).toBe('Delete');
    }
    // Actions is its own column, not crammed into another.
    const headers = within(panel)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent);
    expect(headers).toEqual([
      'Suite',
      'Area SF',
      'Status',
      'Tenant',
      'Lease Expiration',
      'Base Rent /SF',
      'Lease Type',
      'Suite Market Rent',
      'Actions',
    ]);
  });

  it('keeps the horizontal scroll wrapper as the narrow-screen fallback', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    expect(document.querySelector('.rent-roll .table-scroll')).not.toBeNull();
  });

  it('keeps the suite column a sticky row header (M15)', async () => {
    const user = await openSixSuiteDeal();
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    const panel = document.getElementById('lease-level-panel-rent-roll') as HTMLElement;

    // Sticky positioning is CSS, but which cell it applies to is structure: the
    // suite must be the row header, and it must be first, or the column that
    // sticks is not the one that identifies the row.
    for (const row of within(panel).getAllByRole('row').slice(1)) {
      const first = row.firstElementChild as HTMLElement;
      expect(first.tagName).toBe('TH');
      expect(first.getAttribute('scope')).toBe('row');
    }
  });
});

// =============================================================================
// M16: formatting did not smuggle in arithmetic
// =============================================================================

describe('M16: no financial math arrived with the formatter', () => {
  it('the formatter parses no numbers at all', async () => {
    const source = withLfLineEndings((await import('./numberFormat?raw')).default as string);
    for (const forbidden of ['Number(', 'parseFloat', 'parseInt', 'toFixed', 'Math.']) {
      expect(source, `numberFormat uses ${forbidden}`).not.toContain(forbidden);
    }
  });

  it('the shared input performs no calculation', async () => {
    const source = withLfLineEndings(
      (await import('./components/NumericInput?raw')).default as string,
    );
    for (const forbidden of ['Number(', 'parseFloat', 'parseInt', 'toFixed', 'Math.']) {
      expect(source, `NumericInput uses ${forbidden}`).not.toContain(forbidden);
    }
  });

  it('no rent, NOI or occupancy appeared in the polished components', () => {
    for (const [name, source] of [
      ['LeaseLevelWorkspace', workspaceSource],
      ['RentRollTable', tableSource],
      ['SuiteLeaseEditor', editorSource],
    ] as const) {
      // Identifiers, not prose: these modules legitimately *mention* WALT and
      // NOI in comments explaining that they do not compute them.
      for (const forbidden of [
        'const annualRent',
        'const totalRent',
        'const noi',
        'const walt',
        'const occupancy',
      ]) {
        expect(source, `${name} computes ${forbidden}`).not.toContain(forbidden);
      }
    }
  });
});
