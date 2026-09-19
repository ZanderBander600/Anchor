/**
 * Second P7.9 / AM1 QA pass -- the collapsed rail keeps every button's name.
 *
 * Below 1024px the sidebar collapses to an icon rail and `.sidebar-nav-label`
 * is `display: none`, which removes the visible text from the accessibility
 * tree. A rail button whose name came only from that text became an unnamed
 * button: browser QA found Deal Library and New Deal announced as "button".
 *
 * jsdom does not evaluate media queries, so these tests lift the stylesheet's
 * own collapsed-rail rules out of its `@media (max-width: 1023px)` block and
 * apply them, then read each button's computed accessible name -- the same
 * name a screen reader would announce, as Testing Library computes it for a
 * role query -- rather than looking for a string in the source.
 */

import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import { AppSidebar } from './components/AppSidebar';
import { withLfLineEndings } from './testSourceText';

async function readCss(): Promise<string> {
  const load = (specifier: string) =>
    import(/* @vite-ignore */ specifier) as Promise<{
      readFileSync: (file: string, encoding: string) => string;
    }>;
  const fs = await load('node:fs');
  const runtime = globalThis as unknown as { process: { cwd: () => string } };
  return withLfLineEndings(fs.readFileSync(`${runtime.process.cwd()}/src/index.css`, 'utf8'));
}

/** The inner rules of the one `@media (max-width: 1023px)` block that
 * collapses the rail -- the block that hides `.sidebar-nav-label`. */
function collapsedRailRules(css: string): string {
  const query = '@media (max-width: 1023px) {';
  const blocks: string[] = [];
  let start = css.indexOf(query);
  while (start !== -1) {
    let depth = 0;
    let end = -1;
    for (let index = css.indexOf('{', start); index < css.length && end === -1; index += 1) {
      if (css[index] === '{') depth += 1;
      if (css[index] === '}') {
        depth -= 1;
        if (depth === 0) end = index;
      }
    }
    blocks.push(css.slice(css.indexOf('{', start) + 1, end));
    start = css.indexOf(query, end);
  }
  const collapsing = blocks.filter((block) => block.includes('.sidebar-nav-label'));
  expect(collapsing).toHaveLength(1);
  return collapsing[0];
}

let RAIL_RULES = '';
let railStyle: HTMLStyleElement | null = null;

beforeAll(async () => {
  RAIL_RULES = collapsedRailRules(await readCss());
});

afterEach(() => {
  cleanup();
  railStyle?.remove();
  railStyle = null;
});

/** Every navigation button's computed accessible name, in document order. */
function railButtonNames(): string[] {
  const names: string[] = [];
  screen.getAllByRole('button', {
    name: (accessibleName, element) => {
      if (element.classList.contains('sidebar-nav-item')) {
        names.push(accessibleName);
      }
      return true;
    },
  });
  return names;
}

function collapseRail() {
  railStyle = document.createElement('style');
  railStyle.textContent = RAIL_RULES;
  document.head.appendChild(railStyle);
}

function renderSidebar() {
  return render(
    <AppSidebar
      deals={[]}
      isDealsLoading={false}
      activeDealId={null}
      view="workspace"
      onOpenLibrary={vi.fn()}
      onNewDeal={vi.fn()}
      onOpenDeal={vi.fn()}
      investments={[]}
      onOpenInvestmentLibrary={vi.fn()}
      onNewInvestment={vi.fn()}
      onOpenInvestment={vi.fn()}
      onOpenAssetManagement={vi.fn()}
    />,
  );
}

const RAIL_BUTTONS = [
  'Acquisitions',
  'Asset Management',
  'Deal Library',
  'New Deal',
  'Investment Library',
  'New Investment',
];

describe('the collapsed rail keeps every navigation button named', () => {
  it('really hides the visible labels when collapsed', () => {
    const { container } = renderSidebar();
    collapseRail();
    const label = container.querySelector('.sidebar-nav-label') as HTMLElement;
    expect(getComputedStyle(label).display).toBe('none');
  });

  it('names Deal Library and New Deal exactly while the labels are hidden', () => {
    renderSidebar();
    collapseRail();
    const names = railButtonNames();
    expect(names).toHaveLength(RAIL_BUTTONS.length);
    expect(names).not.toContain('');
    for (const name of RAIL_BUTTONS) {
      expect(names).toContain(name);
    }
    expect(screen.getByRole('button', { name: 'Deal Library' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'New Deal' })).toBeTruthy();
  });

  it('announces each name once, at desktop width too', () => {
    renderSidebar();
    // Exactly the label: the stated name replaces the content, so the visible
    // text is not spoken a second time ("Deal Library Deal Library").
    expect(railButtonNames()).toEqual(RAIL_BUTTONS);
    for (const name of ['Deal Library', 'New Deal']) {
      expect(screen.getByRole('button', { name }).textContent).toBe(name);
    }
  });
});
