/**
 * Phase 6 Gate D6.6 -- the Business Plan draft/contract boundary.
 *
 * Pure logic, no rendering: identity, hydration, validation, serialization and
 * the display-only timing label, each against the ratified conventions
 * (docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md §3-§5, §18). The editor and
 * the three modes all route through these functions, so what is pinned here is
 * pinned for Quick, Detailed and Lease-Level at once.
 */

import { describe, expect, it } from 'vitest';
import ts from 'typescript';
import {
  CAPITAL_ITEM_CATEGORY_OPTIONS,
  OWNER_EXPENSE_CATEGORY_OPTIONS,
  addCapitalItem,
  addOwnerExpenseItem,
  blankBusinessPlanDraft,
  businessPlanDraftFromInput,
  businessPlanItemIds,
  capitalTimingLabel,
  emptyBusinessPlanInput,
  isBusinessPlanApiIssue,
  isSameBusinessPlanDraft,
  prepareBusinessPlanInput,
  removeCapitalItem,
  removeOwnerExpenseItem,
  placeBusinessPlanApiIssues,
  updateCapitalItem,
  updateOwnerExpenseItem,
  validateBusinessPlanDraft,
} from './businessPlan';
import type { BusinessPlanDraft, BusinessPlanInput } from './businessPlan';
import { referencePlan } from './businessPlanFixture';
import { withLfLineEndings } from './testSourceText';

const REFERENCE_PLAN: BusinessPlanInput = referencePlan();

function sequence(...ids: string[]): () => string {
  let position = 0;
  return () => {
    const id = ids[position];
    position += 1;
    return id;
  };
}

function prepared(draft: BusinessPlanDraft): BusinessPlanInput {
  const result = prepareBusinessPlanInput(draft);
  if (!result.ok) {
    throw new Error(`expected a valid plan: ${JSON.stringify(result.issues)}`);
  }
  return result.plan;
}

describe('the blank plan', () => {
  it('is empty and holds no fabricated rows or amounts', () => {
    expect(blankBusinessPlanDraft()).toEqual({ capitalItems: [], ownerExpenseItems: [] });
    expect(prepared(blankBusinessPlanDraft())).toEqual({
      capital_items: [],
      owner_expense_items: [],
    });
  });

  it('is a new object with new arrays on every call, so forms never share one', () => {
    const first = blankBusinessPlanDraft();
    const second = blankBusinessPlanDraft();
    expect(first).not.toBe(second);
    expect(first.capitalItems).not.toBe(second.capitalItems);
    expect(first.ownerExpenseItems).not.toBe(second.ownerExpenseItems);
    // Mutating one blank instance can never reach another.
    first.capitalItems.push({ itemId: 'x', description: '', category: '', month: '', amount: '' });
    expect(second.capitalItems).toEqual([]);
    expect(blankBusinessPlanDraft().capitalItems).toEqual([]);
    expect(emptyBusinessPlanInput()).not.toBe(emptyBusinessPlanInput());
  });

  it('serializes to the explicit empty wire shape, never an absent one', () => {
    expect(JSON.stringify(prepared(blankBusinessPlanDraft()))).toBe(
      '{"capital_items":[],"owner_expense_items":[]}',
    );
  });
});

