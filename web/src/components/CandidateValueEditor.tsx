/**
 * D5.7 -- the candidate-value editor.
 *
 * A dense row of numeric fields, one per candidate, with Add and Remove. Not a
 * modal, not a wizard, not a stepper: entering five exit caps is something an
 * analyst does dozens of times a day, so it costs one click per value and every
 * value stays on screen and editable at all times.
 *
 * **Every value here is absolute and visible.** There is no "±10%", no
 * "Low / Base / High", and no collapsed summary. What the fields show is what
 * the run submits, after the same percent convention the Underwrite form
 * applies to the same assumption.
 *
 * **The generator populates these fields and nothing else.** Centre / step /
 * count writes absolute values *into* the inputs below, where they become
 * ordinary editable entries; it never reaches the API, never touches a result,
 * and the arithmetic behind it lives alone in `leaseLevelSensitivityLadder.ts`.
 * This component performs no arithmetic of its own.
 */

import { NumericInput } from './NumericInput';
import { groupsThousands } from '../numberFormat';
import { generateLadderValues } from '../leaseLevelSensitivityLadder';
import type { LadderDraft } from '../leaseLevelSensitivityLadder';
import type { LeaseLevelSensitivityTargetConfig } from '../leaseLevelSensitivity';

export interface CandidateValueEditorProps {
  /** Prefix for every input id, so two editors can coexist on one screen. */
  idPrefix: string;
  /** Names the group for assistive technology, e.g. "Row candidate values". */
  legend: string;
  target: LeaseLevelSensitivityTargetConfig;
  values: string[];
  onChange: (values: string[]) => void;
  ladder: LadderDraft;
  onLadderChange: (ladder: LadderDraft) => void;
  disabled: boolean;
}

export function CandidateValueEditor({
  idPrefix,
  legend,
  target,
  values,
  onChange,
  ladder,
  onLadderChange,
  disabled,
}: CandidateValueEditorProps) {
  const group = groupsThousands(target);
  // A percentage needs room for `6.25`; a purchase price needs room for
  // `84,000,000`. Sizing the field to its unit is what keeps a row of five
  // candidates compact enough to read as one set of assumptions.
  const width = target.unit === 'percent' ? 'sensitivity-candidate-input-narrow' : '';
  const unitHint =
    target.unit === 'percent'
      ? 'Entered as percentages, e.g. 6.25 for 6.25%.'
      : target.unit === 'currency_psf'
        ? 'Entered as dollars per square foot.'
        : 'Entered as whole dollars.';

  function setValueAt(index: number, next: string): void {
    onChange(values.map((value, position) => (position === index ? next : value)));
  }

  function removeAt(index: number): void {
    onChange(values.filter((_, position) => position !== index));
  }

  function generate(): void {
    const generated = generateLadderValues(
      Number(ladder.center),
      Number(ladder.step),
      Number(ladder.count),
    );
    if (generated.length > 0) {
      onChange(generated);
    }
  }

  return (
    <fieldset className="sensitivity-candidates">
      <legend className="sensitivity-candidates-legend">{legend}</legend>

      <div className="sensitivity-candidate-list">
        {values.map((value, index) => (
          <div className="sensitivity-candidate" key={`${idPrefix}-${index}`}>
            {target.prefix && <span className="sensitivity-candidate-affix">{target.prefix}</span>}
            <NumericInput
              id={`${idPrefix}-value-${index}`}
              className={`field-input sensitivity-candidate-input ${width}`.trim()}
              aria-label={`${legend} ${index + 1}`}
              value={value}
              group={group}
              disabled={disabled}
              onChange={(next) => setValueAt(index, next)}
            />
            {target.suffix && <span className="sensitivity-candidate-affix">{target.suffix}</span>}
            <button
              type="button"
              className="sensitivity-candidate-remove"
              disabled={disabled}
              aria-label={`Remove ${legend} ${index + 1}`}
              onClick={() => removeAt(index)}
            >
              ×
            </button>
          </div>
        ))}

        <button
          type="button"
          className="sensitivity-add-value"
          disabled={disabled}
          onClick={() => onChange([...values, ''])}
        >
          Add Value
        </button>
      </div>

      <p className="sensitivity-candidate-hint">{unitHint}</p>

      <div className="sensitivity-ladder">
        <span className="sensitivity-ladder-label">Fill from</span>
        <label className="sensitivity-ladder-field">
          <span>Centre</span>
          <NumericInput
            id={`${idPrefix}-ladder-center`}
            className="field-input"
            aria-label={`${legend} generator centre`}
            value={ladder.center}
            group={group}
            disabled={disabled}
            onChange={(next) => onLadderChange({ ...ladder, center: next })}
          />
        </label>
        <label className="sensitivity-ladder-field">
          <span>Step</span>
          <NumericInput
            id={`${idPrefix}-ladder-step`}
            className="field-input"
            aria-label={`${legend} generator step`}
            value={ladder.step}
            group={false}
            disabled={disabled}
            onChange={(next) => onLadderChange({ ...ladder, step: next })}
          />
        </label>
        <label className="sensitivity-ladder-field">
          <span>Count</span>
          <NumericInput
            id={`${idPrefix}-ladder-count`}
            className="field-input"
            aria-label={`${legend} generator count`}
            value={ladder.count}
            group={false}
            disabled={disabled}
            onChange={(next) => onLadderChange({ ...ladder, count: next })}
          />
        </label>
        <button
          type="button"
          className="sensitivity-ladder-apply"
          disabled={disabled}
          onClick={generate}
        >
          Fill Values
        </button>
      </div>
      <p className="sensitivity-candidate-hint">
        Fill writes absolute values into the fields above, where you can edit or delete
        any of them. The run submits exactly what those fields hold.
      </p>
    </fieldset>
  );
}
