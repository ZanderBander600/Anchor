/**
 * Phase 7 Gate P7.8B -- the Capital Structure UI computes nothing.
 *
 * This is the gate where a "harmless" browser calculation would be most
 * tempting and most damaging. The screen shows funded amounts, IRRs, multiples,
 * profit, attachment and detachment points, last-dollar basis, debt yield,
 * coverage, preferred accrual, Funding Requirements and the Common Equity
 * residual -- every one of which the approved P7.8A executor already produces,
 * and any one of which could be "obviously" re-derived in a component from the
 * fields beside it. A second arithmetic authority in the browser is precisely
 * what P-3 and P-5 forbid, and it would be invisible until two surfaces
 * disagreed.
 *
 * So this file parses every P7.8B frontend module and allows exactly the
 * display-scale conversions -- a rate typed as `12.5` and sent as `0.125`, the
 * same conversion `convert.ts` and `strategyForm.ts` already make -- and the
 * position-id sequence. Nothing else computes.
 *
 * It also pins the decisions the gate turns on: no default shortfall
 * resolution and no default accrual convention are invented, changing a
 * position's class or scope mints a new identity (P-8), and the backend is
 * reached only through `api.ts` and only from the hook.
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

function sourceOf(relative: string): string {
  const text = SOURCES[`./${relative}`];
  if (text === undefined) {
    throw new Error(`No source loaded for ./${relative}`);
  }
  return text;
}

/** `node:fs` through a variable specifier, as `decisionArchitecture.test.ts`
 * does: the stylesheet cannot come through `?raw`, which Vitest's CSS handling
 * would empty. */
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