describe('item identity', () => {
  it('mints one ID per new row, with every field blank and economically neutral', () => {
    const { plan, itemId } = addCapitalItem(blankBusinessPlanDraft(), sequence('a1'));
    expect(itemId).toBe('a1');
    expect(plan.capitalItems).toEqual([
      { itemId: 'a1', description: '', category: '', month: '', amount: '' },
    ]);
    const owner = addOwnerExpenseItem(plan, sequence('b1'));
    expect(owner.plan.ownerExpenseItems).toEqual([
      {
        itemId: 'b1',
        description: '',
        category: '',
        annualAmount: '',
        firstYear: '',
        lastYear: '',
      },
    ]);
  });

  it('shares one namespace across Project Capital and Owner Expenses (D17)', () => {
    const withOwner = addOwnerExpenseItem(blankBusinessPlanDraft(), sequence('shared')).plan;
    // The generator offers the ID the owner expense already holds, then a blank,
    // then a fresh one: only the fresh one may be used.
    const added = addCapitalItem(withOwner, sequence('shared', '', 'fresh'));
    expect(added.itemId).toBe('fresh');
    const back = addOwnerExpenseItem(added.plan, sequence('fresh', 'shared', 'third'));
    expect(back.itemId).toBe('third');
    expect(businessPlanItemIds(back.plan)).toEqual(new Set(['shared', 'fresh', 'third']));
  });

  it('never collides with a loaded ID, whatever its syntax', () => {
    const loaded = businessPlanDraftFromInput(REFERENCE_PLAN);
    const added = addCapitalItem(loaded, sequence('cap-roof', 'oe-legal', 'new-1'));
    expect(added.itemId).toBe('new-1');
  });

  it('mints distinct IDs with the real generator across many additions to both collections', () => {
    let plan = blankBusinessPlanDraft();
    for (let round = 0; round < 60; round += 1) {
      plan = addCapitalItem(plan).plan;
      plan = addOwnerExpenseItem(plan).plan;
    }
    const ids = [
      ...plan.capitalItems.map((item) => item.itemId),
      ...plan.ownerExpenseItems.map((item) => item.itemId),
    ];
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.every((id) => id.length > 0)).toBe(true);
  });

  it('keeps the ID and the row position through every edit', () => {
    const loaded = businessPlanDraftFromInput(REFERENCE_PLAN);
    let plan = updateCapitalItem(loaded, 'cap-renovation', 'description', 'Unit Renovation Program');
    plan = updateCapitalItem(plan, 'cap-renovation', 'amount', '1200000');
    plan = updateCapitalItem(plan, 'cap-renovation', 'category', 'other');
    plan = updateOwnerExpenseItem(plan, 'oe-legal', 'lastYear', '');
    expect(plan.capitalItems.map((item) => item.itemId)).toEqual([
      'cap-closing',
      'cap-renovation',
      'cap-roof',
    ]);
    expect(plan.capitalItems[1]).toEqual({
      itemId: 'cap-renovation',
      description: 'Unit Renovation Program',
      category: 'other',
      month: '18',
      amount: '1200000',
    });
    // Edits are immutable: the loaded plan is untouched.
    expect(loaded.capitalItems[1].description).toBe('Unit Renovations');
  });

  it('removes exactly one row and leaves the others, in order, with their IDs', () => {
    const loaded = businessPlanDraftFromInput(REFERENCE_PLAN);
    const plan = removeOwnerExpenseItem(removeCapitalItem(loaded, 'cap-renovation'), 'oe-asset-management');
    expect(plan.capitalItems.map((item) => item.itemId)).toEqual(['cap-closing', 'cap-roof']);
    expect(plan.ownerExpenseItems.map((item) => item.itemId)).toEqual(['oe-legal']);
  });
});

describe('hydration and round trip', () => {
  it('hydrates a stored plan exactly: IDs, order, values and a null Last Year', () => {
    const draft = businessPlanDraftFromInput(REFERENCE_PLAN);
    expect(draft.capitalItems.map((item) => [item.itemId, item.month, item.amount])).toEqual([
      ['cap-closing', '0', '250000'],
      ['cap-renovation', '18', '1000000'],
      ['cap-roof', '61', '500000'],
    ]);
    expect(draft.ownerExpenseItems[0]).toEqual({
      itemId: 'oe-asset-management',
      description: 'Asset Management',
      category: 'asset_management',
      annualAmount: '50000',
      firstYear: '1',
      lastYear: '',
    });
    expect(draft.ownerExpenseItems[1].lastYear).toBe('3');
  });

  it('round-trips the stored plan to the identical contract, byte for byte', () => {
    const plan = prepared(businessPlanDraftFromInput(REFERENCE_PLAN));
    expect(plan).toEqual(REFERENCE_PLAN);
    expect(JSON.stringify(plan)).toBe(JSON.stringify(REFERENCE_PLAN));
  });

  it('keeps an amount no display rounding would survive', () => {
    const awkward: BusinessPlanInput = {
      capital_items: [
        {
          item_id: 'x',
          description: '  Spaced description  ',
          category: 'other',
          month: 7,
          amount: 1234567.8901234567,
        },
      ],
      owner_expense_items: [
        {
          item_id: 'y',
          description: 'Tiny',
          category: 'other',
          annual_amount: 0.1 + 0.2,
          first_year: 1,
          last_year: 1,
        },
      ],
    };
    expect(prepared(businessPlanDraftFromInput(awkward))).toEqual(awkward);
  });

  it('reads an absent or null plan as the empty plan, as the backend does', () => {
    expect(businessPlanDraftFromInput(null)).toEqual(blankBusinessPlanDraft());
    expect(businessPlanDraftFromInput(undefined)).toEqual(blankBusinessPlanDraft());
  });

  it('compares drafts field by field and in order', () => {
    const a = businessPlanDraftFromInput(REFERENCE_PLAN);
    const b = businessPlanDraftFromInput(REFERENCE_PLAN);
    expect(isSameBusinessPlanDraft(a, b)).toBe(true);
    expect(isSameBusinessPlanDraft(a, updateCapitalItem(b, 'cap-roof', 'month', '62'))).toBe(false);
    expect(
      isSameBusinessPlanDraft(a, updateOwnerExpenseItem(b, 'oe-legal', 'lastYear', '')),
    ).toBe(false);
    expect(
      isSameBusinessPlanDraft(a, { ...b, capitalItems: [...b.capitalItems].reverse() }),
    ).toBe(false);
  });
});

