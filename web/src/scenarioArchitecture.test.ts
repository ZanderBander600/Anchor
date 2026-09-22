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

/** Every Scenario module. P7.5 retired the P7.3 Scenario Comparison
 * (`scenarioComparison.ts`, `ScenarioComparisonMatrix.tsx`): the Decision
 * Matrix is the one comparison surface, guarded by
 * `decisionArchitecture.test.ts`. */
const SCENARIO_MODULES = [
  'scenarioTypes.ts',
  'scenarioCatalog.ts',
  'useScenarios.ts',
  'components/ScenarioWorkspace.tsx',
  'components/ScenarioEditor.tsx',
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
      'useScenarios.ts': ['rowSequence.current += 1'],
      'components/ScenarioWorkspace.tsx': [],
      'components/ScenarioEditor.tsx': [],
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

  /**
   * Surfaces that label a *real* P7.4 Strategy, widened at P7.10 Stage 4.
   *
   * This rule was written when the only thing in the product that could be
   * labelled "Strategy" was the Deal Context field under its old, wrong name,
   * so banning the bare token everywhere and banning the mislabel were the same
   * rule. P7.4 then introduced actual Strategies, and the Investment Memo is the
   * first surface that has to *name* one: its decision context asks the analyst
   * which Strategy the recommendation is made from, and the report prints that
   * Strategy's name under the same word.
   *
   * Each file is named literally, and the claim below is unchanged for every
   * other file: the Deal Context is still never called a Strategy, and
   * `StrategyStrip` / `strategy-strip` are still banned outright by the test
   * above, which no exemption reaches.
   */
  const STRATEGY_SELECTORS = [
    './components/MemoDecisionPanel.tsx',
    './components/MemoReportView.tsx',
  ];

  it('no production source renders "Strategy" as a label of its own', () => {
    for (const [path, text] of PRODUCTION) {
      if (STRATEGY_SELECTORS.includes(path)) {
        continue;
      }
      expect(
        textTokens(path, text).filter((token) => token.trim() === 'Strategy'),
        path,
      ).toEqual([]);
    }
  });

  it('the exemption is two named files, and the rule still bites elsewhere', () => {
    // A guard widened until everything passes looks exactly like one that finds
    // nothing, so the exemption is bounded and the rule is shown still firing.
    expect(STRATEGY_SELECTORS).toHaveLength(2);
    for (const path of STRATEGY_SELECTORS) {
      expect(PRODUCTION.map(([candidate]) => candidate)).toContain(path);
    }
    expect(
      textTokens('seeded.tsx', '<span className="deal-context-label">Strategy</span>').filter(
        (token) => token.trim() === 'Strategy',
      ),
    ).toEqual(['Strategy']);
  });

  it('the memo names a Strategy, and never the Deal Context', () => {
    // The exemption is for the P7.4 entity, not a licence to relabel the Deal
    // Context inside the memo.
    for (const path of STRATEGY_SELECTORS) {
      const source = SOURCES[path];
      expect(source).not.toContain('deal-context');
      expect(source).not.toContain('dealContext');
    }
  });

  it('the strip labels the field Deal Context', () => {
    expect(sourceOf('components/DealContextStrip.tsx')).toContain(
      '<span className="deal-context-strip-label">Deal Context</span>',
    );
  });

  it('keeps the Scenario modules and the Deal Context strip free of Strategy', () => {
    // P7.5 ships Strategy in its own modules; a Scenario stays independent of
    // it, and the Deal Context field is still never a Strategy.
    for (const relative of [...SCENARIO_MODULES, 'components/DealContextStrip.tsx']) {
      const named = [...identifiers(relative, sourceOf(relative))].filter((name) => /strateg/i.test(name));
      expect(named, relative).toEqual([]);
    }
  });
});

describe('the Risk workspace', () => {
  it('leads with the Decision Matrix, Strategies and Scenarios, and opens on the matrix in every mode', () => {
    const app = sourceOf('App.tsx');
    // Re-pinned at P7.8B, which added Capital Structure as the fourth decision
    // view, and again at P7.9 Stage 3, which adds Partnership as the fifth --
    // the gate that ships it. Its position is part of the claim: the decision
    // views stay together, ahead of Sensitivity and Break-Even, so the analyst
    // reads "what I choose" before "how it moves". Partnership sits after
    // Capital Structure because it allocates the Common Equity the structure
    // leaves behind.
    expect(app).toContain(
      [
        "  { id: 'matrix', label: 'Decision Matrix' },",
        "  { id: 'strategies', label: 'Strategies' },",
        "  { id: 'scenarios', label: 'Scenarios' },",
        "  { id: 'capital-structure', label: 'Capital Structure' },",
        "  { id: 'partnership', label: 'Partnership' },",
        "  { id: 'sensitivity', label: 'Sensitivity' },",
        "  { id: 'break-even', label: 'Break-Even' },",
      ].join('\n'),
    );
    expect(app).toContain(
      [
        "  { id: 'matrix', label: 'Decision Matrix' },",
        "  { id: 'strategies', label: 'Strategies' },",
        "  { id: 'scenarios', label: 'Scenarios' },",
        "  { id: 'capital-structure', label: 'Capital Structure' },",
        "  { id: 'partnership', label: 'Partnership' },",
        "  { id: 'sensitivity', label: 'Sensitivity' },",
        '];',
      ].join('\n'),
    );
    expect(app).toContain("useState<RiskViewId>('matrix')");
    expect(app).toContain("useState<LeaseLevelRiskViewId>('matrix')");
  });

  it('keys each Scenario workspace by its mode and open deal', () => {
    const app = sourceOf('App.tsx');
    expect(app).toContain("key={`quick:${currentDealId ?? 'unsaved'}`}");
    expect(app).toContain("key={`detailed:${currentDetailedDealId ?? 'unsaved'}`}");
    expect(app).toContain("key={`lease_level:${leaseLevel.currentDealId ?? 'unsaved'}`}");
  });
});

describe('the Scenario panels never widen the page', () => {
  function rule(selector: string): string {
    const start = CSS.indexOf(`\n${selector} {`);
    expect(start, selector).toBeGreaterThan(-1);
    return CSS.slice(start, CSS.indexOf('}', start));
  }

  it('retires the P7.3 comparison styles with the comparison', () => {
    expect(CSS).not.toContain('.scenario-matrix');
  });

  it('lets its containers shrink rather than push the shell', () => {
    expect(rule('.scenario-workspace')).toContain('min-width: 0;');
    expect(rule('.scenario-panel')).toContain('min-width: 0;');
    expect(rule('.scenario-override-block')).toContain('min-width: 0;');
  });
});
