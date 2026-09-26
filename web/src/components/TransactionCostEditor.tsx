/**
 * Phase 7 Gate P7.6 -- the Investment transaction cost editor.
 *
 * One row per cost: Description, Category, Amount, Timing. Timing is always
 * Closing in P7.6 -- shown as a fact, never typed, and sent as model month 0.
 * Category is reporting only. These are closing equity uses of the whole
 * transaction: not financing fees, not Project Capital, not Owner Expenses.
 *
 * Presentation only: the rows are the caller's draft, each change goes back
 * through the caller, and nothing here totals the costs.
 */

import {
  CLOSING_TIMING_LABEL,
  TRANSACTION_COST_CATEGORY_OPTIONS,
  TRANSACTION_COST_NOTE,
  transactionCostCategoryLabel,
} from '../investmentCatalog';
import type { TransactionCostDraft } from '../investmentForm';
import { NumericInput } from './NumericInput';

export interface TransactionCostEditorProps {
  costs: TransactionCostDraft[];
  /** Client and backend findings, by cost id. */
  issues: Readonly<Record<string, string[]>>;
  disabled: boolean;
  onAdd: () => void;
  onChange: (costId: string, field: 'description' | 'category' | 'amount', value: string) => void;
  onRemove: (costId: string) => void;
}

export function TransactionCostEditor({ costs, issues, disabled, onAdd, onChange, onRemove }: TransactionCostEditorProps) {
  return (
    <div className="investment-costs">
      <p className="investment-note">{TRANSACTION_COST_NOTE}</p>
      {costs.length === 0 ? (
        <p className="scenario-muted">No transaction costs.</p>
      ) : (
        <table className="investment-cost-table">
          <caption className="visually-hidden">Investment transaction costs</caption>
          <thead>
            <tr>
              <th scope="col">Description</th>
              <th scope="col">Category</th>
              <th scope="col" className="investment-num">
                Amount
              </th>
              <th scope="col">Timing</th>
              <th scope="col">
                <span className="visually-hidden">Remove</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {costs.map((cost, position) => {
              const rowIssues = issues[cost.costId] ?? [];
              const issuesId = `investment-cost-${position}-issues`;
              const label = cost.description.trim() === '' ? 'this cost' : cost.description;
              return (
                <tr key={cost.costId} className={rowIssues.length > 0 ? 'investment-cost-row investment-cost-row-error' : 'investment-cost-row'}>
                  <td>
                    <label className="scenario-override-label" htmlFor={`investment-cost-${position}-description`}>
                      Description
                    </label>
                    <input
                      id={`investment-cost-${position}-description`}
                      className="field-input"
                      type="text"
                      value={cost.description}
                      onChange={(event) => onChange(cost.costId, 'description', event.target.value)}
                      disabled={disabled}
                      autoComplete="off"
                      aria-invalid={rowIssues.length > 0 ? true : undefined}
                      aria-describedby={rowIssues.length > 0 ? issuesId : undefined}
                    />
                    {rowIssues.length > 0 && (
                      <ul id={issuesId} className="investment-issues" role="alert">
                        {rowIssues.map((message) => (
                          <li key={message}>{message}</li>
                        ))}
                      </ul>
                    )}
                  </td>
                  <td>
                    <label className="scenario-override-label" htmlFor={`investment-cost-${position}-category`}>
                      Category
                    </label>
                    <select
                      id={`investment-cost-${position}-category`}
                      className="field-input"
                      value={cost.category}
                      onChange={(event) => onChange(cost.costId, 'category', event.target.value)}
                      disabled={disabled}
                    >
                      {TRANSACTION_COST_CATEGORY_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="investment-cost-amount">
                    <label className="scenario-override-label" htmlFor={`investment-cost-${position}-amount`}>
                      Amount
                    </label>
                    <div className="field-input-wrap">
                      <span className="field-affix field-affix-left">$</span>
                      <NumericInput
                        id={`investment-cost-${position}-amount`}
                        className="field-input"
                        value={cost.amount}
                        onChange={(value) => onChange(cost.costId, 'amount', value)}
                        group
                        disabled={disabled}
                        style={{ paddingLeft: '1.4rem' }}
                      />
                    </div>
                  </td>
                  <td className="investment-cost-timing">
                    <span className="scenario-override-label">Timing</span>
                    <span className="investment-timing-tag">{CLOSING_TIMING_LABEL}</span>
                  </td>
                  <td className="investment-cost-remove">
                    <button
                      type="button"
                      className="btn btn-remove btn-xs"
                      onClick={() => onRemove(cost.costId)}
                      disabled={disabled}
                      aria-label={`Remove ${label} (${transactionCostCategoryLabel(cost.category)})`}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <div>
        <button type="button" className="btn btn-add btn-sm" onClick={onAdd} disabled={disabled}>
          Add Transaction Cost
        </button>
      </div>
    </div>
  );
}
