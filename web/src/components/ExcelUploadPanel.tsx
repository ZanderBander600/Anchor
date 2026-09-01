import type { ChangeEvent } from 'react';

interface ExcelUploadPanelProps {
  isLoading: boolean;
  error: string | null;
  successMessage: string | null;
  onUpload: (file: File) => void;
}

/**
 * Lets the analyst upload a canonical Anchor Excel workbook. Unlike
 * `OmReviewPanel`, there is no per-field candidate/evidence review here --
 * the backend Excel reader either returns all nine fields already fully
 * validated, or rejects the whole upload with a 422 issue list. A
 * successful upload pre-fills the existing `AssumptionsForm` (via the
 * parent's merge into `values`), where the analyst reviews and edits it
 * exactly like a manually typed or OM-approved value -- this panel never
 * calls `/analyze` itself. `successMessage` is purely a visual confirmation
 * that the import happened; it carries no approval semantics of its own.
 */
export function ExcelUploadPanel({ isLoading, error, successMessage, onUpload }: ExcelUploadPanelProps) {
  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) {
      onUpload(file);
    }
  }

  return (
    <section className="card excel-upload-panel">
      <h3 className="card-title">Excel Upload</h3>

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
          Upload the canonical Anchor .xlsx workbook to pre-fill the assumptions below.
        </div>
      )}
    </section>
  );
}
