/**
 * Phase 7 Gate P7.10 Stage 4 -- valuation views, and which ones this memo
 * includes.
 *
 * **Including a view is an explicit act (Section 22.6).** Selection is stored,
 * never inferred from a view's existence, its display order or which was
 * authored last. A view the analyst is still working out is exploratory: it
 * never blocks publication, and nobody is asked to delete their own working
 * state in order to publish.
 *
 * **A consumed view is load-bearing whether or not it is displayed.** Where a
 * `PctOfValue` funding sizes itself from a valuation, that valuation is a
 * dependency of the selected Capital Structure. The panel marks it, and marks
 * that the analyst cannot opt out of it.
 *
 * **Unavailable is shown, with its own reason, and is never a number.** A view
 * with no value prints the backend's typed reason -- never `$0`, never the
 * purchase price, never another timepoint's value, and never a blank cell.
 *
 * **Exit is the system's (R-B).** It is the existing D6 terminal result read
 * unchanged. There is no second exit calculation and no editable Exit method,
 * so Exit appears as context and cannot be selected.
 */

import { formatCurrency } from '../format';
import { toggleSelectedValuation } from '../memoForm';
import type { MemoDraftForm } from '../memoForm';
import type { ValuationSurface, ValuationView } from '../memoTypes';
import {
  EXPLORATORY_VALUATION_HINT,
  publicationScopeLabel,
  unavailableReasonLabel,
  valuationRoleLabel,
} from '../memoCatalog';
import type { MemoScopeSources } from '../memoCatalog';

export interface MemoValuationPanelProps {
  form: MemoDraftForm;
  onChange: (next: MemoDraftForm) => void;
  surface: ValuationSurface | null;
  isLoading: boolean;
  error: string | null;
  /** True when the draft has not chosen a Strategy and Scenario yet, which is a
   * real state rather than a failure: there is nothing to resolve against. */
  hasSelectedCell: boolean;
  /** The registers a position or view is named from, so this panel shows the
   * analyst's own words rather than a stored key (Correction 2). */
  scopes: MemoScopeSources;
}

function ValuationRow({
  view,
  isSelected,
  isConsumed,
  onToggle,
}: {
  view: ValuationView;
  isSelected: boolean;
  isConsumed: boolean;
  onToggle: () => void;
}) {
  const analystSupplied = view.unit_views.some((unit) => unit.analyst_supplied);
  const role = valuationRoleLabel({
    selected: isSelected,
    consumed: isConsumed,
    systemControlled: false,
  });

  return (
    <tr>
      <td>
        <label className="memo-include">
          <input
            type="checkbox"
            checked={isSelected}
            onChange={onToggle}
            aria-label={`Include ${view.label} in this memo`}
          />
          <span>Include</span>
        </label>
      </td>
      <th scope="row" className="memo-cell-label">
        {view.label}
        {analystSupplied && (
          <span className="memo-tag memo-tag-analyst">Analyst-Supplied Value</span>
        )}
      </th>
      <td>{role}</td>
      <td className="memo-cell-figure">
        {view.value !== null ? (
          <span className="memo-value">{formattedValue(view)}</span>
        ) : (
          <span className="memo-unavailable">
            Unavailable
            {view.unavailable !== null && (
              <span className="memo-unavailable-reason">
                {' '}
                — {unavailableReasonLabel(view.unavailable.reason_code)}
              </span>
            )}
          </span>
        )}
      </td>
    </tr>
  );
}

/**
 * The view's value, exactly as the backend reported it.
 *
 * The Stage 2 valuation surface carries a raw number rather than a formatted
 * string -- it is the engine's surface, not the Stage 4 report package -- so it
 * is rendered through the product's one existing `formatCurrency`, the same
 * helper every other panel uses and a direct mirror of
 * `src/anchor/formatting.py`. That presents a value Anchor computed; it derives
 * nothing. The figures the committee actually reads are the report's, which the
 * backend formats.
 */
