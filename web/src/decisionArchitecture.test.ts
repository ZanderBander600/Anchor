/**
 * Phase 7 Gate P7.5 -- the Strategy and Decision Matrix UI computes nothing,
 * compares nothing and ranks nothing.
 *
 * P-5 and Q22 / DC-5: every cross-cell figure -- Delta vs Base Scenario, Worst
 * Case, Range -- is computed by the backend decision package, and the frontend
 * formats it. The Decision Matrix is exactly where a "harmless" subtraction, a
 * `Math.min` or a sort by value would be tempting, so this file parses every
 * P7.5 module and allows exactly two computing expressions, neither financial:
 * the percent display conversion in `strategyForm.ts` and the editor row-key
 * sequence in `useStrategies.ts`.
 *
 * It also pins what the matrix must never become: an expected-value, scoring
 * or ranking surface (Q19, DC-6), a second metric catalog that decides
 * horizon applicability, or a page-widening table.
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

/** Every P7.5 production module. */
const DECISION_MODULES = [
  'strategyTypes.ts',
  'strategyCatalog.ts',
  'strategyForm.ts',
  'useStrategies.ts',
  'decisionTypes.ts',
  'decisionMatrix.ts',
  'useDecisionMatrix.ts',
  'components/RiskDecisionWorkspace.tsx',
  'components/DecisionMatrixPanel.tsx',
  'components/StrategyManager.tsx',
  'components/StrategyEditor.tsx',
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

/** Aggregating, ordering or re-parsing calls: a total, an extreme, an order
 * by value, or a number rebuilt from a formatted string. */
const COMPUTING_CALLS =
  /(^|\.)(reduce|reduceRight|sort|toSorted|min|max)$|^(parseFloat|parseInt|Number)$/;

/** Every expression that computes: arithmetic, an increment, the negation of
 * a non-literal, any use of `Math`, and the aggregating, ordering or
 * re-parsing calls. */
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

function identifiers(fileName: string, text: string): Set<string> {
  const found = new Set<string>();
  walk(parse(fileName, text), (node) => {
    if (ts.isIdentifier(node)) {
      found.add(node.text);
    }
  });
  return found;
}

/** A module's string literals, template text and JSX text. */
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

describe('the Strategy and Decision Matrix UI computes nothing', () => {
  it('computes nothing but the percent display conversion and the editor row-key sequence', () => {
    const sites = Object.fromEntries(
      DECISION_MODULES.map((relative) => [relative, computationSites(relative, sourceOf(relative))]),
    );
    expect(sites).toEqual({
      'strategyTypes.ts': [],
      'strategyCatalog.ts': [],
      'strategyForm.ts': ['value * 100'],
      'useStrategies.ts': ['rowSequence.current += 1'],
      'decisionTypes.ts': [],
      'decisionMatrix.ts': [],
      'useDecisionMatrix.ts': [],
      'components/RiskDecisionWorkspace.tsx': [],
      'components/DecisionMatrixPanel.tsx': [],
      'components/StrategyManager.tsx': [],
      'components/StrategyEditor.tsx': [],
    });
    const form = sourceOf('strategyForm.ts');
    expect(form.slice(form.indexOf('function percentText'))).toContain(
      'return formatDisplayNumber(value * 100);',
    );
  });

  it('would see a smuggled Delta, Worst Case, Range, ranking or average (M4)', () => {
    expect(
      computationSites('m.tsx', 'const d = cell.metrics[0].value - baseCell.metrics[0].value;'),
    ).toEqual(['cell.metrics[0].value - baseCell.metrics[0].value']);
    expect(computationSites('m.ts', 'const worst = Math.min(...irrs);')).toEqual(['Math.min(...irrs)', 'Math.min']);
    expect(computationSites('m.ts', 'const spread = values.max() ;')).toHaveLength(1);
    expect(computationSites('m.ts', 'const ranked = rows.sort((a, b) => 0);')).toHaveLength(1);
    expect(computationSites('m.ts', 'const total = profits.reduce((a, b) => a, 0);')).toHaveLength(1);
    expect(computationSites('m.ts', "const back = Number('14.23');")).toHaveLength(1);
    expect(computationSites('m.ts', 'const flipped = -cell.value;')).toEqual(['-cell.value']);
  });

  it('names no expected value, probability, weighting, score, ranking or winner', () => {
    // `best` only as a word of its own, so `describeStrategy` is not a match.
    const forbidden = /probab|expected|weight|monte|score|rank|recommend|winner|\bbest(?![a-z])/i;
    for (const relative of DECISION_MODULES) {
      const text = sourceOf(relative);
      const named = [...identifiers(relative, text)].filter((name) => forbidden.test(name));
      expect(named, relative).toEqual([]);
      const shown = textTokens(relative, text).filter((token) => forbidden.test(token));
      expect(shown, relative).toEqual([]);
    }
    expect([...identifiers('m.ts', 'const expectedIrr = 1; const rankStrategies = 2;')].filter((n) => forbidden.test(n)))
      .toEqual(['expectedIrr', 'rankStrategies']);
  });

  it('holds no metric catalog of its own: the backend decides which metrics apply', () => {
    const metricTokens = new Set([
      'levered_irr',
      'unlevered_irr',
      'equity_multiple',
      'total_profit',
      'total_equity_invested',
      'exit_value',
      'min_dscr',
    ]);
    for (const relative of DECISION_MODULES) {
      const tokens = textTokens(relative, sourceOf(relative)).filter((token) => metricTokens.has(token));
      expect(tokens, relative).toEqual([]);
    }
    const panel = sourceOf('components/DecisionMatrixPanel.tsx');
    expect(panel).toContain('matrix.metrics.map(');
    expect(panel).toContain('matrix.omitted_metrics');
    // A hold period is shown, never compared with another to decide which
    // metrics apply.
    expect(panel).not.toMatch(/hold_periods?\b[^;\n]*[!=<>]=?=?\s*[\w.]*hold_period/);
    expect(panel).not.toMatch(/hold_periods\.length/);
  });

  it('reaches the backend only through api.ts, and only from the two hooks', () => {
    for (const relative of DECISION_MODULES) {
      const text = sourceOf(relative);
      expect(text, relative).not.toMatch(/\bfetch\(/);
      const importsApi = /from '\.{1,2}\/api'/.test(text);
      expect(importsApi, relative).toBe(relative === 'useStrategies.ts' || relative === 'useDecisionMatrix.ts');
    }
  });

  it('never builds a Strategy, Scenario or Investment id', () => {
    for (const relative of DECISION_MODULES) {
      const keys = objectLiteralKeys(relative, sourceOf(relative));
      for (const key of ['strategy_id', 'scenario_id', 'investment_id']) {
        expect(keys, relative).not.toContain(key);
      }
    }
  });

  it('never says Strategy on its own, and never shows the hidden Investment', () => {
    for (const relative of DECISION_MODULES) {
      const tokens = textTokens(relative, sourceOf(relative));
      expect(tokens.filter((token) => token.trim() === 'Strategy'), relative).toEqual([]);
      expect(tokens.filter((token) => /Investment/.test(token)), relative).toEqual([]);
    }
  });
});

describe('the P7.3 Scenario Comparison is retired', () => {
  it('leaves no second comparison surface in production code', () => {
    expect(SOURCES['./scenarioComparison.ts']).toBeUndefined();
    expect(SOURCES['./components/ScenarioComparisonMatrix.tsx']).toBeUndefined();
    for (const [path, text] of Object.entries(SOURCES).filter(([p]) => !/\.test\.tsx?$/.test(p))) {
      const tokens = textTokens(path, text);
      expect(tokens.filter((t) => /Scenario Comparison|Run Comparison|Refresh Comparison/.test(t)), path).toEqual([]);
    }
  });

  it('keeps one matrix hook: Scenarios manage Scenarios, and the matrix compares', () => {
    const scenarios = sourceOf('useScenarios.ts');
    expect(scenarios).not.toMatch(/analyzeInvestmentScenario|analyzeAcquisition|getDeal/);
    expect(sourceOf('useDecisionMatrix.ts')).toContain('analyzeDecisionMatrix(investmentId)');
  });
});

describe('the matrix never widens the page, and never colours a winner', () => {
  function rule(selector: string): string {
    const start = CSS.indexOf(`\n${selector} {`);
    expect(start, selector).toBeGreaterThan(-1);
    return CSS.slice(start, CSS.indexOf('}', start));
  }

  const P7_5_BANNER = 'Phase 7 Gate P7.5 -- Strategies and the Decision Matrix (Risk).';
  /** The banner that ends P7.5's section. See the slice below. */
  const P7_6_BANNER = 'Phase 7 Gate P7.6 -- the visible Investment workspace.';

  it('scrolls inside its own region, with the row identity pinned', () => {
    const scroll = rule('.decision-matrix-scroll');
    expect(scroll).toContain('overflow-x: auto;');
    expect(scroll).toContain('max-width: 100%;');
    const pinned = CSS.slice(CSS.indexOf(".decision-matrix-corner,\n.decision-matrix th[scope='row']"));
    expect(pinned.slice(0, pinned.indexOf('}'))).toContain('position: sticky;');
    const panel = sourceOf('components/DecisionMatrixPanel.tsx');
    expect(panel).toContain('role="region"');
    expect(panel).toContain('aria-label="Decision matrix table"');
    expect(panel).toContain('tabIndex={0}');
  });

  it('uses no good / bad / winner colour: only an invalid variant is tinted', () => {
    // Bounded at P7.8B. The slice used to run from P7.5's banner to the end of
    // the stylesheet, so it silently measured every later gate's styles too --
    // a claim about the *matrix* that grew a little less true each time a gate
    // appended to `index.css`, and that would eventually have failed for a
    // reason having nothing to do with the matrix. It now covers exactly P7.5's
    // own section, and the count below stays at its original two. A later
    // gate's colours are that gate's guard's business: P7.8B's are pinned by
    // `capitalStructureArchitecture.test.ts`.
    const start = CSS.indexOf(P7_5_BANNER);
    expect(start).toBeGreaterThan(-1);
    const section = CSS.slice(start, CSS.indexOf(P7_6_BANNER, start));
    expect(section.length).toBeGreaterThan(0);
    expect(section).not.toMatch(/--(success|positive|negative|gain|loss)|heat|winner|best/i);
    const danger = section.split('\n').filter((line) => line.includes('--danger'));
    expect(danger).toHaveLength(2);
    expect(rule('.decision-matrix-invalid')).toContain('var(--danger)');
    expect(rule('.strategy-domain-error .strategy-domain-legend')).toContain('var(--danger)');
  });
});
