/**
 * Phase 7 Gate P7.10 Stage 4 -- the memo UI computes nothing, reaches the
 * backend only by the memo's own routes, and ships no AI.
 *
 * The memo workstation is where a "harmless" frontend figure would be most
 * tempting: a price per unit on a cover page, a year-over-year NOI change
 * beside a thesis, a total under a Sources & Uses table, a risk list ranked by
 * severity. Every one of those is the backend's, and several are things Anchor
 * deliberately does not publish at all. So this file parses every Stage 4
 * module and allows exactly the enumerated presentation expressions below.
 *
 * Each rule has a seeded "would see" check, so it cannot pass vacuously.
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

/** Every P7.10 Stage 4 module. Named exactly: a glob would quietly stop
 * covering a module somebody renamed. */
const MEMO_MODULES = [
  'memoTypes.ts',
  'memoCatalog.ts',
  'memoForm.ts',
  'useInvestmentMemo.ts',
  'useMemoLibrary.ts',
  'components/MemoLibraryPanel.tsx',
  'components/MemoWorkspace.tsx',
  'components/MemoDecisionPanel.tsx',
  'components/MemoNarrativePanel.tsx',
  'components/MemoEvidencePanel.tsx',
  'components/MemoEvidencePicker.tsx',
  'components/MemoValuationPanel.tsx',
  'components/MemoPublishPanel.tsx',
  'components/MemoReportView.tsx',
  // Added at the Stage 4 independent review: Correction 2's in-application
  // confirmation and Correction 3's one loading abstraction. Both are Stage 4
  // production modules and are held to every rule below.
  'components/ConfirmDialog.tsx',
  'useAsyncResource.ts',
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

/** Aggregating, ordering-by-value or re-parsing calls: a total, an extreme, an
 * order, or a number rebuilt from text. */
const COMPUTING_CALLS =
  /(^|\.)(reduce|reduceRight|toSorted|min|max|abs|round|floor|ceil)$|^(parseFloat|parseInt|Number)$/;

/**
 * Every expression that computes.
 *
 * String concatenation counts as arithmetic here, exactly as it does in the
 * P7.6 and P7.8B guards: an audit that forbids browser math cannot tell a
 * concatenated sentence from a sum, so the memo modules join text with template
 * literals and `join` instead, and this rule needs no exception carved into it.
 */
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

/**
 * The memo UI's entire permitted computation, enumerated exactly.
 *
 * Three expressions, all in `memoForm.ts`, and none touching a financial value:
 *
 * - `at - 1` / `at + 1` find an item's neighbour when the analyst reorders a
 *   list. They index a list the analyst authored; there is no money in them.
 * - `order.length - 1` asks whether an item is already last, so the Move Down
 *   control is disabled rather than silently doing nothing.
 *
 * They are listed literally rather than matched by pattern, because a pattern
 * broad enough to admit `a - 1` would also admit `price - costs`.
 */
const ALLOWED_COMPUTATION = new Set([
  'at - 1',
  'at + 1',
  'order.length - 1',
  // `ConfirmDialog`'s focus trap: the last focusable control in the dialog, so
  // Tab wraps to the first instead of escaping the modal. A list index, like
  // the three above, and no more financial than they are.
  'focusable.length - 1',
  // A reload counter. `useAsyncResource` and the report preview each bump one
  // to ask for the same key again after a failure or a publication; it names no
  // quantity and is never shown.
  'count + 1',
]);

/** The comparison `sort` uses to restore the analyst's own stored order.
 *
 * Ordering by an authored `display_order` is presentation, not ranking: it puts
 * items back where the analyst left them. Ranking risks by severity or terms by
 * amount would be a judgement they did not make, and is not here. */
const ALLOWED_SORT = 'left.display_order - right.display_order';

describe('P7.10 Stage 4 -- the memo UI computes nothing', () => {
  it.each(MEMO_MODULES)('%s contains no financial arithmetic', (module) => {
    const sites = computationSites(module, sourceOf(module)).filter(
      (site) => !ALLOWED_COMPUTATION.has(site) && site !== ALLOWED_SORT,
    );
    expect(sites).toEqual([]);
  });

  it('would see a total, a ratio and a re-parse', () => {
    // The rule has teeth: a guard widened until everything passed would look
    // exactly like one that finds nothing.
    const seeded = `
      const total = a.price + b.price;
      const perUnit = price / units;
      const worst = Math.min(one, two);
      const parsed = parseFloat(text);
      const ranked = rows.toSorted((l, r) => r.irr - l.irr);
    `;
    const sites = computationSites('seeded.ts', seeded);
    expect(sites).toContain('a.price + b.price');
    expect(sites).toContain('price / units');
    expect(sites).toContain('Math.min');
    expect(sites).toContain('parseFloat(text)');
    expect(sites.some((site) => site.startsWith('rows.toSorted'))).toBe(true);
  });

  it('the allowlist admits only list navigation, never a figure', () => {
    for (const allowed of ALLOWED_COMPUTATION) {
      expect(allowed).toMatch(/^(at|count|order\.length|focusable\.length) [+-] 1$/);
    }
    expect(ALLOWED_SORT).toContain('display_order');
  });
});

describe('P7.10 Stage 4 -- report figures are the backend`s, already formatted', () => {
  it('the report view renders values without formatting them', () => {
    const source = sourceOf('components/MemoReportView.tsx');
    // It prints `metric.value` and the unavailable label; it calls no
    // formatter, because formatting is where a rounding convention could
    // diverge from the exported PDF's.
    expect(source).toContain('metric.value');
    expect(source).not.toContain('formatCurrency');
    expect(source).not.toContain('formatPercent');
    expect(source).not.toContain('toFixed');
    expect(source).not.toContain('toLocaleString');
  });

  it('an unavailable figure prints its label, never a zero', () => {
    const source = sourceOf('components/MemoReportView.tsx');
    expect(source).toContain('memo-metric-unavailable');
    expect(source).toContain('Unavailable');
    for (const fallback of ["?? '$0'", '?? 0', "|| '$0'", "?? '-'"]) {
      expect(source).not.toContain(fallback);
    }
  });

  it('the valuation panel formats through the product`s one helper', () => {
    // The Stage 2 valuation surface carries raw numbers -- it is the engine's
    // surface, not the Stage 4 report package -- so this one panel formats,
    // and it does so through the shared helper rather than a second convention.
    const source = sourceOf('components/MemoValuationPanel.tsx');
    expect(source).toContain("import { formatCurrency } from '../format'");
    expect(source).not.toContain('Intl.NumberFormat');
  });
});

describe('P7.10 Stage 4 -- the two decision acts stay separate (R-F)', () => {
  it('the analyst recommendation and the committee decision use different vocabularies', () => {
    const catalog = sourceOf('memoCatalog.ts');
    expect(catalog).toContain('RECOMMENDATION_LABELS');
    expect(catalog).toContain('COMMITTEE_LABELS');
    // `deferred` is a committee outcome with no analyst counterpart, and
    // `insufficient_information` an analyst recommendation with no committee
    // one, so neither list can stand in for the other.
    const recommendation = catalog.slice(
      catalog.indexOf('RECOMMENDATION_LABELS'),
      catalog.indexOf('RECOMMENDATION_ORDER'),
    );
    const committee = catalog.slice(
      catalog.indexOf('COMMITTEE_LABELS'),
      catalog.indexOf('COMMITTEE_ORDER'),
    );
    expect(recommendation).not.toContain('deferred');
    expect(committee).not.toContain('insufficient_information');
  });

  it('an unrecorded committee decision is not Pending', () => {
    const catalog = sourceOf('memoCatalog.ts');
    expect(catalog).toContain("COMMITTEE_DECISION_UNRECORDED = 'Not yet recorded'");
  });

  it('the decision panel authors the recommendation only', () => {
    // The committee's outcome is recorded against a *published version*, on a
    // surface the draft authoring panel cannot reach.
    const panel = sourceOf('components/MemoDecisionPanel.tsx');
    expect(panel).toContain('ANALYST_RECOMMENDATION_LABEL');
    expect(panel).not.toContain('COMMITTEE_LABELS');
    expect(panel).not.toContain('recordDecision');
  });
});

describe('P7.10 Stage 4 -- evidence is traceable and never verified by Anchor', () => {
  it('a claim with no source is labelled an analyst assertion', () => {
    expect(sourceOf('memoCatalog.ts')).toContain('UNSOURCED_CLAIM_LABEL');
    expect(sourceOf('components/MemoEvidencePicker.tsx')).toContain('UNSOURCED_CLAIM_LABEL');
    expect(sourceOf('components/MemoReportView.tsx')).toContain('UNSOURCED_CLAIM_LABEL');
  });

  it('approval is stated in words rather than by colour alone', () => {
    for (const module of [
      'components/MemoEvidencePicker.tsx',
      'components/MemoEvidencePanel.tsx',
      'components/MemoReportView.tsx',
    ]) {
      const source = sourceOf(module);
      expect(source).toContain('Not approved');
      expect(source).toContain('Approved');
    }
  });

  it('evidence is optional on every claim', () => {
    // Nothing refuses an item for citing nothing: `evidenceIds` starts empty
    // and no validation here requires one.
    const form = sourceOf('memoForm.ts');
    expect(form).toContain('evidenceIds: []');
    expect(form).not.toContain('evidence is required');
  });
});

describe('P7.10 Stage 4 -- publication and export authority', () => {
  it('the PDF link exists only for a published version', () => {
    const publish = sourceOf('components/MemoPublishPanel.tsx');
    expect(publish).toContain('memoPdfUrl(investmentId, version.version_id)');
    // There is no draft download anywhere.
    expect(publish).not.toContain('memoPdfUrl(investmentId, null)');
    for (const module of MEMO_MODULES) {
      expect(sourceOf(module)).not.toContain('draftPdfUrl');
    }
  });

  it('a refusal is grouped into an action and translated, never the raw message', () => {
    // Changed after browser QA at the independent review. This used to require
    // the backend's own sentence on the grounds that a refusal should not be
    // paraphrased; QA showed that sentence naming an Investment, a timepoint
    // and a Unit by their opaque ids, on the surface whose whole job is to tell
    // an analyst what to fix. The refusal's own upstream reason is still shown,
    // so nothing specific was lost -- only the ids were.
    const publish = sourceOf('components/MemoPublishPanel.tsx');
    expect(publish).toContain('refusalGroupOf');
    expect(publish).toContain('publicationRefusalLabel(refusal.code, refusal.unavailable_reason)');
    expect(publish).toContain('refusal.scope_id');
    expect(publish).not.toContain('refusal.message');
  });

  it('readiness comes from the backend rather than a client-side rule', () => {
    const hook = sourceOf('useInvestmentMemo.ts');
    expect(hook).toContain('readPublicationReadiness');
    // No local re-derivation of whether the draft is publishable.
    expect(hook).not.toContain('function isPublishable');
  });

  it('a published version view offers no draft mutation', () => {
    const workspace = sourceOf('components/MemoWorkspace.tsx');
    const publishedBranch = workspace.slice(
      workspace.indexOf('if (openVersionId !== null)'),
      workspace.indexOf('return (\n    <>\n      <header className="deal-header memo-header">'),
    );
    for (const mutation of ['memo.setForm', 'memo.save(', 'MemoNarrativePanel', 'MemoDecisionPanel']) {
      expect(publishedBranch).not.toContain(mutation);
    }
  });
});

describe('P7.10 Stage 4 -- no AI surface', () => {
  it.each(MEMO_MODULES)('%s ships no AI control', (module) => {
    // Measured on the code, not the prose: several modules say plainly in their
    // own comments that Stage 4 ships no AI, and that sentence must not be the
    // thing that fails this guard.
    const code = sourceOf(module)
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/^\s*\/\/.*$/gm, '');
    expect(code).not.toMatch(/\bAI\b/);
    expect(code).not.toMatch(/\bprompt\b/i);
    expect(code).not.toMatch(/\bgrounding\b/i);
    expect(code).not.toMatch(/coming soon/i);
  });

  it('no memo module imports the AI analyst surface', () => {
    for (const module of MEMO_MODULES) {
      expect(sourceOf(module)).not.toContain('AiAnalystPanel');
      expect(sourceOf(module)).not.toContain('aiSnapshot');
    }
  });
});

