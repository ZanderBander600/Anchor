/**
 * D5.6B -- the operating statement's scrolling hierarchy, tested against the
 * real stylesheet.
 *
 * These are layout tests, and layout is exactly where asserting on markup alone
 * would have missed the bug this gate fixes. It was a cascade failure, not a
 * structural one: the phase band declared `text-align: left` at (0,1,0) and lost
 * to `.cash-flow-table th`'s `text-align: right` at (0,1,1), so the phase name
 * drifted to the far end of its span -- "Forward 12 Months" sitting over the
 * last month of the window rather than the first. The markup was right and the
 * rendering was wrong, and no test that read the DOM could have told them apart.
 *
 * The "Line Item" cell escaped the same fate only by accident: it is the first
 * cell in its row, and `.cash-flow-table th:first-child` left-aligns it at
 * (0,2,1). Its selector is qualified here anyway, so that it stops depending on
 * a position the D5.6A header change had already made fragile.
 *
 * So the stylesheet is loaded into the document and the assertions read
 * `getComputedStyle` on the real rendered component. jsdom resolves the cascade
 * for the properties that matter here -- alignment, position, offsets, z-index,
 * padding, font weight -- so a rule that is written but outranked fails the
 * test instead of passing it.
 *
 * Two things jsdom will not do, stated so nobody reads more into these tests
 * than they prove: it does not resolve `var()` inside a shorthand, so the NOI
 * rules are checked against the declaration text; and it does not lay anything
 * out, so it cannot tell you what a sticky element looks like mid-scroll. The
 * scroll behaviour is held closed structurally -- a sticky box is clamped to
 * its containing block, so which element a label lives in is what decides where
 * it can travel -- and that structure is asserted. A browser pass is still
 * owed and these tests do not replace it.
 */

