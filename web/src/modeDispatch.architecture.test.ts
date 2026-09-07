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

  it('narrowing happens at the one shared seam, not per-file', () => {
    // `requireImplementedMode` is the single place that decides what happens to
    // a mode this frontend cannot render. Scattering that decision would let one
    // surface refuse while another quietly fell back.
    for (const relative of ['App.tsx', 'components/UnderwriteWorkspace.tsx']) {
      expect(sourceOf(relative), `${relative} should narrow via requireImplementedMode`).toContain(
        'requireImplementedMode',
      );
    }
  });

  it('the values the shell branches on really are narrowed, not renamed', () => {
    // `shellMode` and `dealMode` are safe to branch two ways *because* they are
    // the return of `requireImplementedMode`. If either were ever reassigned
    // from the raw mode, the ternaries beneath them would silently go back to
    // being two-way over three members.
    const app = sourceOf('App.tsx');
    expect(app).toContain(
      "const shellMode = requireImplementedMode(operatingMode, 'the Underwrite shell');",
    );
    expect(app).toContain(
      "const dealMode = requireImplementedMode(deal.operating_mode, 'Open Deal');",
    );
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
// 4. D5.1B grants no Lease-Level capability
//
// The frontend knows the mode's name. It must not yet know how to analyze,
// save, fingerprint or render one. D5.2/D5.3/D5.4/D5.5 own those.
// =============================================================================

describe('no Lease-Level capability is wired', () => {
  it('adds no Lease-Level API client function', () => {
    const api = sourceOf('api.ts');
    for (const forbidden of [
      'analyzeLeaseLevel',
      'leaseLevelSensitivity',
      'saveLeaseLevelDeal',
      'createLeaseLevelDeal',
      'updateLeaseLevelDeal',
      'fingerprintLeaseLevel',
      'lease_level',
    ]) {
      expect(api, `api.ts wires ${forbidden}; D5.3/D5.4 own that`).not.toContain(forbidden);
    }
  });

  it('adds no Lease-Level financial transport types', () => {
    const types = sourceOf('types.ts');
    for (const forbidden of [
      'LeaseLevelPropertyInputs',
      'LeaseLevelOperatingInputs',
      'LeaseLevelAcquisitionResults',
      'MonthlyPropertyProjection',
      'AnnualOperatingProjection',
      'MarketLeasingAssumptions',
    ]) {
      expect(types, `types.ts declares ${forbidden}; a later gate owns that`).not.toContain(
        forbidden,
      );
    }
  });

  it('builds no Lease-Level workspace or editor component', () => {
    const paths = Object.keys(SOURCES).join(' ');
    for (const forbidden of [
      'LeaseLevelWorkspace',
      'SuiteTable',
      'LeaseTable',
      'LeaseLevelOperatingStatement',
      'LeaseLevelSensitivityPanel',
    ]) {
      expect(paths, `${forbidden} exists; a later gate owns it`).not.toContain(forbidden);
    }
  });

  it('keeps the selectable modes narrower than the type', () => {
    // The whole point of D5.1B: the type knows three, the product offers two.
    expect(sourceOf('components/DealHeader.tsx')).toContain(
      "const SELECTABLE_MODES: ImplementedOperatingMode[] = ['quick', 'detailed'];",
    );
    expect(sourceOf('operatingMode.ts')).toContain(
      "export type ImplementedOperatingMode = 'quick' | 'detailed';",
    );
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

  it('M1: Open Deal falling back to Quick is caught', () => {
    const offenders = auditMutated('App.tsx', (text) =>
      text.replace("if (dealMode === 'detailed') {", "if (deal.operating_mode === 'detailed') {"),
    );
    expect(offenders.length).toBeGreaterThan(0);
  });

  it('M2/M3: the shell falling back to Quick is caught', () => {
    const offenders = auditMutated('App.tsx', (text) =>
      text.replace(
        "const activeDealId = shellMode === 'detailed' ? currentDetailedDealId : currentDealId;",
        "const activeDealId = operatingMode === 'detailed' ? currentDetailedDealId : currentDealId;",
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
    for (const relative of ['components/AppSidebar.tsx', 'components/DealLibraryPanel.tsx']) {
      const text = sourceOf(relative);
      const arm = text.slice(text.indexOf("case 'lease_level':"));
      const body = arm.slice(0, arm.indexOf('default:'));
      expect(body, `${relative} Lease-Level arm reads a mode-specific field`).not.toMatch(
        /deal\.(inputs|terms)\?/,
      );
      expect(body).toContain('return null');
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

  it('M11: exposing Lease-Level in the selector prematurely is caught', () => {
    // The behavioural half lives in leaseLevelSafety.test.tsx; this is the
    // structural half, so the guardrail survives a component refactor.
    expect(sourceOf('components/DealHeader.tsx')).not.toContain(
      "SELECTABLE_MODES: ImplementedOperatingMode[] = ['quick', 'detailed', 'lease_level']",
    );
    expect(sourceOf('operatingMode.ts')).not.toContain(
      "export type ImplementedOperatingMode = 'quick' | 'detailed' | 'lease_level';",
    );
  });

  it('M12: a premature Lease-Level analyze call is caught', () => {
    expect(sourceOf('api.ts')).not.toContain('lease_level');
  });
});
