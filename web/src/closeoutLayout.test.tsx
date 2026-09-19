/**
 * P7.9 closeout and AM1 QA corrections -- list alignment and page overflow.
 *
 * Live browser QA found four layout defects, each guarded here at its cause:
 *
 * 1. **The Asset Management lists centred their headers over left-aligned
 *    text.** A header without a class inherits the browser's centred `th`
 *    default. Every list column now carries one alignment class, the same on
 *    its header and its cells, scoped to `.am-list-table` so the monthly
 *    statement table's right-aligned figures are untouched. The empty action
 *    header now has an accessible name.
 * 2. **The Managed Asset header pushed "Edit Actuals" past a 390px viewport**:
 *    a full-width, non-wrapping row of no-wrap buttons (461px document width).
 * 3. **The Acquisitions shell's operating-mode switch was 428px at 390**
 *    (508px document width on every Deal workspace, Partnership included).
 * 4. **The NOI trend's visually hidden data table still widened the page**
 *    (411px on Monthly Performance): a table sizes to its content whatever
 *    its `width` says, so the hiding class moved to a wrapper.
 *
 * jsdom has no layout, so (2) and (3) are guarded at the exact rules that
 * caused them; actual `scrollWidth <= clientWidth` is measured in browser QA.
 *
 * The final review pass adds (5) the Tier Audit's scoped, role-based table
 * styles and (6) the Managed Asset header's action order, destructive last.
 */

import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AssetManagementShell } from './components/AssetManagementShell';
import { ManagedAssetWorkspace } from './components/ManagedAssetWorkspace';
import { MonthlyPerformancePanel } from './components/MonthlyPerformancePanel';
import { NoiTrendChart } from './components/NoiTrendChart';
import { DEMO_ASSET, DEMO_PERFORMANCE, DEMO_REPORT } from './assetManagementFixture';
import type { ManagedAsset } from './assetManagementTypes';
import type { AssetPerformanceState } from './useManagedAssets';
import { withLfLineEndings } from './testSourceText';

afterEach(cleanup);

/** `node:fs` through a variable specifier: the stylesheet cannot come through
 * `?raw`, which Vitest's CSS handling would empty. */
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

/** The declarations of the one rule whose selector is exactly `selector`,
 * within `scope` (the whole sheet, or one media block). */
function ruleBody(scope: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`(^|\\n)\\s*${escaped}\\s*\\{([^}]*)\\}`).exec(scope);
  expect(match, `no rule for ${selector}`).not.toBeNull();
  return (match as RegExpExecArray)[2];
}

/** The body of the one `@media` block with this exact query that states a
 * rule for `selector` -- the stylesheet has several blocks per breakpoint. */
function mediaBlock(query: string, selector: string): string {
  const blocks: string[] = [];
  let start = CSS.indexOf(`@media ${query} {`);
  while (start !== -1) {
    let depth = 0;
    let end = -1;
    for (let index = CSS.indexOf('{', start); index < CSS.length && end === -1; index += 1) {
      if (CSS[index] === '{') depth += 1;
      if (CSS[index] === '}') {
        depth -= 1;
        if (depth === 0) end = index;
      }
    }
    blocks.push(CSS.slice(start, end));
    start = CSS.indexOf(`@media ${query} {`, end);
  }
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const holding = blocks.filter((block) => new RegExp(`\\n\\s*${escaped}\\s*\\{`).test(block));
  expect(holding, `one ${query} block for ${selector}`).toHaveLength(1);
  return holding[0];
}

const ALIGNMENT_CLASSES = ['am-col-line', 'am-col-text', 'am-col-action', 'am-col-figure'];

function alignmentOf(cell: Element): string | null {
  const found = ALIGNMENT_CLASSES.filter((name) => cell.classList.contains(name));
  return found.length === 1 ? found[0] : null;
}

/** Every column's alignment class, on its header and on each body cell. */
function columnAlignments(table: HTMLElement): { header: (string | null)[]; rows: (string | null)[][] } {
  const header = [...table.querySelectorAll('thead tr > *')].map(alignmentOf);
  const rows = [...table.querySelectorAll('tbody tr')].map((row) =>
    [...row.children].map(alignmentOf),
  );
  return { header, rows };
}