describe('P7.10 Stage 4 -- reaching the backend', () => {
  it('every memo request goes through the api module', () => {
    for (const module of MEMO_MODULES) {
      const source = sourceOf(module);
      // No component or hook builds its own request.
      expect(source).not.toContain('fetch(');
      expect(source).not.toContain('XMLHttpRequest');
    }
  });

  it('the api client adds the memo routes without touching the frozen ones', () => {
    const api = sourceOf('api.ts');
    for (const route of [
      '/memo-library',
      '/memo/report-preview',
      '/memo/publication-readiness',
      '/memo/publish',
      '/memo-versions',
      '/exports/investment-memo.pdf',
    ]) {
      expect(api).toContain(route);
    }
  });
});

describe('P7.10 Stage 4 -- presentation stays free of implementation vocabulary', () => {
  /** Rendered text: JSX text nodes and string literals, which is what an
   * analyst can actually read. */
  function renderedText(fileName: string, text: string): string[] {
    const source = parse(fileName, text);
    const found: string[] = [];
    walk(source, (node) => {
      if (ts.isJsxText(node)) {
        found.push(node.getText(source));
      }
      if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
        found.push(node.text);
      }
    });
    return found;
  }

  it.each([
    'components/MemoReportView.tsx',
    'components/MemoLibraryPanel.tsx',
    'components/MemoWorkspace.tsx',
    'components/MemoDecisionPanel.tsx',
  ])('%s says nothing about fingerprints or ids', (module) => {
    const text = renderedText(module, sourceOf(module))
      // Class names and element ids are markup, not words on screen.
      .filter((entry) => !/^[a-z-]+( [a-z-]+)*$/.test(entry))
      .join('\n')
      .toLowerCase();
    for (const jargon of ['fingerprint', 'investment_id', 'timepoint_id', 'memo_id', 'sqlite']) {
      expect(text).not.toContain(jargon);
    }
  });

  it('the one place an identity is shown says what it is for', () => {
    // Section 13.3 requires the PDF to carry the version fingerprint, so the
    // on-screen report shows the same code -- once, labelled for a reader who
    // needs to confirm they hold the same package somebody else read.
    const report = sourceOf('components/MemoReportView.tsx');
    expect(report).toContain('Verification code');
    expect(report).toContain('verification_code');
  });
});

