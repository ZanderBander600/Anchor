/**
 * D5.1B -- the frontend successor to Sprint D's mode-deferral guardrails.
 *
 * The backend invariant D5.1A established was "every valid `OperatingMode` has
 * an explicit behavior, everywhere". This file states the frontend half, plus
 * the one thing that is *only* true on the frontend: the TypeScript union may
 * know a mode that the user interface does not yet offer.
 *
 * OLD (pre-D5.1B): frontend TypeScript knows only Quick and Detailed.
 * NEW (this file): frontend TypeScript knows Lease-Level, every frontend mode
 *                  dispatch is total, and the visible selector still exposes
 *                  only the modes that actually work.
 *
 * **Why an AST walk rather than a grep.** The dangerous pattern is semantic, not
 * textual. `mode === 'detailed' ? a : b` is unsafe when `mode` is the *wire*
 * mode, and completely fine when `mode` has already been narrowed to a closed
 * two-member union one line earlier -- the resulting code looks identical. A
 * regex cannot tell those apart. The rule below therefore flags only
 * comparisons against a **wide** mode expression, and separately proves that
 * every narrowing is performed by the one shared seam.
 *
 * **Why `tsc` is the primary proof, and this file the backstop.** Every mode
 * switch ends in `assertNeverMode(mode)`, whose parameter is `never`, so adding
 * a member to the union turns each unhandled site into a compile error rather
 * than a silent fallthrough. That was observed live during this gate: widening
 * the union produced exactly six TS2345 errors -- one per switch -- and zero
 * silent fallthroughs. These structural tests exist because `tsc` cannot see
 * *ternaries*, which are precisely what the old code was written with.
 */

import { describe, expect, it } from 'vitest';
import ts from 'typescript';

/** Every production source file, read as text. Vite's `?raw` rather than
 * `node:fs`, so the suite needs no Node type definitions and runs in the same
 * jsdom environment as every other test in this project. */
const SOURCES = import.meta.glob('./**/*.{ts,tsx}', {
  query: '?raw',
  eager: true,
  import: 'default',
}) as Record<string, string>;

function sourceOf(relative: string): string {
  const key = `./${relative}`;
  const text = SOURCES[key];
  if (text === undefined) {
    throw new Error(`No source loaded for ${key}`);
  }
  return text;
}

/** Production modules that make a decision based on operating mode. Named
 * explicitly so a *new* mode-aware module is a deliberate addition to the audit
 * rather than a silent omission from it. */
const AUDITED = [
  'App.tsx',
  'underwrite.ts',
  'operatingMode.ts',
  'ownerSummary.ts',
  'components/AppSidebar.tsx',
  'components/DealLibraryPanel.tsx',
  'components/OwnerSummaryPanel.tsx',
  'components/UnderwriteWorkspace.tsx',
  'components/DealHeader.tsx',
  // D5.5A. `useLeaseLevelDeal.ts` holds one mode's state and makes no mode
  // decision, so it is audited to prove it never starts making one.
  'useLeaseLevelDeal.ts',
  'components/LeaseLevelWorkspace.tsx',
];

const MODE_LITERALS = new Set(['quick', 'detailed', 'lease_level']);

