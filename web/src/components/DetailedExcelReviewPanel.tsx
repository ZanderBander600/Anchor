import type { ChangeEvent } from 'react';
import { SpreadsheetIcon } from './ExcelUploadPanel';
import { DETAILED_OPERATING_FIELD_GROUPS, TERMS_FIELD_GROUPS } from '../convert';
import type { AcquisitionTermsFormValues, DetailedOperatingFormValues } from '../types';

interface DetailedExcelReviewPanelProps {
  fileName: string;
  termsValues: AcquisitionTermsFormValues;
  operatingValues: DetailedOperatingFormValues;
  error: string | null;
  onTermsFieldChange: (key: keyof AcquisitionTermsFormValues, value: string) => void;
  onOperatingFieldChange: (key: keyof DetailedOperatingFormValues, value: string) => void;
  onApprove: () => void;
  onCancel: () => void;
}

/**
 * Detailed Operating Model V2.1 Gate 10 -- the Detailed counterpart to
 * `ExcelReviewPanel`, over the Detailed workbook's own two field sets
 * (`AcquisitionTerms` + `DetailedOperatingInputs`) instead of Quick's
 * fourteen. Same analyst-control philosophy: everything here is a
 * temporary, editable proposal -- nothing reaches `DetailedFormValues` (and
 * therefore nothing marks the Detailed workspace's downstream analysis
 * state) until "Approve & Load Assumptions" is clicked. Unlike
 * `ExcelReviewPanel`, there is no "Requires input" badge -- every Detailed
 * Field ID is always required and the backend never returns a partial
 * result, so nothing is ever defaulted-and-blanked here.
 */
export function DetailedExcelReviewPanel({
  fileName,
  termsValues,
  operatingValues,
  error,
  onTermsFieldChange,
  onOperatingFieldChange,
  onApprove,
  onCancel,
}: DetailedExcelReviewPanelProps) {
  return (
    <section className="card excel-review-panel">
      <div className="card-title-row">
        <span className="card-icon card-icon-excel">
          <SpreadsheetIcon />
        </span>
        <div>
          <h3 className="card-title">Detailed Excel Ingestion Review</h3>
          <p className="card-subtitle">{fileName}</p>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <h4 className="detailed-form-section-title">Acquisition, Transaction &amp; Debt</h4>
      <div className="excel-review-groups">
        {TERMS_FIELD_GROUPS.map((group) => (
          <div className="excel-review-group" key={group.title}>
            <h4 className="assumptions-group-title">{group.title}</h4>
            {group.fields.map((field) => (
              <div className="field" key={field.key}>
                <span className="om-field-header">
                  <span className="field-label">{field.label}</span>
                </span>
                <div className="field-input-wrap">
                  {field.prefix && (
                    <span className="field-affix field-affix-left">{field.prefix}</span>
                  )}
                  <input
                    className="field-input"
                    type="number"
                    inputMode="decimal"
                    step="any"
                    aria-label={`Detailed Excel Review ${field.label}`}
                    value={termsValues[field.key]}
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
              </div>
            ))}
          </div>
        ))}
      </div>

      <h4 className="detailed-form-section-title">Detailed Operating Model</h4>
      <div className="excel-review-groups">
        {DETAILED_OPERATING_FIELD_GROUPS.map((group) => (
          <div className="excel-review-group" key={group.title}>
            <h4 className="assumptions-group-title">{group.title}</h4>
            {group.fields.map((field) => (
              <div className="field" key={field.key}>
                <span className="om-field-header">
                  <span className="field-label">{field.label}</span>
                </span>
                <div className="field-input-wrap">
                  {field.prefix && (
                    <span className="field-affix field-affix-left">{field.prefix}</span>
                  )}
                  <input
                    className="field-input"
                    type="number"
                    inputMode="decimal"
                    step="any"
                    aria-label={`Detailed Excel Review ${field.label}`}
                    value={operatingValues[field.key]}
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
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="om-handoff">
        <p className="om-excluded-summary">
          Reviewing &ldquo;{fileName}&rdquo;. Edit any value above, then approve to load these into
          the Detailed deal.
        </p>
        <div className="excel-review-actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Cancel Review
          </button>
          <button type="button" className="btn btn-primary" onClick={onApprove}>
            Approve &amp; Load Assumptions
          </button>
        </div>
      </div>
    </section>
  );
}
