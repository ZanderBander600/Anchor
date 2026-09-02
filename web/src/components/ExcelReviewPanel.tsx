import type { ChangeEvent } from 'react';
import { SpreadsheetIcon } from './ExcelUploadPanel';
import { ASSUMPTIONS_FIELD_GROUPS, buildV2ReviewMessage, V2_FIELD_TO_FORM_KEY } from '../convert';
import type { AcquisitionFormValues, V2FieldId } from '../types';
import { V2_FIELD_IDS } from '../types';

/** Inverse of `V2_FIELD_TO_FORM_KEY` -- looks up which V2 Field ID (if any)
 * a given `AssumptionsForm` key corresponds to, so a review field can be
 * marked "Requires input" without a second, hand-maintained field list. */
const FORM_KEY_TO_V2_FIELD_ID = new Map<keyof AcquisitionFormValues, V2FieldId>(
  V2_FIELD_IDS.map((fieldId) => [V2_FIELD_TO_FORM_KEY[fieldId], fieldId]),
);

interface ExcelReviewPanelProps {
  fileName: string;
  values: AcquisitionFormValues;
  /** Underwriting V2 Gate 6: the V2 Field IDs the workbook left defaulted
   * (absent) -- these must be completed by the analyst, explicit `0`
   * included, before approval is allowed. Empty for a complete
   * fourteen-field workbook. */
  requiredV2FieldIds: V2FieldId[];
  error: string | null;
  onFieldChange: (key: keyof AcquisitionFormValues, value: string) => void;
  onApprove: () => void;
  onCancel: () => void;
}

/**
 * Analyst-control review surface for a parsed Excel workbook (same
 * philosophy as `OmReviewPanel`, R9/R11 for OM): the values here are
 * proposed assumptions only, held in temporary review state -- nothing
 * reaches the canonical `AssumptionsForm` (and therefore nothing marks the
 * active deal dirty) until the analyst clicks "Approve & Load Assumptions".
 * Editing here reuses the exact same grouping, labels, and display
 * conventions as `AssumptionsForm` (`ASSUMPTIONS_FIELD_GROUPS`), and
 * approval reuses `buildAcquisitionRequest`'s existing validation/
 * conversion (via the caller) rather than duplicating any financial
 * validation here.
 */
export function ExcelReviewPanel({
  fileName,
  values,
  requiredV2FieldIds,
  error,
  onFieldChange,
  onApprove,
  onCancel,
}: ExcelReviewPanelProps) {
  const requiredSet = new Set(requiredV2FieldIds);

  function v2FieldIdFor(key: keyof AcquisitionFormValues): V2FieldId | undefined {
    return FORM_KEY_TO_V2_FIELD_ID.get(key);
  }

  function isRequiredAndBlank(key: keyof AcquisitionFormValues): boolean {
    const v2FieldId = v2FieldIdFor(key);
    return v2FieldId !== undefined && requiredSet.has(v2FieldId) && values[key].trim() === '';
  }

  const stillBlankRequiredIds = requiredV2FieldIds.filter(
    (fieldId) => values[V2_FIELD_TO_FORM_KEY[fieldId]].trim() === '',
  );
  const reviewMessage = buildV2ReviewMessage(stillBlankRequiredIds);

  return (
    <section className="card excel-review-panel">
      <div className="card-title-row">
        <span className="card-icon card-icon-excel">
          <SpreadsheetIcon />
        </span>
        <div>
          <h3 className="card-title">Excel Ingestion Review</h3>
          <p className="card-subtitle">{fileName}</p>
        </div>
      </div>

      {reviewMessage && <div className="v2-review-banner">{reviewMessage}</div>}

      {error && <div className="error-banner">{error}</div>}

      <div className="excel-review-groups">
        {ASSUMPTIONS_FIELD_GROUPS.map((group) => (
          <div className="excel-review-group" key={group.title}>
            <h4 className="assumptions-group-title">{group.title}</h4>
            {group.fields.map((field) => {
              const requiredAndBlank = isRequiredAndBlank(field.key);
              return (
                // A plain `div` (not `label`) deliberately -- the input's
                // accessible name comes solely from its own `aria-label`
                // below (disambiguated from AssumptionsForm's identical
                // field labels for `getByLabelText`); a wrapping `<label>`
                // would additionally expose this text as its own implicit
                // label, colliding with AssumptionsForm's.
                <div className="field" key={field.key}>
                  <span className="om-field-header">
                    <span className="field-label">{field.label}</span>
                    {requiredAndBlank && (
                      <span className="om-evidence-badge om-evidence-badge-conflicting">
                        Requires input
                      </span>
                    )}
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
                      aria-label={`Excel Review ${field.label}`}
                      value={values[field.key]}
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
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div className="om-handoff">
        <p className="om-excluded-summary">
          Reviewing &ldquo;{fileName}&rdquo;. Edit any value above, then approve to load these into
          the deal.
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