describe('P7.10 Stage 4 -- no native browser dialog (Correction 2)', () => {
  /** `confirm`, `alert` and `prompt`, however they are reached: on `window`, on
   * `globalThis`, or bare. */
  const NATIVE_DIALOG = /(^|[^.\w])(window|globalThis)\s*\.\s*(confirm|alert|prompt)\s*\(|(^|[^.\w])(confirm|alert|prompt)\s*\(/;

  it.each(MEMO_MODULES)('%s opens no native dialog', (module) => {
    // Comments are stripped first: `ConfirmDialog` explains at length *why*
    // `confirm()` is gone, and that explanation must not be what fails here.
    const code = sourceOf(module)
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/^\s*\/\/.*$/gm, '');
    expect(code).not.toMatch(NATIVE_DIALOG);
  });

  it('would see each of the three, however it is reached', () => {
    for (const seeded of [
      'if (window.confirm("go?")) { run(); }',
      'globalThis.alert("done");',
      'const name = prompt("name?");',
      'if (confirm("go?")) { run(); }',
    ]) {
      expect(seeded).toMatch(NATIVE_DIALOG);
    }
    // And it is not so broad that any call trips it.
    expect('const answer = await confirmSwitch();').not.toMatch(NATIVE_DIALOG);
    expect('setPendingMemo(entry);').not.toMatch(NATIVE_DIALOG);
  });

  it('the memo flow in App.tsx opens none either', () => {
    // `App.tsx` is a shared file nine gates deep, and older workspaces do use
    // `window.confirm`. This measures the memo functions Stage 4 added, by
    // name, rather than the whole file -- and finds a native dialog in any of
    // them if one ever returns.
    const source = sourceOf('App.tsx');
    const tree = parse('App.tsx', source);
    const memoFunctions: string[] = [];
    walk(tree, (node) => {
      if (ts.isFunctionDeclaration(node) && node.name !== undefined && /Memo/.test(node.name.text)) {
        memoFunctions.push(node.getText(tree));
      }
    });
    expect(memoFunctions.length).toBeGreaterThanOrEqual(4);
    for (const body of memoFunctions) {
      expect(body).not.toMatch(NATIVE_DIALOG);
    }
  });

  it('the confirmation it uses instead is the accessible one', () => {
    const app = sourceOf('App.tsx');
    expect(app).toContain("import { ConfirmDialog } from './components/ConfirmDialog'");
    expect(app).toContain('<ConfirmDialog');

    const dialog = sourceOf('components/ConfirmDialog.tsx');
    // Announced as a modal dialog, labelled and described by its own content.
    expect(dialog).toContain('role="dialog"');
    expect(dialog).toContain('aria-modal="true"');
    expect(dialog).toContain('aria-labelledby');
    expect(dialog).toContain('aria-describedby');
    // Escape cancels, focus is trapped, and the safe action is the focused one.
    expect(dialog).toContain("event.key === 'Escape'");
    expect(dialog).toContain('cancelRef.current?.focus()');
    expect(dialog).toContain('event.preventDefault()');
    // Focus goes back where it came from.
    expect(dialog).toContain('openerRef.current');
  });
});

describe('P7.10 Stage 4 -- one loading abstraction (Correction 3)', () => {
  it('every memo loading flow goes through it', () => {
    for (const module of ['useInvestmentMemo.ts', 'useMemoLibrary.ts', 'components/MemoWorkspace.tsx']) {
      expect(sourceOf(module)).toContain('useAsyncResource');
    }
  });

  it('loading is derived during render, never set from an effect', () => {
    // The lint rule this satisfies is `react(set-state-in-effect)`, and the fix
    // is structural rather than suppressed: nothing sets loading state in an
    // effect, because loading *is* "the settled key is not the asked-for key".
    const hook = sourceOf('useAsyncResource.ts');
    expect(hook).toContain('settled.key !== key');
    expect(hook).not.toContain('setIsLoading');
    expect(hook).not.toContain('eslint-disable');
    expect(hook).not.toContain('oxlint-disable');
  });

  it('a stale response cannot overwrite a newer one', () => {
    // The request-loop fix and the cancellation it replaced are both still
    // here: a resolved promise writes only if it is still the current request.
    const hook = sourceOf('useAsyncResource.ts');
    expect(hook).toContain('cancelled');
  });

  it('no memo module suppresses a lint rule', () => {
    for (const module of MEMO_MODULES) {
      const source = sourceOf(module);
      expect(source).not.toContain('eslint-disable');
      expect(source).not.toContain('oxlint-disable');
      expect(source).not.toContain('@ts-ignore');
      expect(source).not.toContain('@ts-expect-error');
    }
  });
});