describe('serialization', () => {
  it('sends closing capital as month 0, never as a word', () => {
    const plan = prepared(businessPlanDraftFromInput(REFERENCE_PLAN));
    expect(plan.capital_items[0].month).toBe(0);
    expect(JSON.stringify(plan)).toContain('"month":0');
    // Every month travels as a JSON number -- never as a label or a string.
    expect(JSON.stringify(plan)).not.toContain('"month":"');
    expect(plan.capital_items.every((item) => typeof item.month === 'number')).toBe(true);
  });

  it('sends a blank Last Year as null, and never as the hold period', () => {
    let draft = addOwnerExpenseItem(blankBusinessPlanDraft(), sequence('o')).plan;
    draft = updateOwnerExpenseItem(draft, 'o', 'description', 'Asset Management');
    draft = updateOwnerExpenseItem(draft, 'o', 'category', 'asset_management');
    draft = updateOwnerExpenseItem(draft, 'o', 'annualAmount', '50000');
    draft = updateOwnerExpenseItem(draft, 'o', 'firstYear', '2');
    const plan = prepared(draft);
    expect(plan.owner_expense_items[0].last_year).toBeNull();
    expect(JSON.stringify(plan)).toContain('"last_year":null');
    // The serializer has no access to the hold period at all.
    expect(prepareBusinessPlanInput.length).toBe(1);
  });

  it('keeps zero as zero -- a real amount, distinct from blank', () => {
    let draft = addCapitalItem(blankBusinessPlanDraft(), sequence('c')).plan;
    draft = updateCapitalItem(draft, 'c', 'description', 'Contingent scope');
    draft = updateCapitalItem(draft, 'c', 'category', 'other');
    draft = updateCapitalItem(draft, 'c', 'month', '12');
    draft = updateCapitalItem(draft, 'c', 'amount', '0');
    draft = addOwnerExpenseItem(draft, sequence('o')).plan;
    draft = updateOwnerExpenseItem(draft, 'o', 'description', 'Waived fee');
    draft = updateOwnerExpenseItem(draft, 'o', 'category', 'other');
    draft = updateOwnerExpenseItem(draft, 'o', 'annualAmount', '0');
    draft = updateOwnerExpenseItem(draft, 'o', 'firstYear', '1');
    const plan = prepared(draft);
    expect(plan.capital_items[0].amount).toBe(0);
    expect(plan.owner_expense_items[0].annual_amount).toBe(0);

    const blankAmount = updateCapitalItem(draft, 'c', 'amount', '');
    expect(validateBusinessPlanDraft(blankAmount)).toEqual([
      { collection: 'capital', itemId: 'c', field: 'amount', message: 'Enter an amount.' },
    ]);
  });

  it('sends rows in the order they are shown', () => {
    const draft = businessPlanDraftFromInput(REFERENCE_PLAN);
    const reordered = { ...draft, capitalItems: [...draft.capitalItems].reverse() };
    expect(prepared(reordered).capital_items.map((item) => item.item_id)).toEqual([
      'cap-roof',
      'cap-renovation',
      'cap-closing',
    ]);
  });

  it('offers exactly the ratified categories, labelled, and persists the enum token', () => {
    expect(CAPITAL_ITEM_CATEGORY_OPTIONS).toEqual([
      { value: 'value_add_renovation', label: 'Value-Add Renovation' },
      { value: 'deferred_maintenance', label: 'Deferred Maintenance' },
      { value: 'building_systems', label: 'Building Systems' },
      { value: 'exterior_common_area', label: 'Exterior / Common Area' },
      { value: 'other', label: 'Other' },
    ]);
    expect(OWNER_EXPENSE_CATEGORY_OPTIONS).toEqual([
      { value: 'asset_management', label: 'Asset Management' },
      { value: 'legal_partnership', label: 'Legal / Partnership' },
      { value: 'other', label: 'Other' },
    ]);
  });
});