/** Every P7.8B production module. */
const CAPITAL_MODULES = [
  'capitalTypes.ts',
  'capitalStructureForm.ts',
  'useCapitalStructure.ts',
  'usePositionDecisionMatrix.ts',
  'components/CapitalStructureEditor.tsx',
  'components/CapitalStructureResults.tsx',
  'components/CapitalStructureWorkspace.tsx',
  'components/PositionDecisionMatrixPanel.tsx',
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

/** Aggregating, ordering or re-parsing calls: a total, an extreme, an order by
 * value, or a number rebuilt from a formatted string. */
const COMPUTING_CALLS =
  /(^|\.)(reduce|reduceRight|sort|toSorted|min|max)$|^(parseFloat|parseInt|Number)$/;

/** Every expression that computes, exactly as `decisionArchitecture.test.ts`
 * defines it, so the two gates' guards cannot drift into two different ideas of
 * what counts as arithmetic. */
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

describe('the Capital Structure UI computes nothing', () => {
  it('computes nothing but the display-scale conversions and the id sequence', () => {
    const sites = Object.fromEntries(
      CAPITAL_MODULES.map((relative) => [relative, computationSites(relative, sourceOf(relative))]),
    );
    expect(sites).toEqual({
      'capitalTypes.ts': [],
      'capitalStructureForm.ts': [
        'index += 1',
        'rule.pct * 100',
        'terms.interest_rate * 100',
        'terms.preferred_rate * 100',
        'terms.current_pay_rate * 100',
      ],
      'useCapitalStructure.ts': ['key + 1'],
      'usePositionDecisionMatrix.ts': ['key + 1'],
      'components/CapitalStructureEditor.tsx': [],
      'components/CapitalStructureResults.tsx': [],
      'components/CapitalStructureWorkspace.tsx': [],
      'components/PositionDecisionMatrixPanel.tsx': [],
    });
  });

  it('would see a smuggled funded amount, return, coverage or attachment (M4)', () => {
    expect(
      computationSites('m.ts', 'const funded = price * position.pct;'),
    ).toEqual(['price * position.pct']);
    expect(
      computationSites('m.ts', 'const profit = received - invested;'),
    ).toEqual(['received - invested']);
    expect(
      computationSites('m.ts', 'const moic = received / invested;'),
    ).toEqual(['received / invested']);
    expect(computationSites('m.ts', 'const worst = Math.min(...coverages);')).toEqual([
      'Math.min(...coverages)',
      'Math.min',
    ]);
    expect(
      computationSites('m.ts', 'const total = positions.reduce((a, b) => a, 0);'),
    ).toHaveLength(1);
    expect(computationSites('m.ts', "const back = Number('1.48');")).toHaveLength(1);
    expect(computationSites('m.ts', 'const shortfall = -requirement.amount;')).toEqual([
      '-requirement.amount',
    ]);
  });

  it('reaches the backend only through api.ts, and only from the hook', () => {
    for (const relative of CAPITAL_MODULES) {
      const text = sourceOf(relative);
      expect(text, relative).not.toMatch(/\bfetch\(/);
      const importsApi = /from '\.{1,2}\/api'/.test(text);
      expect(importsApi, relative).toBe(
        relative === 'useCapitalStructure.ts' || relative === 'usePositionDecisionMatrix.ts',
      );
    }
  });

  it('invents no shortfall resolution and no accrual convention', () => {
    const form = sourceOf('capitalStructureForm.ts');
    // A new claim-bearing position starts with neither stated, and the form
    // sends `null` rather than a guess. The engine refuses to assume either
    // (P-14, FR-4), and the editor says so before the round trip.
    expect(form).toContain("shortfallResolution: ''");
    expect(form).toContain("accrualConvention: ''");
    expect(form).toContain('accrualPermitted: false');
    expect(form).toContain('export function unstatedChoices');
    // The editor offers the unstated choice explicitly rather than defaulting
    // the first option.
    const editor = sourceOf('components/CapitalStructureEditor.tsx');
    expect(textTokens('components/CapitalStructureEditor.tsx', editor)).toContain('Choose…');
  });

  it('mints a new identity when a position changes class or scope (P-8)', () => {
    const form = sourceOf('capitalStructureForm.ts');
    const change = form.slice(form.indexOf('export function withClassOrScope'));
    expect(change).toContain('identityMoved');
    expect(change).toContain('nextPositionId(form, ID_PREFIXES[positionClass])');
    // The editor routes every class and scope change through it rather than
    // assigning the field directly.
    const editor = sourceOf('components/CapitalStructureEditor.tsx');
    expect(editor).toContain('withClassOrScope(form, position, {');
    expect(editor).not.toMatch(/set\('positionClass'/);
    expect(editor).not.toMatch(/set\('scopeKind'/);
  });

  it('authors only what P7.8 executes: no PctOfValue, no PIK, no refinancing', () => {
    const forbidden = /pct_of_value|timepoint|pik|refinanc|recapitali|waterfall|partner|promote/i;
    for (const relative of CAPITAL_MODULES) {
      // The wire contracts may *represent* what the backend can send; the
      // editor's form model and the surfaces may not author it.
      if (relative === 'capitalTypes.ts') {
        continue;
      }
      const text = sourceOf(relative);
      const shown = textTokens(relative, text)
        .filter((token) => forbidden.test(token))
        // `capitalStructureForm.ts` may name `pct_of_value` -- and only that
        // one token -- because naming it is how it *refuses* to author it: a
        // valuation-based rule is shown blank rather than silently rewritten.
        // The assertion below pins that to a single, specific occurrence, so
        // this exemption cannot grow into authoring support.
        .filter(
          (token) => !(relative === 'capitalStructureForm.ts' && token === 'pct_of_value'),
        );
      expect(shown, relative).toEqual([]);
    }
    // `capitalStructureForm.ts` names `pct_of_value` exactly once, to refuse to
    // author it: a valuation-based rule is shown blank rather than silently
    // rewritten.
    // Counted as *literals*, not as raw text: the module also explains the
    // refusal in a comment, and prose about why a rule is not authored is not
    // authoring it. Exactly one string literal, in the branch that blanks it.
    const form = sourceOf('capitalStructureForm.ts');
    const literals = textTokens('capitalStructureForm.ts', form).filter(
      (token) => token === 'pct_of_value',
    );
    expect(literals).toHaveLength(1);
    expect(form).toContain("rule.kind === 'pct_of_value'");
  });

  it('names no expected value, probability, weighting, score, ranking or winner', () => {
    const forbidden = /probab|expected|weight|monte|score|rank|recommend|winner|\bbest(?![a-z])/i;
    for (const relative of CAPITAL_MODULES) {
      const text = sourceOf(relative);
      expect([...identifiers(relative, text)].filter((name) => forbidden.test(name)), relative).toEqual([]);
      expect(textTokens(relative, text).filter((token) => forbidden.test(token)), relative).toEqual([]);
    }
  });

  it('keeps returns and structural metrics apart on screen (DC-2)', () => {
    const results = sourceOf('components/CapitalStructureResults.tsx');
    // Returns are reported only when the settlement completed; the structural
    // metrics are contractual facts and stand whatever it did. They are
    // rendered by different components over different fields.
    expect(results).toContain('function PositionReturnsTable');
    expect(results).toContain('function StructuralMetricsTable');
    expect(results).toContain('unavailable_message');
    // The Common Equity figures are the structured residual, never the
    // project's levered return (NS-1).
    expect(results).not.toContain('levered_irr');
    expect(results).not.toContain('equity_multiple: ');
    expect(results).toContain('common_equity');
  });
});

describe('the Capital Structure styles rank nothing and never widen the page', () => {
  const BANNER = 'Phase 7 Gate P7.8B -- Capital Structure';

  /** P7.8B's own section of the stylesheet, bounded at the next banner rather
   * than running to the end of the file. P7.5's equivalent slice was unbounded
   * and silently measured every later gate's styles, including this one's; this
   * one cannot repeat that when a later gate appends. */
  function section(): string {
    const start = CSS.indexOf(BANNER);
    expect(start).toBeGreaterThan(-1);
    const next = CSS.indexOf('\n/* ====', start + BANNER.length);
    return next === -1 ? CSS.slice(start) : CSS.slice(start, next);
  }

  it('colours no good or bad outcome: only a refusal and an unresolved claim', () => {
    const text = section();
    expect(text).not.toMatch(/--(success|positive|negative|gain|loss)|heat|winner|best/i);
    // Exactly two: the border of a position the backend refused, and the word
    // "Unresolved" on a Funding Requirement. Neither ranks an outcome, and the
    // unresolved status is written as well as coloured.
    const danger = text.split('\n').filter((line) => line.includes('--danger'));
    expect(danger).toHaveLength(2);
  });

  it('lets every container shrink and scrolls its tables inside their own region', () => {
    const text = section();
    expect(text).toContain('min-width: 0;');
    expect(text).toContain('@media (max-width: 720px)');
    const results = sourceOf('components/CapitalStructureResults.tsx');
    expect(results.match(/className="table-scroll"/g)?.length).toBeGreaterThan(0);
  });
});

describe('the Acquisition Loans table aligns its headers over its figures', () => {
  /** The shared rule, as every Capital Structure table still reads it. */
  function sharedHeaderRule(): string {
    const start = CSS.indexOf('.capital-result-table thead th,');
    expect(start).toBeGreaterThan(-1);
    return CSS.slice(start, CSS.indexOf('}', start) + 1);
  }

  it('keeps the shared header rule left-aligned for the other tables', () => {
    // Three of the four Capital Structure tables carry genuine text columns --
    // Scope, Period, Status -- whose headers belong over left-aligned text. The
    // correction must not reach them, so the shared rule is unchanged.
    const shared = sharedHeaderRule();
    expect(shared).toContain('.capital-result-table thead th,');
    expect(shared).toContain('.capital-result-table tbody th');
    expect(shared).toContain('text-align: left;');
    expect(shared).not.toContain('text-align: right;');
  });

  it('right-aligns the numeric headers through a scoped hook, not the shared rule', () => {
    // Scoped by naming both classes, so the rule wins on specificity rather
    // than on where in the stylesheet it happens to sit.
    expect(CSS).toContain('.capital-result-table.capital-loan-table thead th {');
    const rule = CSS.slice(CSS.indexOf('.capital-result-table.capital-loan-table thead th {'));
    expect(rule.slice(0, rule.indexOf('}'))).toContain('text-align: right;');
    // The Unit column is the one label column, and keeps its header on the
    // left over the row labels the shared `tbody th` rule already left-aligns.
    expect(CSS).toContain('.capital-result-table.capital-loan-table thead th:first-child {');
    const first = CSS.slice(
      CSS.indexOf('.capital-result-table.capital-loan-table thead th:first-child {'),
    );
    expect(first.slice(0, first.indexOf('}'))).toContain('text-align: left;');
  });

  it('gives the hook to the Acquisition Loans table alone', () => {
    const results = sourceOf('components/CapitalStructureResults.tsx');
    // One table carries it; the other three keep the shared class by itself,
    // so no other Capital Structure result table can be moved by this rule.
    expect(results.match(/capital-loan-table/g)).toHaveLength(1);
    expect(results).toContain(
      'className="capital-result-table capital-loan-table"',
    );
    expect(results.match(/className="capital-result-table"/g)).toHaveLength(3);
    // The hook is presentation only: it changes no figure and no formatter.
    const loans = results.slice(results.indexOf('function LegacyLoans'));
    expect(loans).toContain('formatCurrency(loan.loan_amount)');
    expect(loans).toContain('formatPercent(loan.interest_rate)');
  });
});
