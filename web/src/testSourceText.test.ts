/**
 * D5.9 -- the line-ending oracle for every test that reads source text.
 *
 * Several suites assert structure against production sources and the
 * stylesheet read as text, and two of them encode a line break in the literal
 * they look for. Those passed or failed depending on whether git had checked a
 * file out with LF or CRLF -- a property of the working tree, not of the code.
 * `withLfLineEndings` closes that at the point the text is loaded.
 *
 * This file proves three things, in memory and without touching a file on
 * disk: the normaliser maps every line-ending convention to the same text; the
 * exact multiline literals the suites depend on hold identically for LF and
 * CRLF content once normalised (and demonstrably do not on raw CRLF, which is
 * the fragility); and every test that reads source text routes it through the
 * normaliser, so a new one cannot quietly reintroduce the problem.
 */

import { describe, expect, it } from 'vitest';
import { withLfLineEndings } from './testSourceText';

import appSourceText from './App.tsx?raw';

/** `node:fs` through a variable specifier, as `leaseLevelStatementLayout`
 * does: the stylesheet cannot come through `?raw`, which Vitest's CSS
 * handling would empty. */
async function readCss(): Promise<string> {
  const load = (specifier: string) =>
    import(/* @vite-ignore */ specifier) as Promise<{
      readFileSync: (file: string, encoding: string) => string;
    }>;
  const fs = await load('node:fs');
  const runtime = globalThis as unknown as { process: { cwd: () => string } };
  return withLfLineEndings(fs.readFileSync(`${runtime.process.cwd()}/src/index.css`, 'utf8'));
}

/** The same content as a CRLF working tree would hold it. */
function asCrlf(text: string): string {
  return withLfLineEndings(text).replace(/\n/g, '\r\n');
}

const APP = withLfLineEndings(appSourceText);

/** Every frontend source a structural test can read -- production and test. */
const ALL_SOURCES = import.meta.glob('./**/*.{ts,tsx}', {
  query: '?raw',
  eager: true,
  import: 'default',
}) as Record<string, string>;

describe('withLfLineEndings', () => {
  it('maps CRLF, a lone CR and LF to LF', () => {
    expect(withLfLineEndings('a\r\nb\rc\nd')).toBe('a\nb\nc\nd');
    expect(withLfLineEndings('a\r\n\r\nb')).toBe('a\n\nb');
    expect(withLfLineEndings('a\r\r\nb')).toBe('a\n\nb');
  });

  it('changes nothing else', () => {
    expect(withLfLineEndings('')).toBe('');
    expect(withLfLineEndings('\ta  b\t\n')).toBe('\ta  b\t\n');
    expect(withLfLineEndings("const x = '\\r\\n';")).toBe("const x = '\\r\\n';");
  });

  it('is idempotent', () => {
    const once = withLfLineEndings('a\r\nb\rc');
    expect(withLfLineEndings(once)).toBe(once);
  });

  it('yields identical text from the LF and CRLF form of every frontend source', () => {
    const paths = Object.keys(ALL_SOURCES);
    expect(paths.length).toBeGreaterThan(50);
    for (const [path, raw] of Object.entries(ALL_SOURCES)) {
      const lf = withLfLineEndings(raw);
      expect(withLfLineEndings(asCrlf(lf)), path).toBe(lf);
    }
  });
});

describe('CRLF oracle -- the assertions that encode a line break', () => {
  // The literals are the ones the suites actually use. Each is checked against
  // the real source in both forms: raw CRLF text does not contain it, which is
  // the fragility, and the normalised text does, identically to LF.
  it('the NOI selector list `leaseLevelStatementLayout` reads from index.css', async () => {
    const lf = await readCss();
    const literal = '.lease-level-statement-noi th,\n.lease-level-statement-noi td {';
    const crlf = asCrlf(lf);

    expect(crlf).not.toBe(lf);
    expect(lf).toContain(literal);
    expect(crlf).not.toContain(literal);
    expect(withLfLineEndings(crlf)).toBe(lf);
    expect(withLfLineEndings(crlf)).toContain(literal);
  });

  it('the Lease-Level Open Deal arm `modeDispatch` M15 reads from App.tsx', () => {
    const literal = "case 'lease_level':\n        return openLeaseLevelDealFromLibrary(deal);";
    const crlf = asCrlf(APP);

    expect(crlf).not.toBe(APP);
    expect(APP).toContain(literal);
    expect(crlf).not.toContain(literal);
    expect(withLfLineEndings(crlf)).toBe(APP);
    expect(withLfLineEndings(crlf)).toContain(literal);
  });

  it('keeps a multiline `not.toContain` meaningful on a CRLF file', () => {
    // The quieter half of the problem. On raw CRLF text a forbidden multiline
    // shape can never match, so a negative assertion passed without looking.
    // Here the shape is really present -- the M15 mutant, Lease-Level opened as
    // Quick -- and only the normalised text lets the check see it.
    const guarded = "case 'lease_level':\n        return openLeaseLevelDealFromLibrary(deal);";
    const forbidden = "case 'lease_level':\n        return openQuickDealFromLibrary(deal);";
    const mutant = APP.replace(guarded, forbidden);

    expect(mutant).toContain(forbidden);
    expect(asCrlf(mutant)).not.toContain(forbidden);
    expect(withLfLineEndings(asCrlf(mutant))).toContain(forbidden);
  });
});

describe('every test that reads source text normalises it', () => {
  const TESTS = Object.entries(ALL_SOURCES)
    .filter(([path]) => /\.test\.tsx?$/.test(path))
    .map(([path, text]) => [path, withLfLineEndings(text)] as const);
  const READERS = TESTS.filter(([, text]) => /\?raw['"]|readFileSync\(/.test(text));

  it('finds the readers it is auditing', () => {
    // The files known at D5.9. A scan that found none would pass every check
    // below by finding nothing to check. (Vite's glob omits the file that
    // calls it, so this one is not in the list; it normalises everything it
    // reads above, where that can be read directly.)
    const names = READERS.map(([path]) => path);
    for (const known of [
      './modeDispatch.architecture.test.ts',
      './leaseLevelStatementLayout.test.tsx',
      './hiddenIssues.mutations.test.tsx',
      './inputPolish.test.tsx',
      './leaseLevelAnalysisPersistence.test.tsx',
      './ownerSummary.test.ts',
      './components/OwnerSummaryPanel.test.tsx',
    ]) {
      expect(names).toContain(known);
    }
  });

  it.each(READERS.map(([path, text]) => ({ path, text })))(
    '$path routes what it reads through withLfLineEndings',
    ({ path, text }) => {
      expect(text, `${path} reads source text and never normalises it`).toContain(
        'withLfLineEndings(',
      );
      // A statically imported source is the common case, and the easiest to
      // leave raw by accident: every such binding must reach the normaliser.
      for (const match of text.matchAll(/^import (\w+) from '[^']+\?raw';$/gm)) {
        expect(text, `${path} uses ${match[1]} without normalising it`).toContain(
          `withLfLineEndings(${match[1]})`,
        );
      }
    },
  );
});
