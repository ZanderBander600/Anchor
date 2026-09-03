import { useState } from 'react';
import type { ChangeEvent } from 'react';
import { DocumentIcon, FieldReviewCard } from './OmReviewPanel';
import type { FieldReviewState } from './OmReviewPanel';
import {
  DETAILED_OM_FIELD_LABELS,
  DETAILED_OPERATING_FIELD_GROUPS,
  DETAILED_OPERATING_FIELD_TO_FORM_KEY,
  DETAILED_TERMS_FIELD_TO_FORM_KEY,
  TERMS_FIELD_GROUPS,
} from '../convert';
import type {
  AcquisitionTermsFormValues,
  DetailedExtractionResult,
  DetailedOperatingFieldId,
  DetailedOperatingFormValues,
  DetailedTermsFieldId,
} from '../types';
import { DETAILED_OPERATING_FIELD_IDS, DETAILED_TERMS_FIELD_IDS } from '../types';

type DetailedFieldId = DetailedTermsFieldId | DetailedOperatingFieldId;
type ReviewStateMap = Record<DetailedFieldId, FieldReviewState>;

const ALL_DETAILED_OM_FIELD_IDS: readonly DetailedFieldId[] = [
  ...DETAILED_TERMS_FIELD_IDS,
  ...DETAILED_OPERATING_FIELD_IDS,
];

/** Inverse of `DETAILED_TERMS_FIELD_TO_FORM_KEY`/
 * `DETAILED_OPERATING_FIELD_TO_FORM_KEY` -- lets the group layout (keyed by
 * camelCase form key, same as `DetailedAssumptionsForm`) look up which
 * snake_case Detailed Field ID each group entry corresponds to, without a
 * second hand-maintained field list. */
const FORM_KEY_TO_TERMS_FIELD_ID = new Map<keyof AcquisitionTermsFormValues, DetailedTermsFieldId>(
  DETAILED_TERMS_FIELD_IDS.map((fieldId) => [DETAILED_TERMS_FIELD_TO_FORM_KEY[fieldId], fieldId]),
);
const FORM_KEY_TO_OPERATING_FIELD_ID = new Map<
  keyof DetailedOperatingFormValues,
  DetailedOperatingFieldId
>(
  DETAILED_OPERATING_FIELD_IDS.map((fieldId) => [
    DETAILED_OPERATING_FIELD_TO_FORM_KEY[fieldId],
    fieldId,
  ]),
);

function initialReviewStates(): ReviewStateMap {
  const map = {} as ReviewStateMap;
  for (const fieldId of ALL_DETAILED_OM_FIELD_IDS) {
    map[fieldId] = { kind: 'pending' };
  }
  return map;
}

interface DetailedOmReviewPanelProps {
  extraction: DetailedExtractionResult | null;
  isLoading: boolean;
  error: string | null;
  onUpload: (file: File) => void;
  onFinishReview: (approvedValues: Partial<Record<DetailedFieldId, string>>) => void;
  onCancel: () => void;
}

/**
 * Detailed Operating Model V2.1 Gate 12 -- the Detailed counterpart to
 * `OmReviewPanel`, over the 22 Detailed target fields (the eleven
 * `AcquisitionTerms` fields plus the eleven `DetailedOperatingInputs`
 * fields) instead of Quick's nine. Reuses `FieldReviewCard`/`CandidateRow`/
 * `EvidenceBadge`/`ReviewStateBadge` exactly as-is -- the same per-field
 * approve/edit/reject review-state machine and evidence language, never a
 * second implementation of it. No deal-context section (out of this
 * gate's scope).
 *
 * Unlike Quick's `OmReviewPanel`, this panel also exposes an explicit
 * "Cancel Review" action: Quick's OM review has no such control (a new
 * upload simply replaces it, and New/Open Deal clears it), but Gate 12
 * explicitly requires a saved Detailed deal to survive an OM upload
 * untouched until an explicit approve/cancel decision -- the same
 * analyst-control guarantee Gate 10's Excel review already gives Detailed
 * mode.
 */
