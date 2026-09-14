/**
 * Phase 7 Gate P7.3 -- the Scenario UI computes nothing, compares nothing, and
 * calls nothing a Strategy.
 *
 * The P7 architecture keeps every financial number in the backend (P-5,
 * Q22): the frontend formats what the engine returned, and nothing more. The
 * Scenario modules are the newest place browser arithmetic could creep in, and
 * a comparison matrix is exactly where a "harmless" delta or worst case would
 * be tempting. So this file parses each module and allows exactly one
 * arithmetic expression: the percent display conversion in
 * `scenarioCatalog.ts`.
 *
 * It also pins the P7.3 vocabulary cleanup. "Strategy" is reserved for the P7.4
 * decision configuration. The Deal Context field is never called that again in
 * code or on screen, and P7.3 introduces no Strategy entity or state of any
 * kind. History comments may still name the old component; code may not.
 */

import { beforeAll, describe, expect, it } from 'vitest';
import ts from 'typescript';
import { withLfLineEndings } from './testSourceText';

const SOURCES = Object.fromEntries(
  Object.entries(
    import.meta.glob('./**/*.{ts,tsx}', {
      query: '?raw',
      eager: true,
      import: 'default',
    }) as Record<string, string>,
  ).map(([path, text]) => [path, withLfLineEndings(text)]),
) as Record<string, string>;

/** `node:fs` through a variable specifier, as `testSourceText.test.ts` does:
 * the stylesheet cannot come through `?raw`, which Vitest's CSS handling would
 * empty. */
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

function sourceOf(relative: string): string {
  const text = SOURCES[`./${relative}`];
  if (text === undefined) {
    throw new Error(`No source loaded for ./${relative}`);
  }
  return text;
}

const PRODUCTION = Object.entries(SOURCES).filter(([path]) => !/\.test\.tsx?$/.test(path));

/** Every P7.3 Scenario module. */
const SCENARIO_MODULES = [
  'scenarioTypes.ts',
  'scenarioCatalog.ts',
  'scenarioComparison.ts',
  'useScenarios.ts',
  'components/ScenarioWorkspace.tsx',
  'components/ScenarioEditor.tsx',
  'components/ScenarioComparisonMatrix.tsx',
];

function parse(fileName: string, text: string): ts.SourceFile {
  return ts.createSourceFile(
    fileName,
    text,
    ts.ScriptTarget.Latest,
    true,
    fileName.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
}

function walk(node: ts.Node, visit: (node: ts.Node) => void): void {
  visit(node);
  node.forEachChild((child) => walk(child, visit));
}

const ARITHMETIC = new Set<ts.SyntaxKind>([
  ts.SyntaxKind.PlusToken,
  ts.SyntaxKind.MinusToken,
  ts.SyntaxKind.AsteriskToken,
  ts.SyntaxKind.SlashToken,
  ts.SyntaxKind.PercentToken,
  ts.SyntaxKind.AsteriskAsteriskToken,
  ts.SyntaxKind.PlusEqualsToken,
  ts.SyntaxKind.MinusEqualsToken,
  ts.SyntaxKind.AsteriskEqualsToken,
  ts.SyntaxKind.SlashEqualsToken,
  ts.SyntaxKind.PercentEqualsToken,
]);

/** Aggregating or re-parsing calls: a total, an extreme, or a number rebuilt
 * from a formatted string. */
const COMPUTING_CALLS = /(^|\.)(reduce|reduceRight)$|^(parseFloat|parseInt|Number)$/;

/** Every expression that computes: arithmetic, an increment, the negation of a
 * non-literal, `Math`, and the aggregating or re-parsing calls. */
function computationSites(fileName: string, text: string): string[] {
  const source = parse(fileName, text);
  const sites: string[] = [];
  walk(source, (node) => {
    if (ts.isBinaryExpression(node) && ARITHMETIC.has(node.operatorToken.kind)) {
      sites.push(node.getText(source));
    }
    if (ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node)) {
      const op = node.operator;
      const negation =
        ts.isPrefixUnaryExpression(node) &&
        (op === ts.SyntaxKind.MinusToken || op === ts.SyntaxKind.PlusToken) &&
        !ts.isNumericLiteral(node.operand);
      if (op === ts.SyntaxKind.PlusPlusToken || op === ts.SyntaxKind.MinusMinusToken || negation) {
        sites.push(node.getText(source));
      }
    }
    if (ts.isPropertyAccessExpression(node) && node.expression.getText(source) === 'Math') {
      sites.push(node.getText(source));
    }
    if (ts.isCallExpression(node) && COMPUTING_CALLS.test(node.expression.getText(source))) {
      sites.push(node.getText(source));
    }
  });
  return sites;
}

