/**
 * Phase 7 Gate P7.10 Stage 4 -- Decision Summary.
 *
 * The analyst's ask, their recommendation, the executive summary, and the one
 * decision cell the memo is written from.
 *
 * **The recommendation is a proposal, and reads like one (R-F).** This panel
 * carries the analyst's recommendation only. The committee's decision is
 * recorded elsewhere, against a *published version*, on a surface this one
 * cannot reach -- so nothing here can look like a committee outcome, and no
 * committee outcome can be inferred from what an analyst chose.
 *
 * **Selecting a cell changes nothing.** Naming a Strategy, Scenario and
 * perspective says which decision this memo recommends. It never edits a
 * Strategy, moves a Scenario or alters a position, and the copy says so rather
 * than leaving an analyst to wonder whether a dropdown just changed their
 * model.
 */

import type { MemoDraftForm } from '../memoForm';
import type { DecisionPerspectiveKind, MemoIssue } from '../memoTypes';
import type { MemoDecisionContext } from '../useInvestmentMemo';
import {
  ANALYST_RECOMMENDATION_LABEL,
  COMPLEXITY_LABELS,
  COMPLEXITY_ORDER,
  PERSPECTIVE_LABELS,
  RECOMMENDATION_LABELS,
  RECOMMENDATION_ORDER,
} from '../memoCatalog';

export interface MemoDecisionPanelProps {
  form: MemoDraftForm;
  onChange: (next: MemoDraftForm) => void;
  context: MemoDecisionContext;
  issues: MemoIssue[];
}

const PERSPECTIVE_ORDER: DecisionPerspectiveKind[] = ['project', 'position', 'partner'];

/** The issues that belong to one field, so a refusal is shown on the input it
 * concerns rather than only in a banner at the top. */
function issuesFor(issues: MemoIssue[], field: string): MemoIssue[] {
  return issues.filter((issue) => issue.field === field);
}

function FieldIssues({ issues }: { issues: MemoIssue[] }) {
  if (issues.length === 0) {
    return null;
  }
  return (
    <p className="memo-field-error" role="alert">
      {issues.map((issue) => issue.message).join(' ')}
    </p>
  );
}

