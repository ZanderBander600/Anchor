import type { ChangeEvent, FormEvent } from 'react';
import { DETAILED_OPERATING_FIELD_GROUPS, TERMS_FIELD_GROUPS } from '../convert';
import type { AcquisitionTermsFormValues, DetailedOperatingFormValues } from '../types';

interface DetailedAssumptionsFormProps {
  termsValues: AcquisitionTermsFormValues;
  operatingValues: DetailedOperatingFormValues;
  onTermsFieldChange: (key: keyof AcquisitionTermsFormValues, value: string) => void;
  onOperatingFieldChange: (key: keyof DetailedOperatingFormValues, value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  isSubmitting: boolean;
}

/**
 * Detailed Operating Model V2.1 Gate 6 -- the Detailed Underwrite form.
 *
 * Mirrors `AssumptionsForm`'s data-driven field-group layout exactly, over
 * two field sets instead of one: the 11 `AcquisitionTerms` acquisition/
 * transaction/debt assumptions (shared in shape with 11 of Quick's 14
 * fields), and the 11 `DetailedOperatingInputs` fields under their own
 * "Operating Model" heading. Neither section shows `current_noi` or
 * `noi_growth` as an editable assumption -- NOI is calculated, never
 * entered, in Detailed mode. No `occupancy` field appears here either: the
 * backend's `AcquisitionTerms`/`DetailedOperatingInputs` have no such
 * field, so there is nothing to render, and no risk of a second, competing
 * vacancy mechanism appearing next to `vacancyCreditLossPct`.
 */
export function DetailedAssumptionsForm({
  termsValues,
  operatingValues,
  onTermsFieldChange,
  onOperatingFieldChange,
  onSubmit,
  isSubmitting,
}: DetailedAssumptionsFormProps) {
  return (
    <form className="card assumptions-form detailed-assumptions-form" onSubmit={onSubmit}>
      <h2 className="card-title">Detailed Assumptions</h2>

      <h3 className="detailed-form-section-title">Acquisition, Transaction &amp; Debt</h3>
      <div className="field-grid">
        {TERMS_FIELD_GROUPS.map((group) => (
          <div className="assumptions-group" key={group.title}>
            <h3 className="assumptions-group-title">{group.title}</h3>
            <div className="assumptions-group-fields">
              {group.fields.map((field) => (
                <label className="field" key={field.key}>
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
                      value={termsValues[field.key]}
                      disabled={isSubmitting}
                      onChange={(event: ChangeEvent<HTMLInputElement>) =>
                        onTermsFieldChange(field.key, event.target.value)
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
          </div>
        ))}
      </div>

      <h3 className="detailed-form-section-title">Operating Model</h3>
      <div className="field-grid">
        {DETAILED_OPERATING_FIELD_GROUPS.map((group) => (
          <div className="assumptions-group" key={group.title}>
            <h3 className="assumptions-group-title">{group.title}</h3>
            <div className="assumptions-group-fields">
              {group.fields.map((field) => (
                <label className="field" key={field.key}>
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
                      value={operatingValues[field.key]}
                      disabled={isSubmitting}
                      onChange={(event: ChangeEvent<HTMLInputElement>) =>
                        onOperatingFieldChange(field.key, event.target.value)
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
          </div>
        ))}
      </div>

      <button className="btn btn-primary btn-block analyze-button" type="submit" disabled={isSubmitting}>
        {isSubmitting ? 'Analyzing…' : 'Analyze Deal'}
      </button>
    </form>
  );
}
