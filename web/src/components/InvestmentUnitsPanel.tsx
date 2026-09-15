/**
 * Phase 7 Gate P7.6 -- the Units of a visible Investment.
 *
 * Every member Deal, in presentation order: its name, its operating mode, the
 * Investment's label and Unit Kind for it, and its own stored purchase price
 * and hold (read off its contract, never totalled). Open Underwriting opens the
 * existing Deal workspace: the Investment owns structure, the Deal owns
 * underwriting, and no underwriting form is repeated here.
 *
 * **Display metadata** (label, Unit Kind, order) is edited in place and is
 * never economic.
 *
 * **Structure changes are one request each.** Add Unit and Remove Unit each ask
 * the analyst to state the Investment's resulting Transaction Price, sent in
 * the same request; nothing is added or subtracted for them. A refusal -- the
 * price does not reconcile, the hold or Lease-Level calendar differs, a Strategy
 * or Scenario still addresses the Unit -- is shown in the backend's words with
 * the Unit named, and the draft stays open. The last Unit cannot be removed.
 */

import { useEffect, useRef } from 'react';
import { formatCurrency } from '../format';
import {
  LAST_UNIT_MESSAGE,
  REMOVE_UNIT_CONSEQUENCES,
  storedHoldPeriod,
  storedPurchasePrice,
  UNIT_KIND_NOTE,
  UNIT_KIND_OPTIONS,
  UNIT_UNDERWRITING_NOTE,
  unitKindLabel,
} from '../investmentCatalog';
import { RESULTING_PRICE_LABEL } from '../investmentForm';
import type { UnitKind, VisibleInvestment } from '../investmentTypes';
import { operatingModeLabel } from '../operatingMode';
import type { Deal } from '../types';
import type { InvestmentWorkspaceState } from '../useInvestmentWorkspace';
import { InvestmentIssueList } from './InvestmentIssueList';
import { NumericInput } from './NumericInput';

export interface InvestmentUnitsPanelProps {
  workspace: InvestmentWorkspaceState;
  /** Every visible Investment, to say which Deals already belong to one. */
  investments: VisibleInvestment[];
  onOpenUnit: (deal: Deal) => void;
}

function holdText(hold: number | null): string {
  return hold === null ? 'N/A' : `${hold} yrs`;
}

const SAVE_FIRST_MESSAGE = 'Save or cancel the Investment changes before adding or removing a Unit.';

