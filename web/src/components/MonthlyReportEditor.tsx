import { useMemo, useState } from 'react';

import { FIELD_LABELS } from '../assetManagementFormat';
import { FIGURE_FIELDS } from '../assetManagementTypes';
import type {
  FigureField,
  MonthlyAssetReport,
  OperatingFigures,
} from '../assetManagementTypes';
import { groupDigits } from '../numberFormat';
import { NumericInput } from './NumericInput';

/** Gate AM1 -- entering a month's approved budget and actual results.
 *
 * Two states, and the difference between them is the whole point:
 *
 * * **Creating** a month's first report: both columns are editable, because the
 *   approved budget is being recorded for the first time.
 * * **Editing** an existing report: the budget column is visibly locked and
 *   rendered as read-only text, and only actuals and commentary can change.
 *
 * The lock is presentation reinforcing a rule the server enforces
 * independently: `update_monthly_report_actuals` has no SQL that can move a
 * budget column, and the route refuses a changed budget with a typed 409. This
 * component never sends a budget on an edit at all.
 *
 * It performs no financial calculation. It collects the twelve authored figures
 * plus occupancy and hands them to the API; every total and variance on the
 * screen after saving comes back from the Python engine.
 */

/** Occupancy is authored in percent and stored as a fraction. The conversion is
 * a scale change on an input the analyst typed, not a financial result -- the
 * same conversion the existing assumption fields already perform. */
const PERCENT_FIELDS: ReadonlySet<FigureField> = new Set<FigureField>(['occupancy']);

function toDisplay(field: FigureField, value: number): string {
  return PERCENT_FIELDS.has(field) ? String(value * 100) : String(value);
}

function fromDisplay(field: FigureField, raw: string): number {
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) {
    return Number.NaN;
  }
  return PERCENT_FIELDS.has(field) ? parsed / 100 : parsed;
}

type Draft = Record<FigureField, string>;

function blankDraft(): Draft {
  return Object.fromEntries(FIGURE_FIELDS.map((field) => [field, ''])) as Draft;
}

function draftOf(figures: OperatingFigures): Draft {
  return Object.fromEntries(
    FIGURE_FIELDS.map((field) => [field, toDisplay(field, figures[field])]),
  ) as Draft;
}

function figuresOf(draft: Draft): OperatingFigures {
  return Object.fromEntries(
    FIGURE_FIELDS.map((field) => [field, fromDisplay(field, draft[field])]),
  ) as unknown as OperatingFigures;
}

export interface MonthlyReportEditorProps {
  /** The existing report being edited, or `null` when creating a month's
   * first report. */
  report: MonthlyAssetReport | null;
  /** The month being created. Ignored when `report` is supplied. */
  month: string;
  onMonthChange: (month: string) => void;
  onCancel: () => void;
  onCreate: (request: {
    reporting_month: string;
    budget: OperatingFigures;
    actual: OperatingFigures;
    commentary: string | null;
  }) => Promise<void>;
  onUpdate: (request: { actual: OperatingFigures; commentary: string | null }) => Promise<void>;
  error: string | null;
}

