/**
 * Phase 7 Gate P7.6 -- the state of one open visible Investment.
 *
 * A dedicated hook, never `App.tsx` state. It owns the Investment as saved,
 * its member Deals, the one details draft (name, Transaction Price,
 * Investment Business Plan, transaction costs), each Unit's display metadata,
 * adding and removing a Unit, deleting the Investment, and the decision scope
 * its Strategies, Scenarios and Decision Matrix run in.
 *
 * **One draft, one explicit Save Investment.** The four details are replaced
 * together by `PUT /investments/{id}/details`, so no intermediate state is ever
 * committed. Cancel restores what is saved. The draft is dirty when it differs
 * from what is saved; it is *economically* dirty when the Transaction Price, the
 * Investment Business Plan or a transaction cost differs -- a name alone never
 * blocks analysis.
 *
 * **Structure changes are single requests.** Adding a Unit states the
 * resulting Transaction Price in the same request; removing one states it in
 * the same DELETE. Nothing is derived: no price is summed or subtracted here,
 * and a refusal keeps the analyst's draft on screen with the backend's reason.
 * While an add or a removal is open, the membership is about to change, so it
 * blocks analysis and decision edits exactly as unsaved details do.
 *
 * **Display metadata is not economic.** A label, a Unit Kind or an order
 * changes presentation only; the saved economic state token ignores them.
 */

import { useEffect, useMemo, useState } from 'react';
import {
  addInvestmentUnit,
  deleteVisibleInvestment,
  getVisibleInvestment,
  InvestmentApiError,
  listDeals,
  removeInvestmentUnit,
  updateInvestmentUnitDisplay,
  updateVisibleInvestmentDetails,
} from './api';
import type { BusinessPlanDraft } from './businessPlan';
import { FormValidationError, parseWholeNumber } from './convert';
import type { DecisionUnit, InvestmentDecisionScope } from './investmentCatalog';
import { unitNames } from './investmentCatalog';
import {
  blankCostDraft,
  buildDetailsRequest,
  detailsDraftFrom,
  investmentStateToken,
  isDraftChange,
  isEconomicDraftChange,
  parseStatedPrice,
  placeDetailsRefusal,
} from './investmentForm';
import type { InvestmentDetailsDraft, InvestmentDetailsFeedback, TransactionCostDraft } from './investmentForm';
import type { InvestmentIssue, InvestmentUnitMembership, UnitKind, VisibleInvestment } from './investmentTypes';
import type { Deal } from './types';

export interface UseInvestmentWorkspaceOptions {
  investmentId: string;
  /** A new object asks for the Investment and its Deals again -- after the
   * analyst returns from a Unit's underwriting. */
  refreshSignal?: object;
  /** Called after every saved change, so lists elsewhere refresh. */
  onChanged: () => void;
  /** Called once the Investment is deleted. */
  onDeleted: () => void;
}

/** One Unit as the Units workspace shows it: its membership and its Deal. */
export interface InvestmentUnitRow {
  membership: InvestmentUnitMembership;
  deal: Deal | null;
}

export interface UnitDisplayDraft {
  unitId: string;
  label: string;
  kind: UnitKind;
  ordinal: string;
}

export interface AddUnitDraft {
  dealId: string;
  label: string;
  kind: UnitKind;
  price: string;
}

export interface RemovalDraft {
  unitId: string;
  price: string;
}

/** A refusal of one action, in the backend's words: its Investment issues
 * (each naming its Unit) or its one-sentence reasons. */
export interface ActionFeedback {
  message: string;
  issues: InvestmentIssue[];
}

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; investment: VisibleInvestment; deals: Deal[] }
  | { status: 'error'; message: string };

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'The request could not be completed.';
}

function localIssue(message: string): InvestmentIssue {
  return { code: 'incomplete', message, unit_id: null, field: null, source_code: null };
}

/** An action's refusal: the structured Investment issues when the backend
 * sent them, otherwise every reason it gave. */
function actionFeedback(error: unknown, message: string): ActionFeedback {
  if (error instanceof InvestmentApiError) {
    return {
      message,
      issues: error.investmentIssues.length > 0 ? error.investmentIssues : error.reasons.map(localIssue),
    };
  }
  return { message, issues: [localIssue(messageOf(error))] };
}

