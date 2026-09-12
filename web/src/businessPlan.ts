/**
 * Phase 6 Gate D6.6 -- the Business Plan as the analyst edits it.
 *
 * One module for all three operating modes. The Business Plan is a
 * mode-agnostic deal contract (conventions §1, §13): Quick, Detailed and
 * Lease-Level each hold one instance of the *same* draft shape, convert it
 * with the *same* functions and send the *same* wire object. There is no
 * per-mode Business Plan here, and nothing below may learn which mode it is
 * serving.
 *
 * **Draft state is not contract state.** While an analyst types, a row may
 * hold a blank description or a half-entered amount -- so the draft holds
 * strings, exactly as every other Anchor form does. `prepareBusinessPlanInput`
 * is the one boundary where a draft becomes the wire contract, and it refuses
 * rather than repairs: a blank is never read as zero and a zero is never read
 * as blank.
 *
 * **It computes no economics.** No total, no bucketing of dollars, no
 * owner-expense year expansion: the backend resolver owns every one of those.
 * The single arithmetic expression in this module is the display-only timing
 * label, `capitalTimingLabel`, which classifies a model month as Closing, a
 * hold year or Post-Hold for the analyst to read and is never submitted.
 *
 * **The backend is authoritative.** The client rules below exist so the
 * analyst is told immediately, and mirror the D6.1 validation authority
 * without extending it. When they disagree, the backend's 422 wins and is
 * mapped back onto the row it names (`placeBusinessPlanApiIssues`).
 */

// =============================================================================
// Wire contract -- mirrors `anchor.business_plan.contracts` and the D6.5 wire
// parser (`anchor.business_plan.parsing`). A saved deal serialises to exactly
// this shape, so a plan read from `GET /deals/{id}` can be sent back unchanged.
// =============================================================================

/** Mirrors `CapitalItemCategory`. Reporting metadata only (conventions §3). */
export type CapitalItemCategory =
  | 'value_add_renovation'
  | 'deferred_maintenance'
  | 'building_systems'
  | 'exterior_common_area'
  | 'other';

/** Mirrors `OwnerExpenseCategory`. Reporting metadata only (conventions §5). */
export type OwnerExpenseCategory = 'asset_management' | 'legal_partnership' | 'other';

/** Mirrors `CapitalPlanItem`. `month` is a model-month index: 0 is closing. */
export interface CapitalPlanItemInput {
  item_id: string;
  description: string;
  category: CapitalItemCategory;
  month: number;
  amount: number;
}

/** Mirrors `OwnerExpenseItem`. `last_year: null` means through the current
 * underwriting hold -- the resolver's reading, never the client's. */
export interface OwnerExpenseItemInput {
  item_id: string;
  description: string;
  category: OwnerExpenseCategory;
  annual_amount: number;
  first_year: number;
  last_year: number | null;
}

/** Mirrors `BusinessPlan`. Both collections empty is `BusinessPlan()`. */
export interface BusinessPlanInput {
  capital_items: CapitalPlanItemInput[];
  owner_expense_items: OwnerExpenseItemInput[];
}

/** A fresh, genuinely empty plan -- a new object every call, so no two
 * requests or forms ever share a collection. */
export function emptyBusinessPlanInput(): BusinessPlanInput {
  return { capital_items: [], owner_expense_items: [] };
}

/** Analyst-facing labels, in the ratified order. The value is the exact enum
 * token the backend persists; the label is presentation only. */
export const CAPITAL_ITEM_CATEGORY_OPTIONS: readonly {
  value: CapitalItemCategory;
  label: string;
}[] = [
  { value: 'value_add_renovation', label: 'Value-Add Renovation' },
  { value: 'deferred_maintenance', label: 'Deferred Maintenance' },
  { value: 'building_systems', label: 'Building Systems' },
  { value: 'exterior_common_area', label: 'Exterior / Common Area' },
  { value: 'other', label: 'Other' },
];