export function MonthlyReportEditor({
  report,
  month,
  onMonthChange,
  onCancel,
  onCreate,
  onUpdate,
  error,
}: MonthlyReportEditorProps) {
  const isNew = report === null;
  const [budget, setBudget] = useState<Draft>(() =>
    report === null ? blankDraft() : draftOf(report.budget),
  );
  const [actual, setActual] = useState<Draft>(() =>
    report === null ? blankDraft() : draftOf(report.actual),
  );
  const [commentary, setCommentary] = useState(report?.commentary ?? '');
  const [isSaving, setIsSaving] = useState(false);

  const frozenBudget = useMemo(
    () => (report === null ? null : draftOf(report.budget)),
    [report],
  );

  const submit = async () => {
    setIsSaving(true);
    try {
      const trimmed = commentary.trim();
      if (isNew) {
        await onCreate({
          reporting_month: month,
          budget: figuresOf(budget),
          actual: figuresOf(actual),
          commentary: trimmed === '' ? null : trimmed,
        });
      } else {
        await onUpdate({
          actual: figuresOf(actual),
          commentary: trimmed === '' ? null : trimmed,
        });
      }
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <form
      className="am-editor"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className="am-editor-head">
        <h3 className="am-panel-title">
          {isNew ? 'New Monthly Report' : 'Edit Actual Results'}
        </h3>
        {isNew ? (
          <label className="am-field">
            <span className="am-field-label">Reporting Month</span>
            <input
              type="month"
              className="am-month-input"
              value={month.slice(0, 7)}
              onChange={(event) => onMonthChange(`${event.target.value}-01`)}
              required
            />
          </label>
        ) : (
          <p className="am-editor-month">{report.reporting_month.slice(0, 7)}</p>
        )}
      </div>

      {isNew ? (
        <p className="am-editor-note">
          The approved budget is recorded once, with this month&rsquo;s first report. After it
          is saved it is locked, and only actual results and commentary can be changed.
        </p>
      ) : (
        <p className="am-editor-note">
          The approved budget was frozen when this report was created and cannot be
          changed. Record differences in the actual results or in commentary.
        </p>
      )}

      {error !== null && (
        <div className="am-error" role="alert">
          {error}
        </div>
      )}

      <div className="am-table-scroll">
        <table className="am-table am-editor-table">
          <thead>
            <tr>
              <th scope="col" className="am-col-line">
                Financial Line
              </th>
              <th scope="col" className="am-col-figure">
                Approved Budget{!isNew && <span className="am-lock-note"> · Locked</span>}
              </th>
              <th scope="col" className="am-col-figure">
                Actual
              </th>
            </tr>
          </thead>
          <tbody>
            {FIGURE_FIELDS.map((field) => {
              const suffix = PERCENT_FIELDS.has(field) ? '%' : '$';
              return (
                <tr key={field}>
                  <th scope="row" className="am-col-line">
                    {FIELD_LABELS[field]}
                    <span className="am-unit"> ({suffix})</span>
                  </th>
                  <td className="am-col-figure">
                    {isNew ? (
                      <NumericInput
                        id={`am-budget-${field}`}
                        className="am-input"
                        value={budget[field]}
                        group={!PERCENT_FIELDS.has(field)}
                        onChange={(value) => setBudget({ ...budget, [field]: value })}
                        aria-label={`Budget ${FIELD_LABELS[field]}`}
                      />
                    ) : (
                      // Read-only text, not a disabled input: a locked budget is
                      // a figure of record, and rendering it as a greyed-out
                      // field would suggest it is merely unavailable right now.
                      // Grouped exactly as the editable column groups on blur,
                      // so the locked figure reads as the same kind of number
                      // rather than as raw digits beside a formatted one.
                      <span className="am-locked-figure" aria-label={`Budget ${FIELD_LABELS[field]}, locked`}>
                        {PERCENT_FIELDS.has(field)
                          ? frozenBudget?.[field]
                          : groupDigits(frozenBudget?.[field] ?? '')}
                        <span className="am-unit"> {suffix === '%' ? '%' : ''}</span>
                      </span>
                    )}
                  </td>
                  <td className="am-col-figure">
                    <NumericInput
                      id={`am-actual-${field}`}
                      className="am-input"
                      value={actual[field]}
                      group={!PERCENT_FIELDS.has(field)}
                      onChange={(value) => setActual({ ...actual, [field]: value })}
                      aria-label={`Actual ${FIELD_LABELS[field]}`}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <label className="am-field am-field-block">
        <span className="am-field-label">Management Commentary</span>
        <textarea
          className="am-textarea"
          rows={4}
          value={commentary}
          onChange={(event) => setCommentary(event.target.value)}
          placeholder="Optional. What explains this month's results?"
        />
      </label>

      <div className="am-editor-actions">
        <button type="button" className="am-secondary-button" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="am-primary-button" disabled={isSaving}>
          {isSaving ? 'Saving…' : isNew ? 'Save Monthly Report' : 'Save Actual Results'}
        </button>
      </div>
    </form>
  );
}
