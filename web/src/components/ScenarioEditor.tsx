/**
 * Phase 7 Gate P7.3 -- the Scenario editor.
 *
 * Name, optional description, and an override table: Assumption, Operation,
 * Value, Remove. The analyst never sees a unit id, a scenario id, an enum token
 * or a wire-scale decimal. The open Deal supplies the unit, the backend assigns
 * the id, and values are typed in the units an analyst reads (see
 * `scenarioCatalog.ts`).
 *
 * **A Unit column for a visible Investment (P7.6).** Each override row names
 * the Unit it addresses, by name, first; its assumptions are then that Unit's
 * own operating mode's, and its operations that assumption's whitelist. A Deal
 * keeps the table exactly as it was: the Deal is the unit.
 *
 * **The registry decides what is offered.** Assumptions come from the
 * operating mode's catalog (`GET /scenario-targets`), and each assumption's
 * operations come from its own whitelist. An assumption already used for the
 * same Unit in another row is not offered again, which prevents the obvious
 * duplicate. The backend still refuses duplicates itself; this is a
 * convenience, not the rule.
 *
 * **Refusals are shown as the backend worded them.** Each issue appears on the
 * row it names, or above the table if no row owns it. A failed save keeps every
 * value the analyst typed.
 *
 * **Locked while the base is dirty.** An editor that is already open when the
 * analyst edits the base stays on screen with its draft intact, but every
 * control that could change it is disabled until the base is saved or its
 * edits are reverted. Cancel stays available. The workspace states the reason.
 */

import { Fragment, useEffect, useRef } from 'react';
import { operatingModeLabel } from '../operatingMode';
import { unitDisplayName } from '../investmentCatalog';
import {
  SCENARIO_OPERATION_LABELS,
  scenarioTargetLabel,
  scenarioValueFormat,
} from '../scenarioCatalog';
import type { ScenarioEditorDraft, ScenarioEditorRow, ScenariosState } from '../useScenarios';
import type { ScenarioOperation } from '../scenarioTypes';
import { NumericInput } from './NumericInput';

export interface ScenarioEditorProps {
  /** The id the opening button's `aria-controls` names. */
  id: string;
  state: ScenariosState;
  editor: ScenarioEditorDraft;
}

/** Room for the suffix inside the value field. A lookup, not a measurement. */
function suffixPadding(suffix: string | null): string | undefined {
  if (suffix === null) {
    return undefined;
  }
  return suffix.length > 2 ? '3.9rem' : '1.8rem';
}

/** One (Unit, assumption) pair: a Deal's rows share the one implicit Unit. */
function takenKey(unitId: string, target: string): string {
  return `${unitId}|${target}`;
}

interface OverrideRowProps {
  row: ScenarioEditorRow;
  taken: ReadonlySet<string>;
  issues: string[];
  state: ScenariosState;
  withUnit: boolean;
}