function formattedValue(view: ValuationView): string {
  if (view.value === null) {
    return 'Unavailable';
  }
  return formatCurrency(view.value);
}

export function MemoValuationPanel({
  form,
  onChange,
  surface,
  isLoading,
  error,
  hasSelectedCell,
  scopes,
}: MemoValuationPanelProps) {
  const selectedIds = new Set(form.selectedValuationTimepointIds);
  const consumedIds = new Set(surface?.consumed_timepoint_ids ?? []);
  const unresolvedFundings = (surface?.funding_states ?? []).filter(
    (state) => state.unavailable !== null,
  );

  return (
    <div className="memo-panel">
      <section className="memo-section">
        <h3 className="memo-section-title">Valuation views</h3>
        <p className="memo-section-hint">{EXPLORATORY_VALUATION_HINT}</p>

        {!hasSelectedCell && (
          <p className="memo-empty">
            Choose a Strategy and Scenario on Decision Summary to resolve valuation views.
          </p>
        )}

        {hasSelectedCell && isLoading && (
          <p className="memo-empty" role="status">
            Resolving valuation views…
          </p>
        )}

        {error !== null && (
          <div className="error-banner" role="alert">
            <span>{error}</span>
          </div>
        )}

        {surface !== null && surface.views.length === 0 && (
          <p className="memo-empty">
            This Investment defines no valuation views, so there is nothing to include here. Exit
            value, below, is always reported.
          </p>
        )}

        {surface !== null && surface.views.length > 0 && (
          <div className="memo-table-scroll" tabIndex={0} role="group" aria-label="Valuation views">
            <table className="memo-table">
              <caption className="memo-table-caption">
                Views this Investment defines, and whether this memo includes them
              </caption>
              <thead>
                <tr>
                  <th scope="col">In memo</th>
                  <th scope="col">View</th>
                  <th scope="col">Role</th>
                  <th scope="col" className="memo-cell-figure">
                    Value
                  </th>
                </tr>
              </thead>
              <tbody>
                {surface.views.map((view) => (
                  <ValuationRow
                    key={view.timepoint_id}
                    view={view}
                    isSelected={selectedIds.has(view.timepoint_id)}
                    isConsumed={consumedIds.has(view.timepoint_id)}
                    onToggle={() => onChange(toggleSelectedValuation(form, view.timepoint_id))}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {consumedIds.size > 0 && (
        <section className="memo-section">
          <h3 className="memo-section-title">Consumed by funding</h3>
          <p className="memo-section-hint">
            A value-sized funding in the selected Capital Structure sizes itself from these views,
            so each is a dependency of this package whether or not the report displays it. That is
            not a choice this memo can opt out of.
          </p>
        </section>
      )}

      {unresolvedFundings.length > 0 && (
        <section className="memo-section">
          <h3 className="memo-section-title">Value-sized fundings that could not be sized</h3>
          <ul className="memo-item-list">
            {unresolvedFundings.map((state) => (
              <li key={`${state.position_id}-${state.event_id}`} className="memo-disclosure" role="note">
                {/* The position by the name its own Capital Structure gives
                  * it. Found by the identifier guard at the second Stage 4
                  * review: this printed the stored key. */}
                <p className="memo-disclosure-title">
                  {publicationScopeLabel('selected_perspective_missing', state.position_id, scopes)}
                </p>
                <p className="memo-disclosure-detail">
                  {unavailableReasonLabel(state.unavailable?.reason_code)}
                </p>
                <p className="memo-disclosure-detail">
                  No amount is reported for this funding, because there is none to report.
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="memo-section">
        <h3 className="memo-section-title">Exit</h3>
        <p className="memo-section-hint">
          Exit is the terminal value of the selected analysis, derived by Anchor and read
          unchanged. It is not an editable valuation and is always reported in the memo.
        </p>
      </section>
    </div>
  );
}