function parseFailure(error: unknown): ActionFeedback {
  if (!(error instanceof FormValidationError)) {
    throw error;
  }
  return { message: 'Complete the highlighted field.', issues: [localIssue(error.message)] };
}

function load(investmentId: string, setLoad: (state: LoadState) => void): void {
  Promise.all([getVisibleInvestment(investmentId), listDeals()]).then(
    ([investment, deals]) => setLoad({ status: 'ready', investment, deals }),
    (error: unknown) => setLoad({ status: 'error', message: messageOf(error) }),
  );
}

export function useInvestmentWorkspace({
  investmentId,
  refreshSignal,
  onChanged,
  onDeleted,
}: UseInvestmentWorkspaceOptions) {
  const [loaded, setLoad] = useState<LoadState>({ status: 'loading' });
  const [editing, setEditing] = useState<InvestmentDetailsDraft | null>(null);
  const [detailsFeedback, setDetailsFeedback] = useState<InvestmentDetailsFeedback | null>(null);
  const [isSavingDetails, setIsSavingDetails] = useState(false);
  const [unitEdit, setUnitEdit] = useState<UnitDisplayDraft | null>(null);
  const [unitEditFeedback, setUnitEditFeedback] = useState<ActionFeedback | null>(null);
  const [isSavingUnit, setIsSavingUnit] = useState(false);
  const [addUnit, setAddUnit] = useState<AddUnitDraft | null>(null);
  const [addUnitFeedback, setAddUnitFeedback] = useState<ActionFeedback | null>(null);
  const [isAddingUnit, setIsAddingUnit] = useState(false);
  const [removal, setRemoval] = useState<RemovalDraft | null>(null);
  const [removalFeedback, setRemovalFeedback] = useState<ActionFeedback | null>(null);
  const [isRemoving, setIsRemoving] = useState(false);
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    load(investmentId, setLoad);
  }, [investmentId, refreshSignal]);

  const investment = loaded.status === 'ready' ? loaded.investment : null;
  const deals = useMemo(() => (loaded.status === 'ready' ? loaded.deals : []), [loaded]);
  const saved = useMemo(() => (investment === null ? null : detailsDraftFrom(investment)), [investment]);

  const unitRows = useMemo<InvestmentUnitRow[]>(() => {
    if (investment === null) {
      return [];
    }
    const byId = new Map(deals.map((deal) => [deal.id, deal]));
    return investment.units.map((membership) => ({ membership, deal: byId.get(membership.unit_id) ?? null }));
  }, [investment, deals]);

  const unitDeals = useMemo(
    () => unitRows.flatMap((row) => (row.deal === null ? [] : [row.deal])),
    [unitRows],
  );

  const stateToken = useMemo(
    () => (investment === null ? null : investmentStateToken(investment, unitDeals)),
    [investment, unitDeals],
  );

  const scope = useMemo<InvestmentDecisionScope | null>(() => {
    if (investment === null || stateToken === null) {
      return null;
    }
    const units: DecisionUnit[] = unitRows.flatMap((row) =>
      row.deal === null
        ? []
        : [
            {
              unitId: row.membership.unit_id,
              dealName: row.deal.name,
              label: row.membership.label,
              operatingMode: row.deal.operating_mode,
              savedAt: row.deal.updated_at,
            },
          ],
    );
    return { investmentId: investment.id, units, stateToken };
  }, [investment, unitRows, stateToken]);

  const names = useMemo(() => (scope === null ? {} : unitNames(scope.units)), [scope]);

  const isDirty = editing !== null && saved !== null && isDraftChange(editing, saved);
  const isEconomicDirty = editing !== null && saved !== null && isEconomicDraftChange(editing, saved);
  /** Membership is about to change while an add or a removal is open. */
  const isMembershipChanging = addUnit !== null || removal !== null;
  /** Analysis, the Decision Matrix and every Strategy / Scenario change wait. */
  const isEconomicBlocked = isEconomicDirty || isMembershipChanging;

  function applySaved(updated: VisibleInvestment) {
    setLoad((current) => (current.status === 'ready' ? { ...current, investment: updated } : current));
    onChanged();
  }

  function editDraft(update: (draft: InvestmentDetailsDraft) => InvestmentDetailsDraft) {
    setEditing((current) => (current === null ? current : update(current)));
  }

  async function saveDetails() {
    if (editing === null || isSavingDetails) {
      return;
    }
    const built = buildDetailsRequest(editing);
    if ('feedback' in built) {
      setDetailsFeedback(built.feedback);
      return;
    }
    setIsSavingDetails(true);
    setDetailsFeedback(null);
    try {
      const updated = await updateVisibleInvestmentDetails(investmentId, built.request);
      applySaved(updated);
      setEditing(null);
    } catch (error) {
      // The draft keeps every value the analyst typed.
      setDetailsFeedback(
        error instanceof InvestmentApiError
          ? placeDetailsRefusal(error.status, error.investmentIssues, error.planIssues, error.reasons, built)
          : placeDetailsRefusal(0, [], [], [messageOf(error)], built),
      );
    } finally {
      setIsSavingDetails(false);
    }
  }

  async function saveUnitEdit() {
    if (unitEdit === null || isSavingUnit) {
      return;
    }
    let ordinal: number;
    try {
      ordinal = parseWholeNumber('Order', unitEdit.ordinal);
    } catch (error) {
      setUnitEditFeedback(parseFailure(error));
      return;
    }
    setIsSavingUnit(true);
    setUnitEditFeedback(null);
    try {
      const updated = await updateInvestmentUnitDisplay(investmentId, unitEdit.unitId, {
        label: unitEdit.label.trim() === '' ? null : unitEdit.label.trim(),
        unit_kind: unitEdit.kind,
        ordinal,
      });
      applySaved(updated);
      setUnitEdit(null);
    } catch (error) {
      setUnitEditFeedback(actionFeedback(error, 'The unit was not updated.'));
    } finally {
      setIsSavingUnit(false);
    }
  }

  async function submitAddUnit() {
    if (addUnit === null || isAddingUnit) {
      return;
    }
    if (addUnit.dealId === '') {
      setAddUnitFeedback({ message: 'Complete the highlighted field.', issues: [localIssue('Choose a deal.')] });
      return;
    }
    let price: number;
    try {
      price = parseStatedPrice(addUnit.price);
    } catch (error) {
      setAddUnitFeedback(parseFailure(error));
      return;
    }
    setIsAddingUnit(true);
    setAddUnitFeedback(null);
    try {
      const updated = await addInvestmentUnit(investmentId, {
        unit_id: addUnit.dealId,
        label: addUnit.label.trim() === '' ? null : addUnit.label.trim(),
        unit_kind: addUnit.kind,
        transaction_price: price,
      });
      applySaved(updated);
      setAddUnit(null);
    } catch (error) {
      setAddUnitFeedback(actionFeedback(error, 'The unit was not added. The backend refused it:'));
    } finally {
      setIsAddingUnit(false);
    }
  }

  /** ONE request removes the Unit and restates the Transaction Price as the
   * analyst stated it. A refusal leaves the Investment unchanged and keeps the
   * confirmation open with the backend's reason. */
  async function confirmRemoval() {
    if (removal === null || isRemoving) {
      return;
    }
    let price: number;
    try {
      price = parseStatedPrice(removal.price);
    } catch (error) {
      setRemovalFeedback(parseFailure(error));
      return;
    }
    setIsRemoving(true);
    setRemovalFeedback(null);
    try {
      const updated = await removeInvestmentUnit(investmentId, removal.unitId, price);
      applySaved(updated);
      setRemoval(null);
    } catch (error) {
      setRemovalFeedback(actionFeedback(error, 'The unit was not removed. The backend refused it:'));
    } finally {
      setIsRemoving(false);
    }
  }

  async function confirmDelete() {
    if (isDeleting) {
      return;
    }
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await deleteVisibleInvestment(investmentId);
      onDeleted();
    } catch (error) {
      setDeleteError(messageOf(error));
      setIsDeleting(false);
    }
  }

  return {
    investmentId,
    status: loaded.status,
    loadError: loaded.status === 'error' ? loaded.message : null,
    retryLoad: () => {
      setLoad({ status: 'loading' });
      load(investmentId, setLoad);
    },
    investment,
    deals,
    unitRows,
    scope,
    names,
    stateToken,

    // Details
    /** What is saved, as the editor shows it. */
    savedDetails: saved,
    editing,
    isEditing: editing !== null,
    isDirty,
    isEconomicDirty,
    isMembershipChanging,
    isEconomicBlocked,
    detailsFeedback,
    isSavingDetails,
    startEdit: () => {
      if (saved !== null && editing === null) {
        setDetailsFeedback(null);
        setEditing(saved);
      }
    },
    cancelEdit: () => {
      setEditing(null);
      setDetailsFeedback(null);
    },
    setName: (name: string) => editDraft((draft) => ({ ...draft, name })),
    setTransactionPrice: (transactionPrice: string) => editDraft((draft) => ({ ...draft, transactionPrice })),
    setBusinessPlan: (businessPlan: BusinessPlanDraft) => {
      editDraft((draft) => ({ ...draft, businessPlan }));
      setDetailsFeedback((current) => (current === null ? current : { ...current, planIssues: [] }));
    },
    addCost: () => editDraft((draft) => ({ ...draft, costs: [...draft.costs, blankCostDraft()] })),
    updateCost: (costId: string, field: Exclude<keyof TransactionCostDraft, 'costId'>, value: string) =>
      editDraft((draft) => ({
        ...draft,
        costs: draft.costs.map((cost) => (cost.costId === costId ? { ...cost, [field]: value } : cost)),
      })),
    removeCost: (costId: string) =>
      editDraft((draft) => ({ ...draft, costs: draft.costs.filter((cost) => cost.costId !== costId) })),
    saveDetails,

    // Unit display metadata
    unitEdit,
    unitEditFeedback,
    isSavingUnit,
    startUnitEdit: (unitId: string) => {
      const membership = investment?.units.find((unit) => unit.unit_id === unitId);
      if (membership === undefined) {
        return;
      }
      setUnitEditFeedback(null);
      setUnitEdit({
        unitId,
        label: membership.label ?? '',
        kind: membership.unit_kind,
        ordinal: String(membership.ordinal),
      });
    },
    setUnitEdit: (update: Partial<Omit<UnitDisplayDraft, 'unitId'>>) =>
      setUnitEdit((current) => (current === null ? current : { ...current, ...update })),
    cancelUnitEdit: () => {
      setUnitEdit(null);
      setUnitEditFeedback(null);
    },
    saveUnitEdit,

    // Add a Unit
    addUnit,
    addUnitFeedback,
    isAddingUnit,
    openAddUnit: () => {
      setAddUnitFeedback(null);
      setAddUnit({ dealId: '', label: '', kind: 'property', price: '' });
    },
    setAddUnit: (update: Partial<AddUnitDraft>) =>
      setAddUnit((current) => (current === null ? current : { ...current, ...update })),
    cancelAddUnit: () => {
      setAddUnit(null);
      setAddUnitFeedback(null);
    },
    submitAddUnit,

    // Remove a Unit
    removal,
    removalFeedback,
    isRemoving,
    requestRemoval: (unitId: string) => {
      setRemovalFeedback(null);
      setRemoval({ unitId, price: '' });
    },
    setRemovalPrice: (price: string) =>
      setRemoval((current) => (current === null ? current : { ...current, price })),
    cancelRemoval: () => {
      setRemoval(null);
      setRemovalFeedback(null);
    },
    confirmRemoval,

    // Delete the Investment
    isConfirmingDelete,
    isDeleting,
    deleteError,
    requestDelete: () => {
      setDeleteError(null);
      setIsConfirmingDelete(true);
    },
    cancelDelete: () => {
      setIsConfirmingDelete(false);
      setDeleteError(null);
    },
    confirmDelete,
  };
}

export type InvestmentWorkspaceState = ReturnType<typeof useInvestmentWorkspace>;
