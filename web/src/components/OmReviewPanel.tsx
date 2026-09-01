import { useState } from 'react';
import type { ChangeEvent } from 'react';
import { ACQUISITION_FIELD_LABELS } from '../convert';
import type {
  AcquisitionFieldId,
  DealContext,
  EvidenceStatus,
  ExtractionCandidate,
  ExtractionResult,
  FieldCandidates,
} from '../types';
import { ACQUISITION_FIELD_IDS } from '../types';

function DocumentIcon() {
  return (
    <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false">
      <path
        d="M5 2.5h6.5L15 6v11.5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-14a1 1 0 0 1 1-1Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
      <path d="M11.5 2.5V6H15" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M6.5 10h6M6.5 12.5h6M6.5 15h4" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  );
}

const EVIDENCE_LABELS: Record<EvidenceStatus, string> = {
  stated: 'Stated',
  interpreted: 'Interpreted',
  conflicting: 'Conflicting',
  unverifiable: 'Unverifiable',
  missing: 'Missing',
};

const DEAL_CONTEXT_FIELDS: { key: keyof DealContext; label: string }[] = [
  { key: 'property_name', label: 'Property Name' },
  { key: 'address', label: 'Address' },
  { key: 'property_type', label: 'Property Type' },
  { key: 'unit_count_or_building_area', label: 'Unit Count / Building Area' },
  { key: 'year_built', label: 'Year Built' },
];

type FieldReviewState =
  | { kind: 'pending' }
  | { kind: 'approved'; value: string; candidateIndex: number | null }
  | { kind: 'rejected' };

type ReviewStateMap = Record<AcquisitionFieldId, FieldReviewState>;

function initialReviewStates(): ReviewStateMap {
  const map = {} as ReviewStateMap;
  for (const fieldId of ACQUISITION_FIELD_IDS) {
    map[fieldId] = { kind: 'pending' };
  }
  return map;
}

function EvidenceBadge({ status }: { status: EvidenceStatus }) {
  return (
    <span className={`om-evidence-badge om-evidence-badge-${status}`}>{EVIDENCE_LABELS[status]}</span>
  );
}

function ReviewStateBadge({ state }: { state: FieldReviewState }) {
  const label =
    state.kind === 'pending' ? 'Pending review' : state.kind === 'approved' ? 'Approved' : 'Rejected';
  return <span className={`om-review-state-badge om-review-state-badge-${state.kind}`}>{label}</span>;
}

interface CandidateRowProps {
  candidate: ExtractionCandidate;
  isApproved: boolean;
  onApprove: () => void;
}

function CandidateRow({ candidate, isApproved, onApprove }: CandidateRowProps) {
  return (
    <div className={`om-candidate om-candidate-${candidate.status}`}>
      <div className="om-candidate-value-row">
        <span className="om-candidate-value">{candidate.value}</span>
        <EvidenceBadge status={candidate.status} />
      </div>
      {candidate.provenance ? (
        <p className="om-candidate-provenance">
          Page {candidate.provenance.page}: &ldquo;{candidate.provenance.snippet}&rdquo;
        </p>
      ) : (
        <p className="om-candidate-provenance om-candidate-provenance-none">
          No verifiable source citation.
        </p>
      )}
      <button
        type="button"
        className="btn btn-secondary btn-sm om-approve-button"
        onClick={onApprove}
      >
        {isApproved ? 'Approved' : 'Approve'}
      </button>
    </div>
  );
}

interface FieldReviewCardProps {
  fieldId: AcquisitionFieldId;
  field: FieldCandidates;
  reviewState: FieldReviewState;
  onApprove: (candidateIndex: number, value: string) => void;
  onEdit: (value: string) => void;
  onReject: () => void;
}

function FieldReviewCard({ fieldId, field, reviewState, onApprove, onEdit, onReject }: FieldReviewCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const label = ACQUISITION_FIELD_LABELS[fieldId];
  const isMissing = field.candidates.length === 0;

  function startEdit() {
    const current = reviewState.kind === 'approved' ? reviewState.value : (field.candidates[0]?.value ?? '');
    setDraft(current);
    setIsEditing(true);
  }

  function commitEdit() {
    onEdit(draft);
    setIsEditing(false);
  }

  // R7/R11 boundary: a truly missing field carries no document evidence at
  // all, so the review screen offers no value-entry, edit, or approval
  // control for it -- this stays a document-evidence review surface, not a
  // second place to originate underwriting assumptions. The field simply
  // stays absent from the handoff; the analyst supplies it (if at all) in
  // the existing AssumptionsForm, exactly as today.
  if (isMissing) {
    return (
      <div className="om-field-card om-field-card-missing">
        <div className="om-field-header">
          <h4 className="om-field-label">{label}</h4>
          <EvidenceBadge status="missing" />
        </div>
        <p className="om-field-missing">Not found in OM.</p>
      </div>
    );
  }

  return (
    <div className="om-field-card">
      <div className="om-field-header">
        <h4 className="om-field-label">{label}</h4>
        <ReviewStateBadge state={reviewState} />
      </div>

      {field.candidates.map((candidate, index) => (
        <CandidateRow
          key={index}
          candidate={candidate}
          isApproved={reviewState.kind === 'approved' && reviewState.candidateIndex === index}
          onApprove={() => onApprove(index, candidate.value)}
        />
      ))}

      <div className="om-field-actions">
        {isEditing ? (
          <>
            <input
              className="om-edit-input"
              aria-label={`Edit ${label}`}
              value={draft}
              onChange={(event: ChangeEvent<HTMLInputElement>) => setDraft(event.target.value)}
            />
            <button type="button" className="btn btn-ghost btn-sm" onClick={commitEdit}>
              Save
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setIsEditing(false)}>
              Cancel
            </button>
          </>
        ) : (
          <button type="button" className="btn btn-ghost btn-sm" onClick={startEdit}>
            Edit
          </button>
        )}
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onReject}
          disabled={reviewState.kind === 'rejected'}
        >
          Reject
        </button>
      </div>
    </div>
  );
}