import { beforeAll, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import { afterEach } from 'vitest';
import { LeaseLevelOperatingStatement } from './components/LeaseLevelOperatingStatement';
import type { OperatingPeriodView } from './components/LeaseLevelOperatingStatement';
import type { LeaseLevelAcquisitionResults } from './leaseLevelTypes';
import fixture from './leaseLevelResultsFixture.json';
import { withLfLineEndings } from './testSourceText';

const HEALTHY = fixture.healthy as unknown as LeaseLevelAcquisitionResults;

/** The stylesheet, as text, for the assertions jsdom cannot compute. */
let CSS = '';

/** `node:fs` through a variable specifier: this project has no `@types/node`,
 * and a literal one would be type-checked against types that are not
 * installed. Test-only, and the only file that reaches outside `src`. */
async function readCss(path: string): Promise<string> {
  const load = (specifier: string) =>
    import(/* @vite-ignore */ specifier) as Promise<{
      readFileSync: (file: string, encoding: string) => string;
    }>;
  const fs = await load('node:fs');
  // D5.9: `ruleFor` below matches a selector list across a line break, so the
  // text is normalised to LF here, once, whatever the working tree holds.
  return withLfLineEndings(fs.readFileSync(path, 'utf8'));
}

beforeAll(async () => {
  const runtime = globalThis as unknown as { process: { cwd: () => string } };
  CSS = await readCss(`${runtime.process.cwd()}/src/index.css`);
  const style = document.createElement('style');
  style.textContent = CSS;
  document.head.appendChild(style);
});

afterEach(cleanup);

function draw(view: OperatingPeriodView) {
  render(<LeaseLevelOperatingStatement analysis={HEALTHY} view={view} onViewChange={() => {}} />);
}

function one(selector: string): HTMLElement {
  const found = document.querySelector(selector);
  if (found === null) {
    throw new Error(`Nothing matched ${selector}`);
  }
  return found as HTMLElement;
}

function all(selector: string): HTMLElement[] {
  return Array.from(document.querySelectorAll(selector)) as HTMLElement[];
}

/** The body of one CSS rule, by its exact selector. */
function ruleFor(selector: string): string {
  const index = CSS.indexOf(`${selector} {`);
  expect(index, `no rule for ${selector}`).toBeGreaterThan(-1);
  return CSS.slice(index, CSS.indexOf('}', index));
}

// =============================================================================
// 1. Net operating income: a ruled subtotal, not a shaded panel
// =============================================================================

describe('the NOI row', () => {
  it.each(['annual', 'monthly'] as const)('is emphasised in the %s view (M3)', (view) => {
    draw(view);
    const label = one('.lease-level-statement-noi th[scope="row"]');
    const value = one('.lease-level-statement-noi td');

    expect(label.textContent).toBe('Net Operating Income');
    expect(getComputedStyle(label).fontWeight).toBe('700');
    expect(getComputedStyle(value).fontWeight).toBe('700');
    // Larger than the body of the statement, so it reads as the line the
    // statement resolves to.
    expect(parseFloat(getComputedStyle(value).fontSize)).toBeGreaterThan(
      parseFloat(getComputedStyle(one('.lease-level-statement-table td')).fontSize) - 0.01,
    );
  });

  it.each(['annual', 'monthly'] as const)(
    'carries no fill and no darker label cell in the %s view (M4)',
    (view) => {
      draw(view);
      const label = getComputedStyle(one('.lease-level-statement-noi th[scope="row"]'));
      const value = getComputedStyle(one('.lease-level-statement-noi td'));

      // The shaded block, and the darker cell behind the label that made the
      // row look selected rather than totalled, are both gone.
      expect(value.backgroundImage).toBe('none');
      expect(label.backgroundImage).toBe('none');
      // The label cell keeps a plain opaque surface -- it is sticky, so it
      // cannot be transparent -- and it is the ordinary surface, not a tint.
      expect(label.background).toContain('--color-surface');
      expect(label.background).not.toContain('accent-soft');
    },
  );

  it('has more air above the line than below it (M4)', () => {
    draw('annual');
    const value = getComputedStyle(one('.lease-level-statement-noi td'));
    const above = parseFloat(value.paddingTop);
    const below = parseFloat(value.paddingBottom);

    // A total closes the block above it. Equal padding read as a floating
    // band; more above than below reads as a rule under a section.
    expect(above).toBeGreaterThan(below);
    const ordinary = parseFloat(
      getComputedStyle(one('.lease-level-statement-table tbody td')).paddingTop,
    );
    expect(above).toBeGreaterThan(ordinary);
  });

  it('is ruled, heavily above and lightly below', () => {
    // jsdom will not resolve `var()` inside a border shorthand, so this reads
    // the declaration rather than the computed value, and says so.
    const rule = ruleFor('.lease-level-statement-noi th,\n.lease-level-statement-noi td');
    expect(rule).toContain('border-top: 2px solid var(--color-accent)');
    expect(rule).toContain('border-bottom: 1px solid var(--color-border)');
    expect(rule).toContain('background: none');
  });

  it('is still its own row group, outside Operating Expenses (M1, M2)', () => {
    draw('annual');
    const group = one('.lease-level-statement-noi').closest('tbody') as HTMLTableSectionElement;

    expect(all('.lease-level-statement-noi')).toHaveLength(1);
    expect(group.querySelectorAll('th[scope="row"]')).toHaveLength(1);
    expect(group.querySelector('th[scope="rowgroup"]')).toBeNull();
    // And no band anywhere repeats its name.
    expect(all('th[scope="rowgroup"]').map((cell) => cell.textContent)).not.toContain(
      'Net Operating Income',
    );
  });
});

// =============================================================================
// 2. Phase labels: leading edge, sticky within their own span
// =============================================================================

describe('the phase labels', () => {
  it('lead their span rather than centring or trailing it (M5, M6, M7, M8)', () => {
    draw('monthly');
    for (const cell of all('th.lease-level-statement-period')) {
      const style = getComputedStyle(cell);
      expect(style.textAlign, cell.textContent ?? '').toBe('left');
      expect(style.textAlign).not.toBe('center');
      expect(style.textAlign).not.toBe('right');
    }
  });

  it('names the phase first inside the label', () => {
    draw('monthly');
    const [hold, forward] = all('.lease-level-statement-period-label');
    expect(hold.firstElementChild?.textContent).toBe('Hold Period');
    expect(forward.firstElementChild?.textContent).toBe('Forward 12 Months');
  });

  it('slides with the scroll, from the token offset (M9)', () => {
    draw('monthly');
    const label = getComputedStyle(one('.lease-level-statement-period-label'));

    expect(label.position).toBe('sticky');
    // The offset is the shared label-column token, not a repeated magic
    // number: the sticky offset and the column width cannot drift apart if
    // there is only one of them.
    expect(label.left).toContain('--ll-label-col');
    expect(ruleFor('.lease-level-statement-table')).toContain('--ll-label-col:');
  });

  it('cannot leave its own phase (M10)', () => {
    draw('monthly');
    const cells = all('th.lease-level-statement-period');
    expect(cells).toHaveLength(2);

    // A sticky box is clamped to its containing block. Each label's containing
    // block is its own band cell, so Hold Period travels as far as the sale and
    // then goes with its band -- it cannot cross into the Forward 12 columns
    // and mislabel them, and Forward 12 cannot back into the hold period.
    for (const cell of cells) {
      const labels = cell.querySelectorAll('.lease-level-statement-period-label');
      expect(labels).toHaveLength(1);
      expect(labels[0].parentElement).toBe(cell);
    }
    expect(all('.lease-level-statement-period-label')).toHaveLength(2);
  });

  it('starts clear of the Line Item column, which stays put (M10)', () => {
    draw('monthly');
    const corner = getComputedStyle(one('.lease-level-statement-corner'));

    expect(corner.position).toBe('sticky');
    expect(corner.left).toBe('0px');
    // The regression that started this gate: a bare class lost to
    // `.cash-flow-table th`, and the words "Line Item" rendered right-aligned
    // against the first month.
    expect(corner.textAlign).toBe('left');
    expect(one('.lease-level-statement-corner').textContent).toBe('Line Item');

    // The phase labels sit to its right, and are opaque so the months passing
    // beneath do not read through them.
    const label = getComputedStyle(one('.lease-level-statement-period-label'));
    expect(label.left).not.toBe('0px');
    expect(label.background).toContain('--color-surface-muted');
  });

  it('belongs to the annual view not at all', () => {
    draw('annual');
    expect(document.querySelector('.lease-level-statement-period')).toBeNull();
    expect(document.querySelector('.lease-level-statement-period-label')).toBeNull();
    // The Line Item cell is still the left-aligned sticky corner without it.
    const corner = getComputedStyle(one('.lease-level-statement-corner'));
    expect(corner.textAlign).toBe('left');
    expect(corner.position).toBe('sticky');
  });
});

// =============================================================================
// 3. Section labels: sticky to the visible table
// =============================================================================

const MONTHLY_SECTIONS = ['Revenue', 'Operating Expenses', 'Leasing & Capital Costs', 'Occupancy'];
const ANNUAL_SECTIONS = [
  'Revenue',
  'Operating Expenses',
  'Leasing & Capital Costs',
  'Financing',
  'Occupancy',
];

describe('the section labels', () => {
  it.each([
    ['annual', ANNUAL_SECTIONS],
    ['monthly', MONTHLY_SECTIONS],
  ] as const)('gives every %s band exactly one label', (view, expected) => {
    draw(view);
    const labels = all('.lease-level-statement-section-label');
    expect(labels.map((label) => label.textContent)).toEqual(expected);
    // One band, one label. Never repeated into the month cells, which at 72
    // columns would be 72 copies of the word "Occupancy".
    expect(all('th[scope="rowgroup"]')).toHaveLength(expected.length);
    for (const band of all('th[scope="rowgroup"]')) {
      expect(band.querySelectorAll('.lease-level-statement-section-label')).toHaveLength(1);
    }
  });

  it.each(ANNUAL_SECTIONS)('keeps "%s" visible while the table scrolls (M14-M18)', (title) => {
    draw('annual');
    const label = all('.lease-level-statement-section-label').find(
      (candidate) => candidate.textContent === title,
    );
    expect(label, `no label for ${title}`).toBeDefined();

    const style = getComputedStyle(label as HTMLElement);
    expect(style.position).toBe('sticky');
    // Aligned with the line-item column, which is where the rows the section
    // names are read from.
    expect(style.left).toBe('0px');
  });

  it('is the label that moves, not the band cell (M14)', () => {
    draw('monthly');
    // The band cell spans every column, so a sticky *cell* has nowhere to go:
    // it is clamped to a containing block exactly as wide as itself. That is
    // why the title used to scroll out of view and leave an empty stripe.
    expect(getComputedStyle(one('.lease-level-statement-section th')).position).toBe('static');
    expect(getComputedStyle(one('.lease-level-statement-section-label')).position).toBe('sticky');
  });

  it('is opaque and sits above the cells it passes (M19, M20)', () => {
    draw('monthly');
    const style = getComputedStyle(one('.lease-level-statement-section-label'));

    expect(style.background).toContain('--color-surface-muted');
    expect(style.background).not.toContain('transparent');
    expect(Number(style.zIndex)).toBeGreaterThan(0);
  });

  it('never repeats a section title into a data cell (M21)', () => {
    draw('monthly');
    const titles = new Set(MONTHLY_SECTIONS);
    for (const cell of all('.lease-level-statement-table td')) {
      expect(titles.has(cell.textContent ?? ''), `a cell reads ${cell.textContent}`).toBe(false);
    }
  });
});

// =============================================================================
// 4. The two stickinesses are different things (M22)
// =============================================================================

describe('the two sticky scopes', () => {
  it('do not share an offset, because they do not share a purpose (M22)', () => {
    draw('monthly');
    const phase = getComputedStyle(one('.lease-level-statement-period-label'));
    const section = getComputedStyle(one('.lease-level-statement-section-label'));

    // A section applies to every column, so its title sticks to the visible
    // table at the line-item column. A phase applies to a range of columns, so
    // its title sticks within that range, clear of the line-item column. Giving
    // them the same offset would put the phase name over the row labels.
    expect(section.left).toBe('0px');
    expect(phase.left).toContain('--ll-label-col');
    expect(phase.left).not.toBe(section.left);

    // And they are constrained differently: the phase label by its band cell,
    // the section label by a cell that spans the whole table.
    expect(one('.lease-level-statement-period-label').closest('th')?.getAttribute('scope')).toBe(
      'colgroup',
    );
    expect(one('.lease-level-statement-section-label').closest('th')?.getAttribute('scope')).toBe(
      'rowgroup',
    );
  });

  it('leaves the boundary rule on the first forward column (M11)', () => {
    draw('monthly');
    const boundaries = all('.lease-level-statement-boundary');
    // The band cell and every cell of the first forward column.
    expect(boundaries.length).toBeGreaterThan(1);
    expect(ruleFor('.lease-level-statement-boundary')).toContain('border-left: 3px solid');

    const headers = Array.from(
      document.querySelectorAll('.lease-level-statement-table thead tr:last-child th'),
    );
    const flagged = HEALTHY.monthly_projection.months.map((month) => month.is_forward_exit_month);
    const marked = headers.map((cell) =>
      cell.classList.contains('lease-level-statement-boundary'),
    );
    // Exactly one boundary column, and it is the first month the backend
    // flagged -- not a position this file worked out for itself.
    expect(marked.filter(Boolean)).toHaveLength(1);
    expect(marked.indexOf(true)).toBe(flagged.indexOf(true));
  });
});