export const OWNER_EXPENSE_CATEGORY_OPTIONS: readonly {
  value: OwnerExpenseCategory;
  label: string;
}[] = [
  { value: 'asset_management', label: 'Asset Management' },
  { value: 'legal_partnership', label: 'Legal / Partnership' },
  { value: 'other', label: 'Other' },
];

function isCapitalItemCategory(value: string): value is CapitalItemCategory {
  return CAPITAL_ITEM_CATEGORY_OPTIONS.some((option) => option.value === value);
}

function isOwnerExpenseCategory(value: string): value is OwnerExpenseCategory {
  return OWNER_EXPENSE_CATEGORY_OPTIONS.some((option) => option.value === value);
}

// =============================================================================
// Draft state
// =============================================================================

/** One Project Capital row as the analyst edits it. */
export interface CapitalItemDraft {
  /** Opaque and stable. Minted once when the row is added, or carried from the
   * saved deal exactly as stored. Never displayed, never edited, never
   * regenerated. */
  readonly itemId: string;
  description: string;
  /** `''` until the analyst chooses -- no category is picked on their behalf. */
  category: CapitalItemCategory | '';
  month: string;
  amount: string;
}

/** One Owner Expense row as the analyst edits it. */
export interface OwnerExpenseItemDraft {
  readonly itemId: string;
  description: string;
  category: OwnerExpenseCategory | '';
  annualAmount: string;
  firstYear: string;
  /** Blank means through the hold. It is sent as `null`, never as the hold
   * period itself, so a later change to the hold extends the expense with it. */
  lastYear: string;
}

export interface BusinessPlanDraft {
  capitalItems: CapitalItemDraft[];
  ownerExpenseItems: OwnerExpenseItemDraft[];
}

export type CapitalItemField = Exclude<keyof CapitalItemDraft, 'itemId'>;
export type OwnerExpenseItemField = Exclude<keyof OwnerExpenseItemDraft, 'itemId'>;

/** The one blank-plan factory every mode starts from. A new object with new
 * arrays on every call: editing one form's plan can never reach another's. */
export function blankBusinessPlanDraft(): BusinessPlanDraft {
  return { capitalItems: [], ownerExpenseItems: [] };
}

// =============================================================================
// Item identity -- one namespace across both collections (conventions §3, D17)
// =============================================================================

/** Mints one opaque item ID. A UUID where the browser offers one; otherwise
 * 128 random bits as hex, which `getRandomValues` provides even outside a
 * secure context. The contract requires only a unique nonempty string -- the
 * UUID syntax is this client's choice, not the contract's. */