/** Every identifier a module declares or reads. Comments are not code. */
function identifiers(fileName: string, text: string): Set<string> {
  const found = new Set<string>();
  walk(parse(fileName, text), (node) => {
    if (ts.isIdentifier(node)) {
      found.add(node.text);
    }
  });
  return found;
}

/** What a module can put on screen or on the wire: its string literals,
 * template text and JSX text. Comments are excluded. */
function textTokens(fileName: string, text: string): string[] {
  const tokens: string[] = [];
  walk(parse(fileName, text), (node) => {
    if (
      ts.isStringLiteral(node) ||
      ts.isNoSubstitutionTemplateLiteral(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node) ||
      ts.isJsxText(node)
    ) {
      tokens.push(node.text);
    }
  });
  return tokens;
}

/** The keys of every object literal a module builds. */
function objectLiteralKeys(fileName: string, text: string): string[] {
  const keys: string[] = [];
  walk(parse(fileName, text), (node) => {
    if (
      (ts.isPropertyAssignment(node) || ts.isShorthandPropertyAssignment(node)) &&
      ts.isObjectLiteralExpression(node.parent)
    ) {
      keys.push(node.name.getText());
    }
  });
  return keys;
}

describe('the Scenario UI computes nothing', () => {
  it('computes nothing but the percent display conversion and the editor row-key sequence', () => {
    const sites = Object.fromEntries(
      SCENARIO_MODULES.map((relative) => [relative, computationSites(relative, sourceOf(relative))]),
    );
    // Two approved sites, neither a financial value:
    // - `value * 100`: a stored decimal rate shown as the percentage an
    //   analyst types (display units, the `convert.ts` convention);
    // - `rowSequence.current += 1`: the React key of an editor row, which is
    //   never an id and never leaves the browser.
    expect(sites).toEqual({
      'scenarioTypes.ts': [],
      'scenarioCatalog.ts': ['value * 100'],
      'scenarioComparison.ts': [],
      'useScenarios.ts': ['rowSequence.current += 1'],
      'components/ScenarioWorkspace.tsx': [],
      'components/ScenarioEditor.tsx': [],
      'components/ScenarioComparisonMatrix.tsx': [],
    });
    const catalog = sourceOf('scenarioCatalog.ts');
    const conversion = catalog.slice(catalog.indexOf('export function scenarioValueToText'));
    expect(conversion).toContain('formatDisplayNumber(value * 100)');
  });

  it('would see a smuggled cross-cell figure', () => {
    expect(
      computationSites('m.ts', 'const d = cell.results.levered_irr - base.results.levered_irr;'),
    ).toEqual(['cell.results.levered_irr - base.results.levered_irr']);
    expect(computationSites('m.ts', 'const worst = Math.min(...irrs);')).toEqual(['Math.min']);
    expect(computationSites('m.ts', 'const total = profits.reduce((a, b) => a, 0);')).toHaveLength(1);
    expect(computationSites('m.ts', "const back = Number('14.23');")).toHaveLength(1);
    expect(computationSites('m.ts', 'const flipped = -cell.value;')).toEqual(['-cell.value']);
  });

  it('names no cross-cell figure, ranking or expected value', () => {
    const forbidden = /delta|worst|best|average|weighted|expected|rank|spread|variance/i;
    for (const relative of SCENARIO_MODULES) {
      const named = [...identifiers(relative, sourceOf(relative))].filter((name) => forbidden.test(name));
      expect(named, relative).toEqual([]);
    }
    // The name check has teeth.
    expect(
      [...identifiers('m.ts', 'const worstCase = cells; const deltaVsBase = 1;')].filter((name) =>
        forbidden.test(name),
      ),
    ).toEqual(['worstCase', 'deltaVsBase']);
  });

  it('reaches the backend only through api.ts, and only from the hook', () => {
    for (const relative of SCENARIO_MODULES) {
      const text = sourceOf(relative);
      expect(text, relative).not.toMatch(/\bfetch\(/);
      const importsApi = /from '\.{1,2}\/api'/.test(text);
      expect(importsApi, relative).toBe(relative === 'useScenarios.ts');
    }
  });

  it('never builds a Scenario id, an Investment id or a Base scenario', () => {
    for (const relative of SCENARIO_MODULES) {
      const keys = objectLiteralKeys(relative, sourceOf(relative));
      expect(keys, relative).not.toContain('scenario_id');
      expect(keys, relative).not.toContain('investment_id');
    }
    expect(objectLiteralKeys('m.ts', "const s = { scenario_id: 'base', name: 'Base' };")).toContain(
      'scenario_id',
    );
  });
});

describe('Deal Context is never called a Strategy', () => {
  it('no production code keeps the old component or class names', () => {
    for (const [path, text] of PRODUCTION) {
      const code = [...identifiers(path, text), ...textTokens(path, text)];
      expect(
        code.filter((token) => /StrategyStrip|strategy-strip/.test(token)),
        path,
      ).toEqual([]);
    }
    expect(CSS).not.toContain('strategy-strip');
    expect(CSS).toContain('.deal-context-strip-label');
  });

  it('no production source renders "Strategy" as a label of its own', () => {
    for (const [path, text] of PRODUCTION) {
      expect(
        textTokens(path, text).filter((token) => token.trim() === 'Strategy'),
        path,
      ).toEqual([]);
    }
  });

  it('the strip labels the field Deal Context', () => {
    expect(sourceOf('components/DealContextStrip.tsx')).toContain(
      '<span className="deal-context-strip-label">Deal Context</span>',
    );
  });

  it('introduces no Strategy entity, state or selector', () => {
    for (const relative of [...SCENARIO_MODULES, 'App.tsx', 'components/DealContextStrip.tsx']) {
      const named = [...identifiers(relative, sourceOf(relative))].filter((name) => /strateg/i.test(name));
      expect(named, relative).toEqual([]);
    }
  });
});

describe('the Risk workspace', () => {
  it('puts Scenarios first and opens on it in every mode', () => {
    const app = sourceOf('App.tsx');
    expect(app).toContain(
      "{ id: 'scenarios', label: 'Scenarios' },\n  { id: 'returns', label: 'Return Sensitivity' },",
    );
    expect(app).toContain(
      "{ id: 'scenarios', label: 'Scenarios' },\n  { id: 'sensitivity', label: 'Sensitivity' },",
    );
    expect(app).toContain("useState<RiskViewId>('scenarios')");
    expect(app).toContain("useState<LeaseLevelRiskViewId>('scenarios')");
  });

  it('keys each Scenario workspace by its mode and open deal', () => {
    const app = sourceOf('App.tsx');
    expect(app).toContain("key={`quick:${currentDealId ?? 'unsaved'}`}");
    expect(app).toContain("key={`detailed:${currentDetailedDealId ?? 'unsaved'}`}");
    expect(app).toContain("key={`lease_level:${leaseLevel.currentDealId ?? 'unsaved'}`}");
  });
});

describe('the comparison never widens the page', () => {
  function rule(selector: string): string {
    const start = CSS.indexOf(`\n${selector} {`);
    expect(start, selector).toBeGreaterThan(-1);
    return CSS.slice(start, CSS.indexOf('}', start));
  }

  it('scrolls inside its own region', () => {
    const scroll = rule('.scenario-matrix-scroll');
    expect(scroll).toContain('overflow-x: auto;');
    expect(scroll).toContain('max-width: 100%;');
  });

  it('lets its containers shrink rather than push the shell', () => {
    expect(rule('.scenario-workspace')).toContain('min-width: 0;');
    expect(rule('.scenario-panel')).toContain('min-width: 0;');
    expect(rule('.scenario-override-block')).toContain('min-width: 0;');
  });
});