const SECOND_ASSET: ManagedAsset = {
  ...DEMO_ASSET,
  id: 'asset-2',
  source_deal_id: 'deal-2',
  name: 'Lakeshore Commons',
  property_type: null,
  market: null,
};

function renderShell() {
  return render(
    <AssetManagementShell
      state={{
        assets: [DEMO_ASSET, SECOND_ASSET],
        isLoading: false,
        error: null,
        reload: vi.fn(),
        create: vi.fn(),
        remove: vi.fn().mockResolvedValue(undefined),
      }}
      dealCount={2}
      onViewAcquisitionBasis={vi.fn()}
      onOpenAcquisitions={vi.fn()}
    />,
  );
}

// =============================================================================
// 1. List alignment
// =============================================================================

describe('the Asset Management lists align each header with its own values', () => {
  it('pairs every Managed Assets column’s header and cells', () => {
    renderShell();
    const table = screen.getByRole('table');
    expect(table.classList.contains('am-list-table')).toBe(true);
    const { header, rows } = columnAlignments(table);
    expect(header).toEqual(['am-col-line', 'am-col-text', 'am-col-text', 'am-col-text', 'am-col-action']);
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      expect(row).toEqual(header);
    }
  });

  it('pairs every Monthly Reporting column’s header and cells', async () => {
    renderShell();
    await userEvent.click(screen.getAllByRole('button', { name: 'Monthly Reporting' })[0]);
    const table = screen.getByRole('table');
    expect(table.classList.contains('am-list-table')).toBe(true);
    const { header, rows } = columnAlignments(table);
    // Asset Types 1 adds the Asset Type column beside Market.
    expect(header).toEqual(['am-col-line', 'am-col-text', 'am-col-text', 'am-col-action']);
    for (const row of rows) {
      expect(row).toEqual(header);
    }
  });

  it('names the action column “Actions” for assistive technology', async () => {
    renderShell();
    expect(screen.getByRole('columnheader', { name: 'Actions' })).toBeTruthy();
    await userEvent.click(screen.getAllByRole('button', { name: 'Monthly Reporting' })[0]);
    expect(screen.getByRole('columnheader', { name: 'Actions' })).toBeTruthy();
  });

  it('states each list alignment in CSS, scoped to the list tables only', () => {
    expect(ruleBody(CSS, '.am-list-table .am-col-text')).toContain('text-align: left;');
    expect(ruleBody(CSS, '.am-list-table .am-col-action')).toContain('text-align: right;');
    // Only the two list-table rules name `.am-list-table`: no shared `.am-table`
    // rule was changed to fix the lists.
    expect(CSS.match(/\.am-list-table[^{]*\{/g)).toHaveLength(2);
    // The shared figure rule, which the statement relies on, is intact.
    expect(ruleBody(CSS, '.am-col-figure')).toContain('text-align: right;');
  });

  it('leaves the monthly statement table as it was: figures right-aligned, no list class', () => {
    render(
      <MonthlyPerformancePanel
        performance={DEMO_PERFORMANCE}
        view="monthly"
        onViewChange={vi.fn()}
        onEditActuals={vi.fn()}
        onSaveCommentary={vi.fn()}
      />,
    );
    for (const table of screen.getAllByRole('table')) {
      expect(table.classList.contains('am-list-table')).toBe(false);
    }
    const statement = screen
      .getAllByRole('table')
      .find((table) => table.querySelector('thead .am-col-figure') !== null) as HTMLElement;
    const figureHeaders = [...statement.querySelectorAll('thead th.am-col-figure')];
    expect(figureHeaders.length).toBeGreaterThan(0);
  });
});

// =============================================================================
// 2. The Managed Asset header wraps, and states each action once
// =============================================================================

function performanceState(): AssetPerformanceState {
  return {
    reports: [DEMO_REPORT],
    reportsStatus: 'ready',
    performance: DEMO_PERFORMANCE,
    performanceStatus: 'ready',
    isRefreshing: false,
    selectedMonth: '2027-03-01',
    error: null,
    selectMonth: vi.fn(),
    reload: vi.fn(),
    saveReport: vi.fn().mockResolvedValue(undefined),
    saveActuals: vi.fn().mockResolvedValue(undefined),
    saveCommentary: vi.fn().mockResolvedValue(undefined),
  };
}

describe('the Managed Asset header fits a phone and says each thing once', () => {
  it('wraps its action row rather than pushing an action off screen', () => {
    expect(ruleBody(CSS, '.am-asset-actions')).toContain('flex-wrap: wrap;');
    const narrow = mediaBlock('(max-width: 720px)', '.am-asset-actions button');
    const buttons = ruleBody(narrow, '.am-asset-actions button');
    expect(buttons).toContain('min-width: 0;');
    // A basis, not `flex: 1`: equal shares of a non-wrapping row were the cause.
    expect(buttons).toMatch(/flex: 1 1 \d/);
  });

  it('offers View Acquisition Basis exactly once, reachable from both tabs', async () => {
    const onView = vi.fn();
    render(
      <ManagedAssetWorkspace
        asset={DEMO_ASSET}
        state={performanceState()}
        onViewAcquisitionBasis={onView}
        onDelete={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    expect(screen.getAllByRole('button', { name: 'View Acquisition Basis' })).toHaveLength(1);
    await userEvent.click(screen.getByRole('tab', { name: 'Overview' }));
    expect(screen.getAllByRole('button', { name: 'View Acquisition Basis' })).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: 'View Acquisition Basis' }));
    expect(onView).toHaveBeenCalledWith(DEMO_ASSET.source_deal_id);
  });

  it('formats the Overview acquisition date as the rest of Asset Management does', async () => {
    render(
      <ManagedAssetWorkspace
        asset={DEMO_ASSET}
        state={performanceState()}
        onViewAcquisitionBasis={vi.fn()}
        onDelete={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    await userEvent.click(screen.getByRole('tab', { name: 'Overview' }));
    const acquired = screen.getByText('Acquired', { selector: 'dt' }).parentElement as HTMLElement;
    expect(within(acquired).getByText('Oct 2026')).toBeTruthy();
    expect(document.body.textContent).not.toContain('2026-10-01');
  });
});

// =============================================================================
// 3. The operating-mode switch fits a phone
// =============================================================================

describe('the operating-mode switch never widens a phone-width page', () => {
  it('takes its own row and lets each label wrap below 768px', () => {
    const narrow = mediaBlock('(max-width: 767px)', '.mode-switch');
    const switchRule = ruleBody(narrow, '.mode-switch');
    expect(switchRule).toContain('flex: 1 1 100%;');
    expect(switchRule).toContain('min-width: 0;');
    const tabRule = ruleBody(narrow, '.mode-switch-tab');
    expect(tabRule).toContain('white-space: normal;');
    expect(tabRule).toContain('min-width: 0;');
  });

  it('keeps the desktop switch on one line', () => {
    // The fix is phone-only: the desktop segmented control is unchanged.
    expect(ruleBody(CSS, '.mode-switch-tab')).toContain('white-space: nowrap;');
  });
});

// =============================================================================
// 4. The trend's accessible table is hidden by a box that can be hidden
// =============================================================================

describe('the NOI trend’s accessible table never widens the page', () => {
  it('hides a wrapper around the table, not the table itself', () => {
    render(<NoiTrendChart points={DEMO_PERFORMANCE.result.noi_trend} />);
    const table = screen.getByRole('table', {
      name: /budget and actual net operating income by month/i,
    });
    expect(table.classList.contains('am-visually-hidden')).toBe(false);
    expect(table.parentElement?.classList.contains('am-visually-hidden')).toBe(true);
    expect(table.parentElement?.tagName).toBe('DIV');
  });
});

// =============================================================================
// 5. The Partnership table styles are scoped, role-based and pattern-free
// =============================================================================

/** Each rule's selector parts and body, comments removed. */
function cssRules(): { parts: string[]; body: string }[] {
  const uncommented = CSS.replace(/\/\*[\s\S]*?\*\//g, '');
  return [...uncommented.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => ({
    parts: match[1].split(',').map((part) => part.trim()),
    body: match[2],
  }));
}

/** The body of the one rule whose selector parts include every given part. */
function ruleWith(...parts: string[]): string {
  const rules = cssRules().filter((rule) => parts.every((part) => rule.parts.includes(part)));
  expect(rules, parts.join(' + ')).toHaveLength(1);
  return rules[0].body;
}

describe('the Partnership table styles touch only the Partnership tables', () => {
  it('right-aligns figures in tabular numerals, in the audit and the results alike', () => {
    const figure = ruleWith(
      '.partnership-audit-table .partnership-audit-figure',
      '.partnership-result-table .partnership-result-figure',
    );
    expect(figure).toContain('text-align: right;');
    expect(figure).toContain('font-variant-numeric: tabular-nums;');
  });

  it('keeps identity and words on the left', () => {
    const words = ruleWith(
      '.partnership-audit-table .partnership-audit-period',
      '.partnership-audit-table .partnership-audit-status',
      '.partnership-audit-table .partnership-audit-text',
      '.partnership-audit-table .partnership-audit-shares',
      '.partnership-result-table .partnership-result-identity',
      '.partnership-result-table .partnership-result-text',
    );
    expect(words).toContain('text-align: left;');
  });

  it('pads each cell, separates rows and gives the header its own band', () => {
    const cells = ruleWith(
      '.partnership-audit-table th',
      '.partnership-audit-table td',
      '.partnership-result-table th',
      '.partnership-result-table td',
    );
    expect(cells).toMatch(/padding: \d+px 1\dpx;/);
    expect(cells).toContain('border-bottom: 1px solid var(--border);');
    const header = ruleWith('.partnership-audit-table thead th', '.partnership-result-table thead th');
    expect(header).toContain('background: var(--surface-muted);');
    expect(header).toContain('border-bottom: 1px solid var(--border-strong);');
  });

  it('scopes every role rule to its own table family and positions nothing by index', () => {
    let scoped = 0;
    for (const rule of cssRules()) {
      for (const part of rule.parts) {
        if (/\.partnership-audit-(figure|period|status|text|shares)\b/.test(part)) {
          expect(part.startsWith('.partnership-audit-table '), part).toBe(true);
          scoped += 1;
        }
        if (/\.partnership-result-(figure|identity|text)\b/.test(part)) {
          expect(part.startsWith('.partnership-result-table '), part).toBe(true);
          scoped += 1;
        }
      }
    }
    expect(scoped).toBeGreaterThan(0);
    const tableRules = CSS.slice(CSS.indexOf('.partnership-audit-table,\n.partnership-result-table {'));
    expect(tableRules.slice(0, tableRules.indexOf('/* --- The PARTNER matrix'))).not.toMatch(
      /nth-child|nth-of-type|first-child|last-child/,
    );
    // The shared `.data-table` class is still unstyled: the Partnership tables
    // are styled through their own scoped classes, and nothing else that uses
    // `.data-table` changed.
    expect(CSS).not.toMatch(/(^|\n)\s*\.data-table[\s,{.]/);
  });
});

// =============================================================================
// 6. The Managed Asset header leads with the operating workflow
// =============================================================================

describe('the Managed Asset header puts the destructive action last', () => {
  it('orders Edit Actuals, View Acquisition Basis, then Delete Asset', () => {
    const { container } = render(
      <ManagedAssetWorkspace
        asset={DEMO_ASSET}
        state={performanceState()}
        onViewAcquisitionBasis={vi.fn()}
        onDelete={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    const actions = [...container.querySelectorAll('.am-asset-actions button')];
    expect(actions.map((button) => button.textContent)).toEqual([
      'Edit Actuals',
      'View Acquisition Basis',
      'Delete Asset',
    ]);
    // Still visibly destructive.
    expect(actions[2].classList.contains('am-danger-button')).toBe(true);
  });

  it('still confirms inline, focuses Cancel, deletes nothing on cancel and returns focus', async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    render(
      <ManagedAssetWorkspace
        asset={DEMO_ASSET}
        state={performanceState()}
        onViewAcquisitionBasis={vi.fn()}
        onDelete={onDelete}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Delete Asset' }));
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByText(/deletes the managed asset and all of its monthly reports/i)).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onDelete).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Delete Asset' }));
  });
});