function DealContextRow({ label, field }: { label: string; field: FieldCandidates }) {
  const values = field.candidates.map((candidate) => candidate.value);
  return (
    <div className="om-deal-context-row">
      <span className="om-deal-context-label">{label}</span>
      <span className="om-deal-context-value">
        {values.length > 0 ? values.join(' / ') : 'Not found in document'}
      </span>
    </div>
  );
}

interface OmReviewPanelProps {
  extraction: ExtractionResult | null;
  isLoading: boolean;
  error: string | null;
  onUpload: (file: File) => void;
  onFinishReview: (approvedValues: Partial<Record<AcquisitionFieldId, string>>) => void;
}

/**
 * Lets the analyst upload an OM PDF and review, edit, approve, or reject
 * each proposed acquisition-input candidate before any value reaches
 * `AssumptionsForm` (R9, R11). A field with no candidate at all (missing --
 * R7) renders as read-only "Not found in OM" with no value-entry, edit, or
 * approval control of any kind -- this stays a document-evidence review
 * surface, never a second place to originate an underwriting assumption
 * the OM doesn't support. Deal-context fields render read-only alongside
 * the review too (R10). Approving, editing, and rejecting a field is purely
 * local UI state -- nothing here calls `/analyze`; "Use approved values"
 * only ever hands proposed, document-derived values up to the caller
 * (KTD4/KTD5).
 */
export function OmReviewPanel({ extraction, isLoading, error, onUpload, onFinishReview }: OmReviewPanelProps) {
  const [reviewStates, setReviewStates] = useState<ReviewStateMap>(initialReviewStates);
  // Resets review state when a new extraction arrives, without an effect
  // (https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes).
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

  function handleApprove(fieldId: AcquisitionFieldId, candidateIndex: number, value: string) {
    setReviewStates((previous) => ({
      ...previous,
      [fieldId]: { kind: 'approved', value, candidateIndex },
    }));
  }

  function handleEdit(fieldId: AcquisitionFieldId, value: string) {
    setReviewStates((previous) => ({
      ...previous,
      [fieldId]: { kind: 'approved', value, candidateIndex: null },
    }));
  }

  function handleReject(fieldId: AcquisitionFieldId) {
    setReviewStates((previous) => ({ ...previous, [fieldId]: { kind: 'rejected' } }));
  }

  const excludedLabels = ACQUISITION_FIELD_IDS.filter(
    (fieldId) => reviewStates[fieldId].kind !== 'approved',
  ).map((fieldId) => ACQUISITION_FIELD_LABELS[fieldId]);

  function handleFinish() {
    const approvedValues: Partial<Record<AcquisitionFieldId, string>> = {};
    for (const fieldId of ACQUISITION_FIELD_IDS) {
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
          <h3 className="card-title">OM Ingestion Review</h3>
          <p className="card-subtitle">Offering Memorandum (PDF)</p>
        </div>
      </div>

      <div className="om-upload-row">
        <label className="om-upload-label" htmlFor="om-upload-input">
          Upload OM (PDF)
        </label>
        <input
          id="om-upload-input"
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
          Upload an Offering Memorandum PDF to propose assumption values for review.
        </div>
      )}

      {extraction && !isLoading && (
        <div className="om-review-body">
          <div className="om-deal-context">
            <h4 className="om-section-title">Deal Context (reference only)</h4>
            {DEAL_CONTEXT_FIELDS.map(({ key, label }) => (
              <DealContextRow key={key} label={label} field={extraction.deal_context[key]} />
            ))}
          </div>

          <div className="om-fields">
            {ACQUISITION_FIELD_IDS.map((fieldId) => (
              <FieldReviewCard
                key={fieldId}
                fieldId={fieldId}
                field={extraction[fieldId]}
                reviewState={reviewStates[fieldId]}
                onApprove={(candidateIndex, value) => handleApprove(fieldId, candidateIndex, value)}
                onEdit={(value) => handleEdit(fieldId, value)}
                onReject={() => handleReject(fieldId)}
              />
            ))}
          </div>

          <div className="om-handoff">
            <p className="om-excluded-summary">
              {excludedLabels.length > 0
                ? `Not carried to the form (still pending, rejected, or unresolved): ${excludedLabels.join(', ')}.`
                : 'All fields reviewed and approved.'}
            </p>
            <button type="button" className="btn btn-primary" onClick={handleFinish}>
              Use approved values
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
