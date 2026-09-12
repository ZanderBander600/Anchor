/**
 * Phase 6 Gate D6.6 -- the Business Plan editor.
 *
 * **One editor, three modes.** Quick, Detailed and Lease-Level render this same
 * component over the same draft shape. Nothing here knows which mode it is in:
 * the Business Plan is a mode-agnostic deal contract, and the labels,
 * categories, month semantics and year semantics an analyst sees must be the
 * same wherever they see them.
 *
 * **Two authorities, kept apart.** Project Capital (one-time, model-month
 * timing) and Owner Expenses (fixed annual dollars over a year range) are
 * separate subsections with separate tables. Neither is labelled "Expenses"
 * alone, and neither is folded into operating expenses, the rent roll or the
 * debt terms.
 *
 * **It computes nothing.** Every figure is a string the analyst typed or a row
 * loaded from the deal. The one derived thing on screen -- the Closing / Year N
 * / Post-Hold tag beside a model month -- is `capitalTimingLabel`, which is
 * display-only and never submitted. There is no total anywhere: aggregation
 * belongs to the backend's results.
 *
 * **Identity is invisible and stable.** Rows are keyed by their item ID, which
 * the analyst never sees or types. Typing, reordering renders, analysis and
 * saving never change it.
 */

import { useEffect, useRef } from 'react';
import type { ChangeEvent } from 'react';
import { NumericInput } from './NumericInput';
import {
  CAPITAL_ITEM_CATEGORY_OPTIONS,
  OWNER_EXPENSE_CATEGORY_OPTIONS,
  addCapitalItem,
  addOwnerExpenseItem,
  capitalTimingLabel,
  removeCapitalItem,
  removeOwnerExpenseItem,
  updateCapitalItem,
  updateOwnerExpenseItem,
} from '../businessPlan';
import type {
  BusinessPlanDraft,
  BusinessPlanFieldIssue,
  CapitalItemField,
  OwnerExpenseItemField,
} from '../businessPlan';

export interface BusinessPlanEditorProps {
  plan: BusinessPlanDraft;
  onChange: (next: BusinessPlanDraft) => void;
  /** Client and backend issues, already placed on rows by item ID. */
  issues: BusinessPlanFieldIssue[];
  /** The hold period as currently entered. Read only to tag a model month as
   * Post-Hold for display; never written, and never substituted for a blank
   * Last Year. */
  holdPeriod: string;
  /** True while an analysis or save is in flight. */
  disabled: boolean;
}

const ADD_CAPITAL_ID = 'business-plan-add-capital';
const ADD_OWNER_EXPENSE_ID = 'business-plan-add-owner-expense';

function countLabel(count: number): string {
  return count === 1 ? '1 item' : `${count} items`;
}

function fieldMessage(
  issues: BusinessPlanFieldIssue[],
  collection: 'capital' | 'owner_expense',
  itemId: string,
  field: CapitalItemField | OwnerExpenseItemField,
): string | undefined {
  return issues.find(
    (issue) =>
      issue.collection === collection && issue.itemId === itemId && issue.field === field,
  )?.message;
}

interface CellProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  error: string | undefined;
}

/** The error beneath a control, wired to it by `aria-describedby`. */
function CellError({ id, error }: { id: string; error: string | undefined }) {
  return error === undefined ? null : (
    <span className="field-error" id={`${id}-error`} role="alert">
      {error}
    </span>
  );
}

function TextCell({ id, label, value, onChange, disabled, error }: CellProps) {
  return (
    <>
      <input
        id={id}
        className="business-plan-input"
        type="text"
        value={value}
        disabled={disabled}
        aria-label={label}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(event.target.value)}
      />
      <CellError id={id} error={error} />
    </>
  );
}

function SelectCell({
  id,
  label,
  value,
  onChange,
  disabled,
  error,
  options,
}: CellProps & { options: readonly { value: string; label: string }[] }) {
  return (
    <>
      <select
        id={id}
        className="business-plan-input"
        value={value}
        disabled={disabled}
        aria-label={label}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(event: ChangeEvent<HTMLSelectElement>) => onChange(event.target.value)}
      >
        {/* An explicit unselected entry: a category is the analyst's choice,
            and defaulting to the first option would make it for them. */}
        <option value="">Select&hellip;</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <CellError id={id} error={error} />
    </>
  );
}

/** A dollar amount: grouped while not focused (`250,000`), raw while editing,
 * through the one shared numeric input. */