describe('client validation (PART AN)', () => {
  function capitalRow(overrides: Partial<Record<'description' | 'category' | 'month' | 'amount', string>>) {
    let draft = addCapitalItem(blankBusinessPlanDraft(), sequence('c')).plan;
    const values = { description: 'Roof', category: 'building_systems', month: '12', amount: '1000', ...overrides };
    for (const [field, value] of Object.entries(values)) {
      draft = updateCapitalItem(draft, 'c', field as 'description', value);
    }
    return draft;
  }

  function ownerRow(
    overrides: Partial<Record<'description' | 'category' | 'annualAmount' | 'firstYear' | 'lastYear', string>>,
  ) {
    let draft = addOwnerExpenseItem(blankBusinessPlanDraft(), sequence('o')).plan;
    const values = {
      description: 'Asset Management',
      category: 'asset_management',
      annualAmount: '50000',
      firstYear: '1',
      lastYear: '',
      ...overrides,
    };
    for (const [field, value] of Object.entries(values)) {
      draft = updateOwnerExpenseItem(draft, 'o', field as 'description', value);
    }
    return draft;
  }

  const messages = (draft: BusinessPlanDraft) =>
    validateBusinessPlanDraft(draft).map((issue) => [issue.itemId, issue.field, issue.message]);

  it.each([
    [{ description: '   ' }, 'description', 'Enter a description.'],
    [{ category: '' }, 'category', 'Select a category.'],
    [{ category: 'contingency' }, 'category', 'Select a category.'],
    [{ amount: '-1' }, 'amount', 'Amount must be 0 or greater.'],
    [{ amount: 'abc' }, 'amount', 'Amount must be a number.'],
    [{ amount: '' }, 'amount', 'Enter an amount.'],
    [{ month: '1.5' }, 'month', 'Model Month must be a whole number.'],
    [{ month: '-1' }, 'month', 'Model Month must be 0 or greater.'],
    [{ month: '' }, 'month', 'Enter a model month.'],
  ])('Project Capital %j is refused on %s', (overrides, field, message) => {
    expect(messages(capitalRow(overrides))).toEqual([['c', field, message]]);
    expect(prepareBusinessPlanInput(capitalRow(overrides)).ok).toBe(false);
  });

  it.each([
    [{ description: '' }, 'description', 'Enter a description.'],
    [{ annualAmount: '-5' }, 'annualAmount', 'Annual Amount must be 0 or greater.'],
    [{ firstYear: '0' }, 'firstYear', 'First Year must be 1 or later.'],
    [{ firstYear: '1.5' }, 'firstYear', 'First Year must be a whole number.'],
    [{ firstYear: '' }, 'firstYear', 'Enter a first year.'],
    [{ firstYear: '3', lastYear: '2' }, 'lastYear', 'Last Year must be on or after First Year.'],
    [{ lastYear: '2.5' }, 'lastYear', 'Last Year must be a whole number.'],
  ])('Owner Expense %j is refused on %s', (overrides, field, message) => {
    expect(messages(ownerRow(overrides))).toEqual([['o', field, message]]);
  });

  it('accepts the boundary values the backend accepts', () => {
    expect(validateBusinessPlanDraft(capitalRow({ month: '0', amount: '0' }))).toEqual([]);
    expect(validateBusinessPlanDraft(ownerRow({ firstYear: '1', lastYear: '1' }))).toEqual([]);
    // Owner-expense years beyond the hold are valid (conventions §5, §18).
    expect(validateBusinessPlanDraft(ownerRow({ firstYear: '7', lastYear: '10' }))).toEqual([]);
  });

  it('reports every problem on a row at once, and never changes the draft', () => {
    const draft = capitalRow({ description: '', month: '-2', amount: '-3' });
    const before = JSON.stringify(draft);
    expect(messages(draft).map(([, field]) => field)).toEqual(['description', 'month', 'amount']);
    expect(JSON.stringify(draft)).toBe(before);
  });
});