function parse(relative: string): ts.SourceFile {
  return ts.createSourceFile(
    relative,
    sourceOf(relative),
    ts.ScriptTarget.Latest,
    true,
    relative.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
}

function walk(node: ts.Node, visit: (n: ts.Node) => void): void {
  visit(node);
  node.forEachChild((child) => walk(child, visit));
}

function lineOf(source: ts.SourceFile, node: ts.Node): number {
  return source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
}

/**
 * Whether an expression is the **wire** operating mode -- the wide
 * `OperatingMode` value, which can be any published member.
 *
 * Two shapes qualify, and only two:
 *   * `operating_mode` in snake_case, which is the wire field on a `Deal` and
 *     is by definition the full union;
 *   * the bare identifier `operatingMode`, which is the prop/state carrying the
 *     wide type through the shell and its components.
 *
 * A locally narrowed value (`shellMode`, `dealMode`) or a discriminated-union
 * member (`source.operatingMode`) is deliberately *not* wide: those are closed
 * two-member types, and branching on them two ways is total by construction,
 * not by omission. The companion tests below prove those narrowings are real.
 */
function isWideModeExpression(node: ts.Expression): boolean {
  const text = node.getText();
  if (/(^|\.)operating_mode$/.test(text)) return true;
  return text === 'operatingMode';
}

/** A comparison of the wide wire mode against a mode string literal. */
function comparesWideModeToLiteral(node: ts.Node): boolean {
  if (!ts.isBinaryExpression(node)) return false;
  const op = node.operatorToken.kind;
  if (
    op !== ts.SyntaxKind.EqualsEqualsEqualsToken &&
    op !== ts.SyntaxKind.ExclamationEqualsEqualsToken
  ) {
    return false;
  }
  for (const side of [node.left, node.right]) {
    if (ts.isStringLiteral(side) && MODE_LITERALS.has(side.text)) {
      const other = side === node.left ? node.right : node.left;
      if (isWideModeExpression(other)) return true;
    }
  }
  return false;
}

/** Whether a statement always leaves its enclosing block. */
function alwaysExits(statement: ts.Statement): boolean {
  if (ts.isReturnStatement(statement) || ts.isThrowStatement(statement)) return true;
  if (ts.isBlock(statement)) {
    return statement.statements.length > 0
      && alwaysExits(statement.statements[statement.statements.length - 1]);
  }
  return false;
}

/**
 * Sites where the wide mode selects between exactly two behaviours.
 *
 * Three shapes count as dispatch, and the third is the one that matters most:
 *
 *   1. a ternary whose condition compares the wire mode;
 *   2. an `if` with an `else` -- one branch per mode, explicitly;
 *   3. **an `if` whose body always returns, followed by more statements** --
 *      `if (mode === 'detailed') { …; return; } <the other mode's behaviour>`.
 *      There is no `else` keyword anywhere, but the trailing statements *are*
 *      the else, and this is precisely the shape the pre-D5.1B frontend used in
 *      `handleOpenDeal` and `handleAnalyzeFromHeader` (and the pre-D5.1A backend
 *      used across eight endpoints). A detector that only looked for `else`
 *      would have declared those files clean while the hazard sat in them.
 *
 * A bare `if` with no `else` and no trailing statements is not flagged: it adds
 * behaviour for one mode without claiming anything about the others.
 */
function unsafeDispatchSites(source: ts.SourceFile): string[] {
  const offenders: string[] = [];

  function scanStatements(statements: readonly ts.Statement[]): void {
    statements.forEach((statement, index) => {
      if (!ts.isIfStatement(statement)) return;
      if (!comparesWideModeToLiteral(statement.expression)) return;

      if (statement.elseStatement) {
        offenders.push(`${source.fileName}:${lineOf(source, statement)} if/else`);
        return;
      }
      const hasTrailing = index < statements.length - 1;
      if (hasTrailing && alwaysExits(statement.thenStatement)) {
        offenders.push(`${source.fileName}:${lineOf(source, statement)} early-return dispatch`);
      }
    });
  }

  walk(source, (node) => {
    if (ts.isConditionalExpression(node) && comparesWideModeToLiteral(node.condition)) {
      offenders.push(`${source.fileName}:${lineOf(source, node)} ternary`);
    }
    if (ts.isBlock(node) || ts.isSourceFile(node)) {
      scanStatements(node.statements);
    }
    if (ts.isCaseClause(node) || ts.isDefaultClause(node)) {
      scanStatements(node.statements);
    }
  });

  return offenders;
}

// =============================================================================
// 1. No binary dispatch on the wide mode survives
// =============================================================================

describe('frontend mode dispatch is total', () => {
  it.each(AUDITED)('%s branches on the wire mode only via a total form', (relative) => {
    expect(
      unsafeDispatchSites(parse(relative)),
      `binary dispatch on the wire operating mode survives in ${relative}: a third ` +
        `OperatingMode would silently inherit one of the two named modes' behaviour`,
    ).toEqual([]);
  });

  it('the shared Quick/Detailed workspace still narrows at the one seam', () => {
    // D5.5A: `requireImplementedMode` became `requireUnderwriteWorkspaceMode`,
    // and the shell stopped needing it -- the shell now chooses per mode rather
    // than refusing a third one. The seam survives where it is still true:
    // `UnderwriteWorkspace` serves exactly Quick and Detailed, and must refuse
    // anything else rather than guessing which of the two it resembles.
    expect(
      sourceOf('components/UnderwriteWorkspace.tsx'),
      'UnderwriteWorkspace should narrow via requireUnderwriteWorkspaceMode',
    ).toContain('requireUnderwriteWorkspaceMode');
  });

  it('the shell chooses per mode through byMode, never through a ternary', () => {
    // D5.5A's successor to the `shellMode`/`dealMode` pin. Those two locals were
    // safe because they were the return of a narrowing call; they are gone, and
    // what replaced them is stronger: `byMode` takes a `Record<OperatingMode, T>`,
    // so an omitted arm is a compile error rather than a convention. Pinned by
    // *count* so a single site cannot quietly revert to a ternary.
    const app = sourceOf('App.tsx');
    expect(app).not.toContain('const shellMode =');
    expect(app).not.toContain('const isDetailed =');
    const byModeCalls = app.match(/byMode\(operatingMode, \{/g) ?? [];
    expect(
      byModeCalls.length,
      'the shell should resolve every per-mode chrome value through byMode',
    ).toBeGreaterThanOrEqual(10);
  });

  it('every byMode call names all three modes', () => {
    // A `Record<OperatingMode, T>` cannot compile with an arm missing, so this
    // is belt-and-braces against an `as` cast sneaking one past the compiler.
    const app = sourceOf('App.tsx');
    const blocks = app.split('byMode(operatingMode, {').slice(1);
    expect(blocks.length).toBeGreaterThanOrEqual(10);
    for (const block of blocks) {
      const body = block.slice(0, block.indexOf('})'));
      for (const mode of MODE_LITERALS) {
        expect(body, `a byMode call omits '${mode}'`).toContain(`${mode}:`);
      }
    }
  });

  it('the owner-summary discriminants are closed unions, not the wire mode', () => {
    // `ownerSummary.ts` branches two ways on `source.operatingMode` and
    // `operatingStory.operatingMode`. That is total by construction only while
    // those fields are declared as literal two-member unions rather than as
    // `OperatingMode`. Pin that, because widening them would silently reopen the
    // hazard without touching a single branch.
    const text = sourceOf('ownerSummary.ts');
    const source = parse('ownerSummary.ts');

    let closedDiscriminants = 0;
    walk(source, (node) => {
      if (
        ts.isPropertySignature(node) &&
        node.name.getText(source) === 'operatingMode' &&
        node.type &&
        ts.isLiteralTypeNode(node.type)
      ) {
        closedDiscriminants += 1;
      }
    });

    expect(
      closedDiscriminants,
      'ownerSummary.ts must keep its literal-typed mode discriminants',
    ).toBeGreaterThanOrEqual(4);
    expect(text).toContain("operatingMode: 'quick';");
    expect(text).toContain("operatingMode: 'detailed';");
  });
});

// =============================================================================
// 2. Every mode switch is compiler-checked for exhaustiveness
// =============================================================================

describe('mode switches are compiler-checked', () => {
  function modeSwitches(source: ts.SourceFile): ts.SwitchStatement[] {
    const found: ts.SwitchStatement[] = [];
    walk(source, (node) => {
      if (!ts.isSwitchStatement(node)) return;
      const usesModeLiteral = node.caseBlock.clauses.some(
        (clause) =>
          ts.isCaseClause(clause) &&
          ts.isStringLiteral(clause.expression) &&
          MODE_LITERALS.has(clause.expression.text),
      );
      if (usesModeLiteral) found.push(node);
    });
    return found;
  }

  it.each(AUDITED)('%s: every mode switch defaults to assertNeverMode', (relative) => {
    const source = parse(relative);
    for (const statement of modeSwitches(source)) {
      const defaultClause = statement.caseBlock.clauses.find(ts.isDefaultClause);
      expect(
        defaultClause,
        `${relative}:${lineOf(source, statement)} mode switch has no default arm`,
      ).toBeDefined();

      const body = defaultClause!.statements.map((s) => s.getText(source)).join('\n');
      expect(
        body,
        `${relative}:${lineOf(source, statement)} default arm must call assertNeverMode, ` +
          `never return a mode's behaviour`,
      ).toContain('assertNeverMode');
    }
  });

  it('every mode switch names all three published modes explicitly', () => {
    let checked = 0;
    for (const relative of AUDITED) {
      const source = parse(relative);
      for (const statement of modeSwitches(source)) {
        const named = statement.caseBlock.clauses
          .filter(ts.isCaseClause)
          .map((clause) => (ts.isStringLiteral(clause.expression) ? clause.expression.text : ''));
        for (const mode of MODE_LITERALS) {
          expect(
            named,
            `${relative}:${lineOf(source, statement)} never names '${mode}'; a published ` +
              `mode handled only by the default arm is a mode nobody decided about`,
          ).toContain(mode);
        }
        checked += 1;
      }
    }
    expect(checked, 'the switch finder located nothing').toBeGreaterThanOrEqual(5);
  });
});

// =============================================================================
// 3. The union is published, in the backend's wire spelling
// =============================================================================

describe('the TypeScript OperatingMode union', () => {
  it('contains exactly the three published modes', () => {
    const match = sourceOf('types.ts').match(/export type OperatingMode = ([^;]+);/);
    expect(match).not.toBeNull();
    const members = match![1]
      .split('|')
      .map((part: string) => part.trim().replace(/'/g, ''));
    expect(members).toEqual(['quick', 'detailed', 'lease_level']);
  });

  it('introduces no rival spelling of the third mode', () => {
    for (const [path, text] of Object.entries(SOURCES)) {
      if (path.includes('.test.')) continue;
      for (const wrong of ["'lease-level'", "'leaseLevel'", "'leaselevel'", "'LEASE_LEVEL'"]) {
        expect(text, `${path} uses ${wrong} instead of the wire value`).not.toContain(wrong);
      }
    }
  });
});

// =============================================================================
// 4. D5.5A grants Lease-Level exactly the capability it owns
//
// D5.1B asserted the negative: the frontend knew the mode's name and nothing
// else. Four of those five assertions stop being true at D5.5A, so they are
// transitioned into their successors rather than deleted -- the invariant is
// still "the frontend claims exactly what it has built", only the boundary has
// moved. What remains forbidden is what D5.5B, D5.6, D5.7 and D5.8 own.
// =============================================================================

describe('the Lease-Level capability boundary', () => {
  it('wires the analysis and persistence client functions D5.3/D5.4 activated', () => {
    const api = sourceOf('api.ts');
    for (const required of [
      'analyzeLeaseLevelAcquisition',
      'createLeaseLevelDeal',
      'updateLeaseLevelDeal',
    ]) {
      expect(api, `api.ts should wire ${required}`).toContain(required);
    }
  });

  it('wires no client function for a surface a later gate owns', () => {
    // The successor to D5.1B's blanket refusal. `/sensitivity` supports
    // Lease-Level on the backend and `/ai/analysis` will, but no D5.5A screen
    // consumes either, and a client function with no caller is a claim that a
    // workflow exists.
    const api = sourceOf('api.ts');
    for (const forbidden of [
      'LeaseLevelSensitivity',
      'leaseLevelSensitivity',
      'fetchLeaseLevelPresets',
      'LeaseLevelBreakEven',
      'leaseLevelAiAnalysis',
    ]) {
      expect(api, `api.ts wires ${forbidden}; a later gate owns that`).not.toContain(forbidden);
    }
  });

  it('keeps the Lease-Level contracts in their own module, not in types.ts', () => {
    // Not a deferral any more -- a boundary. The contracts exist, in
    // `leaseLevelTypes.ts`. `types.ts` is the hand-maintained mirror of every
    // other backend shape, and folding six contracts and five enums into it
    // would roughly double it for one mode.
    const types = sourceOf('types.ts');
    for (const elsewhere of [
      'LeaseLevelAcquisitionResults',
      'MonthlyPropertyProjection',
      'AnnualOperatingProjection',
      'MarketLeasingAssumptionsRequest',
    ]) {
      expect(types, `types.ts declares ${elsewhere}; leaseLevelTypes.ts owns it`).not.toContain(
        `interface ${elsewhere}`,
      );
    }
  });

  it('declares no `any` in the Lease-Level transport or response contracts', () => {
    // A stop condition for this gate, stated structurally. `any` in a financial
    // response type would let a renamed backend field reach a screen as
    // `undefined` with nothing objecting.
    for (const relative of ['leaseLevelTypes.ts', 'leaseLevelConvert.ts', 'api.ts']) {
      const source = parse(relative);
      const offenders: string[] = [];
      walk(source, (node) => {
        if (node.kind === ts.SyntaxKind.AnyKeyword) {
          offenders.push(`${relative}:${lineOf(source, node)}`);
        }
      });
      expect(offenders, `${relative} uses the any type`).toEqual([]);
    }
  });

  it('builds the Lease-Level workspace, and none of the editors a later gate owns', () => {
    const paths = Object.keys(SOURCES).join(' ');
    expect(paths, 'LeaseLevelWorkspace should exist at D5.5A').toContain('LeaseLevelWorkspace');
    for (const forbidden of [
      'SuiteTable',
      'LeaseTable',
      'SuiteOverrideDrawer',
      'InitialVacancyDrawer',
      'RentRollPasteImport',
      'LeaseLevelOperatingStatement',
      'MonthlyRentRollTable',
      'LeaseLevelAuditCard',
      'LeaseLevelSensitivityPanel',
    ]) {
      expect(paths, `${forbidden} exists; D5.5B/D5.6/D5.7 own it`).not.toContain(forbidden);
    }
  });

  it('renders no Lease-Level results, and asks for no Lease-Level results views', () => {
    // D5.6 owns every result surface. The proof that D5.5A did not start one:
    // the workspace never calls `resultsViewsFor`, which still refuses this
    // mode, and never reads a projection off the analysis the shell holds.
    const workspace = sourceOf('components/LeaseLevelWorkspace.tsx');
    // A *call*, not a mention: the module's own docstring names the function to
    // explain why it does not use it, which is exactly the comment a reader
    // needs and exactly what a naive substring check would forbid.
    expect(workspace).not.toContain('resultsViewsFor(');
    for (const forbidden of [
      'monthly_projection',
      'annual_projection',
      'noi_by_year',
      'tenant_improvements',
      'physical_occupancy',
    ]) {
      expect(workspace, `the workspace renders ${forbidden}; D5.6 owns that`).not.toContain(
        forbidden,
      );
    }
    expect(sourceOf('underwrite.ts')).toContain('UnsupportedOperatingModeError');
  });

  it('the selector is now exactly as wide as the type', () => {
    // The inversion of D5.1B's keystone assertion. The type knew three and the
    // product offered two; now it offers three, because all three work.
    expect(sourceOf('components/DealHeader.tsx')).toContain(
      "const SELECTABLE_MODES: SelectableMode[] = ['quick', 'detailed', 'lease_level'];",
    );
  });

  it('computes no lease economics in the browser (G-M7)', () => {
    // The two approved carve-outs (plan section 10.1) are the sensitivity ladder
    // and area totals -- neither of which exists yet, so at D5.5A the correct
    // count of client-side lease calculations is zero.
    //
    // `leaseLevelConvert.ts` carries the one arithmetic this app has always done
    // at the form boundary: the percent convention, `x / 100` and `x * 100`,
    // shared verbatim with Quick and Detailed. It is a unit convention on a
    // value the analyst typed, not an economic derivation, so it is allowed by
    // literal here and nowhere else.
    for (const relative of [
      'components/LeaseLevelWorkspace.tsx',
      'useLeaseLevelDeal.ts',
      'leaseLevelConvert.ts',
    ]) {
      const source = parse(relative);
      const offenders: string[] = [];
      walk(source, (node) => {
        if (!ts.isBinaryExpression(node)) return;
        const op = node.operatorToken.kind;
        if (
          op === ts.SyntaxKind.AsteriskToken ||
          op === ts.SyntaxKind.SlashToken ||
          op === ts.SyntaxKind.MinusToken ||
          op === ts.SyntaxKind.PlusToken
        ) {
          offenders.push(`${relative}:${lineOf(source, node)} ${node.getText(source)}`);
        }
      });
      const disallowed = offenders.filter((site) => !/\b100\b/.test(site));
      expect(disallowed, `${relative} performs lease arithmetic in the browser`).toEqual([]);
    }
  });
});

// =============================================================================
// 5. Mutation kills
//
// Each named mutant is applied to the real source and shown to be caught by the
// audit above, rather than asserted to be impossible.
// =============================================================================

describe('mutation kills', () => {
  function auditMutated(relative: string, mutate: (text: string) => string): string[] {
    const mutated = mutate(sourceOf(relative));
    expect(mutated, `${relative}: mutation changed nothing`).not.toBe(sourceOf(relative));
    const source = ts.createSourceFile(
      relative,
      mutated,
      ts.ScriptTarget.Latest,
      true,
      relative.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    );
    return unsafeDispatchSites(source);
  }

  it('M1: Open Deal reverting to early-return dispatch is caught', () => {
    // D5.5A replaced `handleOpenDeal`'s narrow-then-branch shape with a switch,
    // so the mutant is the old shape coming back: an `if` on the wire mode whose
    // body returns, with the other mode's behaviour trailing it. That is exactly
    // the pre-D5.1B code, and the detector must still see it.
    const offenders = auditMutated('App.tsx', (text) =>
      text.replace(
        '    switch (deal.operating_mode) {',
        [
          "    if (deal.operating_mode === 'detailed') {",
          '      return openDetailedDealFromLibrary(deal);',
          '    }',
          '    return openQuickDealFromLibrary(deal);',
          '    switch (deal.operating_mode) {',
        ].join('\n'),
      ),
    );
    expect(offenders.length).toBeGreaterThan(0);
  });

  it('M2/M3: the shell falling back to Quick is caught', () => {
    // The mutant D5.1B killed, retargeted at D5.5A's `byMode` call: a ternary on
    // the wide mode, which answers Quick for every mode that is not Detailed.
    const offenders = auditMutated('App.tsx', (text) =>
      text.replace(
        'const activeDealId = byMode(operatingMode, {',
        [
          "const activeDealId = operatingMode === 'detailed'",
          '    ? currentDetailedDealId',
          '    : currentDealId;',
          '  const unusedActiveDealId = byMode(operatingMode, {',
        ].join('\n'),
      ),
    );
    expect(offenders.length).toBeGreaterThan(0);
  });

  it('M4/M5: a binary deal badge is caught', () => {
    for (const relative of ['components/AppSidebar.tsx', 'components/DealLibraryPanel.tsx']) {
      const offenders = auditMutated(relative, (text) =>
        text.replace(
          'operatingModeLabel(deal.operating_mode)',
          "deal.operating_mode === 'detailed' ? 'Detailed' : 'Quick'",
        ),
      );
      expect(offenders.length, `${relative} badge mutant survived`).toBeGreaterThan(0);
    }
  });

  it('M6: a binary owner-summary identity badge is caught', () => {
    // `identity.operatingMode` is the *wide* mode -- unlike the discriminated
    // union in `ownerSummary.ts` -- so restoring a ternary here is dispatch.
    const offenders = auditMutated('components/OwnerSummaryPanel.tsx', (text) =>
      text.replace(
        'operatingModeUnderwriteLabel(identity.operatingMode)',
        "operatingMode === 'quick' ? 'Quick Underwrite' : 'Detailed Underwrite'",
      ),
    );
    expect(offenders.length).toBeGreaterThan(0);
  });

  it('M7: reading another mode’s purchase price for Lease-Level is caught', () => {
    // D5.5A transition. D5.1B pinned `return null`, because no Lease-Level deal
    // had a purchase price to show. D5.4 gave it `terms`, so the arm must now
    // read `terms` -- and must still never read Quick's `inputs`, which is the
    // substitution the mutant models.
    for (const relative of ['components/AppSidebar.tsx', 'components/DealLibraryPanel.tsx']) {
      const text = sourceOf(relative);
      const arm = text.slice(text.indexOf("case 'lease_level':"));
      const body = arm.slice(0, arm.indexOf('default:'));
      expect(body, `${relative} Lease-Level arm reads Quick's inputs`).not.toContain(
        'deal.inputs',
      );
      expect(body).toContain('deal.terms?.purchase_price ?? null');
    }
  });

  it('M8: returning Quick result views for Lease-Level is caught', () => {
    const text = sourceOf('underwrite.ts');
    const arm = text.slice(text.indexOf("case 'lease_level':"));
    const body = arm.slice(0, arm.indexOf('default:'));
    expect(body).toContain('UnsupportedOperatingModeError');
    expect(body).not.toContain('return views');
  });

  it('M9: a default arm returning a mode instead of asserting is caught', () => {
    const text = sourceOf('operatingMode.ts');
    expect(text).not.toMatch(/default:\s*\n\s*return 'quick'/);
    expect(text).not.toMatch(/default:\s*\n\s*return 'detailed'/);
    const defaults = text.match(/default:/g) ?? [];
    const asserts = text.match(/assertNeverMode/g) ?? [];
    expect(asserts.length).toBeGreaterThanOrEqual(defaults.length);
  });

  it('M10: the union cannot widen without the compiler objecting', () => {
    // The ordering invariant. Observed live in this gate: widening the union
    // before adding the third arms produced six TS2345 errors -- one per mode
    // switch -- and zero silent fallthroughs.
    expect(sourceOf('operatingMode.ts')).toContain(
      'export function assertNeverMode(value: never): never',
    );
  });

  it('M11: dropping Lease-Level back out of the selector is caught', () => {
    // The inverse of D5.1B's M11, for the inverse hazard: the workspace ships,
    // so a selector that still offers two modes hides it. The behavioural half
    // lives in leaseLevelSafety.test.tsx; this is the structural half.
    expect(sourceOf('components/DealHeader.tsx')).not.toContain(
      "SELECTABLE_MODES: SelectableMode[] = ['quick', 'detailed'];",
    );
  });

  it('M12: a Lease-Level client function losing its mode literal is caught', () => {
    // D5.1B forbade the literal outright. Its successor: every Lease-Level
    // client function must carry the Lease-Level discriminator, because the
    // mode is a *fact about the function* rather than a runtime branch -- one
    // wrong literal would run a rent roll through Quick's endpoint arm.
    const api = sourceOf('api.ts');
    const literals = api.match(/operating_mode: 'lease_level'/g) ?? [];
    expect(
      literals.length,
      'analyze, create and update must each carry the Lease-Level discriminator',
    ).toBe(3);
    for (const forbidden of ["operating_mode: 'quick',\n    terms,\n    ...inputs"]) {
      expect(api, 'a Lease-Level body carries another mode').not.toContain(forbidden);
    }
  });

  it('M13: the shell mounting another mode’s workspace for Lease-Level is caught', () => {
    // The D5.5A hazard in one line. `byMode` makes an *omitted* arm impossible,
    // so the surviving mutant is the *wrong* arm: pointing Lease-Level at
    // Quick's render tree. That is a value swap the compiler cannot see.
    const app = sourceOf('App.tsx');
    expect(app).toContain('lease_level: leaseLevelWorkspace,');
    expect(app).not.toContain('lease_level: quickWorkspaces,');
    expect(app).not.toContain('lease_level: detailedWorkspaces,');
  });

  it('M14: the shell reading another mode’s deal state for Lease-Level is caught', () => {
    // Same class as M13, over the header chrome: a Lease-Level deal showing
    // Quick's name, save status or analyzing flag would report one deal's state
    // under another deal's label. Every Lease-Level arm must name Lease-Level
    // state, and the audit walks all of them rather than a chosen few.
    const app = sourceOf('App.tsx');
    const blocks = app.split('byMode(operatingMode, {').slice(1);
    expect(blocks.length).toBeGreaterThanOrEqual(10);
    let audited = 0;
    for (const block of blocks) {
      const body = block.slice(0, block.indexOf('})'));
      const arm = body.slice(body.indexOf('lease_level:'));
      const value = arm
        .slice('lease_level:'.length, arm.indexOf('\n'))
        .trim()
        .replace(/,$/, '');
      if (value === 'null') continue;
      audited += 1;
      expect(
        value,
        `a byMode Lease-Level arm reads ${value}, which is not Lease-Level state`,
      ).toMatch(/^(leaseLevel\.|leaseLevelWorkspace|handleNewLeaseLevelDeal|\(\) =>)/);
    }
    expect(audited, 'the arm audit found nothing to check').toBeGreaterThanOrEqual(9);
  });

  it('M15: Open Deal opening a Lease-Level deal as Quick is caught', () => {
    // The D5.1B M1 mutant, retargeted. `handleOpenDeal` is now a switch, so the
    // omission hazard is gone; what remains is an arm calling the wrong opener.
    const app = sourceOf('App.tsx');
    expect(app).toContain("case 'lease_level':\n        return openLeaseLevelDealFromLibrary(deal);");
    expect(app).not.toContain("case 'lease_level':\n        return openQuickDealFromLibrary(deal);");
  });

  it('M16: the Lease-Level opener hydrating from another mode’s fields is caught', () => {
    // A Lease-Level deal carries no `inputs` and no `detailed_operating_inputs`.
    // Reading either would mean fabricating a shape the deal never had.
    const hook = sourceOf('useLeaseLevelDeal.ts');
    expect(hook).not.toContain('deal.inputs');
    expect(hook).not.toContain('deal.detailed_operating_inputs');
    for (const required of [
      'deal.property_inputs',
      'deal.operating_inputs',
      'deal.market_leasing',
      'deal.suites',
      'deal.leases',
    ]) {
      expect(hook, `the opener never reads ${required}`).toContain(required);
    }
  });
});