export function newBusinessPlanItemId(): string {
  const source = globalThis.crypto;
  if (typeof source.randomUUID === 'function') {
    return source.randomUUID();
  }
  const bytes = source.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** Every item ID in the plan, Project Capital and Owner Expenses together --
 * the single namespace a new ID must be unique within. */
export function businessPlanItemIds(plan: BusinessPlanDraft): Set<string> {
  return new Set([
    ...plan.capitalItems.map((item) => item.itemId),
    ...plan.ownerExpenseItems.map((item) => item.itemId),
  ]);
}

/** A new ID no row in either collection already holds. Loaded IDs are opaque
 * and could be anything, so a freshly minted one is checked rather than
 * assumed unique. */
function unusedItemId(plan: BusinessPlanDraft, generate: () => string): string {
  const taken = businessPlanItemIds(plan);
  let candidate = generate();
  while (candidate === '' || taken.has(candidate)) {
    candidate = generate();
  }
  return candidate;
}

// =============================================================================
// Row operations -- structural only. Each returns a new plan; none mutates.
// =============================================================================

/** Appends one blank Project Capital row. Every field is blank: no sample
 * amount, no default month, no category chosen for the analyst. */
export function addCapitalItem(
  plan: BusinessPlanDraft,
  generate: () => string = newBusinessPlanItemId,
): { plan: BusinessPlanDraft; itemId: string } {
  const itemId = unusedItemId(plan, generate);
  return {
    itemId,
    plan: {
      ...plan,
      capitalItems: [
        ...plan.capitalItems,
        { itemId, description: '', category: '', month: '', amount: '' },
      ],
    },
  };
}

/** Appends one blank Owner Expense row. Last Year starts blank, which is
 * through the hold. */
export function addOwnerExpenseItem(
  plan: BusinessPlanDraft,
  generate: () => string = newBusinessPlanItemId,
): { plan: BusinessPlanDraft; itemId: string } {
  const itemId = unusedItemId(plan, generate);
  return {
    itemId,
    plan: {
      ...plan,
      ownerExpenseItems: [
        ...plan.ownerExpenseItems,
        {
          itemId,
          description: '',
          category: '',
          annualAmount: '',
          firstYear: '',
          lastYear: '',
        },
      ],
    },
  };
}

/** Sets one field of one Project Capital row. The row keeps its ID and its
 * position; `itemId` is not an editable field. */
export function updateCapitalItem(
  plan: BusinessPlanDraft,
  itemId: string,
  field: CapitalItemField,
  value: string,
): BusinessPlanDraft {
  return {
    ...plan,
    capitalItems: plan.capitalItems.map((item) =>
      item.itemId === itemId ? ({ ...item, [field]: value } as CapitalItemDraft) : item,
    ),
  };
}

export function updateOwnerExpenseItem(
  plan: BusinessPlanDraft,
  itemId: string,
  field: OwnerExpenseItemField,
  value: string,
): BusinessPlanDraft {
  return {
    ...plan,
    ownerExpenseItems: plan.ownerExpenseItems.map((item) =>
      item.itemId === itemId ? ({ ...item, [field]: value } as OwnerExpenseItemDraft) : item,
    ),
  };
}

export function removeCapitalItem(plan: BusinessPlanDraft, itemId: string): BusinessPlanDraft {
  return { ...plan, capitalItems: plan.capitalItems.filter((item) => item.itemId !== itemId) };
}

export function removeOwnerExpenseItem(
  plan: BusinessPlanDraft,
  itemId: string,
): BusinessPlanDraft {
  return {
    ...plan,
    ownerExpenseItems: plan.ownerExpenseItems.filter((item) => item.itemId !== itemId),
  };
}

// =============================================================================
// Hydration -- a saved plan into the editor, exactly
// =============================================================================

/**
 * A stored plan as draft rows.
 *
 * Exact by construction: IDs are carried, not minted; rows keep the stored
 * order; `String(number)` is the shortest text that parses back to the same
 * double, so an amount survives open-and-save bit for bit (a display rounding
 * would quietly rewrite an API-created amount on an unrelated save). A null
 * `last_year` becomes a blank Last Year, which is through the hold.
 *
 * `null`/absent is the empty plan -- the same reading the backend gives an
 * absent `business_plan`.
 */
export function businessPlanDraftFromInput(
  plan: BusinessPlanInput | null | undefined,
): BusinessPlanDraft {
  if (plan === null || plan === undefined) {
    return blankBusinessPlanDraft();
  }
  return {
    capitalItems: plan.capital_items.map((item) => ({
      itemId: item.item_id,
      description: item.description,
      category: item.category,
      month: String(item.month),
      amount: String(item.amount),
    })),
    ownerExpenseItems: plan.owner_expense_items.map((item) => ({
      itemId: item.item_id,
      description: item.description,
      category: item.category,
      annualAmount: String(item.annual_amount),
      firstYear: String(item.first_year),
      lastYear: item.last_year === null ? '' : String(item.last_year),
    })),
  };
}

/** Field-by-field equality over what would be submitted, in order. Used by
 * the dirty snapshots -- never `JSON.stringify`, whose key order is an
 * accident of whichever code built the object. */
export function isSameBusinessPlanDraft(a: BusinessPlanDraft, b: BusinessPlanDraft): boolean {
  return (
    a.capitalItems.length === b.capitalItems.length &&
    a.ownerExpenseItems.length === b.ownerExpenseItems.length &&
    a.capitalItems.every((item, index) => {
      const other = b.capitalItems[index];
      return (
        item.itemId === other.itemId &&
        item.description === other.description &&
        item.category === other.category &&
        item.month === other.month &&
        item.amount === other.amount
      );
    }) &&
    a.ownerExpenseItems.every((item, index) => {
      const other = b.ownerExpenseItems[index];
      return (
        item.itemId === other.itemId &&
        item.description === other.description &&
        item.category === other.category &&
        item.annualAmount === other.annualAmount &&
        item.firstYear === other.firstYear &&
        item.lastYear === other.lastYear
      );
    })
  );
}

// =============================================================================
// Validation and serialization -- the one draft-to-contract boundary
// =============================================================================

/** One problem, anchored to the row and field it belongs to.
 *
 * `itemId` is the row; `null` means the issue could not be placed on a row
 * and is shown for its whole subsection (`collection`) or, with `collection`
 * also `null`, for the whole plan. `field: null` on a row is a row-level
 * message. */
export interface BusinessPlanFieldIssue {
  collection: 'capital' | 'owner_expense' | null;
  itemId: string | null;
  field: CapitalItemField | OwnerExpenseItemField | null;
  message: string;
}

type ParsedNumber =
  | { kind: 'blank' }
  | { kind: 'invalid' }
  | { kind: 'number'; value: number };

/** A typed string as a finite number, a blank, or neither. Never defaults a
 * blank to zero. */
function parseDraftNumber(raw: string): ParsedNumber {
  const trimmed = raw.trim();
  if (trimmed === '') {
    return { kind: 'blank' };
  }
  const value = Number(trimmed);
  return Number.isFinite(value) ? { kind: 'number', value } : { kind: 'invalid' };
}

/** Finite and `>= 0`; zero is a valid amount (conventions §3, §18). */
function dollars(
  raw: string,
  label: string,
  report: (message: string) => void,
): number | null {
  const parsed = parseDraftNumber(raw);
  if (parsed.kind === 'blank') {
    report(`Enter ${label === 'Amount' ? 'an amount' : 'an annual amount'}.`);
    return null;
  }
  if (parsed.kind === 'invalid') {
    report(`${label} must be a number.`);
    return null;
  }
  if (parsed.value < 0) {
    report(`${label} must be 0 or greater.`);
    return null;
  }
  return parsed.value;
}

/** An integer at or above `minimum`. Fractional values are refused, never
 * rounded -- the backend refuses `12.5` rather than reading month 12. */
function wholeNumber(
  raw: string,
  label: string,
  minimum: number,
  minimumMessage: string,
  report: (message: string) => void,
): number | null {
  const parsed = parseDraftNumber(raw);
  if (parsed.kind === 'blank') {
    report(`Enter ${label === 'Model Month' ? 'a model month' : 'a first year'}.`);
    return null;
  }
  if (parsed.kind === 'invalid') {
    report(`${label} must be a number.`);
    return null;
  }
  if (!Number.isInteger(parsed.value)) {
    report(`${label} must be a whole number.`);
    return null;
  }
  if (parsed.value < minimum) {
    report(minimumMessage);
    return null;
  }
  return parsed.value;
}

export type BusinessPlanPreparation =
  | { ok: true; plan: BusinessPlanInput }
  | { ok: false; issues: BusinessPlanFieldIssue[] };

/**
 * The draft as the wire contract, or every reason it cannot be one yet.
 *
 * The rules are the D6.1 rules the analyst can break by typing: a nonempty
 * description, a ratified category, an integer month `>= 0`, finite
 * non-negative dollars, an integer First Year `>= 1`, and a Last Year that is
 * blank or an integer on or after First Year. Item IDs are minted uniquely
 * and never typed, so the ID rules are the backend's alone.
 *
 * Nothing is repaired on the way out. The description is sent exactly as
 * typed (a loaded description with surrounding spaces must survive an
 * unrelated save byte for byte); a blank Last Year is sent as `null`; rows
 * are sent in the order they are shown.
 */
export function prepareBusinessPlanInput(draft: BusinessPlanDraft): BusinessPlanPreparation {
  const issues: BusinessPlanFieldIssue[] = [];

  const capitalItems: CapitalPlanItemInput[] = [];
  for (const item of draft.capitalItems) {
    const report =
      (field: CapitalItemField) =>
      (message: string): void => {
        issues.push({ collection: 'capital', itemId: item.itemId, field, message });
      };
    if (item.description.trim() === '') {
      report('description')('Enter a description.');
    }
    const category = item.category;
    if (!isCapitalItemCategory(category)) {
      report('category')('Select a category.');
    }
    const month = wholeNumber(
      item.month,
      'Model Month',
      0,
      'Model Month must be 0 or greater.',
      report('month'),
    );
    const amount = dollars(item.amount, 'Amount', report('amount'));
    if (
      item.description.trim() !== '' &&
      isCapitalItemCategory(category) &&
      month !== null &&
      amount !== null
    ) {
      capitalItems.push({
        item_id: item.itemId,
        description: item.description,
        category,
        month,
        amount,
      });
    }
  }

  const ownerExpenseItems: OwnerExpenseItemInput[] = [];
  for (const item of draft.ownerExpenseItems) {
    const report =
      (field: OwnerExpenseItemField) =>
      (message: string): void => {
        issues.push({ collection: 'owner_expense', itemId: item.itemId, field, message });
      };
    if (item.description.trim() === '') {
      report('description')('Enter a description.');
    }
    const category = item.category;
    if (!isOwnerExpenseCategory(category)) {
      report('category')('Select a category.');
    }
    const annualAmount = dollars(item.annualAmount, 'Annual Amount', report('annualAmount'));
    const firstYear = wholeNumber(
      item.firstYear,
      'First Year',
      1,
      'First Year must be 1 or later.',
      report('firstYear'),
    );
    let lastYear: number | null = null;
    let lastYearValid = true;
    const parsedLast = parseDraftNumber(item.lastYear);
    if (parsedLast.kind === 'invalid') {
      report('lastYear')('Last Year must be a number, or blank for through hold.');
      lastYearValid = false;
    } else if (parsedLast.kind === 'number') {
      if (!Number.isInteger(parsedLast.value)) {
        report('lastYear')('Last Year must be a whole number.');
        lastYearValid = false;
      } else if (firstYear !== null && parsedLast.value < firstYear) {
        report('lastYear')('Last Year must be on or after First Year.');
        lastYearValid = false;
      } else {
        lastYear = parsedLast.value;
      }
    }
    if (
      item.description.trim() !== '' &&
      isOwnerExpenseCategory(category) &&
      annualAmount !== null &&
      firstYear !== null &&
      lastYearValid
    ) {
      ownerExpenseItems.push({
        item_id: item.itemId,
        description: item.description,
        category,
        annual_amount: annualAmount,
        first_year: firstYear,
        last_year: lastYear,
      });
    }
  }

  if (issues.length > 0) {
    return { ok: false, issues };
  }
  return {
    ok: true,
    plan: { capital_items: capitalItems, owner_expense_items: ownerExpenseItems },
  };
}

/** Every client-side issue in the draft, or none. */
export function validateBusinessPlanDraft(draft: BusinessPlanDraft): BusinessPlanFieldIssue[] {
  const prepared = prepareBusinessPlanInput(draft);
  return prepared.ok ? [] : prepared.issues;
}

// =============================================================================
// Backend refusals -- a D6.5 structured 422, placed on its row
// =============================================================================

/** One entry of a D6.5 Business Plan 422: `code`, `path`, `message`, with the
 * path rooted at the request (`business_plan.capital_items[2].month`). */
export interface BusinessPlanApiIssue {
  code: string;
  path: string;
  message: string;
}

/** Whether one 422 detail entry is a Business Plan issue. Structural: it has
 * the shape and a path under `business_plan`, whichever endpoint sent it. */
export function isBusinessPlanApiIssue(entry: unknown): entry is BusinessPlanApiIssue {
  if (typeof entry !== 'object' || entry === null) {
    return false;
  }
  const candidate = entry as Record<string, unknown>;
  return (
    typeof candidate.code === 'string' &&
    typeof candidate.message === 'string' &&
    typeof candidate.path === 'string' &&
    (candidate.path === 'business_plan' || candidate.path.startsWith('business_plan.'))
  );
}

const API_ITEM_PATH = /^business_plan\.(capital_items|owner_expense_items)\[(\d+)\](?:\.([a-z_]+))?$/;

const CAPITAL_WIRE_FIELDS: Readonly<Record<string, CapitalItemField>> = {
  description: 'description',
  category: 'category',
  month: 'month',
  amount: 'amount',
};

const OWNER_EXPENSE_WIRE_FIELDS: Readonly<Record<string, OwnerExpenseItemField>> = {
  description: 'description',
  category: 'category',
  annual_amount: 'annualAmount',
  first_year: 'firstYear',
  last_year: 'lastYear',
};

/**
 * Backend issues, placed on the rows that produced them.
 *
 * A path carries an array index, and an index means nothing against a plan the
 * analyst may have edited since. So it is resolved against `submitted` -- the
 * exact plan the request carried -- whose rows name their `item_id`. An issue
 * naming a row that cannot be found, or naming the plan itself, is kept at
 * subsection or plan level rather than dropped.
 */
export function placeBusinessPlanApiIssues(
  issues: readonly BusinessPlanApiIssue[],
  submitted: BusinessPlanInput,
): BusinessPlanFieldIssue[] {
  return issues.map((issue) => {
    const match = API_ITEM_PATH.exec(issue.path);
    if (match === null) {
      return { collection: null, itemId: null, field: null, message: issue.message };
    }
    const [, collection, indexText, wireField] = match;
    const index = Number(indexText);
    if (collection === 'capital_items') {
      return {
        collection: 'capital',
        itemId: submitted.capital_items[index]?.item_id ?? null,
        field: wireField === undefined ? null : (CAPITAL_WIRE_FIELDS[wireField] ?? null),
        message: issue.message,
      };
    }
    return {
      collection: 'owner_expense',
      itemId: submitted.owner_expense_items[index]?.item_id ?? null,
      field: wireField === undefined ? null : (OWNER_EXPENSE_WIRE_FIELDS[wireField] ?? null),
      message: issue.message,
    };
  });
}

// =============================================================================
// Display-only timing -- never submitted
// =============================================================================

/**
 * What a model month means, for the analyst to read.
 *
 * The ratified convention (conventions §4): month 0 is closing; months
 * `12(y-1)+1 .. 12y` are hold year `y`; a month after `12H` is after the hold.
 * `Math.ceil(month / 12)` is that hold year for every whole month from 1 up,
 * and `year > H` is exactly `month > 12H` for whole numbers.
 *
 * Presentation only. The stored and submitted value is always the month; this
 * label is recomputed from it on every render, so changing the hold period
 * reclassifies the label and never the month. Returns `null` when the month is
 * not yet a valid model month, and names no Post-Hold until the hold period is
 * itself a valid whole number of years.
 */
export function capitalTimingLabel(month: string, holdPeriod: string): string | null {
  const parsedMonth = parseDraftNumber(month);
  if (
    parsedMonth.kind !== 'number' ||
    !Number.isInteger(parsedMonth.value) ||
    parsedMonth.value < 0
  ) {
    return null;
  }
  if (parsedMonth.value === 0) {
    return 'Closing';
  }
  const holdYear = Math.ceil(parsedMonth.value / 12);
  const hold = parseDraftNumber(holdPeriod);
  if (
    hold.kind === 'number' &&
    Number.isInteger(hold.value) &&
    hold.value >= 1 &&
    holdYear > hold.value
  ) {
    return 'Post-Hold';
  }
  return `Year ${holdYear}`;
}
