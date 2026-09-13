/**
 * Phase 6 Gate D6.7 closeout -- IRR status consistency and the pinned Year
 * column.
 *
 * 1. The Lease-Level Summary and the Capital Economics view explain an
 *    unreported IRR with the SAME words, from the one frontend mapping
 *    (`irrNotReportedExplanation`), for every status the engine can return.
 * 2. On narrow widths the annual tables keep their Year / Period column in view
 *    while the figures scroll -- and only then, so desktop is unchanged.
 *
 * Results come from `capitalEconomicsFixture.json` (captured `/analyze`
 * responses); only the IRR field and its status are varied, never a figure.
 */

import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { cleanup, render, within } from '@testing-library/react';
import { CapitalEconomicsSection } from './components/CapitalEconomicsSection';
import { LeaseLevelMetricSummary } from './components/LeaseLevelMetricSummary';
import { IRR_NOT_REPORTED_REASONS, irrNotReportedExplanation } from './capitalEconomics';
import { formatPercent } from './format';
import { IRR_STATUSES } from './types';
import type { IrrStatus } from './types';
import type { LeaseLevelAcquisitionResults } from './leaseLevelTypes';
import { withLfLineEndings } from './testSourceText';
import fixture from './capitalEconomicsFixture.json';
import summaryRaw from './components/LeaseLevelMetricSummary.tsx?raw';

afterEach(() => {
  cleanup();
});

const LEASE_LEVEL = fixture.lease_level.v9_leasing_and_project_capital
  .response as unknown as LeaseLevelAcquisitionResults;

const UNREPORTED = IRR_STATUSES.filter((status) => status !== 'defined');

function withLeveredStatus(status: IrrStatus): LeaseLevelAcquisitionResults {
  return {
    ...LEASE_LEVEL,
    results: {
      ...LEASE_LEVEL.results,
      levered_irr: status === 'defined' ? 0.0735 : null,
      levered_irr_status: status,
    },
  };
}

/** One Summary metric: its value and the note set beneath it, if any. */
function summaryMetric(container: HTMLElement, label: string): { value: string; note: string | null } {
  const term = Array.from(container.querySelectorAll('.lease-level-summary dt')).find(
    (dt) => dt.textContent === label,
  );
  if (term === undefined) {
    throw new Error(`No ${label} metric in the Summary`);
  }
  const metric = term.parentElement as HTMLElement;
  return {
    value: metric.querySelector('dd')?.textContent ?? '',
    note: metric.querySelector('.lease-level-metric-note')?.textContent ?? null,
  };
}

/** The explanation Capital Economics wires to one IRR row, if any. */
function capitalEconomicsNote(container: HTMLElement, label: string): string | null {
  const returns = within(container).getByRole('region', { name: 'Project Returns' });
  const header = Array.from(returns.querySelectorAll('th[scope="row"]')).find(
    (cell) => cell.textContent === label,
  );
  const cell = header?.closest('tr')?.querySelector('td');
  const id = cell?.getAttribute('aria-describedby');
  return id ? (document.getElementById(id)?.textContent ?? null) : null;
}

// =============================================================================
// 1. The Lease-Level Summary explains an unreported IRR with the shared words
// =============================================================================

describe('the Lease-Level Summary IRR', () => {
  it('shows a reported Levered IRR normally, with no status label', () => {
    const { container } = render(<LeaseLevelMetricSummary analysis={withLeveredStatus('defined')} />);
    const levered = summaryMetric(container, 'Levered IRR');
    expect(levered.value).toBe(formatPercent(0.0735));
    expect(levered.note).toBeNull();
    expect(levered.value.toLowerCase()).not.toContain('defined');
  });

  for (const status of UNREPORTED) {
    it(`reads N/A with the engine's reason for ${status}`, () => {
      const { container } = render(<LeaseLevelMetricSummary analysis={withLeveredStatus(status)} />);
      const levered = summaryMetric(container, 'Levered IRR');
      expect(levered.value).toBe('N/A');
      expect(levered.note).toBe(irrNotReportedExplanation('Levered IRR', status));
      expect(levered.note).toBe(
        `Levered IRR is not reported because ${IRR_NOT_REPORTED_REASONS[status]}.`,
      );
    });
  }

  it('explains an unreported Unlevered IRR from its own status', () => {
    expect(LEASE_LEVEL.results.unlevered_irr).toBeNull();
    const { container } = render(<LeaseLevelMetricSummary analysis={LEASE_LEVEL} />);
    const unlevered = summaryMetric(container, 'Unlevered IRR');
    expect(unlevered.value).toBe('N/A');
    expect(unlevered.note).toBe(
      irrNotReportedExplanation('Unlevered IRR', LEASE_LEVEL.results.unlevered_irr_status),
    );
  });

  it('never disagrees with Capital Economics about why an IRR is unavailable', () => {
    for (const status of UNREPORTED) {
      const analysis = withLeveredStatus(status);
      const { container } = render(
        <>
          <LeaseLevelMetricSummary analysis={analysis} />
          <CapitalEconomicsSection results={analysis.results} purchasePrice={9_000_000} showLeasingCapital />
        </>,
      );
      const summaryNote = summaryMetric(container, 'Levered IRR').note;
      expect(summaryNote, status).not.toBeNull();
      expect(capitalEconomicsNote(container, 'Levered IRR'), status).toBe(summaryNote);
      expect(capitalEconomicsNote(container, 'Unlevered IRR')).toBe(
        summaryMetric(container, 'Unlevered IRR').note,
      );
      cleanup();
    }
  });

  it('holds no reason of its own: it reuses the one mapping', () => {
    const source = withLfLineEndings(summaryRaw);
    expect(source).toContain("import { irrNotReportedExplanation } from '../capitalEconomics';");
    expect(source).toContain('irrNotReportedExplanation(label, status)');
    for (const stale of ['changes sign', 'Not uniquely defined', 'UNDEFINED_IRR_LABEL', 'no single IRR']) {
      expect(source, stale).not.toContain(stale);
    }
    // Every reason sentence lives in exactly one production module.
    const production = Object.entries(
      import.meta.glob('./**/*.{ts,tsx}', { query: '?raw', eager: true, import: 'default' }) as Record<
        string,
        string
      >,
    ).filter(([path]) => !/\.test\.tsx?$/.test(path));
    for (const reason of Object.values(IRR_NOT_REPORTED_REASONS)) {
      const holders = production.filter(([, text]) => text.includes(reason)).map(([path]) => path);
      expect(holders, reason).toEqual(['./capitalEconomics.ts']);
    }
  });
});