export function MemoDecisionPanel({ form, onChange, context, issues }: MemoDecisionPanelProps) {
  const selected = form.selectedDecision;
  const perspective = selected?.perspective ?? 'project';

  /** One change to the selected cell.
   *
   * A perspective change clears the scope the previous one carried: a Position
   * memo switched to Partner must not keep pointing at a position id, which the
   * contract refuses and which would read as a stale selection. */
  function setSelection(next: Partial<NonNullable<MemoDraftForm['selectedDecision']>>): void {
    const base = selected ?? {
      strategy_id: context.strategies[0]?.id ?? '',
      scenario_id: context.scenarios[0]?.id ?? '',
      perspective: 'project' as DecisionPerspectiveKind,
      position_id: null,
      partner_id: null,
    };
    const merged = { ...base, ...next };
    onChange({
      ...form,
      selectedDecision: {
        ...merged,
        position_id: merged.perspective === 'position' ? merged.position_id : null,
        partner_id: merged.perspective === 'partner' ? merged.partner_id : null,
      },
    });
  }

  return (
    <div className="memo-panel">
      <section className="memo-section">
        <h3 className="memo-section-title">The decision requested</h3>
        <p className="memo-section-hint">
          What the committee is being asked to approve, in the analyst's own words.
        </p>
        <label className="memo-field">
          <span className="memo-field-label">Decision ask</span>
          <textarea
            className="memo-textarea"
            rows={3}
            value={form.decisionAsk}
            onChange={(event) => onChange({ ...form, decisionAsk: event.target.value })}
            placeholder="Approve the acquisition of …"
          />
        </label>
        <FieldIssues issues={issuesFor(issues, 'decision_ask')} />

        <label className="memo-field">
          <span className="memo-field-label">Executive summary</span>
          <textarea
            className="memo-textarea"
            rows={5}
            value={form.executiveSummary}
            onChange={(event) => onChange({ ...form, executiveSummary: event.target.value })}
          />
        </label>
      </section>

      <section className="memo-section">
        <h3 className="memo-section-title">{ANALYST_RECOMMENDATION_LABEL}</h3>
        <p className="memo-section-hint">
          Your proposed action. The Investment Committee records its own decision separately,
          against a published version.
        </p>
        <div className="memo-choice-row" role="radiogroup" aria-label={ANALYST_RECOMMENDATION_LABEL}>
          {RECOMMENDATION_ORDER.map((value) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={form.analystRecommendation === value}
              className={
                form.analystRecommendation === value
                  ? 'memo-choice memo-choice-active'
                  : 'memo-choice'
              }
              onClick={() => onChange({ ...form, analystRecommendation: value })}
            >
              {RECOMMENDATION_LABELS[value]}
            </button>
          ))}
        </div>
      </section>

      <section className="memo-section">
        <h3 className="memo-section-title">Decision context</h3>
        <p className="memo-section-hint">
          Which Strategy, Scenario and stakeholder perspective this recommendation is made from.
          Selecting a cell changes no Strategy, Scenario, position or Partnership.
        </p>

        {context.error !== null && (
          <p className="memo-field-error" role="alert">
            {context.error}
          </p>
        )}

        <div className="memo-field-grid">
          <label className="memo-field">
            <span className="memo-field-label">Strategy</span>
            <select
              className="memo-select"
              value={selected?.strategy_id ?? ''}
              onChange={(event) => setSelection({ strategy_id: event.target.value })}
            >
              <option value="">Not selected</option>
              {context.strategies.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.name}
                </option>
              ))}
            </select>
          </label>

          <label className="memo-field">
            <span className="memo-field-label">Scenario</span>
            <select
              className="memo-select"
              value={selected?.scenario_id ?? ''}
              onChange={(event) => setSelection({ scenario_id: event.target.value })}
            >
              <option value="">Not selected</option>
              {context.scenarios.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.name}
                </option>
              ))}
            </select>
          </label>

          <label className="memo-field">
            <span className="memo-field-label">Decision perspective</span>
            <select
              className="memo-select"
              value={perspective}
              onChange={(event) =>
                setSelection({ perspective: event.target.value as DecisionPerspectiveKind })
              }
            >
              {PERSPECTIVE_ORDER.map((value) => (
                <option key={value} value={value}>
                  {PERSPECTIVE_LABELS[value]}
                </option>
              ))}
            </select>
          </label>

          {perspective === 'position' && (
            <label className="memo-field">
              <span className="memo-field-label">Capital position</span>
              <select
                className="memo-select"
                value={selected?.position_id ?? ''}
                onChange={(event) => setSelection({ position_id: event.target.value })}
              >
                <option value="">Not selected</option>
                {context.positions.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.name}
                  </option>
                ))}
              </select>
              {context.positions.length === 0 && !context.isLoading && (
                <span className="memo-field-hint">
                  This Investment has no capital positions to report from.
                </span>
              )}
            </label>
          )}

          {perspective === 'partner' && (
            <label className="memo-field">
              <span className="memo-field-label">Partner</span>
              <select
                className="memo-select"
                value={selected?.partner_id ?? ''}
                onChange={(event) => setSelection({ partner_id: event.target.value })}
              >
                <option value="">Not selected</option>
                {context.partners.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.name}
                  </option>
                ))}
              </select>
              {context.partners.length === 0 && !context.isLoading && (
                <span className="memo-field-hint">
                  This Investment resolves no Partnership, so there is no partner to report from.
                </span>
              )}
            </label>
          )}
        </div>
      </section>

      <section className="memo-section">
        <h3 className="memo-section-title">Execution</h3>
        <p className="memo-section-hint">
          Your own qualitative judgement. Anchor never derives it from a return.
        </p>
        <div className="memo-field-grid">
          <label className="memo-field">
            <span className="memo-field-label">Execution complexity</span>
            <select
              className="memo-select"
              value={form.executionComplexity}
              onChange={(event) =>
                onChange({
                  ...form,
                  executionComplexity: event.target
                    .value as MemoDraftForm['executionComplexity'],
                })
              }
            >
              {COMPLEXITY_ORDER.map((value) => (
                <option key={value} value={value}>
                  {COMPLEXITY_LABELS[value]}
                </option>
              ))}
            </select>
          </label>

          <label className="memo-field">
            <span className="memo-field-label">Prepared by</span>
            <input
              className="memo-input"
              type="text"
              value={form.preparedBy}
              onChange={(event) => onChange({ ...form, preparedBy: event.target.value })}
              placeholder="Display name"
            />
            <span className="memo-field-hint">
              Display text on the memo. It is not a verified identity.
            </span>
          </label>
        </div>

        <label className="memo-field">
          <span className="memo-field-label">Return on time notes</span>
          <textarea
            className="memo-textarea"
            rows={3}
            value={form.returnOnTimeNotes}
            onChange={(event) => onChange({ ...form, returnOnTimeNotes: event.target.value })}
          />
        </label>
      </section>
    </div>
  );
}
