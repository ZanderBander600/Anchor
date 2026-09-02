import type { ChangeEvent } from 'react';

interface ExcelUploadPanelProps {
  isLoading: boolean;
  error: string | null;
  successMessage: string | null;
  onUpload: (file: File) => void;
}

export function SpreadsheetIcon() {
  return (
    <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false">
      <rect x="2.5" y="2.5" width="15" height="15" rx="2" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path
        d="M2.5 8h15M2.5 13h15M8 2.5v15M13 2.5v15"
        stroke="currentColor"
        strokeWidth="1.1"
      />
    </svg>
  );
}

/**
 * Lets the analyst upload a canonical Anchor Excel workbook. Unlike
 * `OmReviewPanel`, there is no per-field candidate/evidence review here --
 * the backend Excel reader either returns all fourteen fields already fully
 * validated (defaulting any absent Underwriting V2 field to a neutral
 * compatibility value, see `ExcelIntakeReport.defaulted_v2_field_ids`), or
 * rejects the whole upload with a 422 issue list. A successful upload never
 * touches the active `AssumptionsForm` itself -- it hands the parsed
 * workbook to `ExcelReviewPanel` as a temporary, analyst-editable review
 * state (same analyst-control philosophy as OM ingestion: Upload -> Review
 * -> Approve -> Populate Assumptions). `successMessage` is purely a visual
 * confirmation; it carries no approval semantics of its own.
 */
export function ExcelUploadPanel({
  isLoading,
  error,
  successMessage,
  onUpload,
}: ExcelUploadPanelProps) {
  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) {
      onUpload(file);
    }
  }

  return (
    <section className="card excel-upload-panel">
      <div className="card-title-row">
        <span className="card-icon card-icon-excel">
          <SpreadsheetIcon />
        </span>
        <div>
          <h3 className="card-title">Excel Upload</h3>
          <p className="card-subtitle">Canonical Anchor workbook (.xlsx)</p>
        </div>
      </div>

      <div className="excel-upload-row">
        <label className="excel-upload-label" htmlFor="excel-upload-input">
          Upload Anchor Workbook (.xlsx)
        </label>
        <input
          id="excel-upload-input"
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={handleFileChange}
          disabled={isLoading}
        />
      </div>

      {isLoading && <div className="excel-upload-status">Parsing workbook…</div>}

      {error && <div className="error-banner">{error}</div>}

      {!isLoading && !error && successMessage && (
        <div className="success-banner">{successMessage}</div>
      )}

      {!isLoading && !error && !successMessage && (
        <div className="excel-upload-empty">
          Upload the canonical Anchor .xlsx workbook to review its assumptions before loading them
          into the deal.
        </div>
      )}
    </section>
  );
}