function MoneyCell({ id, label, value, onChange, disabled, error }: CellProps) {
  return (
    <>
      <div className="business-plan-money">
        <span className="business-plan-affix" aria-hidden="true">
          $
        </span>
        <NumericInput
          id={id}
          className="business-plan-input business-plan-input-numeric"
          value={value}
          onChange={onChange}
          disabled={disabled}
          group
          aria-label={label}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
        />
      </div>
      <CellError id={id} error={error} />
    </>
  );
}

/** A month or a year: an ungrouped number. */
function IndexCell({
  id,
  label,
  value,
  onChange,
  disabled,
  error,
  placeholder,
  describedBy,
}: CellProps & { placeholder?: string; describedBy?: string }) {
  const described = [error ? `${id}-error` : null, describedBy ?? null]
    .filter((part) => part !== null)
    .join(' ');
  return (
    <>
      <NumericInput
        id={id}
        className="business-plan-input business-plan-input-numeric"
        value={value}
        onChange={onChange}
        disabled={disabled}
        group={false}
        placeholder={placeholder}
        aria-label={label}
        aria-invalid={error ? true : undefined}
        aria-describedby={described === '' ? undefined : described}
      />
      <CellError id={id} error={error} />
    </>
  );
}

export function BusinessPlanEditor({
  plan,
  onChange,
  issues,
  holdPeriod,
  disabled,
}: BusinessPlanEditorProps) {
  // The control to focus once the plan it belongs to has rendered: the new
  // row's Description after an add, the section's Add action after a remove.
  const pendingFocus = useRef<string | null>(null);
  useEffect(() => {
    if (pendingFocus.current === null) {
      return;
    }
    const target = document.getElementById(pendingFocus.current);
    pendingFocus.current = null;
    target?.focus();
  });

  const planLevel = issues.filter((issue) => issue.itemId === null);
  const capitalRowIds = new Set(plan.capitalItems.map((item) => item.itemId));
  const ownerRowIds = new Set(plan.ownerExpenseItems.map((item) => item.itemId));

  function handleAddCapital() {
    const added = addCapitalItem(plan);
    // The new row is appended, so it takes the position the collection's
    // current length names.
    pendingFocus.current = `business-plan-capital-${plan.capitalItems.length}-description`;
    onChange(added.plan);
  }

  function handleAddOwnerExpense() {
    const added = addOwnerExpenseItem(plan);
    pendingFocus.current = `business-plan-owner-${plan.ownerExpenseItems.length}-description`;
    onChange(added.plan);
  }

  return (
    <section className="assumption-section business-plan" aria-labelledby="business-plan-title">
      <div className="business-plan-head">
        <h3 className="assumption-section-title business-plan-title" id="business-plan-title">
          Business Plan
        </h3>
        <span className="business-plan-optional">Optional</span>
      </div>
      <p className="business-plan-lede">
        Model project capital and owner-level expenses below NOI.
      </p>

      {planLevel.length > 0 && (
        <div className="error-banner business-plan-issues" role="alert">
          <ul>
            {planLevel.map((issue, position) => (
              <li key={`${issue.message}-${position}`}>{issue.message}</li>
            ))}
          </ul>
        </div>
      )}

      {/* ---------------------------------------------------------------- */}
      {/* Project Capital                                                  */}
      {/* ---------------------------------------------------------------- */}
      <div
        className="business-plan-group"
        role="group"
        aria-labelledby="business-plan-capital-title"
      >
        <div className="business-plan-group-head">
          <h4 className="business-plan-group-title" id="business-plan-capital-title">
            Project Capital
          </h4>
          {plan.capitalItems.length > 0 && (
            <span className="business-plan-count">{countLabel(plan.capitalItems.length)}</span>
          )}
        </div>
        <p className="business-plan-hint">
          One-time owner capital at closing, during the hold or after it. Separate from the
          recurring CapEx Reserve and from tenant improvements and leasing commissions.
        </p>

        {plan.capitalItems.length === 0 ? (
          <p className="business-plan-empty">No project capital scheduled.</p>
        ) : (
          <div className="business-plan-table-wrap">
            <table className="business-plan-table business-plan-table-capital">
              <caption className="visually-hidden">
                Project Capital items, in the order they are saved.
              </caption>
              <colgroup>
                <col className="business-plan-col-description" />
                <col className="business-plan-col-category" />
                <col className="business-plan-col-month" />
                <col className="business-plan-col-amount" />
                <col className="business-plan-col-actions" />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">Description</th>
                  <th scope="col">Category</th>
                  <th scope="col" className="business-plan-num">
                    Model Month
                    <span className="business-plan-col-hint">0 = Closing</span>
                  </th>
                  <th scope="col" className="business-plan-num">
                    Amount
                  </th>
                  <th scope="col">
                    <span className="visually-hidden">Remove</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {plan.capitalItems.map((item, index) => {
                  const row = item.description.trim() || 'new Project Capital item';
                  const base = `business-plan-capital-${index}`;
                  const timing = capitalTimingLabel(item.month, holdPeriod);
                  const hasError = issues.some(
                    (issue) => issue.collection === 'capital' && issue.itemId === item.itemId,
                  );
                  const rowMessage = issues.find(
                    (issue) =>
                      issue.collection === 'capital' &&
                      issue.itemId === item.itemId &&
                      issue.field === null,
                  )?.message;
                  const set = (field: CapitalItemField) => (value: string) =>
                    onChange(updateCapitalItem(plan, item.itemId, field, value));
                  const message = (field: CapitalItemField) =>
                    fieldMessage(issues, 'capital', item.itemId, field);
                  return (
                    <tr
                      key={item.itemId}
                      className={
                        hasError ? 'business-plan-row business-plan-row-error' : 'business-plan-row'
                      }
                    >
                      <td data-label="Description">
                        <TextCell
                          id={`${base}-description`}
                          label={`Description, ${row}`}
                          value={item.description}
                          onChange={set('description')}
                          disabled={disabled}
                          error={message('description')}
                        />
                        {rowMessage && (
                          <span className="field-error" role="alert">
                            {rowMessage}
                          </span>
                        )}
                      </td>
                      <td data-label="Category">
                        <SelectCell
                          id={`${base}-category`}
                          label={`Category, ${row}`}
                          value={item.category}
                          onChange={set('category')}
                          disabled={disabled}
                          error={message('category')}
                          options={CAPITAL_ITEM_CATEGORY_OPTIONS}
                        />
                      </td>
                      <td data-label="Model Month" className="business-plan-num">
                        <IndexCell
                          id={`${base}-month`}
                          label={`Model Month, ${row}`}
                          value={item.month}
                          onChange={set('month')}
                          disabled={disabled}
                          error={message('month')}
                          describedBy={timing === null ? undefined : `${base}-timing`}
                        />
                        {timing !== null && (
                          <span className="business-plan-timing" id={`${base}-timing`}>
                            {timing}
                          </span>
                        )}
                      </td>
                      <td data-label="Amount" className="business-plan-num">
                        <MoneyCell
                          id={`${base}-amount`}
                          label={`Amount, ${row}`}
                          value={item.amount}
                          onChange={set('amount')}
                          disabled={disabled}
                          error={message('amount')}
                        />
                      </td>
                      <td className="business-plan-actions">
                        <button
                          type="button"
                          className="btn btn-ghost btn-xs"
                          disabled={disabled}
                          aria-label={`Remove ${row}`}
                          onClick={() => {
                            pendingFocus.current = ADD_CAPITAL_ID;
                            onChange(removeCapitalItem(plan, item.itemId));
                          }}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {issues
          .filter(
            (issue) =>
              issue.collection === 'capital' &&
              issue.itemId !== null &&
              !capitalRowIds.has(issue.itemId),
          )
          .map((issue, position) => (
            <p className="field-error" role="alert" key={`${issue.message}-${position}`}>
              {issue.message}
            </p>
          ))}

        <div className="business-plan-toolbar">
          <button
            id={ADD_CAPITAL_ID}
            type="button"
            className="btn btn-secondary btn-sm"
            disabled={disabled}
            onClick={handleAddCapital}
          >
            Add Project Capital
          </button>
          {plan.capitalItems.length > 0 && (
            <p className="business-plan-note">
              Model Month counts from closing: 0 = Closing, 1&ndash;12 = Year 1, 13&ndash;24 =
              Year 2, and so on.
            </p>
          )}
        </div>
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Owner Expenses                                                   */}
      {/* ---------------------------------------------------------------- */}
      <div
        className="business-plan-group"
        role="group"
        aria-labelledby="business-plan-owner-title"
      >
        <div className="business-plan-group-head">
          <h4 className="business-plan-group-title" id="business-plan-owner-title">
            Owner Expenses
          </h4>
          {plan.ownerExpenseItems.length > 0 && (
            <span className="business-plan-count">
              {countLabel(plan.ownerExpenseItems.length)}
            </span>
          )}
        </div>
        <p className="business-plan-hint">
          Owner-level annual costs below NOI. Property management fees and property operating
          expenses belong in the operating assumptions.
        </p>

        {plan.ownerExpenseItems.length === 0 ? (
          <p className="business-plan-empty">No owner expenses.</p>
        ) : (
          <div className="business-plan-table-wrap">
            <table className="business-plan-table business-plan-table-owner">
              <caption className="visually-hidden">
                Owner Expense items, in the order they are saved.
              </caption>
              <colgroup>
                <col className="business-plan-col-description" />
                <col className="business-plan-col-category" />
                <col className="business-plan-col-amount" />
                <col className="business-plan-col-first-year" />
                <col className="business-plan-col-last-year" />
                <col className="business-plan-col-actions" />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">Description</th>
                  <th scope="col">Category</th>
                  <th scope="col" className="business-plan-num">
                    Annual Amount
                  </th>
                  <th scope="col" className="business-plan-num">
                    First Year
                  </th>
                  <th scope="col" className="business-plan-num">
                    Last Year
                  </th>
                  <th scope="col">
                    <span className="visually-hidden">Remove</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {plan.ownerExpenseItems.map((item, index) => {
                  const row = item.description.trim() || 'new Owner Expense item';
                  const base = `business-plan-owner-${index}`;
                  const hasError = issues.some(
                    (issue) =>
                      issue.collection === 'owner_expense' && issue.itemId === item.itemId,
                  );
                  const rowMessage = issues.find(
                    (issue) =>
                      issue.collection === 'owner_expense' &&
                      issue.itemId === item.itemId &&
                      issue.field === null,
                  )?.message;
                  const set = (field: OwnerExpenseItemField) => (value: string) =>
                    onChange(updateOwnerExpenseItem(plan, item.itemId, field, value));
                  const message = (field: OwnerExpenseItemField) =>
                    fieldMessage(issues, 'owner_expense', item.itemId, field);
                  return (
                    <tr
                      key={item.itemId}
                      className={
                        hasError ? 'business-plan-row business-plan-row-error' : 'business-plan-row'
                      }
                    >
                      <td data-label="Description">
                        <TextCell
                          id={`${base}-description`}
                          label={`Description, ${row}`}
                          value={item.description}
                          onChange={set('description')}
                          disabled={disabled}
                          error={message('description')}
                        />
                        {rowMessage && (
                          <span className="field-error" role="alert">
                            {rowMessage}
                          </span>
                        )}
                      </td>
                      <td data-label="Category">
                        <SelectCell
                          id={`${base}-category`}
                          label={`Category, ${row}`}
                          value={item.category}
                          onChange={set('category')}
                          disabled={disabled}
                          error={message('category')}
                          options={OWNER_EXPENSE_CATEGORY_OPTIONS}
                        />
                      </td>
                      <td data-label="Annual Amount" className="business-plan-num">
                        <MoneyCell
                          id={`${base}-annual-amount`}
                          label={`Annual Amount, ${row}`}
                          value={item.annualAmount}
                          onChange={set('annualAmount')}
                          disabled={disabled}
                          error={message('annualAmount')}
                        />
                      </td>
                      <td data-label="First Year" className="business-plan-num">
                        <IndexCell
                          id={`${base}-first-year`}
                          label={`First Year, ${row}`}
                          value={item.firstYear}
                          onChange={set('firstYear')}
                          disabled={disabled}
                          error={message('firstYear')}
                        />
                      </td>
                      <td data-label="Last Year" className="business-plan-num">
                        <IndexCell
                          id={`${base}-last-year`}
                          label={`Last Year, ${row}`}
                          value={item.lastYear}
                          onChange={set('lastYear')}
                          disabled={disabled}
                          error={message('lastYear')}
                          placeholder="Through Hold"
                        />
                      </td>
                      <td className="business-plan-actions">
                        <button
                          type="button"
                          className="btn btn-ghost btn-xs"
                          disabled={disabled}
                          aria-label={`Remove ${row}`}
                          onClick={() => {
                            pendingFocus.current = ADD_OWNER_EXPENSE_ID;
                            onChange(removeOwnerExpenseItem(plan, item.itemId));
                          }}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {issues
          .filter(
            (issue) =>
              issue.collection === 'owner_expense' &&
              issue.itemId !== null &&
              !ownerRowIds.has(issue.itemId),
          )
          .map((issue, position) => (
            <p className="field-error" role="alert" key={`${issue.message}-${position}`}>
              {issue.message}
            </p>
          ))}

        <div className="business-plan-toolbar">
          <button
            id={ADD_OWNER_EXPENSE_ID}
            type="button"
            className="btn btn-secondary btn-sm"
            disabled={disabled}
            onClick={handleAddOwnerExpense}
          >
            Add Owner Expense
          </button>
          {plan.ownerExpenseItems.length > 0 && (
            <p className="business-plan-note">Leave Last Year blank for through hold.</p>
          )}
        </div>
      </div>
    </section>
  );
}
