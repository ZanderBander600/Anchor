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
  // D5.5B. None of these makes a mode decision; they are audited to prove they
  // never start making one.
  'components/RentRollTable.tsx',
  'components/SuiteLeaseEditor.tsx',
  'leaseLevelIssues.ts',
  // D5.6. Result presentation: audited to prove it presents and does not
  // compute.
  'components/LeaseLevelResults.tsx',
  'components/LeaseLevelOperatingStatement.tsx',
  'components/LeaseLevelMetricSummary.tsx',
  'leaseLevelFormat.ts',
  // D5.7. The sensitivity workspace. None of these makes a mode decision, and
  // none may compute an economic quantity: a sensitivity surface that derived a
  // metric would be the most dangerous possible place for browser math.
  'components/LeaseLevelSensitivityWorkspace.tsx',
  'components/LeaseLevelOneWaySensitivity.tsx',
  'components/LeaseLevelTwoWaySensitivity.tsx',
  'components/CandidateValueEditor.tsx',
  'leaseLevelSensitivity.ts',
  // D5.8B. The out-of-date notice, shared by the AI panel and both sensitivity
  // panels. It makes no mode decision and computes nothing -- it is audited so
  // that it never starts.
  'components/StaleAnalysisNotice.tsx',
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

  it('wires the D5.7 sensitivity client functions, and none a later gate owns', () => {
    // D5.7 transition. D5.5A forbade every sensitivity client function because
    // no screen consumed one; the Risk workspace consumes both now, so the
    // successor invariant requires them -- and still forbids presets, which
    // Lease-Level deliberately never calls, plus break-even and AI, which
    // remain unsupported and D5.8's.
    const api = sourceOf('api.ts');
    for (const required of [
      'runLeaseLevelOneWaySensitivity',
      'runLeaseLevelTwoWaySensitivity',
    ]) {
      expect(api, `api.ts should wire ${required}`).toContain(required);
    }
    for (const forbidden of [
      'fetchLeaseLevelPresets',
      'LeaseLevelSensitivityPresets',
      'LeaseLevelBreakEven',
      'leaseLevelAiAnalysis',
    ]) {
      expect(api, `api.ts wires ${forbidden}; a later gate owns that`).not.toContain(forbidden);
    }
  });

  it('never asks for a Lease-Level sensitivity preset', () => {
    // D5.0's decision, stated structurally: the analyst owns the scenario
    // values, so `POST /sensitivity/presets` is never reachable from any
    // Lease-Level surface, and no control silently populates an assumption with
    // a named package.
    //
    // Every forbidden token below is an *identifier* a preset implementation
    // would have to name. A doc comment explaining why Lease-Level has no
    // presets writes the English word, and must not be what fails this test.
    for (const relative of [
      'components/LeaseLevelSensitivityWorkspace.tsx',
      'components/LeaseLevelOneWaySensitivity.tsx',
      'components/LeaseLevelTwoWaySensitivity.tsx',
      'components/CandidateValueEditor.tsx',
    ]) {
      const code = sourceOf(relative);
      for (const forbidden of [
        '/sensitivity/presets',
        'fetchSensitivityPresets',
        'fetchDetailedSensitivityPresets',
        'StandardSensitivityPresets',
        'Conservative',
        'Upside',
        'Downside',
        'Base Case',
      ]) {
        expect(code, `${relative} offers a preset (${forbidden})`).not.toContain(forbidden);
      }
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

  it('builds the rent-roll editor, and none of the surfaces a later gate owns', () => {
    // D5.5B transition. D5.5A forbade every rent-roll editor because it had
    // none; the successor requires the ones this gate owns and still forbids
    // the result, sensitivity and AI surfaces D5.6-D5.8 own.
    const paths = Object.keys(SOURCES).join(' ');
    for (const required of ['LeaseLevelWorkspace', 'RentRollTable', 'SuiteLeaseEditor']) {
      expect(paths, `${required} should exist at D5.5B`).toContain(required);
    }
    // D5.6 transition: the result surfaces this gate owns now exist, and the
    // ones D5.7/D5.8 own still must not.
    for (const required of [
      'LeaseLevelResults',
      'LeaseLevelOperatingStatement',
      'LeaseLevelMetricSummary',
    ]) {
      expect(paths, `${required} should exist at D5.6`).toContain(required);
    }
    // D5.7 transition: the sensitivity workspace this gate owns now exists, and
    // break-even -- which Lease-Level does not support -- still must not.
    for (const required of [
      'LeaseLevelSensitivityWorkspace',
      'LeaseLevelOneWaySensitivity',
      'LeaseLevelTwoWaySensitivity',
    ]) {
      expect(paths, `${required} should exist at D5.7`).toContain(required);
    }
    for (const forbidden of ['RentRollPasteImport', 'LeaseLevelBreakEven', 'LeaseLevelAiPanel']) {
      expect(paths, `${forbidden} exists; a later gate owns it`).not.toContain(forbidden);
    }
  });

  it('offers no Lease-Level break-even', () => {
    // Break-even is unsupported for Lease-Level. The Risk workspace therefore
    // does not show a tab for it -- a control that refuses is worse than one
    // that is absent -- and Quick's and Detailed's break-even panel is not
    // reachable from any Lease-Level surface.
    for (const relative of [
      'components/LeaseLevelSensitivityWorkspace.tsx',
      'components/LeaseLevelOneWaySensitivity.tsx',
      'components/LeaseLevelTwoWaySensitivity.tsx',
    ]) {
      const text = sourceOf(relative);
      for (const forbidden of [
        'BreakEvenPanel',
        'breakEven',
        'fetchBreakEvenAnalysis',
        'fetchDetailedBreakEvenAnalysis',
        'BreakEvenResult',
      ]) {
        expect(text, `${relative} offers ${forbidden}`).not.toContain(forbidden);
      }
    }
  });

  it('adds no sequential-known-lease surface', () => {
    // D4 acquisition supports at most one known lease per suite. A future,
    // committed or second lease is deferred, and the UI must not imply it can
    // be entered.
    for (const relative of [
      'components/RentRollTable.tsx',
      'components/SuiteLeaseEditor.tsx',
      'useLeaseLevelDeal.ts',
      'leaseLevelTypes.ts',
    ]) {
      const text = sourceOf(relative);
      for (const forbidden of [
        'Add Lease',
        'addLease',
        'Add another lease',
        'nextLease',
        'futureLease',
        'leaseStack',
        'leases: LeaseFormValues[]',
      ]) {
        expect(text, `${relative} offers ${forbidden}`).not.toContain(forbidden);
      }
    }
    // Structural: a row holds at most one lease, by type.
    expect(sourceOf('leaseLevelTypes.ts')).toContain('lease: LeaseFormValues | null;');
  });

  it('reads its result surfaces from the authoritative response only', () => {
    // D5.6 transition. D5.5A asserted the workspace rendered *no* result at
    // all, which was right while none existed. The successor invariant is that
    // every rendered figure comes off the response rather than out of a
    // calculation -- so the components may name those fields, and must not
    // reduce, sum or average them.
    for (const relative of [
      'components/LeaseLevelResults.tsx',
      'components/LeaseLevelOperatingStatement.tsx',
      'components/LeaseLevelMetricSummary.tsx',
      // The formatter too: a total slipped into a label would be the same
      // mutant wearing a different hat (M25).
      'leaseLevelFormat.ts',
      // D5.7: a sensitivity table is a result surface too. A `Math.max` here
      // would be the first step towards ranking scenarios, and a `.reduce`
      // towards an average row -- both financial claims the backend never made.
      'components/LeaseLevelOneWaySensitivity.tsx',
      'components/LeaseLevelTwoWaySensitivity.tsx',
      'leaseLevelSensitivity.ts',
    ]) {
      const source = sourceOf(relative);
      for (const forbidden of ['.reduce(', 'Math.max(', 'Math.min(', '.filter((', 'sum(']) {
        expect(source, `${relative} aggregates with ${forbidden}`).not.toContain(forbidden);
      }
    }
    // Lease-Level result views exist and are its own.
    expect(sourceOf('underwrite.ts')).toContain("case 'lease_level':");
    expect(sourceOf('underwrite.ts')).toContain("{ id: 'operating-statement', label: 'Operating Statement' }");
  });

  it('the selector is now exactly as wide as the type', () => {
    // The inversion of D5.1B's keystone assertion. The type knew three and the
    // product offered two; now it offers three, because all three work.
    expect(sourceOf('components/DealHeader.tsx')).toContain(
      "const SELECTABLE_MODES: SelectableMode[] = ['quick', 'detailed', 'lease_level'];",
    );
  });

  // The only two additions D5.0 approved: area totals and the sensitivity
  // ladder. These are the exact expressions the area aid evaluates.
  const AREA_CARVE_OUT = /allocatedSf \+ area|rentableAreaSf - allocatedSf/;

  // D5.7. `index + 1` is the one-based position of a candidate field inside an
  // `aria-label` ("Exit Cap Rate candidate value 3"). It is a list position, not
  // a value: it is never submitted, never formatted as money, and never reaches
  // a result cell. Named by literal, and confined below to the one component
  // that renders a list of inputs.
  const POSITION_CARVE_OUT = /\bindex \+ 1\b/;

  it('confines the area carve-out to one display-only function', () => {
    const text = sourceOf('leaseLevelConvert.ts');
    const start = text.indexOf('export function reconcileArea');
    expect(start, 'reconcileArea should exist').toBeGreaterThan(-1);
    const body = text.slice(start);
    const end = body.indexOf('\n}\n');
    // Every area expression the G-M7 filter tolerates lives inside this one
    // function, so the carve-out cannot leak into a component.
    const inside = body.slice(0, end);
    expect(inside).toMatch(AREA_CARVE_OUT);
    for (const relative of [
      'components/RentRollTable.tsx',
      'components/SuiteLeaseEditor.tsx',
      'useLeaseLevelDeal.ts',
    ]) {
      expect(sourceOf(relative), `${relative} sums area itself`).not.toMatch(AREA_CARVE_OUT);
    }
  });

  it('confines the ladder carve-out to one generator module (D5.7)', () => {
    // The D5.0-approved sensitivity ladder. `center + step * offset` is genuine
    // arithmetic, so it is permitted in exactly one module, inside exactly one
    // function, reachable only from the candidate editor.
    const text = sourceOf('leaseLevelSensitivityLadder.ts');
    const start = text.indexOf('export function generateLadderValues');
    expect(start, 'generateLadderValues should exist').toBeGreaterThan(-1);
    expect(text.slice(start)).toContain('center + step * offset');

    // Nothing before the generator computes anything, so the carve-out cannot
    // quietly grow a second resident.
    const preamble = ts.createSourceFile(
      'ladder-preamble.ts',
      text.slice(0, start),
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TS,
    );
    const early: string[] = [];
    walk(preamble, (node) => {
      if (!ts.isBinaryExpression(node)) return;
      const op = node.operatorToken.kind;
      if (
        op === ts.SyntaxKind.AsteriskToken ||
        op === ts.SyntaxKind.SlashToken ||
        op === ts.SyntaxKind.MinusToken ||
        op === ts.SyntaxKind.PlusToken
      ) {
        early.push(node.getText(preamble));
      }
    });
    expect(early, 'the ladder module computes before its generator').toEqual([]);

    // It is a typing aid, not an analysis. Its only import is the shipped
    // display rounding, so it has no result, no request and no metric within
    // reach -- nothing financial to compute even by accident.
    expect(text).toContain("import { formatDisplayNumber } from './convert';");
    expect(text.match(/^import .*$/gm), 'the ladder module imports something else').toHaveLength(1);
    for (const forbidden of ['fetch(', 'metric_values', 'matrix', 'baseline_']) {
      expect(text, `the ladder module reaches ${forbidden}`).not.toContain(forbidden);
    }

    // Only the candidate editor reaches it. A result surface importing the
    // generator would be the first move towards computing a cell.
    for (const relative of [
      'components/LeaseLevelSensitivityWorkspace.tsx',
      'components/LeaseLevelOneWaySensitivity.tsx',
      'components/LeaseLevelTwoWaySensitivity.tsx',
      'components/LeaseLevelResults.tsx',
      'components/LeaseLevelMetricSummary.tsx',
    ]) {
      expect(sourceOf(relative), `${relative} imports the ladder generator`).not.toContain(
        'generateLadderValues',
      );
    }
  });

  it('confines the candidate-position carve-out to the candidate editor (D5.7)', () => {
    // `index + 1` is tolerated by the G-M7 filter below. It is tolerated in one
    // file, for one purpose -- naming an input in a list for assistive
    // technology -- and nowhere near a value.
    expect(sourceOf('components/CandidateValueEditor.tsx')).toMatch(POSITION_CARVE_OUT);
    for (const relative of [
      'components/LeaseLevelSensitivityWorkspace.tsx',
      'components/LeaseLevelOneWaySensitivity.tsx',
      'components/LeaseLevelTwoWaySensitivity.tsx',
      'leaseLevelSensitivity.ts',
    ]) {
      expect(sourceOf(relative), `${relative} uses the position carve-out`).not.toMatch(
        POSITION_CARVE_OUT,
      );
    }
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
      // D5.5B.
      'components/RentRollTable.tsx',
      'components/SuiteLeaseEditor.tsx',
      'leaseLevelIssues.ts',
      // D5.6.
      'components/LeaseLevelResults.tsx',
      'components/LeaseLevelOperatingStatement.tsx',
      'components/LeaseLevelMetricSummary.tsx',
      'leaseLevelFormat.ts',
      // D5.7. The sensitivity surface. The ladder generator is deliberately
      // *not* in this list -- it is the approved carve-out, lives alone in
      // `leaseLevelSensitivityLadder.ts`, and the test above proves that is its
      // only home.
      'components/LeaseLevelSensitivityWorkspace.tsx',
      'components/LeaseLevelOneWaySensitivity.tsx',
      'components/LeaseLevelTwoWaySensitivity.tsx',
      'components/CandidateValueEditor.tsx',
      'leaseLevelSensitivity.ts',
      'leaseLevelSensitivityTypes.ts',
      // D5.8B. It renders two strings; there is nothing for it to compute, and
      // this holds that closed.
      'components/StaleAnalysisNotice.tsx',
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
      // Two carve-outs, both named by literal so neither can widen silently:
      //   * the percent convention (`* 100` / `/ 100`), unchanged since Phase 5
      //     and shared verbatim with Quick and Detailed;
      //   * D5.0's area reconciliation, which adds integers the analyst typed
      //     and is display-only -- it is confined to `reconcileArea`, and the
      //     assertion below proves that function is where it lives.
      const disallowed = offenders.filter(
        (site) =>
          !/\b100\b/.test(site) &&
          !AREA_CARVE_OUT.test(site) &&
          !POSITION_CARVE_OUT.test(site),
      );
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

  it('M8: returning Quick or Detailed result views for Lease-Level is caught', () => {
    // D5.6 transition. The refusal became a list; the mutant it guards against
    // is unchanged -- Lease-Level must not return `views`, which is Quick's
    // array, nor Detailed's `[...views, ...]` extension of it.
    const text = sourceOf('underwrite.ts');
    const arm = text.slice(text.indexOf("case 'lease_level':"));
    const body = arm.slice(0, arm.indexOf('default:'));
    expect(body).not.toContain('return views');
    expect(body).not.toContain('...views');
    expect(body).not.toContain('owner-returns');
    expect(body).toContain("{ id: 'summary', label: 'Summary' }");
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
      'analyze, create, update, the two D5.7 sensitivity runs, the D5.8 AI ' +
        'analysis and the D5.8A fingerprint fetch must each carry the ' +
        'Lease-Level discriminator',
    ).toBe(7);
    for (const forbidden of ["operating_mode: 'quick',\n    terms,\n    ...inputs"]) {
      expect(api, 'a Lease-Level body carries another mode').not.toContain(forbidden);
    }
  });

  it('M14: the AI Analyst cannot be run or left standing without a current analysis', () => {
    // Claims the UI cannot exercise, because the panel's own gate stops the
    // analyst reaching them. They are defence in depth beneath that gate -- and
    // defence in depth that nothing asserts is defence that quietly disappears
    // -- so they are pinned where they live.
    const hook = sourceOf('useLeaseLevelDeal.ts');

    // 1. The generator refuses outright when nothing grounded exists for these
    //    assumptions. D5.8A widened what counts as grounded by one case -- a
    //    report restored from the deal, whose stored fingerprint still matched
    //    it. D5.8B narrows that back by the case D5.8A could not yet see: a
    //    report that is on screen but OUT OF DATE evidences an analysis of
    //    inputs the analyst has since changed, so it evidences nothing about
    //    the inputs a new report would describe. The refusal is one named
    //    predicate now, and the generator consults it before doing anything.
    expect(hook).toContain('if (!canGenerateAiAnalysis) {');
    expect(hook).toContain(
      'results !== null || (aiAnalysis !== null && !isAiAnalysisStale)',
    );

    // 2. An input edit still drops the deterministic result, inside
    //    `resetDownstream` -- the one place downstream state is dropped. That is
    //    what makes claim 1 bite: with `results` gone, an out-of-date report is
    //    the only thing left, and it cannot be regenerated from.
    const reset = hook.slice(
      hook.indexOf('function resetDownstream()'),
      hook.indexOf('function currentProvenance()'),
    );
    expect(reset).toContain('setResults(null);');
    expect(reset).toContain('setAiAnalysisError(null);');
    expect(reset).toContain('setOneWayError(null);');
    expect(reset).toContain('setTwoWayError(null);');

    // 3. **D5.8B: an edit destroys no completed analytical work at all.**
    //
    //    D5.8A protected the persisted snapshot here and dropped this session's
    //    copy. Human review asked for the result to stay visible and be marked
    //    instead, so `resetDownstream` now clears neither -- and this asserts it
    //    clears neither, which is the mutant "stale result deleted" in its most
    //    direct form.
    for (const destructive of [
      'setLiveAiAnalysis',
      'setLiveOneWay',
      'setLiveTwoWay',
      'setRestoredAiAnalysis',
      'setRestoredOneWay',
      'setRestoredTwoWay',
    ]) {
      expect(
        reset,
        `resetDownstream destroys completed analytical work via ${destructive}`,
      ).not.toContain(destructive);
    }

    // 4. Staleness is derived, never stored, so it cannot go out of sync with
    //    the assumptions it describes and cannot survive an exact revert. There
    //    is no mutable flag to set.
    for (const stored of ['setIsStale', 'setIsAiAnalysisStale', 'isStale, set']) {
      expect(hook, `staleness is stored in state (${stored})`).not.toContain(stored);
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

  it('D5.6A M6/M7: deriving the Forward 12 boundary instead of reading it is caught', () => {
    // The forward valuation window is classified by the backend, on each month,
    // and the statement's only job is to render that classification. Two
    // plausible shortcuts would both produce a boundary in the right place on
    // today's fixture and the wrong place the moment the engine changed shape:
    // counting `hold_period * 12` months, or taking the last twelve entries.
    const source = sourceOf('components/LeaseLevelOperatingStatement.tsx');

    expect(source, 'the statement reads the authoritative flag').toContain(
      'is_forward_exit_month',
    );
    // No hold-period arithmetic, and no `12` anywhere: the number of forward
    // months is the backend's business, not a constant this module knows.
    expect(source).not.toContain('hold_period');
    expect(source).not.toMatch(/\* 12|\/ 12|12 \*/);
    // No positional classification.
    expect(source).not.toMatch(/length\s*-\s*12|slice\(-12\)|slice\(-\s*12/);
    // `slice` survives for one purpose only -- trimming the annual debt and
    // capex arrays to the hold years the operating arrays cover -- and both of
    // those start at zero.
    for (const match of source.match(/\.slice\([^)]*\)/g) ?? []) {
      expect(match, `unexpected slice: ${match}`).toBe('.slice(0, holdYears)');
    }
  });

  it('D5.6A M4/M5: manufacturing a monthly debt or capex series is caught', () => {
    // There is no canonical monthly debt service and no canonical monthly
    // capex. The only way to show either monthly is to divide an annual figure
    // by twelve, which is a schedule the loan does not follow.
    const source = sourceOf('components/LeaseLevelOperatingStatement.tsx');

    const monthly = source.slice(
      source.indexOf('function monthlySections'),
      source.indexOf('function annualSections'),
    );
    expect(monthly.length, 'the monthly section builder was not found').toBeGreaterThan(0);
    for (const forbidden of [
      'annual_debt_service',
      'capex_by_year',
      'Debt Service',
      'CapEx Reserve',
      'results.',
    ]) {
      expect(monthly, `the monthly view reaches for ${forbidden}`).not.toContain(forbidden);
    }
    // And the monthly builder takes only the monthly projection, so an annual
    // array is not in scope for it to divide even if someone tried.
    expect(source).toContain('function monthlySections(monthly: MonthlyPropertyProjection)');
  });

  it('D5.6 M21/M22: a Lease-Level change reaching Quick or Detailed output is caught', () => {
    // The behavioural proof that Quick and Detailed results are unchanged is
    // their own suites, which run unedited. This is the structural half: the
    // only way D5.6 could have moved a Quick or Detailed number is by adding a
    // mode branch to a module all three modes render through. There is none.
    //
    // Listed by hand deliberately -- these are the shared rendering modules
    // D5.6 reuses, and a new one joining them should be a conscious addition
    // here rather than something a glob quietly absorbs.
    for (const shared of [
      'format.ts',
      'components/CashFlowTable.tsx',
      'components/ResultsSummaryPanel.tsx',
      'components/OwnerSummaryPanel.tsx',
      'components/SubNav.tsx',
    ]) {
      const source = sourceOf(shared);
      for (const branch of ['lease_level', 'LeaseLevel', 'leaseLevel']) {
        expect(
          source,
          `${shared} branches on ${branch}; Quick and Detailed render through it`,
        ).not.toContain(branch);
      }
    }

    // And the reverse direction: Lease-Level reuses `CashFlowTable` whole
    // rather than forking it, which is what makes the shared module worth
    // keeping branch-free.
    expect(sourceOf('components/LeaseLevelResults.tsx')).toContain(
      "import { CashFlowTable } from './CashFlowTable'",
    );
  });
});