export function InvestmentUnitsPanel({ workspace, investments, onOpenUnit }: InvestmentUnitsPanelProps) {
  const investment = workspace.investment;
  const removalCancel = useRef<HTMLButtonElement>(null);
  const removalUnit = workspace.removal?.unitId ?? null;

  useEffect(() => {
    if (removalUnit !== null) {
      removalCancel.current?.focus();
    }
  }, [removalUnit]);

  if (investment === null) {
    return null;
  }
  // A refusal may quote any Deal -- a candidate Unit included -- by id. Each is
  // named: a member by its Unit name, any other Deal by its own name.
  const names = { ...Object.fromEntries(workspace.deals.map((deal) => [deal.id, deal.name])), ...workspace.names };
  const memberIds = new Set(investment.units.map((unit) => unit.unit_id));
  const candidates = workspace.deals.filter((deal) => !memberIds.has(deal.id));
  const otherInvestment = (dealId: string) =>
    investments.find(
      (candidate) => candidate.id !== investment.id && candidate.units.some((unit) => unit.unit_id === dealId),
    );
  const isLastUnit = investment.units.length === 1;
  const structureLocked = workspace.isDirty;
  const structureBusy = workspace.addUnit !== null || workspace.removal !== null;

  return (
    <div className="investment-units">
      <section className="scenario-panel investment-section" aria-labelledby="investment-units-title">
        <div className="scenario-panel-header">
          <div className="scenario-panel-heading">
            <h3 id="investment-units-title" className="scenario-panel-title">
              Units
            </h3>
            <p className="scenario-panel-subtitle">{UNIT_UNDERWRITING_NOTE}</p>
          </div>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={workspace.openAddUnit}
            disabled={structureLocked || structureBusy}
            aria-describedby={structureLocked ? 'investment-units-locked' : undefined}
          >
            Add Unit
          </button>
        </div>

        {structureLocked && (
          <p id="investment-units-locked" className="scenario-blocked" role="status">
            {SAVE_FIRST_MESSAGE}
          </p>
        )}

        <div className="investment-table-scroll" role="region" aria-label="Units table" tabIndex={0}>
          <table className="investment-table investment-units-table">
            <caption className="visually-hidden">The Investment&apos;s Units</caption>
            <thead>
              <tr>
                <th scope="col">Unit</th>
                <th scope="col">Mode</th>
                <th scope="col">Unit Kind</th>
                <th scope="col" className="investment-num">
                  Purchase Price
                </th>
                <th scope="col" className="investment-num">
                  Hold
                </th>
                <th scope="col" className="investment-num">
                  Order
                </th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            {workspace.unitRows.map((row) => {
              const unitId = row.membership.unit_id;
              const dealName = row.deal?.name ?? unitId;
              const isEditing = workspace.unitEdit?.unitId === unitId;
              const isRemoving = workspace.removal?.unitId === unitId;
              return (
                <tbody key={unitId} className="investment-unit-group">
                  <tr>
                    <th scope="row" className="investment-name-cell">
                      <span className="investment-unit-name">{dealName}</span>
                      {row.membership.label !== null && (
                        <span className="investment-row-note">{row.membership.label}</span>
                      )}
                    </th>
                    <td>{row.deal === null ? 'N/A' : operatingModeLabel(row.deal.operating_mode)}</td>
                    <td>{unitKindLabel(row.membership.unit_kind)}</td>
                    <td className="investment-num">
                      {formatCurrency(row.deal === null ? null : storedPurchasePrice(row.deal))}
                    </td>
                    <td className="investment-num">{holdText(row.deal === null ? null : storedHoldPeriod(row.deal))}</td>
                    <td className="investment-num">{row.membership.ordinal}</td>
                    <td className="investment-actions-cell">
                      <div className="investment-row-actions">
                        <button
                          type="button"
                          className="btn btn-secondary btn-xs"
                          onClick={() => {
                            if (row.deal !== null) {
                              onOpenUnit(row.deal);
                            }
                          }}
                          disabled={row.deal === null}
                          aria-label={`Open underwriting for ${dealName}`}
                        >
                          Open Underwriting
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-xs"
                          onClick={() => workspace.startUnitEdit(unitId)}
                          disabled={workspace.unitEdit !== null}
                          aria-expanded={isEditing}
                          aria-label={`Edit label, kind and order of ${dealName}`}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-xs"
                          onClick={() => workspace.requestRemoval(unitId)}
                          disabled={isLastUnit || structureLocked || structureBusy}
                          title={isLastUnit ? LAST_UNIT_MESSAGE : undefined}
                          aria-label={`Remove ${dealName}`}
                        >
                          Remove
                        </button>
                      </div>
                    </td>
                  </tr>
                  {isEditing && workspace.unitEdit !== null && (
                    <tr className="investment-subrow">
                      <td colSpan={7}>
                        <div className="investment-inline-form" role="group" aria-label={`Display settings for ${dealName}`}>
                          <div className="field">
                            <label className="field-label" htmlFor={`investment-unit-${unitId}-label`}>
                              Label (optional)
                            </label>
                            <input
                              id={`investment-unit-${unitId}-label`}
                              className="field-input"
                              type="text"
                              value={workspace.unitEdit.label}
                              onChange={(event) => workspace.setUnitEdit({ label: event.target.value })}
                              disabled={workspace.isSavingUnit}
                              autoComplete="off"
                            />
                          </div>
                          <div className="field">
                            <label className="field-label" htmlFor={`investment-unit-${unitId}-kind`}>
                              Unit Kind
                            </label>
                            <select
                              id={`investment-unit-${unitId}-kind`}
                              className="field-input"
                              value={workspace.unitEdit.kind}
                              onChange={(event) => workspace.setUnitEdit({ kind: event.target.value as UnitKind })}
                              disabled={workspace.isSavingUnit}
                            >
                              {UNIT_KIND_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>
                                  {option.label}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div className="field">
                            <label className="field-label" htmlFor={`investment-unit-${unitId}-order`}>
                              Order
                            </label>
                            <NumericInput
                              id={`investment-unit-${unitId}-order`}
                              className="field-input"
                              value={workspace.unitEdit.ordinal}
                              onChange={(value) => workspace.setUnitEdit({ ordinal: value })}
                              group={false}
                              disabled={workspace.isSavingUnit}
                            />
                          </div>
                          <div className="investment-inline-actions">
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              onClick={workspace.cancelUnitEdit}
                              disabled={workspace.isSavingUnit}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              onClick={() => void workspace.saveUnitEdit()}
                              disabled={workspace.isSavingUnit}
                            >
                              {workspace.isSavingUnit ? 'Saving…' : 'Save Unit'}
                            </button>
                          </div>
                        </div>
                        <p className="investment-note">
                          {UNIT_KIND_NOTE} Label and order change presentation only.
                        </p>
                        {workspace.unitEditFeedback !== null && (
                          <div className="error-banner investment-feedback" role="alert">
                            <p className="scenario-editor-feedback-message">{workspace.unitEditFeedback.message}</p>
                            <InvestmentIssueList issues={workspace.unitEditFeedback.issues} names={names} />
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                  {isRemoving && workspace.removal !== null && (
                    <tr className="investment-subrow">
                      <td colSpan={7}>
                        <div className="investment-confirm" role="group" aria-label={`Confirm removing ${dealName}`}>
                          <p className="investment-confirm-text">{REMOVE_UNIT_CONSEQUENCES}</p>
                          <p className="investment-note">
                            Current Transaction Price {formatCurrency(investment.transaction_price)} ·{' '}
                            {dealName}&apos;s own purchase price{' '}
                            {formatCurrency(row.deal === null ? null : storedPurchasePrice(row.deal))}
                          </p>
                          <div className="investment-inline-form">
                            <div className="field">
                              <label className="field-label" htmlFor="investment-removal-price">
                                {RESULTING_PRICE_LABEL}
                              </label>
                              <div className="field-input-wrap">
                                <span className="field-affix field-affix-left">$</span>
                                <NumericInput
                                  id="investment-removal-price"
                                  className="field-input"
                                  value={workspace.removal.price}
                                  onChange={workspace.setRemovalPrice}
                                  group
                                  disabled={workspace.isRemoving}
                                  style={{ paddingLeft: '1.4rem' }}
                                  aria-describedby={
                                    workspace.removalFeedback !== null ? 'investment-removal-issues' : undefined
                                  }
                                />
                              </div>
                            </div>
                            <div className="investment-inline-actions">
                              <button
                                type="button"
                                className="btn btn-danger btn-sm"
                                onClick={() => void workspace.confirmRemoval()}
                                disabled={workspace.isRemoving}
                              >
                                {workspace.isRemoving ? 'Removing…' : 'Remove Unit'}
                              </button>
                              <button
                                ref={removalCancel}
                                type="button"
                                className="btn btn-ghost btn-sm"
                                onClick={workspace.cancelRemoval}
                                disabled={workspace.isRemoving}
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                          {workspace.removalFeedback !== null && (
                            <div id="investment-removal-issues" className="error-banner investment-feedback" role="alert">
                              <p className="scenario-editor-feedback-message">{workspace.removalFeedback.message}</p>
                              <InvestmentIssueList issues={workspace.removalFeedback.issues} names={names} />
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              );
            })}
          </table>
        </div>
        {isLastUnit && <p className="investment-note">{LAST_UNIT_MESSAGE}</p>}
      </section>

      {workspace.addUnit !== null && (
        <section className="scenario-panel investment-section" aria-labelledby="investment-add-unit-title">
          <div className="scenario-panel-heading">
            <h3 id="investment-add-unit-title" className="scenario-panel-title">
              Add Unit
            </h3>
            <p className="scenario-panel-subtitle">
              Add a saved standalone Deal. State the Investment&apos;s resulting Transaction Price; the Units
              must reconcile to it. Nothing is added to the price for you.
            </p>
          </div>
          <div className="investment-inline-form">
            <div className="field">
              <label className="field-label" htmlFor="investment-add-deal">
                Deal
              </label>
              <select
                id="investment-add-deal"
                className="field-input"
                value={workspace.addUnit.dealId}
                onChange={(event) => workspace.setAddUnit({ dealId: event.target.value })}
                disabled={workspace.isAddingUnit}
              >
                <option value="">Choose a deal…</option>
                {candidates.map((deal) => {
                  const other = otherInvestment(deal.id);
                  return (
                    <option key={deal.id} value={deal.id}>
                      {`${deal.name} · ${operatingModeLabel(deal.operating_mode)} · ${formatCurrency(storedPurchasePrice(deal))}${other === undefined ? '' : ` · Unit of ${other.name}`}`}
                    </option>
                  );
                })}
              </select>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="investment-add-label">
                Label (optional)
              </label>
              <input
                id="investment-add-label"
                className="field-input"
                type="text"
                value={workspace.addUnit.label}
                onChange={(event) => workspace.setAddUnit({ label: event.target.value })}
                disabled={workspace.isAddingUnit}
                autoComplete="off"
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="investment-add-kind">
                Unit Kind
              </label>
              <select
                id="investment-add-kind"
                className="field-input"
                value={workspace.addUnit.kind}
                onChange={(event) => workspace.setAddUnit({ kind: event.target.value as UnitKind })}
                disabled={workspace.isAddingUnit}
              >
                {UNIT_KIND_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="investment-add-price">
                {RESULTING_PRICE_LABEL}
              </label>
              <div className="field-input-wrap">
                <span className="field-affix field-affix-left">$</span>
                <NumericInput
                  id="investment-add-price"
                  className="field-input"
                  value={workspace.addUnit.price}
                  onChange={(value) => workspace.setAddUnit({ price: value })}
                  group
                  disabled={workspace.isAddingUnit}
                  style={{ paddingLeft: '1.4rem' }}
                  aria-describedby="investment-add-price-note"
                />
              </div>
              <span className="field-hint" id="investment-add-price-note">
                Current Transaction Price {formatCurrency(investment.transaction_price)}
              </span>
            </div>
          </div>
          <p className="investment-note">{UNIT_KIND_NOTE}</p>
          {workspace.addUnitFeedback !== null && (
            <div className="error-banner investment-feedback" role="alert">
              <p className="scenario-editor-feedback-message">{workspace.addUnitFeedback.message}</p>
              <InvestmentIssueList issues={workspace.addUnitFeedback.issues} names={names} />
            </div>
          )}
          <div className="scenario-editor-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={workspace.cancelAddUnit}
              disabled={workspace.isAddingUnit}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => void workspace.submitAddUnit()}
              disabled={workspace.isAddingUnit}
            >
              {workspace.isAddingUnit ? 'Adding…' : 'Add Unit'}
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
