/**
 * Phase 7 Gate P7.10 Stage 4 -- the memo draft's one boundary to the wire.
 *
 * The workspace edits a `MemoDraftForm`; this module is the only place that
 * turns one into the `MemoDraftRequest` the API accepts, and the only place
 * that turns a loaded draft back into one. There is no second frontend memo
 * model: every field here exists on the Stage 2 contract, and none is invented.
 *
 * **Nothing here computes.** `display_order` is taken from an item's position
 * in its own list, which `map` supplies -- no index is added to, no list is
 * sorted by a value, and no number is parsed out of analyst text. Reordering
 * moves an element and lets the positions follow.
 *
 * **Identity survives editing (Section 7.4).** An item is its `itemId`. Editing
 * its text, changing its severity, moving it, or re-pointing its sources edits
 * *that* item; it never creates a new one, and a claim's evidence links survive
 * an edit to either side because both ends are stable ids.
 *
 * **Evidence is never required (R-G).** `evidenceIds` may be empty on any item.
 * A claim that cites nothing is a real analyst assertion, labelled as one.
 */

import type {
  AnalystRecommendation,
  EvidenceSourceKind,
  ExecutionComplexity,
  InvestmentMemoDraft,
  MemoDraftRequest,
  MemoEvidenceReference,
  MemoItem,
  MemoRiskItem,
  MemoSectionKind,
  MemoTermItem,
  RiskSeverity,
  SelectedDecision,
  TermPriority,
} from './memoTypes';

/** One authored text item while it is being edited. */
export interface MemoItemForm {
  itemId: string;
  section: MemoSectionKind;
  text: string;
  evidenceIds: string[];
}

export interface MemoRiskForm {
  itemId: string;
  text: string;
  severity: RiskSeverity;
  residualRisk: RiskSeverity;
  mitigant: string;
  evidenceIds: string[];
}

export interface MemoTermForm {
  itemId: string;
  text: string;
  priority: TermPriority;
  evidenceIds: string[];
}

export interface MemoDraftForm {
  preparedBy: string;
  decisionAsk: string;
  analystRecommendation: AnalystRecommendation;
  executiveSummary: string;
  executionComplexity: ExecutionComplexity;
  returnOnTimeNotes: string;
  selectedDecision: SelectedDecision | null;
  items: MemoItemForm[];
  riskItems: MemoRiskForm[];
  termItems: MemoTermForm[];
  evidenceIds: string[];
  selectedValuationTimepointIds: string[];
}

/** A new memo, with nothing assumed.
 *
 * The recommendation starts at `insufficient_information`, which is a real
 * recommendation and the honest one for a memo nobody has written yet: it says
 * the package does not yet support a decision, rather than pre-filling
 * `approve` and inviting an analyst to publish a default they never chose. */
export const EMPTY_MEMO_FORM: MemoDraftForm = {
  preparedBy: '',
  decisionAsk: '',
  analystRecommendation: 'insufficient_information',
  executiveSummary: '',
  executionComplexity: 'not_assessed',
  returnOnTimeNotes: '',
  selectedDecision: null,
  items: [],
  riskItems: [],
  termItems: [],
  evidenceIds: [],
  selectedValuationTimepointIds: [],
};

/** Mints one opaque item id -- a UUID where the browser offers one, otherwise
 * 128 random bits as hex, which `getRandomValues` provides even outside a
 * secure context. The contract asks only for a unique non-empty string. */
