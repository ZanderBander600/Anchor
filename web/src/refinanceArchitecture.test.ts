/**
 * Refinance & Capital Events V1 Stage 3 -- the refinance UI computes nothing.
 *
 * Contract Section 12.5 and F23: every refinance figure on screen -- sizing
 * capacities, gross proceeds, payoffs, the bridge, net event cash, the Common
 * Equity decomposition, achieved LTV and DSCR -- is the backend's, and the
 * browser never re-derives one. This file parses every Stage 3 frontend module
 * with the same definition of "computes" as `capitalStructureArchitecture.test.ts`
 * and allows exactly:
 *
 * - `year * 12`: an end-of-year choice stated as its model month, the same
 *   calendar conversion the backend's Section 5.2 timing rule states;
 * - the event-id sequence (`index + 1`, `index += 1`);
 * - `max_ltv * 100`: a stored fraction shown as the percentage typed, the
 *   display-scale conversion `convert.ts` already makes.
 *
 * It also pins that the backend is reached only through `api.ts`, and that no
 * Stage 3 module keeps its own list of which Decision Matrix metrics are the
 * acquisition-financing reference: the backend's presence route states them.
 */

import { describe, expect, it } from 'vitest';
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

/** Every Stage 3 frontend module. */
const REFINANCE_MODULES = [
  'capitalEventForm.ts',
  'refinanceCatalog.ts',
  'useCapitalEventAudit.ts',
  'useCapitalEventChoices.ts',
  'useRefinancePresence.ts',
  'components/AcquisitionReference.tsx',
  'components/CapitalEventAuditAction.tsx',
  'components/CapitalEventEditor.tsx',
  'components/CapitalEventMatrixNote.tsx',
  'components/CapitalEventResults.tsx',
];

/** The only computation sites any Stage 3 module holds, by module. */
const ALLOWED: Record<string, string[]> = {
  'capitalEventForm.ts': ['year * 12', 'index + 1', 'index += 1', 'index += 1', 'event.sizing.max_ltv.max_ltv * 100'],
};

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

const COMPUTING_CALLS =
  /(^|\.)(reduce|reduceRight|sort|toSorted|min|max)$|^(parseFloat|parseInt|Number)$/;

/** Every expression that computes, as `capitalStructureArchitecture.test.ts`
 * and `decisionArchitecture.test.ts` define it. */
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

/** A literal used only to discriminate a union -- compared, switched on,
 * used as a key or imported -- which is never shown to the analyst. */
function isDiscriminant(node: ts.Node): boolean {
  const parent = node.parent;
  if (parent === undefined) {
    return false;
  }
  if (ts.isBinaryExpression(parent)) {
    const op = parent.operatorToken.kind;
    return (
      op === ts.SyntaxKind.EqualsEqualsEqualsToken ||
      op === ts.SyntaxKind.ExclamationEqualsEqualsToken ||
      op === ts.SyntaxKind.EqualsEqualsToken ||
      op === ts.SyntaxKind.ExclamationEqualsToken
    );
  }
  return (
    ts.isCaseClause(parent) ||
    ts.isImportDeclaration(parent) ||
    ts.isExportDeclaration(parent) ||
    ts.isLiteralTypeNode(parent) ||
    ts.isElementAccessExpression(parent) ||
    (ts.isPropertyAssignment(parent) && parent.name === node)
  );
}

/** A module's string literals, template text and JSX text that could reach
 * the screen. */
function textTokens(fileName: string, text: string): string[] {
  const tokens: string[] = [];
  walk(parse(fileName, text), (node) => {
    if (isDiscriminant(node)) {
      return;
    }
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

describe('the refinance UI computes nothing', () => {
  it.each(REFINANCE_MODULES)('%s holds only its enumerated computation sites', (module) => {
    expect(computationSites(module, sourceOf(module))).toEqual(ALLOWED[module] ?? []);
  });

  it('prints the engine’s signed figures as magnitudes by text, never by negation', () => {
    const catalog = sourceOf('refinanceCatalog.ts');
    expect(catalog).toContain("formatCurrency(value).replace(/^-/, '')");
  });
});

describe('the refinance UI reaches the backend only through api.ts', () => {
  it.each(REFINANCE_MODULES)('%s makes no request of its own', (module) => {
    const text = sourceOf(module);
    expect(text).not.toMatch(/\bfetch\s*\(/);
    expect(text).not.toMatch(/XMLHttpRequest|axios/);
  });
});

describe('the acquisition-financing reference has one list, the backend’s', () => {
  const METRIC_TOKENS = ['levered_irr', 'equity_multiple', 'total_profit', 'total_equity_invested', 'min_dscr'];

  it.each([...REFINANCE_MODULES, 'components/DecisionMatrixPanel.tsx'])('%s names no reference metric itself', (module) => {
    const tokens = textTokens(module, sourceOf(module));
    for (const metric of METRIC_TOKENS) {
      expect(tokens).not.toContain(metric);
    }
  });

  it('the matrix reads the reference metrics from the presence route', () => {
    const presence = sourceOf('useRefinancePresence.ts');
    expect(presence).toContain('acquisition_financing_metrics');
    expect(sourceOf('api.ts')).toContain('/capital-event-presence');
  });
});

describe('the refinance UI states no internal identity', () => {
  it.each(REFINANCE_MODULES.filter((module) => module.endsWith('.tsx')))('%s prints no wire token', (module) => {
    const printed = textTokens(module, sourceOf(module)).join(' ');
    for (const token of ['legacy_acquisition_loan', 'authored_position', 'refinance_proceeds', 'capital_event_id', 'timepoint_id']) {
      expect(printed).not.toContain(token);
    }
  });
});
