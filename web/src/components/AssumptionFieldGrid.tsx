import type { ChangeEvent } from 'react';
import type { FieldSection } from '../underwrite';

export interface AssumptionFieldGridProps {
  sections: FieldSection[];
  disabled: boolean;
}

/**
 * Sprint C Gate C3 -- the single assumption-input renderer.
 *
 * Replaces the two near-identical form component trees (`AssumptionsForm`
 * and `DetailedAssumptionsForm`) with one component driven by resolved
 * sections, so Quick and Detailed share one visual language and one
 * accessibility contract while keeping completely independent state.
 *
 * Input semantics are unchanged from those forms: the same
 * `type="number"` / `inputMode="decimal"` / `step="any"` control, the same
 * raw string value, the same `disabled` behavior while an analysis is in
 * flight, and the same `onChange` string handed straight to the caller. No
 * parsing, coercion, reformatting, or validation happens here -- the
 * existing `convert.ts` conversion remains the only place a typed value
 * becomes a number.
 */
export function AssumptionFieldGrid({ sections, disabled }: AssumptionFieldGridProps) {
  return (
    <div className="assumption-sections">
      {sections.map((section) => (
        <section className="assumption-section" key={section.title}>
          <h3 className="assumption-section-title">{section.title}</h3>
          <div className="assumption-field-grid">
            {section.fields.map((field) => (
              <label className="field" key={field.id}>
                <span className="field-label">{field.label}</span>
                <div className="field-input-wrap">
                  {field.prefix && (
                    <span className="field-affix field-affix-left">{field.prefix}</span>
                  )}
                  <input
                    className="field-input"
                    type="number"
                    inputMode="decimal"
                    step="any"
                    value={field.value}
                    disabled={disabled}
                    onChange={(event: ChangeEvent<HTMLInputElement>) =>
                      field.onChange(event.target.value)
                    }
                    style={{
                      paddingLeft: field.prefix ? '1.4rem' : undefined,
                      paddingRight: field.suffix ? '2.4rem' : undefined,
                    }}
                  />
                  {field.suffix && (
                    <span className="field-affix field-affix-right">{field.suffix}</span>
                  )}
                </div>
              </label>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