export function newMemoItemId(): string {
  const source = globalThis.crypto;
  if (typeof source.randomUUID === 'function') {
    return source.randomUUID();
  }
  const bytes = source.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function textOf(value: string | null): string {
  return value ?? '';
}

/** A loaded draft as editable form state, in the stored display order. */
export function memoFormFromDraft(draft: InvestmentMemoDraft): MemoDraftForm {
  return {
    preparedBy: textOf(draft.prepared_by),
    decisionAsk: draft.decision_ask,
    analystRecommendation: draft.analyst_recommendation,
    executiveSummary: draft.executive_summary,
    executionComplexity: draft.execution_complexity,
    returnOnTimeNotes: draft.return_on_time_notes,
    selectedDecision: draft.selected_decision,
    items: orderedByDisplay(draft.items).map((item) => ({
      itemId: item.item_id,
      section: item.section,
      text: item.text,
      evidenceIds: [...item.evidence_ids],
    })),
    riskItems: orderedByDisplay(draft.risk_items).map((item) => ({
      itemId: item.item_id,
      text: item.text,
      severity: item.severity,
      residualRisk: item.residual_risk,
      mitigant: textOf(item.mitigant),
      evidenceIds: [...item.evidence_ids],
    })),
    termItems: orderedByDisplay(draft.term_items).map((item) => ({
      itemId: item.item_id,
      text: item.text,
      priority: item.priority,
      evidenceIds: [...item.evidence_ids],
    })),
    evidenceIds: [...draft.evidence_ids],
    selectedValuationTimepointIds: [...draft.selected_valuation_timepoint_ids],
  };
}

/** Items in their stored order.
 *
 * `display_order` is the analyst's authored position and `item_id` breaks a tie
 * deterministically. This orders by an authored field, never by a value: no
 * risk is ranked by severity and no term by priority, because the analyst did
 * not ask for that and the stored order is what they meant. */
function orderedByDisplay<T extends { display_order: number; item_id: string }>(
  items: T[],
): T[] {
  return [...items].sort((left, right) =>
    left.display_order === right.display_order
      ? left.item_id.localeCompare(right.item_id)
      : left.display_order - right.display_order,
  );
}

/** Form state as the exact request body the API accepts.
 *
 * `display_order` is each item's position in its own list, supplied by `map`.
 * A blank mitigant is sent as `null` rather than an empty string, because the
 * contract's "there is no mitigant" is an absence and not an empty sentence. */
export function memoRequestFromForm(form: MemoDraftForm): MemoDraftRequest {
  return {
    prepared_by: form.preparedBy.trim() === '' ? null : form.preparedBy,
    decision_ask: form.decisionAsk,
    analyst_recommendation: form.analystRecommendation,
    executive_summary: form.executiveSummary,
    execution_complexity: form.executionComplexity,
    return_on_time_notes: form.returnOnTimeNotes,
    selected_decision: form.selectedDecision,
    items: form.items.map(
      (item, index): MemoItem => ({
        item_id: item.itemId,
        section: item.section,
        display_order: index,
        text: item.text,
        evidence_ids: [...item.evidenceIds],
      }),
    ),
    risk_items: form.riskItems.map(
      (item, index): MemoRiskItem => ({
        item_id: item.itemId,
        display_order: index,
        text: item.text,
        severity: item.severity,
        residual_risk: item.residualRisk,
        mitigant: item.mitigant.trim() === '' ? null : item.mitigant,
        evidence_ids: [...item.evidenceIds],
      }),
    ),
    term_items: form.termItems.map(
      (item, index): MemoTermItem => ({
        item_id: item.itemId,
        display_order: index,
        text: item.text,
        priority: item.priority,
        evidence_ids: [...item.evidenceIds],
      }),
    ),
    evidence_ids: [...form.evidenceIds],
    selected_valuation_timepoint_ids: [...form.selectedValuationTimepointIds],
  };
}

// ---------------------------------------------------------------------------
// Editing
// ---------------------------------------------------------------------------

export function addMemoItem(form: MemoDraftForm, section: MemoSectionKind): MemoDraftForm {
  return {
    ...form,
    items: [...form.items, { itemId: newMemoItemId(), section, text: '', evidenceIds: [] }],
  };
}

export function addMemoRisk(form: MemoDraftForm): MemoDraftForm {
  return {
    ...form,
    riskItems: [
      ...form.riskItems,
      {
        itemId: newMemoItemId(),
        text: '',
        // A new risk is deliberately unassessed rather than "low": severity is
        // the analyst's judgement and nothing derives one for them.
        severity: 'not_assessed',
        residualRisk: 'not_assessed',
        mitigant: '',
        evidenceIds: [],
      },
    ],
  };
}

export function addMemoTerm(form: MemoDraftForm): MemoDraftForm {
  return {
    ...form,
    termItems: [
      ...form.termItems,
      { itemId: newMemoItemId(), text: '', priority: 'desired', evidenceIds: [] },
    ],
  };
}

function replaceAt<T extends { itemId: string }>(items: T[], itemId: string, next: Partial<T>): T[] {
  return items.map((item) => (item.itemId === itemId ? { ...item, ...next } : item));
}

export function updateMemoItem(
  form: MemoDraftForm,
  itemId: string,
  next: Partial<MemoItemForm>,
): MemoDraftForm {
  return { ...form, items: replaceAt(form.items, itemId, next) };
}

export function updateMemoRisk(
  form: MemoDraftForm,
  itemId: string,
  next: Partial<MemoRiskForm>,
): MemoDraftForm {
  return { ...form, riskItems: replaceAt(form.riskItems, itemId, next) };
}

export function updateMemoTerm(
  form: MemoDraftForm,
  itemId: string,
  next: Partial<MemoTermForm>,
): MemoDraftForm {
  return { ...form, termItems: replaceAt(form.termItems, itemId, next) };
}

export function removeMemoItem(form: MemoDraftForm, itemId: string): MemoDraftForm {
  return { ...form, items: form.items.filter((item) => item.itemId !== itemId) };
}

export function removeMemoRisk(form: MemoDraftForm, itemId: string): MemoDraftForm {
  return { ...form, riskItems: form.riskItems.filter((item) => item.itemId !== itemId) };
}

export function removeMemoTerm(form: MemoDraftForm, itemId: string): MemoDraftForm {
  return { ...form, termItems: form.termItems.filter((item) => item.itemId !== itemId) };
}

/** Which way a reorder moves an item. Named rather than a signed offset, so no
 * caller computes a target index. */
export type MoveDirection = 'up' | 'down';

/**
 * One item swapped with its neighbour, within its own section.
 *
 * Reordering is a swap of two elements rather than an index calculation: the
 * pair is found by identity and exchanged, so there is no arithmetic and no way
 * to land outside the list. An item already at the end of its section is
 * returned unchanged, which is what leaves the control correctly disabled.
 */
function moved<T extends { itemId: string }>(
  items: T[],
  itemId: string,
  direction: MoveDirection,
  withinSection: (item: T) => boolean,
): T[] {
  const siblings = items.filter(withinSection);
  const order = siblings.map((item) => item.itemId);
  const at = order.indexOf(itemId);
  if (at < 0) {
    return items;
  }
  const neighbour = direction === 'up' ? order[at - 1] : order[at + 1];
  if (neighbour === undefined) {
    return items;
  }
  return items.map((item) => {
    if (item.itemId === itemId) {
      return siblings.find((sibling) => sibling.itemId === neighbour) as T;
    }
    if (item.itemId === neighbour) {
      return siblings.find((sibling) => sibling.itemId === itemId) as T;
    }
    return item;
  });
}

export function moveMemoItem(
  form: MemoDraftForm,
  itemId: string,
  direction: MoveDirection,
): MemoDraftForm {
  const target = form.items.find((item) => item.itemId === itemId);
  if (target === undefined) {
    return form;
  }
  return {
    ...form,
    items: moved(form.items, itemId, direction, (item) => item.section === target.section),
  };
}

export function moveMemoRisk(
  form: MemoDraftForm,
  itemId: string,
  direction: MoveDirection,
): MemoDraftForm {
  return { ...form, riskItems: moved(form.riskItems, itemId, direction, () => true) };
}

export function moveMemoTerm(
  form: MemoDraftForm,
  itemId: string,
  direction: MoveDirection,
): MemoDraftForm {
  return { ...form, termItems: moved(form.termItems, itemId, direction, () => true) };
}

/** Whether an item can still move in one direction, so the control is disabled
 * rather than silently doing nothing. */
export function canMove(order: string[], itemId: string, direction: MoveDirection): boolean {
  const at = order.indexOf(itemId);
  if (at < 0) {
    return false;
  }
  return direction === 'up' ? at > 0 : at < order.length - 1;
}

/** Attach or detach one source on one claim, preserving authored link order. */
export function toggleEvidenceId(evidenceIds: string[], evidenceId: string): string[] {
  return evidenceIds.includes(evidenceId)
    ? evidenceIds.filter((id) => id !== evidenceId)
    : [...evidenceIds, evidenceId];
}

/** Include or exclude one valuation view. Selection is explicit and stored; it
 * is never inferred from a view's existence, order or recency. */
export function toggleSelectedValuation(form: MemoDraftForm, timepointId: string): MemoDraftForm {
  return {
    ...form,
    selectedValuationTimepointIds: toggleEvidenceId(
      form.selectedValuationTimepointIds,
      timepointId,
    ),
  };
}

/** Whether the form differs from what was last saved.
 *
 * Compared through the request body both sides would produce, so a change that
 * the API would not see -- a reorder that lands where it started -- is not
 * reported as unsaved work. */
export function isMemoFormDirty(form: MemoDraftForm, saved: MemoDraftForm | null): boolean {
  if (saved === null) {
    return JSON.stringify(memoRequestFromForm(form)) !== JSON.stringify(EMPTY_MEMO_REQUEST);
  }
  return JSON.stringify(memoRequestFromForm(form)) !== JSON.stringify(memoRequestFromForm(saved));
}

const EMPTY_MEMO_REQUEST = memoRequestFromForm(EMPTY_MEMO_FORM);

/** A new source, with nothing assumed -- and, in particular, not approved.
 * Approval is an act the analyst performs, never a default a form supplies. */
export function newEvidenceReference(
  investmentId: string,
  displayOrder: number,
): MemoEvidenceReference {
  return {
    evidence_id: newMemoItemId(),
    investment_id: investmentId,
    source_kind: 'case_document' as EvidenceSourceKind,
    title: '',
    reference: '',
    as_of_date: null,
    approved: false,
    display_order: displayOrder,
  };
}