describe('backend 422 placement', () => {
  it('places each issue on the row the submitted plan named, by item ID', () => {
    const submitted = REFERENCE_PLAN;
    const issues = placeBusinessPlanApiIssues(
      [
        { code: 'AMOUNT_OUT_OF_DOMAIN', path: 'business_plan.capital_items[1].amount', message: 'bad amount' },
        { code: 'LAST_YEAR_BEFORE_FIRST_YEAR', path: 'business_plan.owner_expense_items[1].last_year', message: 'bad year' },
        { code: 'DUPLICATE_ITEM_ID', path: 'business_plan.capital_items[2].item_id', message: 'dup' },
        { code: 'MALFORMED_FIELD', path: 'business_plan', message: 'not an object' },
        { code: 'MALFORMED_FIELD', path: 'business_plan.capital_items[9].month', message: 'gone' },
      ],
      submitted,
    );
    expect(issues).toEqual([
      { collection: 'capital', itemId: 'cap-renovation', field: 'amount', message: 'bad amount' },
      { collection: 'owner_expense', itemId: 'oe-legal', field: 'lastYear', message: 'bad year' },
      { collection: 'capital', itemId: 'cap-roof', field: null, message: 'dup' },
      { collection: null, itemId: null, field: null, message: 'not an object' },
      { collection: 'capital', itemId: null, field: 'month', message: 'gone' },
    ]);
  });

  it('recognises a Business Plan issue by its shape and path, and nothing else', () => {
    expect(isBusinessPlanApiIssue({ code: 'X', path: 'business_plan.capital_items[0].month', message: 'm' })).toBe(true);
    expect(isBusinessPlanApiIssue({ code: 'X', path: 'business_plan', message: 'm' })).toBe(true);
    expect(isBusinessPlanApiIssue({ code: 'X', path: 'suites[0].suite_id', message: 'm', severity: 'error' })).toBe(false);
    expect(isBusinessPlanApiIssue({ field_id: 'ltv', category: 'c', message: 'm' })).toBe(false);
    expect(isBusinessPlanApiIssue({ code: 'X', path: 'business_planner', message: 'm' })).toBe(false);
    expect(isBusinessPlanApiIssue(null)).toBe(false);
  });
});

describe('the display-only timing label (PART G, AJ, AK)', () => {
  /** The ratified formula, written independently of the implementation:
   * hold year = ((month - 1) // 12) + 1, and month > 12H is post-hold. */
  function ratified(month: number, hold: number): string {
    if (month === 0) return 'Closing';
    if (month > 12 * hold) return 'Post-Hold';
    return `Year ${Math.floor((month - 1) / 12) + 1}`;
  }

  it('matches the ratified bucketing at every month and hold', () => {
    for (let hold = 1; hold <= 15; hold += 1) {
      for (let month = 0; month <= 240; month += 1) {
        expect(capitalTimingLabel(String(month), String(hold)), `${month}/${hold}`).toBe(
          ratified(month, hold),
        );
      }
    }
  });

  it('names the reference months: 0 Closing, 18 Year 2, 61 Post-Hold on a five-year hold', () => {
    expect(capitalTimingLabel('0', '5')).toBe('Closing');
    expect(capitalTimingLabel('1', '5')).toBe('Year 1');
    expect(capitalTimingLabel('12', '5')).toBe('Year 1');
    expect(capitalTimingLabel('13', '5')).toBe('Year 2');
    expect(capitalTimingLabel('18', '5')).toBe('Year 2');
    expect(capitalTimingLabel('60', '5')).toBe('Year 5');
    expect(capitalTimingLabel('61', '5')).toBe('Post-Hold');
  });

  it('reclassifies with the hold period and leaves the month itself alone', () => {
    const draft = businessPlanDraftFromInput(REFERENCE_PLAN);
    expect(capitalTimingLabel(draft.capitalItems[2].month, '5')).toBe('Post-Hold');
    expect(capitalTimingLabel(draft.capitalItems[2].month, '6')).toBe('Year 6');
    expect(draft.capitalItems[2].month).toBe('61');
    expect(prepared(draft).capital_items[2].month).toBe(61);
  });

  it('claims nothing until both the month and the hold are valid', () => {
    expect(capitalTimingLabel('', '5')).toBeNull();
    expect(capitalTimingLabel('1.5', '5')).toBeNull();
    expect(capitalTimingLabel('-1', '5')).toBeNull();
    expect(capitalTimingLabel('61', '')).toBe('Year 6');
    expect(capitalTimingLabel('61', '5.5')).toBe('Year 6');
  });
});

