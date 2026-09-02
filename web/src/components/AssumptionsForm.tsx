import type { ChangeEvent, FormEvent } from 'react';
import type { AcquisitionFormValues } from '../types';

interface FieldConfig {
  key: keyof AcquisitionFormValues;
  label: string;
  prefix?: string;
  suffix?: string;
}

interface FieldGroup {
  title: string;
  fields: FieldConfig[];
}

const FIELD_GROUPS: FieldGroup[] = [
  {
    title: 'Acquisition',
    fields: [
      { key: 'purchasePrice', label: 'Purchase Price', prefix: '$' },
      { key: 'currentNoi', label: 'Current NOI', prefix: '$' },
      { key: 'occupancy', label: 'Occupancy', suffix: '%' },
    ],
  },
  {
    title: 'Growth & Exit',
    fields: [
      { key: 'noiGrowth', label: 'NOI Growth', suffix: '%' },
      { key: 'holdPeriod', label: 'Hold Period', suffix: 'yrs' },
      { key: 'exitCapRate', label: 'Exit Cap Rate', suffix: '%' },
    ],
  },
  {
    title: 'Transaction Costs',
    fields: [
      { key: 'acquisitionCostPct', label: 'Acquisition Costs', suffix: '%' },
      { key: 'financingFeePct', label: 'Financing Fee', suffix: '%' },
      { key: 'dispositionCostPct', label: 'Disposition Costs', suffix: '%' },
    ],
  },
  {
    title: 'Operations',
    fields: [{ key: 'annualCapexReserve', label: 'Annual CapEx Reserve', prefix: '$' }],
  },
  {
    title: 'Financing',
    fields: [
      { key: 'ltv', label: 'LTV', suffix: '%' },
      { key: 'interestRate', label: 'Interest Rate', suffix: '%' },
      { key: 'amortization', label: 'Amortization', suffix: 'yrs' },
      { key: 'ioPeriod', label: 'Interest-Only Period', suffix: 'yrs' },
    ],
  },
];

interface AssumptionsFormProps {
  values: AcquisitionFormValues;
  onFieldChange: (key: keyof AcquisitionFormValues, value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  isSubmitting: boolean;
}

export function AssumptionsForm({
  values,
  onFieldChange,
  onSubmit,
  isSubmitting,
}: AssumptionsFormProps) {
  return (
    <form className="card assumptions-form" onSubmit={onSubmit}>
      <h2 className="card-title">Assumptions</h2>
      <div className="field-grid">
        {FIELD_GROUPS.map((group) => (
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
                      value={values[field.key]}
                      disabled={isSubmitting}
                      onChange={(event: ChangeEvent<HTMLInputElement>) =>
                        onFieldChange(field.key, event.target.value)
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
