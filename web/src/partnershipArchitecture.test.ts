/**
 * Phase 7 Gate P7.9 Stage 3 -- the Partnership UI computes nothing.
 *
 * This gate shows contributions, distributions, partner IRRs, MOICs, profit,
 * benchmark distributions, a signed distribution difference and its capital and
 * profit halves, an advantage, a disadvantage, Promote Earned, benchmark capital
 * subordination, per-tier attribution, hurdle account balances and catch-up
 * capacity -- every one of which the accepted Stage 1 engine already produces,
 * and any one of which could be "obviously" re-derived in a component from the
 * fields beside it. `distribution_advantage` is `max(D - M, 0)`; it would take
 * one subtraction and one `Math.max` to recompute, and the result would be a
 * second arithmetic authority in the browser, invisible until two surfaces
 * disagreed. P-3 and P-5 forbid exactly that.
 *
 * So this file parses every P7.9 Stage 3 frontend module and allows exactly the
 * display-scale conversions -- a share typed as `90` and sent as `0.9`, the same
 * conversion `convert.ts`, `strategyForm.ts` and `capitalStructureForm.ts`
 * already make -- and the id sequence. Nothing else computes.
 *
 * It also pins the decisions the gate turns on: no economic default is invented
 * and every required selection reads "Choose…"; the promote participants are
 * explicitly confirmed even when empty; no role is ever inferred; the three
 * benchmark comparisons keep their own labels and an advantage is never
 * captioned as promote; a non-participant's Promote Earned is N/A with the
 * engine's reason rather than zero; a partner's identity is its id while its
 * name and role are per-cell presentation; the unsupported catch-up
 * combinations are never offered; and the backend is reached only through
 * `api.ts` and only from the hooks.
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

/** Every P7.9 Stage 3 production module. */
const PARTNERSHIP_MODULES = [
  'partnershipTypes.ts',
  'partnershipForm.ts',
  'decisionStateTokens.ts',
  'usePartnership.ts',
  'usePartnerDecisionMatrix.ts',
  'components/PartnershipEditor.tsx',
  'components/PartnershipResults.tsx',
  'components/PartnershipWorkspace.tsx',
  'components/PartnerDecisionMatrixPanel.tsx',
  // Workstation polish pass: the saved Partnership's read-only summary.
  'components/PartnershipSummary.tsx',
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

/** Every expression that computes, exactly as `decisionArchitecture.test.ts` and
 * `capitalStructureArchitecture.test.ts` define it, so the three gates' guards
 * cannot drift into three different ideas of what counts as arithmetic. */
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

/** One module's source with every comment removed, for claims about what the
 * code does rather than what its prose says about itself. */
function withoutComments(text: string): string {
  // `.` already stops at a line break, so a line comment needs no explicit
  // newline class. The `[^:]` guard keeps a `://` inside a URL intact.
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*/g, '$1');
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

describe('the Partnership UI computes nothing', () => {
  it('computes nothing but the display-scale conversions and the id sequence', () => {
    const sites = Object.fromEntries(
      PARTNERSHIP_MODULES.map((relative) => [
        relative,
        computationSites(relative, sourceOf(relative)),
      ]),
    );
    expect(sites).toEqual({
      'partnershipTypes.ts': [],
      // Pure serialization of already-saved contracts.
      'decisionStateTokens.ts': [],
      // The id sequence, and the four display-scale conversions: a share, a
      // rate and a target profit share are typed as percentages and sent as
      // decimals. Nothing here is a financial figure.
      'partnershipForm.ts': [
        'index += 1',
        'row.share * 100',
        'condition.rate * 100',
        'catchUp.target_profit_share * 100',
        'partner.commitment_share * 100',
      ],
      'usePartnership.ts': ['key + 1'],
      'usePartnerDecisionMatrix.ts': ['key + 1'],
      'components/PartnershipEditor.tsx': [],
      'components/PartnershipResults.tsx': [],
      'components/PartnershipWorkspace.tsx': [],
      'components/PartnerDecisionMatrixPanel.tsx': [],
      'components/PartnershipSummary.tsx': [],
    });
  });

  it('would see a smuggled advantage, promote, subordination or partner return (M1)', () => {
    // Each of these is a real Stage 1 field that the browser could "obviously"
    // re-derive from the fields beside it. The guard sees every one.
    expect(
      computationSites('m.ts', 'const difference = partner.total_distributions - benchmark;'),
    ).toEqual(['partner.total_distributions - benchmark']);
    expect(computationSites('m.ts', 'const advantage = Math.max(difference, 0);')).toEqual([
      'Math.max(difference, 0)',
      'Math.max',
    ]);
    expect(
      computationSites('m.ts', 'const promote = profitDistributions - benchmarkProfit;'),
    ).toEqual(['profitDistributions - benchmarkProfit']);
    expect(computationSites('m.ts', 'const subordination = -capitalReturnDifference;')).toEqual([
      '-capitalReturnDifference',
    ]);
    expect(computationSites('m.ts', 'const moic = distributions / contributions;')).toEqual([
      'distributions / contributions',
    ]);
    expect(
      computationSites('m.ts', 'const total = partners.reduce((a, b) => a, 0);'),
    ).toHaveLength(1);
    expect(
      computationSites('m.ts', 'const attributed = tiers.reduce((a, t) => a, 0);'),
    ).toHaveLength(1);
    expect(computationSites('m.ts', "const back = Number('1.48');")).toHaveLength(1);
  });

  it('reaches the backend only through api.ts, and only from the hooks', () => {
    for (const relative of PARTNERSHIP_MODULES) {
      const text = sourceOf(relative);
      expect(text, relative).not.toMatch(/\bfetch\(/);
      const importsApi = /from '\.{1,2}\/api'/.test(text);
      expect(importsApi, relative).toBe(
        relative === 'usePartnership.ts' || relative === 'usePartnerDecisionMatrix.ts',
      );
    }
  });

  it('every figure it shows is a backend field, never one it derived', () => {
    const results = sourceOf('components/PartnershipResults.tsx');
    // The three benchmark comparisons are read straight off `PartnerResult`.
    for (const field of [
      'distribution_difference',
      'distribution_advantage',
      'distribution_disadvantage',
      'capital_return_difference',
      'profit_distribution_difference',
      'promote_earned',
      'benchmark_capital_subordination',
      'total_benchmark_distributions',
      'benchmark_capital_returned',
    ]) {
      expect(results, field).toContain(`partner.${field}`);
    }
    // Common Equity Total Profit is the engine's derived figure, echoed.
    expect(results).toContain('result.common_equity_total_profit');
    // The catch-up rate is derived by the engine from the split and reported;
    // the surface never recomputes it from the shares.
    expect(results).toContain('tier.catch_up_rate');
  });
});

describe('the Partnership UI invents no economic default', () => {
  it('starts every required selection unstated, and says so before the round trip', () => {
    const form = sourceOf('partnershipForm.ts');
    // A brand-new Partnership states nothing at all.
    expect(form).toContain("contributionRule: ''");
    expect(form).toContain("role: ''");
    expect(form).toContain("splitRule: ''");
    expect(form).toContain("subjectKind: ''");
    expect(form).toContain("combinator: ''");
    expect(form).toContain("recipientKind: ''");
    expect(form).toContain("kind: ''");
    expect(form).toContain("accrualConvention: ''");
    expect(form).toContain("simpleDistributionOrder: ''");
    // The benchmark is typed, never copied implicitly from the commitment.
    expect(form).toContain("benchmarkShare: ''");
    expect(form).toContain('export function unstatedPartnershipChoices');
    // The editor offers each unstated choice explicitly rather than defaulting
    // the first option.
    const editor = sourceOf('components/PartnershipEditor.tsx');
    expect(textTokens('components/PartnershipEditor.tsx', editor)).toContain('Choose…');
  });

  it('requires an explicit promote-participant confirmation, including for none (Q10)', () => {
    const form = sourceOf('partnershipForm.ts');
    expect(form).toContain('promoteParticipantsConfirmed: false');
    // The request is refused while the set is unconfirmed, even though an empty
    // set is a perfectly valid answer.
    const build = form.slice(form.indexOf('export function partnershipFromForm'));
    expect(build).toContain('if (!form.promoteParticipantsConfirmed)');
    const editor = sourceOf('components/PartnershipEditor.tsx');
    expect(editor).toContain('promoteParticipantsConfirmed: false');
  });

  it('never derives the benchmark from the commitment shares (Q2)', () => {
    const form = sourceOf('partnershipForm.ts');
    // The benchmark table is built from what was typed in its own column.
    const build = form.slice(form.indexOf('export function partnershipFromForm'));
    expect(build).toContain('partner.benchmarkShare');
    expect(build).not.toContain('partner.commitmentShare');
    // The copy action writes literal values once; it is not a link.
    const copy = form.slice(form.indexOf('export function withCommitmentsCopiedToBenchmark'));
    expect(copy).toContain('benchmarkShare: partner.commitmentShare');
  });

  it('infers nothing from a partner role', () => {
    // The role is reporting only. No module decides a promote participant, a
    // hurdle subject or a catch-up recipient from it.
    for (const relative of PARTNERSHIP_MODULES) {
      const text = sourceOf(relative);
      expect(text, relative).not.toMatch(/role\s*===\s*'gp'/);
      expect(text, relative).not.toMatch(/role\s*===\s*'lp'/);
      expect(text, relative).not.toMatch(/role\s*===\s*'co_investor'/);
    }
  });

  it('never offers the two unsupported catch-up combinations (Section 18)', () => {
    const form = sourceOf('partnershipForm.ts');
    // A catch-up recipient is never an economic account.
    const recipients = form.slice(form.indexOf('CATCH_UP_RECIPIENT_KIND_LABELS'));
    expect(recipients.slice(0, recipients.indexOf('};'))).not.toContain('economic_account');
    // A catch-up tier never takes a pro-rata split.
    expect(form).toContain('export function splitRulesFor');
    const splits = form.slice(form.indexOf('export function splitRulesFor'));
    expect(splits).toContain("kind === 'catch_up' ? ['explicit']");
    const editor = sourceOf('components/PartnershipEditor.tsx');
    expect(editor).toContain('const RECIPIENT_KINDS: CatchUpRecipientKind[]');
    expect(editor).toContain("splitRulesFor(tier.kind)");
  });
});

describe('the Partnership UI keeps the three benchmark comparisons apart', () => {
  it('gives each its own label, and never captions an advantage as promote (Q3, R-B)', () => {
    const results = sourceOf('components/PartnershipResults.tsx');
    // Three separate sections over three separate fields.
    expect(results).toContain('function BenchmarkComparisonTable');
    expect(results).toContain('function PromoteEarnedTable');
    expect(results).toContain('function SubordinationTable');
    const tokens = textTokens('components/PartnershipResults.tsx', results);
    expect(tokens).toContain('Distribution Advantage');
    expect(tokens).toContain('Distribution Disadvantage');
    expect(tokens).toContain('Promote Earned');
    expect(tokens).toContain('Benchmark Capital Subordination');
    // No heading or caption calls an advantage a promote, in either order.
    for (const token of tokens) {
      expect(token, token).not.toMatch(/advantage[^.]*promote|promote[^.]*advantage/i);
    }
  });

  it('discloses a benchmark that differs from the commitment (R-A)', () => {
    const results = sourceOf('components/PartnershipResults.tsx');
    // The engine reports the equality as information only; the product must say
    // so plainly where it is false.
    expect(results).toContain('partner.benchmark_equals_commitment');
    expect(results).toContain('BENCHMARK_MISMATCH_NOTICE');
    expect(results).toContain('!partner.benchmark_equals_commitment');
  });

  it("reports a non-participant's Promote Earned as N/A with a reason, never zero (R-E)", () => {
    const results = sourceOf('components/PartnershipResults.tsx');
    // `promote_earned === null` is shown through the N/A path, with the
    // engine's own `promote_unavailable_reason` beneath it.
    expect(results).toContain('partner.promote_earned === null');
    expect(results).toContain('partner.promote_unavailable_reason');
    expect(results).toContain('not_a_promote_participant');
    // No module substitutes a zero for an absent promote.
    for (const relative of PARTNERSHIP_MODULES) {
      const text = sourceOf(relative);
      expect(text, relative).not.toMatch(/promote_earned\s*\?\?\s*0/);
      expect(text, relative).not.toMatch(/promote_earned\s*\|\|\s*0/);
    }
  });

  it('never totals Promote Earned against benchmark capital subordination', () => {
    // There is deliberately no identity between the two (Section 11.3), so no
    // surface may place them in one sum or one reconciliation.
    const results = sourceOf('components/PartnershipResults.tsx');
    expect(results).not.toMatch(/promote_earned[^;]*benchmark_capital_subordination/);
    expect(results).not.toMatch(/benchmark_capital_subordination[^;]*promote_earned/);
  });
});

describe('the Partner matrix compares without judging', () => {
  it('names no expected value, probability, weighting, score, ranking or winner', () => {
    const forbidden = /probab|expected|weight|monte|score|rank|recommend|winner|\bbest(?![a-z])/i;
    for (const relative of PARTNERSHIP_MODULES) {
      const text = sourceOf(relative);
      expect(
        [...identifiers(relative, text)].filter((name) => forbidden.test(name)),
        relative,
      ).toEqual([]);
      expect(
        textTokens(relative, text).filter((token) => forbidden.test(token)),
        relative,
      ).toEqual([]);
    }
  });

  it('reports each cell’s own partner name and role, never the perspective’s (P-8)', () => {
    const panel = sourceOf('components/PartnerDecisionMatrixPanel.tsx');
    // The cell's own fields, from the Partnership that cell resolved.
    expect(panel).toContain('cell.partner_name');
    expect(panel).toContain('cell.partner_role');
    // The matrix-level name is used only for the caption and the selector, and
    // never to label a cell.
    expect(panel).toContain('matrix.partner_name');
    const identity = panel.slice(panel.indexOf('function CellIdentity'));
    expect(identity.slice(0, identity.indexOf('\n}'))).not.toContain('matrix.partner_name');
  });

  it('renders every applicability state distinctly, and none of them as zero', () => {
    const panel = sourceOf('components/PartnerDecisionMatrixPanel.tsx');
    expect(panel).toContain("cell.status === 'invalid'");
    expect(panel).toContain("cell.applicability !== 'present'");
    expect(panel).toContain("cell.applicability === 'not_present'");
    expect(panel).toContain('PARTNER_ABSENT_MESSAGE');
    expect(panel).toContain('PARTNER_NOT_ANALYSED_MESSAGE');
    // An unreported figure is the backend's reason, not a zero.
    expect(panel).toContain('figure.value === null');
    expect(panel).toContain('cell.unavailable_message');
  });

  it('shows a stale report as out of date rather than as current (DC-7)', () => {
    const panel = sourceOf('components/PartnerDecisionMatrixPanel.tsx');
    expect(panel).toContain('StaleAnalysisNotice');
    expect(panel).toContain('PARTNER_STALE_MESSAGE');
    const workspace = sourceOf('components/PartnershipWorkspace.tsx');
    expect(workspace).toContain('StaleAnalysisNotice');
    expect(workspace).toContain('!state.isAnalysisCurrent');
  });
});

describe('the P-4 boundary between the downstream matrices holds', () => {
  const TOKENS = 'decisionStateTokens.ts';
  const WORKSPACE = 'components/RiskDecisionWorkspace.tsx';

  /** The body of one exported token builder. */
  function functionBody(name: string): string {
    const text = sourceOf(TOKENS);
    const start = text.indexOf(`export function ${name}`);
    expect(start, name).toBeGreaterThan(-1);
    // Bounded at the next exported declaration, so one builder's body is never
    // measured against the next one's.
    const rest = text.slice(start + 1);
    const next = rest.indexOf('export function ');
    return text.slice(start, next === -1 ? text.length : start + 1 + next);
  }

  it('reads a Strategy’s root overlays only through the domain filter', () => {
    // `root_overlays` is a set of *different* economic domains at different
    // depths of the dependency chain. Handing the whole set to the Position
    // token is what made a Partnership-only edit invalidate a Position report
    // that could not have moved. Only the filter may read the raw field, so
    // every occurrence outside it -- in code, not in prose -- is a regression.
    // Across both the builders and the workspace that calls them.
    const outside = withoutComments(sourceOf(TOKENS))
      .replace(withoutComments(functionBody('rootOverlaysOfDomain')), '')
      .concat(withoutComments(sourceOf(WORKSPACE)));
    expect(outside).not.toContain('root_overlays');
    expect(withoutComments(functionBody('rootOverlaysOfDomain'))).toContain('root_overlays');
  });

  it('keeps the Partnership domain out of the Position token entirely', () => {
    // Measured on code with the comments stripped: prose explaining *why* the
    // Partnership is excluded is not including it.
    const position = withoutComments(functionBody('positionStateTokenOf'));
    expect(position).toContain("rootOverlaysOfDomain(record.strategy, 'capital_structure')");
    expect(position).not.toContain('partnership');
    expect(position).not.toContain('Partnership');
    expect(position).not.toContain('root_overlays');
  });

  it('builds the Partner token from the whole Position state plus the Partnership', () => {
    const partner = functionBody('partnerStateTokenOf');
    // Everything that moves a Position cell moves a Partner cell, because a
    // Partner cell is a Position cell's Common Equity allocated.
    expect(partner).toContain('input.positionStateToken');
    expect(partner).toContain("rootOverlaysOfDomain(record.strategy, 'partnership')");
    expect(partner).toContain('input.basePartnership');
  });

  it('leaves the Project matrix reading no root overlay at all', () => {
    // The Project matrix is upstream of both downstream domains, so neither a
    // Capital Structure nor a Partnership may move it (P-4). Its identity is
    // built in its own P7.5 hook, from the Unit overlays only.
    const project = withoutComments(sourceOf('useDecisionMatrix.ts'));
    expect(project).toContain('record.strategy.overlays');
    expect(project).not.toContain('root_overlays');
    expect(project).not.toContain('partnership');
    expect(project).not.toContain('capital_structure');
  });

  it('gives each matrix its own token, and the Project matrix neither', () => {
    const text = sourceOf(WORKSPACE);
    expect(text).toContain('stateToken: positionStateToken');
    expect(text).toContain('stateToken: partnerStateToken');
    // The Project matrix is upstream of both and takes no structured or
    // Partnership state at all (P-4).
    const projectMatrix = text.slice(text.indexOf('const matrix = useDecisionMatrix('));
    const projectArgs = projectMatrix.slice(0, projectMatrix.indexOf('});'));
    expect(projectArgs).not.toContain('positionStateToken');
    expect(projectArgs).not.toContain('partnerStateToken');
    expect(projectArgs).not.toContain('partnership');
  });
});

describe('the Partnership UI shows no internal identifier and no browser dialog', () => {
  it('labels a condition by its kind, never by its opaque id', () => {
    const form = sourceOf('partnershipForm.ts');
    expect(form).toContain('export function conditionLabel');
    // The id keys React and names the element ids; it is never rendered.
    const editor = sourceOf('components/PartnershipEditor.tsx');
    const legend = editor.slice(editor.indexOf('partnership-condition-legend'));
    expect(legend.slice(0, 200)).toContain('conditionLabel(condition.kind)');
    expect(legend.slice(0, 200)).not.toContain('condition.conditionId');
    // Nor does any analyst-facing message carry one.
    expect(form).not.toContain('${condition.conditionId}');
    // And no ordinal is invented to number them instead.
    expect(computationSites('partnershipForm.ts', form)).not.toContain('index + 1');
  });

  it('confirms a removal in the product’s own words, never with a native dialog', () => {
    const workspace = sourceOf('components/PartnershipWorkspace.tsx');
    // A native confirm cannot say what is lost, cannot be styled, and cannot be
    // read by the same rules as the rest of the product.
    for (const relative of PARTNERSHIP_MODULES) {
      expect(sourceOf(relative), relative).not.toMatch(/(^|[^.\w])(confirm|alert|prompt)\(/m);
    }
    expect(workspace).toContain('REMOVE_CONFIRM_QUESTION');
    expect(workspace).toContain('REMOVE_CONFIRM_MESSAGE');
    expect(workspace).toContain('isConfirmingRemove');
    // The destructive action is only reachable from inside the confirmation.
    const confirming = workspace.slice(workspace.indexOf('{isConfirmingRemove ? ('));
    expect(confirming.slice(0, confirming.indexOf(') : ('))).toContain('void state.remove()');
  });

  it('states the benchmark disclosure once, and marks each figure compactly (R-A)', () => {
    const results = sourceOf('components/PartnershipResults.tsx');
    // The full explanation is rendered once, gated on the backend's own flag
    // across the partner set -- never repeated into every cell.
    expect(results).toContain('partners.some((partner) => !partner.benchmark_equals_commitment)');
    expect(results).toContain('BENCHMARK_MISMATCH_NOTICE');
    expect(results).toContain('BENCHMARK_MISMATCH_MARKER');
    const cell = results.slice(results.indexOf('data-field="benchmark_share"'));
    const cellEnd = cell.slice(0, cell.indexOf('</td>'));
    expect(cellEnd).toContain('BENCHMARK_MISMATCH_MARKER');
    expect(cellEnd).not.toContain('BENCHMARK_MISMATCH_NOTICE');
    // Still the backend boolean, and still no comparison of its own.
    expect(cellEnd).toContain('!partner.benchmark_equals_commitment');
  });
});

describe('the Partnership hooks keep the right things stale', () => {
  it('invalidates the Partnership analysis on a Partnership edit, and nothing upstream', () => {
    const hook = sourceOf('usePartnership.ts');
    // The analysis token carries the saved Partnership, so editing it makes the
    // analysis stale.
    expect(hook).toContain('JSON.stringify([scope, savedAt, saved])');
    // A save drops the token rather than relabelling the old analysis.
    expect(hook).toContain('setAnalysisToken(null)');
    // Nothing here touches a Project or structured result.
    expect(hook).not.toContain('analyzeStructuredVariant');
    expect(hook).not.toContain('analyzeDecisionMatrix');
    expect(hook).not.toContain('analyzePositionDecisionMatrix');
  });

  it('sends the explicit “no Partnership” as null, never as an empty contract', () => {
    const hook = sourceOf('usePartnership.ts');
    expect(hook).toContain('const remove = useCallback');
    expect(hook).toContain('await put(null)');
    // A Partnership always has a partner, so there is no empty one to mean it
    // with: no module builds a Partnership with an empty partner list to clear.
    expect(hook).not.toMatch(/partners:\s*\[\]/);
  });

  it('asks for nothing before its surface is on screen', () => {
    expect(sourceOf('usePartnership.ts')).toContain('if (!isActive || scope === null)');
    expect(sourceOf('usePartnerDecisionMatrix.ts')).toContain(
      'const wantsList = isActive && investmentId !== null',
    );
  });
});

describe('the Partnership styles rank nothing and never widen the page', () => {
  const BANNER = 'Phase 7 Gate P7.9 Stage 3 -- Partnership';

  /** P7.9's own section of the stylesheet, bounded at the next banner rather
   * than running to the end of the file -- the bound P7.8B added after P7.5's
   * unbounded slice silently measured every later gate's styles. */
  function section(): string {
    const start = CSS.indexOf(BANNER);
    expect(start).toBeGreaterThan(-1);
    const next = CSS.indexOf('\n/* ====', start + BANNER.length);
    return next === -1 ? CSS.slice(start) : CSS.slice(start, next);
  }

  it('colours no good or bad outcome: only a refusal', () => {
    const text = section();
    expect(text).not.toMatch(/--(success|positive|negative|gain|loss)|heat|winner|best/i);
    // Exactly one: the border of a partner or tier the backend refused. A
    // partner ahead of the benchmark and one behind it are typeset identically.
    const danger = text.split('\n').filter((line) => line.includes('--danger'));
    expect(danger).toHaveLength(1);
  });

  it('lets every container shrink and scrolls its tables inside their own region', () => {
    const text = section();
    expect(text).toContain('min-width: 0;');
    expect(text).toContain('@media (max-width: 720px)');
    const results = sourceOf('components/PartnershipResults.tsx');
    expect(results.match(/className="table-scroll"/g)?.length).toBeGreaterThan(0);
    const panel = sourceOf('components/PartnerDecisionMatrixPanel.tsx');
    expect(panel).toContain('className="decision-matrix-scroll"');
  });
});