// =============================================================================
// Structural guards
// =============================================================================

const SOURCES = Object.fromEntries(
  Object.entries(
    import.meta.glob('./**/*.{ts,tsx}', { query: '?raw', eager: true, import: 'default' }) as Record<
      string,
      string
    >,
  ).map(([path, text]) => [path, withLfLineEndings(text)]),
) as Record<string, string>;

const PLAN_MODULES = [
  './businessPlan.ts',
  './useBusinessPlan.ts',
  './components/BusinessPlanEditor.tsx',
];

function arithmeticSites(relative: string, text: string): string[] {
  const source = ts.createSourceFile(
    relative,
    text,
    ts.ScriptTarget.Latest,
    true,
    relative.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const sites: string[] = [];
  const visit = (node: ts.Node): void => {
    if (ts.isBinaryExpression(node)) {
      const op = node.operatorToken.kind;
      if (
        op === ts.SyntaxKind.PlusToken ||
        op === ts.SyntaxKind.MinusToken ||
        op === ts.SyntaxKind.AsteriskToken ||
        op === ts.SyntaxKind.SlashToken
      ) {
        sites.push(node.getText(source));
      }
    }
    node.forEachChild(visit);
  };
  visit(source);
  return sites;
}

describe('the frontend computes no Business Plan economics', () => {
  it('has exactly one arithmetic expression: the display-only month-to-year label', () => {
    const sites = PLAN_MODULES.flatMap((path) => arithmeticSites(path, SOURCES[path]));
    expect(sites).toEqual(['parsedMonth.value / 12']);
    const text = SOURCES['./businessPlan.ts'];
    const label = text.slice(text.indexOf('export function capitalTimingLabel'));
    expect(label).toContain('parsedMonth.value / 12');
  });

  it('aggregates nothing and names no resolver or result vocabulary', () => {
    for (const path of PLAN_MODULES) {
      const text = SOURCES[path];
      for (const forbidden of [
        '.reduce(',
        'OwnerCapitalSchedule',
        'resolve_business_plan',
        'post_hold_project_capital',
        'total_equity_invested',
        'Total Project Capital',
      ]) {
        expect(text, `${path} contains ${forbidden}`).not.toContain(forbidden);
      }
      expect(text.toLowerCase(), `${path} says capital call`).not.toContain('capital call');
    }
  });

  it('mints item IDs in exactly one place', () => {
    const minting = Object.entries(SOURCES)
      .filter(([path]) => !/\.test\.tsx?$/.test(path))
      .filter(([, text]) => text.includes('randomUUID') || text.includes('getRandomValues'))
      .map(([path]) => path);
    expect(minting).toEqual(['./businessPlan.ts']);
  });

  it('shows the analyst no contract or developer vocabulary', () => {
    const text = SOURCES['./components/BusinessPlanEditor.tsx'];
    const source = ts.createSourceFile('editor.tsx', text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const visible: string[] = [];
    const visit = (node: ts.Node): void => {
      if (ts.isJsxText(node)) visible.push(node.getText(source));
      if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) visible.push(node.text);
      if (ts.isTemplateExpression(node)) visible.push(node.getText(source));
      node.forEachChild(visit);
    };
    visit(source);
    const copy = visible.join(' ');
    for (const forbidden of [
      'OwnerCapitalSchedule',
      'CapitalPlanItem',
      'OwnerExpenseItem',
      'post_hold',
      'NAER',
      'item_id',
      'Capital Call',
    ]) {
      expect(copy, `the editor shows ${forbidden}`).not.toContain(forbidden);
    }
    for (const required of [
      'Business Plan',
      'Project Capital',
      'Owner Expenses',
      'Description',
      'Category',
      'Model Month',
      'Amount',
      'Annual Amount',
      'First Year',
      'Last Year',
      'Through Hold',
      '0 = Closing',
    ]) {
      expect(copy, `the editor never says ${required}`).toContain(required);
    }
  });
});
