/**
 * Phase 7 Gate P7.6 -- the visible Investment UI computes nothing, reads every
 * figure from the backend, and reaches the backend only by the Investment's own
 * routes.
 *
 * The Investment workspace is where a "harmless" frontend total would be most
 * tempting: summing the Units' purchase prices into a Transaction Price, taking
 * the allocation variance, averaging occupancy, subtracting a removed Unit's
 * price. P-5 and Q22 reserve every one of those for the backend. So this file
 * parses every P7.6 module and allows exactly one computing expression -- the
 * sort of Unit *ids* (strings) inside the staleness token -- and pins:
 *
 * - every consolidated figure on screen is one named `ConsolidatedResults`
 *   field, read and formatted;
 * - Unit Kind is shown and never decides anything;
 * - a visible Investment's Strategies, Scenarios and Decision Matrix use the
 *   Investment-scoped routes, never the Deal-scoped or one-unit ones;
 * - removing a Unit is one request that states the resulting price;
 * - every table scrolls inside its own region and never widens the page.
 *
 * Each rule has a seeded "would see" check so it cannot pass vacuously.
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

/** Every P7.6 Investment module. */
const INVESTMENT_MODULES = [
  'investmentTypes.ts',
  'investmentCatalog.ts',
  'investmentForm.ts',
  'useInvestments.ts',
  'useInvestmentWorkspace.ts',
  'useInvestmentAnalysis.ts',
  'useNewInvestment.ts',
  'components/InvestmentIssueList.tsx',
  'components/InvestmentLibraryPanel.tsx',
  'components/NewInvestmentPanel.tsx',
  'components/TransactionCostEditor.tsx',
  'components/InvestmentOverview.tsx',
  'components/InvestmentUnitsPanel.tsx',
  'components/InvestmentWorkspace.tsx',
  'components/InvestmentReturnBar.tsx',
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

/** Aggregating, ordering or re-parsing calls: a total, an extreme, an order,
 * or a number rebuilt from text. */
const COMPUTING_CALLS =
  /(^|\.)(reduce|reduceRight|sort|toSorted|min|max|abs|round|floor|ceil)$|^(parseFloat|parseInt|Number)$/;

/** Every expression that computes: arithmetic, an increment, the negation of a
 * non-literal, any use of `Math`, and the aggregating, ordering or re-parsing
 * calls. String concatenation is arithmetic here too: nothing is joined with
 * `+`. */
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

/** Every name a module declares: variables, functions, parameters. */
function declaredNames(fileName: string, text: string): string[] {
  const names: string[] = [];
  walk(parse(fileName, text), (node) => {
    if (
      (ts.isVariableDeclaration(node) || ts.isFunctionDeclaration(node) || ts.isParameter(node)) &&
      node.name !== undefined &&
      ts.isIdentifier(node.name)
    ) {
      names.push(node.name.text);
    }
  });
  return names;
}

/** The properties a module reads off an expression named `receiver`. */
function propertiesRead(fileName: string, text: string, receiver: string): Set<string> {
  const found = new Set<string>();
  walk(parse(fileName, text), (node) => {
    if (ts.isPropertyAccessExpression(node) && node.expression.getText() === receiver) {
      found.add(node.name.text);
    }
  });
  return found;
}

/** The calls made inside one function declaration of a module. */
function callsInFunction(fileName: string, text: string, functionName: string): string[] {
  const calls: string[] = [];
  walk(parse(fileName, text), (node) => {
    if (ts.isFunctionDeclaration(node) && node.name?.text === functionName) {
      walk(node, (inner) => {
        if (ts.isCallExpression(inner)) {
          calls.push(inner.expression.getText());
        }
      });
    }
  });
  return calls;
}

// =============================================================================
// 1. No frontend financial arithmetic
// =============================================================================

describe('the Investment UI computes no financial figure', () => {
  it('computes nothing but the sort of Unit ids inside the staleness token', () => {
    const sites = Object.fromEntries(
      INVESTMENT_MODULES.map((relative) => [relative, computationSites(relative, sourceOf(relative))]),
    );
    const { 'investmentForm.ts': formSites, ...rest } = sites;
    for (const [relative, found] of Object.entries(rest)) {
      expect(found, relative).toEqual([]);
    }
    // The one approved site orders Unit id strings, so presentation order
    // never reaches the token. No figure is compared, ordered or combined.
    expect(formSites).toHaveLength(1);
    expect(formSites[0]).toMatch(/^investment\.units\.map\(\(unit\) => `\$\{unit\.unit_id\}@/);
    expect(formSites[0].endsWith('.sort()')).toBe(true);
  });

  it('would see a summed price, a variance, an average or a subtracted Unit (M1, M2)', () => {
    expect(computationSites('m.ts', 'const price = units.reduce((a, u) => a + u.price, 0);')).toEqual([
      'units.reduce((a, u) => a + u.price, 0)',
      'a + u.price',
    ]);
    expect(computationSites('m.ts', 'const variance = transaction_price - allocated;')).toEqual([
      'transaction_price - allocated',
    ]);
    expect(computationSites('m.ts', 'const next = current.transaction_price - deal.purchase_price;')).toHaveLength(1);
    expect(computationSites('m.ts', 'const avg = Math.round(occupied / area);')).toHaveLength(3);
    expect(computationSites('m.ts', "const price = Number('45000000');")).toHaveLength(1);
    expect(computationSites('m.ts', 'const flipped = -results.total_profit;')).toEqual(['-results.total_profit']);
  });

  it('declares no total, sum, allocation, variance or average of its own', () => {
    // Copy constants (SCREAMING_CASE) name words shown to the analyst, not
    // figures; a figure computed into one would still be arithmetic above.
    const forbidden = /^(sum|total|allocated|allocation|variance|average|avg|combined|aggregate)/i;
    const isCopyConstant = (name: string) => /^[A-Z0-9_]+$/.test(name);
    for (const relative of INVESTMENT_MODULES) {
      const named = declaredNames(relative, sourceOf(relative)).filter(
        (name) => forbidden.test(name) && !isCopyConstant(name),
      );
      expect(named, relative).toEqual([]);
    }
    expect(declaredNames('m.ts', 'const totalPrice = 1; function sumUnits(prices) {}').filter((n) => forbidden.test(n)))
      .toEqual(['totalPrice', 'sumUnits']);
  });

  it('shows exactly the named ConsolidatedResults fields, each read and formatted', () => {
    const read = propertiesRead('components/InvestmentOverview.tsx', sourceOf('components/InvestmentOverview.tsx'), 'results');
    expect([...read].sort()).toEqual(
      [
        'acquisition_costs',
        'aggregate_dscr_by_year',
        'allocated_purchase_price',
        'allocation_variance',
        'annual_debt_service',
        'capex_by_year',
        'closing_project_capital',
        'equity_multiple',
        'exit_value',
        'financing_fees',
        'going_in_cap_rate',
        'headline_aggregate_dscr',
        'hold_period',
        'implied_exit_cap_rate',
        'initial_equity',
        'investment_closing_project_capital',
        'investment_owner_expenses_by_year',
        'investment_project_capital_by_year',
        'investment_transaction_costs',
        'leasing_commissions_by_year',
        'levered_irr',
        'levered_irr_status',
        'levered_owner_cash_flow_by_year',
        'loan_amount',
        'min_aggregate_dscr',
        'net_additional_equity_requirement_by_year',
        'noi_by_year',
        'owner_expenses_by_year',
        'physical_occupancy_at_year_end',
        'physical_occupancy_message',
        'project_capital_by_year',
        'property_cash_flow_by_year',
        'tenant_improvements_by_year',
        'total_closing_sources',
        'total_closing_uses',
        'total_equity_invested',
        'total_profit',
        'transaction_price',
        'unlevered_irr',
        'unlevered_irr_status',
        'unlevered_owner_cash_flow_by_year',
        'year_1_debt_yield',
      ].sort(),
    );
  });

  it('never proposes a Transaction Price: the builder and Unit forms start blank', () => {
    const builder = sourceOf('useNewInvestment.ts');
    expect(builder).toContain("const [price, setPrice] = useState('');");
    const workspace = sourceOf('useInvestmentWorkspace.ts');
    expect(workspace).toContain("setAddUnit({ dealId: '', label: '', kind: 'property', price: '' });");
    expect(workspace).toContain("setRemoval({ unitId, price: '' });");
    // A Deal's stored price is read for reference, never written into a draft.
    expect(workspace).not.toMatch(/price:\s*(formatDisplayNumber|String)\(\s*storedPurchasePrice/);
  });
});

// =============================================================================
// 2. Unit Kind is reporting metadata
// =============================================================================

const UNIT_KINDS = new Set(['property', 'component', 'phase']);

/** Comparisons of any expression with a Unit Kind token, and switches that
 * name one: the only ways a kind could decide behaviour. */
function kindDecisions(fileName: string, text: string): string[] {
  const found: string[] = [];
  walk(parse(fileName, text), (node) => {
    if (
      ts.isBinaryExpression(node) &&
      (node.operatorToken.kind === ts.SyntaxKind.EqualsEqualsEqualsToken ||
        node.operatorToken.kind === ts.SyntaxKind.ExclamationEqualsEqualsToken ||
        node.operatorToken.kind === ts.SyntaxKind.EqualsEqualsToken ||
        node.operatorToken.kind === ts.SyntaxKind.ExclamationEqualsToken) &&
      [node.left, node.right].some((side) => ts.isStringLiteral(side) && UNIT_KINDS.has(side.text))
    ) {
      found.push(node.getText());
    }
    if (
      ts.isCaseClause(node) &&
      ts.isStringLiteral(node.expression) &&
      UNIT_KINDS.has(node.expression.text)
    ) {
      found.push(node.getText());
    }
  });
  return found;
}

describe('Unit Kind decides nothing (M7)', () => {
  it('no production module compares or switches on a Unit Kind', () => {
    for (const [path, text] of PRODUCTION) {
      expect(kindDecisions(path, text), path).toEqual([]);
    }
  });

  it('would see a kind that changes behaviour', () => {
    expect(kindDecisions('m.ts', "if (unit.unit_kind === 'phase') { skip(); }")).toHaveLength(1);
    expect(kindDecisions('m.ts', "switch (kind) { case 'component': break; }")).toHaveLength(1);
  });

  it('says it is reporting metadata wherever the analyst chooses one', () => {
    expect(sourceOf('investmentCatalog.ts')).toContain(
      'Unit Kind is an organizational and reporting classification only.',
    );
    for (const relative of ['components/NewInvestmentPanel.tsx', 'components/InvestmentUnitsPanel.tsx']) {
      expect(sourceOf(relative), relative).toContain('UNIT_KIND_NOTE');
    }
  });
});

// =============================================================================
// 3. The Investment's own routes
// =============================================================================

describe('a visible Investment reaches the backend by its own routes', () => {
  it('reaches the backend only through api.ts, and only from its hooks', () => {
    const hooks = new Set(['useInvestments.ts', 'useInvestmentWorkspace.ts', 'useInvestmentAnalysis.ts', 'useNewInvestment.ts']);
    for (const relative of INVESTMENT_MODULES) {
      const text = sourceOf(relative);
      expect(text, relative).not.toMatch(/\bfetch\(/);
      expect(/from '\.{1,2}\/api'/.test(text), relative).toBe(hooks.has(relative));
    }
  });

  it('lists and saves Strategies and Scenarios on the Investment-scoped routes (M3, M4)', () => {
    const strategies = sourceOf('useStrategies.ts');
    expect(strategies).toContain('listInvestmentStrategies(investmentId)');
    expect(strategies).toContain('saveInvestmentStrategy(');
    // The Deal-scoped create is reached only when there is no Investment.
    const save = strategies.slice(strategies.indexOf('async function saveEditor'));
    expect(save.indexOf('if (investmentId !== null)')).toBeGreaterThan(-1);
    expect(save.indexOf('if (investmentId !== null)')).toBeLessThan(save.indexOf('createDealStrategy('));
    const scenarios = sourceOf('useScenarios.ts');
    expect(scenarios).toContain('listInvestmentScenarios(investmentId)');
    const scenarioSave = scenarios.slice(scenarios.indexOf('async function saveEditor'));
    expect(scenarioSave.indexOf('createInvestmentScenario(investmentId')).toBeGreaterThan(-1);
    expect(scenarioSave.indexOf('createInvestmentScenario(investmentId')).toBeLessThan(
      scenarioSave.indexOf('createDealScenario('),
    );
  });

  it('runs the consolidated matrix route for a visible Investment, never the one-unit one (M5)', () => {
    const matrix = sourceOf('useDecisionMatrix.ts');
    expect(matrix).toContain('? await analyzeInvestmentDecisionMatrix(investment.investmentId)');
    expect(matrix).not.toMatch(/analyzeDecisionMatrix\(investment\./);
    const api = sourceOf('api.ts');
    const client = api.slice(api.indexOf('export async function analyzeInvestmentDecisionMatrix'));
    expect(client.slice(0, client.indexOf('\n}\n'))).toContain('/investment-decision-matrix`');
  });

  it('removes a Unit in ONE request that states the resulting price (M6)', () => {
    const calls = callsInFunction('useInvestmentWorkspace.ts', sourceOf('useInvestmentWorkspace.ts'), 'confirmRemoval');
    const apiCalls = calls.filter((call) =>
      /^(removeInvestmentUnit|updateVisibleInvestmentDetails|addInvestmentUnit|updateInvestmentUnitDisplay|getVisibleInvestment)$/.test(call),
    );
    expect(apiCalls).toEqual(['removeInvestmentUnit']);
    expect(sourceOf('useInvestmentWorkspace.ts')).toContain(
      'await removeInvestmentUnit(investmentId, removal.unitId, price)',
    );
    const api = sourceOf('api.ts');
    const client = api.slice(api.indexOf('export async function removeInvestmentUnit'));
    expect(client.slice(0, client.indexOf('\n}\n'))).toContain('?transaction_price=');
    // The price parameter is required: a removal never goes without one.
    expect(client).toMatch(/^export async function removeInvestmentUnit\(\s*investmentId: string,\s*unitId: string,\s*transactionPrice: number,/);
  });

  it('would see a removal split into two economic requests', () => {
    const split = `
      async function confirmRemoval() {
        await updateVisibleInvestmentDetails(id, request);
        await removeInvestmentUnit(id, unitId, price);
      }`;
    expect(callsInFunction('m.ts', split, 'confirmRemoval')).toEqual([
      'updateVisibleInvestmentDetails',
      'removeInvestmentUnit',
    ]);
  });

  it('offers no Investment duplication, and no Investment sensitivity or break-even', () => {
    expect(sourceOf('api.ts')).not.toMatch(/duplicate\w*Investment|cloneInvestment|copyInvestment/i);
    for (const relative of INVESTMENT_MODULES) {
      const shown = textTokens(relative, sourceOf(relative));
      expect(shown.filter((token) => /^(Duplicate|Copy|Clone)\b/.test(token.trim())), relative).toEqual([]);
    }
    const workspace = sourceOf('components/InvestmentWorkspace.tsx');
    // Re-pinned at P7.8B, the gate that published Capital Structure at
    // Investment level, and again at P7.9 Stage 3, the gate that publishes
    // Partnership there. Until each shipped, its word was banned here for the
    // reason every unreached capability is: naming it would have been
    // half-wiring. Sensitivity and Break-Even stay Unit-level and stay banned,
    // and so do AI Analyst and Documents, which belong to no shipped gate --
    // which is what keeps this guard's teeth.
    expect(workspace).toContain(
      [
        "const RISK_VIEWS = [",
        "  { id: 'matrix', label: 'Decision Matrix' },",
        "  { id: 'strategies', label: 'Strategies' },",
        "  { id: 'scenarios', label: 'Scenarios' },",
        "  { id: 'capital-structure', label: 'Capital Structure' },",
        "  { id: 'partnership', label: 'Partnership' },",
        '];',
      ].join('\n'),
    );
    expect(textTokens('components/InvestmentWorkspace.tsx', workspace).filter((token) => /^(Sensitivity|Break-Even|AI Analyst|Documents)$/.test(token.trim()))).toEqual([]);
  });

  it('shows no Quick / Detailed / Lease-Level toggle at Investment level', () => {
    const workspace = sourceOf('components/InvestmentWorkspace.tsx');
    expect(workspace).not.toContain('Underwriting Mode');
    expect(workspace).not.toContain('DealHeader');
    expect(workspace).not.toContain('onOperatingModeChange');
  });
});

// =============================================================================
// 4. No page-wide overflow
// =============================================================================

describe('the Investment tables never widen the page', () => {
  function rule(selector: string): string {
    const start = CSS.indexOf(`\n${selector} {`);
    expect(start, selector).toBeGreaterThan(-1);
    return CSS.slice(start, CSS.indexOf('}', start));
  }

  it('scrolls every table inside its own focusable region', () => {
    const scroll = rule('.investment-table-scroll');
    expect(scroll).toContain('overflow-x: auto;');
    expect(scroll).toContain('max-width: 100%;');
    for (const relative of [
      'components/InvestmentLibraryPanel.tsx',
      'components/NewInvestmentPanel.tsx',
      'components/InvestmentOverview.tsx',
      'components/InvestmentUnitsPanel.tsx',
    ]) {
      const text = sourceOf(relative);
      expect(text, relative).toContain('className="investment-table-scroll" role="region"');
      expect(text, relative).toContain('tabIndex={0}');
    }
  });

  it('lets its containers shrink and keeps the hidden workspace out of layout', () => {
    expect(rule('.investment-host')).toContain('min-width: 0;');
    expect(rule('.investment-host[hidden]')).toContain('display: none;');
    expect(rule('.investment-overview,\n.investment-units')).toContain('min-width: 0;');
    expect(rule('.strategy-unit')).toContain('min-width: 0;');
  });

  it('keeps the P7.6 styles free of good / bad / winner colour', () => {
    const section = CSS.slice(CSS.indexOf('Phase 7 Gate P7.6 -- the visible Investment workspace.'));
    expect(section.length).toBeGreaterThan(0);
    expect(section).not.toMatch(/--(success|positive|gain|loss)|heat|winner|best|gradient/i);
  });
});

// =============================================================================
// 5. Open decision drafts survive a Unit visit
// =============================================================================

describe('the Investment’s decision tools stay mounted, never duplicating an id', () => {
  const DECISION_COMPONENTS = [
    'components/RiskDecisionWorkspace.tsx',
    'components/StrategyManager.tsx',
    'components/StrategyEditor.tsx',
    'components/ScenarioWorkspace.tsx',
    'components/ScenarioEditor.tsx',
    'components/DecisionMatrixPanel.tsx',
  ];

  it('renders the Risk section while hidden, so an open Strategy or Scenario draft is never unmounted', () => {
    const workspace = sourceOf('components/InvestmentWorkspace.tsx');
    // Hidden may stop requests (`isActive`), never rendering.
    expect(workspace).not.toMatch(/scope !== null && isShown/);
    expect(workspace).toContain("isActive={isShown && tab === 'risk'}");
    expect(workspace).toContain("{entry.id === 'risk' && workspace.scope !== null && (");
    expect(workspace).toContain('idFor={(id) => `${RISK_IDS}risk-tab-${id}`}');
    expect(workspace).toContain('controlsFor={(id) => `${RISK_IDS}risk-panel-${id}`}');
    expect(workspace).toContain('onDraftsChange={setDrafts}');
  });

  it('namespaces every decision-tool id by scope, with no literal id of its own', () => {
    for (const relative of DECISION_COMPONENTS) {
      const text = sourceOf(relative);
      expect(text, relative).not.toMatch(/\b(id|htmlFor|aria-labelledby|aria-controls|aria-describedby)="/);
      expect(text, relative).toContain('decisionIdScope(');
    }
    expect(sourceOf('investmentCatalog.ts')).toContain("return isInvestment ? 'investment-' : '';");
  });
});