// =============================================================================
// 2. The Year / Period column stays in view on narrow widths
// =============================================================================

/** `node:fs` through a variable specifier, as `leaseLevelStatementLayout` and
 * `testSourceText` do: the stylesheet cannot come through `?raw`, which
 * Vitest's CSS handling would empty, and this project has no `@types/node`. */
async function readCss(): Promise<string> {
  const load = (specifier: string) =>
    import(/* @vite-ignore */ specifier) as Promise<{
      readFileSync: (file: string, encoding: string) => string;
    }>;
  const fs = await load('node:fs');
  const runtime = globalThis as unknown as { process: { cwd: () => string } };
  return withLfLineEndings(fs.readFileSync(`${runtime.process.cwd()}/src/index.css`, 'utf8'));
}

const D6_7_BANNER = 'Phase 6 Gate D6.7 -- Capital Economics results.';
const NARROW = '@container capital-economics (max-width: 620px)';

/** The D6.7 part of the stylesheet, read once. */
let D6_7_CSS = '';

beforeAll(async () => {
  const css = await readCss();
  expect(css.indexOf(D6_7_BANNER), 'the D6.7 stylesheet section is missing').toBeGreaterThan(-1);
  D6_7_CSS = css.slice(css.indexOf(D6_7_BANNER));
});

/** The bodies of every block opened by `header` in `text`. */
function blocks(text: string, header: string): string[] {
  const found: string[] = [];
  let from = 0;
  for (;;) {
    const start = text.indexOf(header, from);
    if (start === -1) {
      return found;
    }
    const open = text.indexOf('{', start);
    let depth = 0;
    let index = open;
    for (; index < text.length; index += 1) {
      if (text[index] === '{') depth += 1;
      if (text[index] === '}') {
        depth -= 1;
        if (depth === 0) break;
      }
    }
    found.push(text.slice(open + 1, index));
    from = index;
  }
}

describe('the pinned Year column', () => {
  it('pins the first column of each annual table, and only while the view is narrow', () => {
    const narrow = blocks(D6_7_CSS, NARROW);
    const pinned = narrow.find((block) => block.includes('position: sticky'));
    expect(pinned, 'no narrow-width sticky rule').toBeDefined();
    expect(pinned).toContain(".capital-economics-table th[scope='row']");
    expect(pinned).toContain('.capital-economics-table thead tr > :first-child');
    expect(pinned).toContain('left: 0;');
    // Opaque, so scrolled figures cannot show through; a hairline edge.
    expect(pinned).toContain('background: var(--color-surface);');
    expect(pinned).toContain('box-shadow: inset -1px 0 0 var(--color-border);');
    // The Closing row keeps its tint while pinned.
    expect(pinned).toContain(
      ".capital-economics-table .capital-economics-closing-row > th[scope='row'] {\n    background: var(--color-surface-muted);",
    );
    // One column only: no data cell is ever pinned.
    expect(pinned).not.toMatch(/\.capital-economics-table td/);
    // Desktop unchanged: outside the narrow query nothing in D6.7 is sticky.
    let outside = D6_7_CSS;
    for (const block of narrow) {
      outside = outside.replace(block, '');
    }
    expect(outside).not.toContain('sticky');
  });

  it('keeps semantic markup: each annual row is headed by its Year / Period cell', () => {
    const { container } = render(
      <CapitalEconomicsSection results={LEASE_LEVEL.results} purchasePrice={9_000_000} showLeasingCapital />,
    );
    for (const name of ['Owner Cash Flow', 'Capital Schedule']) {
      const table = within(within(container).getByRole('region', { name })).getByRole('table');
      const headRows = table.querySelectorAll('thead tr');
      const lastHead = headRows[headRows.length - 1];
      expect(lastHead.firstElementChild?.tagName, name).toBe('TH');
      expect(lastHead.firstElementChild?.getAttribute('scope'), name).toBe('col');
      for (const row of Array.from(table.querySelectorAll('tbody tr'))) {
        expect(row.firstElementChild?.tagName, name).toBe('TH');
        expect(row.firstElementChild?.getAttribute('scope'), name).toBe('row');
      }
      // The pinned column sits inside the table's own scroll container.
      expect(table.parentElement?.className, name).toBe('table-scroll');
    }
  });
});