function OverrideRow({ row, taken, issues, state, withUnit }: OverrideRowProps) {
  const locked = !state.canEdit;
  const entries = state.targetsFor(row.unitId);
  const entry = entries.find((candidate) => candidate.target === row.target);
  const label = row.target === '' ? 'this override' : scenarioTargetLabel(row.target);
  const offered = entries.filter(
    (candidate) => candidate.target === row.target || !taken.has(takenKey(row.unitId, candidate.target)),
  );
  // A stored target the catalog does not offer (or has not loaded yet) is
  // still shown as what it is, never silently replaced.
  const isUnoffered = row.target !== '' && entry === undefined;
  const operations: ScenarioOperation[] =
    entry?.allowed_operations ?? (row.operation === '' ? [] : [row.operation]);
  const format =
    row.target === '' || row.operation === ''
      ? null
      : scenarioValueFormat(row.target, row.operation, entry);
  const issuesId = `${row.key}-issues`;
  const hintId = `${row.key}-hint`;
  const hasIssues = issues.length > 0;
  const describedBy = [format === null ? null : hintId, hasIssues ? issuesId : null]
    .filter((id): id is string => id !== null)
    .join(' ');
  const needsUnit = withUnit && row.unitId === '';
  const knownUnit = state.units.some((unit) => unit.unitId === row.unitId);

  return (
    <Fragment>
      <tr className="scenario-override-row">
        {withUnit && (
          <td className="scenario-override-cell scenario-override-unit">
            <label className="scenario-override-label" htmlFor={`${row.key}-unit`}>
              Unit
            </label>
            <select
              id={`${row.key}-unit`}
              className="field-input scenario-select"
              value={row.unitId}
              onChange={(event) => state.setRowUnit(row.key, event.target.value)}
              disabled={locked}
              aria-invalid={hasIssues ? true : undefined}
              aria-describedby={hasIssues ? issuesId : undefined}
            >
              <option value="">Choose unit…</option>
              {!knownUnit && row.unitId !== '' && <option value={row.unitId}>{row.unitId}</option>}
              {state.units.map((unit) => (
                <option key={unit.unitId} value={unit.unitId}>
                  {`${unitDisplayName(unit)} · ${operatingModeLabel(unit.operatingMode)}`}
                </option>
              ))}
            </select>
          </td>
        )}
        <td className="scenario-override-cell">
          <label className="scenario-override-label" htmlFor={`${row.key}-target`}>
            Assumption
          </label>
          <select
            id={`${row.key}-target`}
            className="field-input scenario-select"
            value={row.target}
            onChange={(event) => state.setRowTarget(row.key, event.target.value)}
            disabled={locked || needsUnit}
            aria-invalid={hasIssues ? true : undefined}
            aria-describedby={hasIssues ? issuesId : undefined}
          >
            <option value="">Choose assumption…</option>
            {isUnoffered && <option value={row.target}>{scenarioTargetLabel(row.target)}</option>}
            {offered.map((candidate) => (
              <option key={candidate.target} value={candidate.target}>
                {scenarioTargetLabel(candidate.target)}
              </option>
            ))}
          </select>
        </td>
        <td className="scenario-override-cell">
          <label className="scenario-override-label" htmlFor={`${row.key}-operation`}>
            Operation<span className="visually-hidden"> for {label}</span>
          </label>
          <select
            id={`${row.key}-operation`}
            className="field-input scenario-select"
            value={row.operation}
            onChange={(event) =>
              state.setRowOperation(row.key, event.target.value as ScenarioOperation | '')
            }
            disabled={locked || row.target === ''}
          >
            <option value="">Choose…</option>
            {operations.map((operation) => (
              <option key={operation} value={operation}>
                {SCENARIO_OPERATION_LABELS[operation]}
              </option>
            ))}
          </select>
        </td>
        <td className="scenario-override-cell scenario-override-value">
          <label className="scenario-override-label" htmlFor={`${row.key}-value`}>
            Value<span className="visually-hidden"> for {label}</span>
          </label>
          <div className="field-input-wrap">
            {format?.prefix && <span className="field-affix field-affix-left">{format.prefix}</span>}
            <NumericInput
              id={`${row.key}-value`}
              className="field-input"
              value={row.value}
              onChange={(value) => state.setRowValue(row.key, value)}
              group={false}
              disabled={locked || format === null}
              aria-invalid={hasIssues ? true : undefined}
              aria-describedby={describedBy === '' ? undefined : describedBy}
              style={{
                paddingLeft: format?.prefix ? '1.4rem' : undefined,
                paddingRight: suffixPadding(format?.suffix ?? null),
              }}
            />
            {format?.suffix && <span className="field-affix field-affix-right">{format.suffix}</span>}
          </div>
          {format !== null && (
            <span className="scenario-override-hint" id={hintId}>
              {format.hint}
            </span>
          )}
        </td>
        <td className="scenario-override-cell scenario-override-remove">
          <button
            type="button"
            className="btn btn-ghost btn-xs"
            onClick={() => state.removeRow(row.key)}
            disabled={locked}
            aria-label={`Remove ${label} override`}
          >
            Remove
          </button>
        </td>
      </tr>
      {hasIssues && (
        <tr className="scenario-override-issue-row">
          <td colSpan={withUnit ? 5 : 4}>
            <ul id={issuesId} className="scenario-override-issues" role="alert">
              {issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          </td>
        </tr>
      )}
    </Fragment>
  );
}

export function ScenarioEditor({ id, state, editor }: ScenarioEditorProps) {
  const nameInput = useRef<HTMLInputElement>(null);
  const feedback = state.feedback;
  const locked = !state.canEdit;
  const withUnit = state.investment !== null;
  const taken = new Set(
    editor.rows.filter((row) => row.target !== '').map((row) => takenKey(row.unitId, row.target)),
  );
  const rowUnits = withUnit ? state.units.map((unit) => unit.unitId) : [''];
  const canAddRow =
    state.catalogStatus === 'ready' &&
    rowUnits.some((unitId) => state.targetsFor(unitId).some((entry) => !taken.has(takenKey(unitId, entry.target))));

  useEffect(() => {
    nameInput.current?.focus();
  }, []);

  return (
    <section id={id} className="scenario-editor" aria-labelledby="scenario-editor-title">
      <h4 id="scenario-editor-title" className="scenario-editor-title">
        {editor.scenarioId === null ? 'New Scenario' : 'Edit Scenario'}
      </h4>

      {feedback !== null && (
        <div className="error-banner scenario-editor-feedback" role="alert">
          <p className="scenario-editor-feedback-message">{feedback.message}</p>
          {feedback.general.length > 0 && (
            <ul className="scenario-editor-feedback-list">
              {feedback.general.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {state.catalogStatus === 'error' && (
        <div className="error-banner scenario-error" role="alert">
          <span>{state.catalogError}</span>
          <button type="button" className="btn btn-ghost btn-xs" onClick={state.retryCatalog}>
            Retry
          </button>
        </div>
      )}

      <div className="scenario-editor-fields">
        <label className="field" htmlFor="scenario-editor-name">
          <span className="field-label">Scenario Name</span>
          <input
            ref={nameInput}
            id="scenario-editor-name"
            className="field-input"
            type="text"
            value={editor.name}
            onChange={(event) => state.setEditorName(event.target.value)}
            disabled={locked}
            autoComplete="off"
          />
        </label>
        <label className="field" htmlFor="scenario-editor-description">
          <span className="field-label">Description (optional)</span>
          <input
            id="scenario-editor-description"
            className="field-input"
            type="text"
            value={editor.description}
            onChange={(event) => state.setEditorDescription(event.target.value)}
            disabled={locked}
            autoComplete="off"
          />
        </label>
      </div>

      <div className="scenario-override-block">
        <table className={withUnit ? 'scenario-override-table scenario-override-table-units' : 'scenario-override-table'}>
          <caption className="scenario-override-caption">Assumption overrides</caption>
          <thead>
            <tr>
              {withUnit && <th scope="col">Unit</th>}
              <th scope="col">Assumption</th>
              <th scope="col">Operation</th>
              <th scope="col">Value</th>
              <th scope="col">
                <span className="visually-hidden">Remove</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {editor.rows.map((row) => (
              <OverrideRow
                key={row.key}
                row={row}
                taken={taken}
                issues={feedback?.byRow[row.key] ?? []}
                state={state}
                withUnit={withUnit}
              />
            ))}
          </tbody>
        </table>
        {editor.rows.length === 0 && (
          <p className="field-hint scenario-override-empty">
            No overrides. This scenario resolves to Base until one is added.
          </p>
        )}
        {state.catalogStatus === 'loading' && (
          <p className="scenario-muted" role="status">
            Loading assumptions…
          </p>
        )}
        <div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={state.addRow} disabled={locked || !canAddRow}>
            Add Override
          </button>
        </div>
      </div>

      <div className="scenario-editor-actions">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={state.cancelEdit}
          disabled={state.isSaving}
        >
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => void state.saveEditor()}
          disabled={state.isSaving || !state.canEdit}
        >
          {state.isSaving ? 'Saving…' : 'Save Scenario'}
        </button>
      </div>
    </section>
  );
}