export function DetailedOmReviewPanel({
  extraction,
  isLoading,
  error,
  onUpload,
  onFinishReview,
  onCancel,
}: DetailedOmReviewPanelProps) {
  const [reviewStates, setReviewStates] = useState<ReviewStateMap>(initialReviewStates);
  // Resets review state when a new extraction arrives, without an effect.
  const [lastExtraction, setLastExtraction] = useState(extraction);
  if (extraction !== lastExtraction) {
    setLastExtraction(extraction);
    setReviewStates(initialReviewStates());
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) {
      onUpload(file);
    }
  }

  function handleApprove(fieldId: DetailedFieldId, candidateIndex: number, value: string) {
    setReviewStates((previous) => ({
      ...previous,
      [fieldId]: { kind: 'approved', value, candidateIndex },
    }));
  }

  function handleEdit(fieldId: DetailedFieldId, value: string) {
    setReviewStates((previous) => ({
      ...previous,
      [fieldId]: { kind: 'approved', value, candidateIndex: null },
    }));
  }

  function handleReject(fieldId: DetailedFieldId) {
    setReviewStates((previous) => ({ ...previous, [fieldId]: { kind: 'rejected' } }));
  }

  const excludedLabels = ALL_DETAILED_OM_FIELD_IDS.filter(
    (fieldId) => reviewStates[fieldId].kind !== 'approved',
  ).map((fieldId) => DETAILED_OM_FIELD_LABELS[fieldId]);

  function handleFinish() {
    const approvedValues: Partial<Record<DetailedFieldId, string>> = {};
    for (const fieldId of ALL_DETAILED_OM_FIELD_IDS) {
      const state = reviewStates[fieldId];
      if (state.kind === 'approved') {
        approvedValues[fieldId] = state.value;
      }
    }
    onFinishReview(approvedValues);
  }

  return (
    <section className="card om-review-panel">
      <div className="card-title-row">
        <span className="card-icon card-icon-om">
          <DocumentIcon />
        </span>
        <div>
          <h3 className="card-title">Detailed OM Ingestion Review</h3>
          <p className="card-subtitle">Offering Memorandum (PDF)</p>
        </div>
      </div>

      <div className="om-upload-row">
        <label className="om-upload-label" htmlFor="detailed-om-upload-input">
          Upload OM (PDF)
        </label>
        <input
          id="detailed-om-upload-input"
          type="file"
          accept="application/pdf"
          onChange={handleFileChange}
          disabled={isLoading}
        />
      </div>

      {isLoading && <div className="om-status">Extracting proposed assumptions…</div>}

      {error && <div className="error-banner">{error}</div>}

      {!extraction && !isLoading && !error && (
        <div className="om-empty">
          Upload an Offering Memorandum PDF to propose Detailed assumption values for review.
        </div>
      )}

      {extraction && !isLoading && (
        <div className="om-review-body">
          <div className="om-fields">
            {TERMS_FIELD_GROUPS.map((group) => (
              <div key={group.title}>
                <h4 className="om-section-title">{group.title}</h4>
                {group.fields.map((field) => {
                  const fieldId = FORM_KEY_TO_TERMS_FIELD_ID.get(field.key);
                  if (!fieldId) {
                    return null;
                  }
                  return (
                    <FieldReviewCard
                      key={fieldId}
                      label={field.label}
                      field={extraction[fieldId]}
                      reviewState={reviewStates[fieldId]}
                      onApprove={(candidateIndex, value) =>
                        handleApprove(fieldId, candidateIndex, value)
                      }
                      onEdit={(value) => handleEdit(fieldId, value)}
                      onReject={() => handleReject(fieldId)}
                    />
                  );
                })}
              </div>
            ))}

            {DETAILED_OPERATING_FIELD_GROUPS.map((group) => (
              <div key={group.title}>
                <h4 className="om-section-title">{group.title}</h4>
                {group.fields.map((field) => {
                  const fieldId = FORM_KEY_TO_OPERATING_FIELD_ID.get(field.key);
                  if (!fieldId) {
                    return null;
                  }
                  return (
                    <FieldReviewCard
                      key={fieldId}
                      label={field.label}
                      field={extraction[fieldId]}
                      reviewState={reviewStates[fieldId]}
                      onApprove={(candidateIndex, value) =>
                        handleApprove(fieldId, candidateIndex, value)
                      }
                      onEdit={(value) => handleEdit(fieldId, value)}
                      onReject={() => handleReject(fieldId)}
                    />
                  );
                })}
              </div>
            ))}
          </div>

          <div className="om-handoff">
            <p className="om-excluded-summary">
              {excludedLabels.length > 0
                ? `Not carried to the form (still pending, rejected, or unresolved): ${excludedLabels.join(', ')}.`
                : 'All fields reviewed and approved.'}
            </p>
            <div className="excel-review-actions">
              <button type="button" className="btn btn-ghost" onClick={onCancel}>
                Cancel Review
              </button>
              <button type="button" className="btn btn-primary" onClick={handleFinish}>
                Use approved values
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
