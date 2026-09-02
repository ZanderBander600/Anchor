import type { ChangeEvent } from 'react';

/** Mirrors the three-state save status the Deal Bar surfaces. "unsaved-deal"
 * means the working deal has never been persisted at all (no id yet), even
 * if its fields are otherwise unchanged since a New Deal reset -- distinct
 * from "unsaved-changes", which means an already-saved/opened deal now
 * differs from its last-saved snapshot. */
export type SaveStatus = 'unsaved-deal' | 'unsaved-changes' | 'saved';

const SAVE_STATUS_LABEL: Record<SaveStatus, string> = {
  'unsaved-deal': 'Unsaved deal',
  'unsaved-changes': 'Unsaved changes',
  saved: 'Saved',
};

/** Formats an ISO 8601 timestamp for the "Saved · <when>" caption. Falls
 * back to omitting the timestamp rather than showing "Invalid Date". */
function formatLastSaved(iso: string): string | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export interface DealBarProps {
  dealName: string;
  onDealNameChange: (value: string) => void;
  isSavedDeal: boolean;
  isSaving: boolean;
  error: string | null;
  saveStatus: SaveStatus;
  lastSavedAt: string | null;
  onSaveDeal: () => void;
  onOpenLibrary: () => void;
  onNewDeal: () => void;
}

/**
 * The deal-identity strip: a name field, a save-status indicator,
 * Save/Update Deal, and navigation to the Deal Library or a fresh New
 * Deal. Persists only the nine assumptions already on the form via the
 * existing conversion/validation path (``buildAcquisitionRequest``) --
 * this component performs no validation, calculation, dirty-state
 * computation, or `/analyze` call of its own; `saveStatus` is computed by
 * the caller from a saved-snapshot comparison.
 */
export function DealBar({
  dealName,
  onDealNameChange,
  isSavedDeal,
  isSaving,
  error,
  saveStatus,
  lastSavedAt,
  onSaveDeal,
  onOpenLibrary,
  onNewDeal,
}: DealBarProps) {
  const lastSavedLabel = saveStatus === 'saved' && lastSavedAt ? formatLastSaved(lastSavedAt) : null;

  return (
    <section className="card deal-bar">
      <div className="deal-bar-row">
        <div className="deal-bar-identity">
          <label className="field deal-name-field">
            <span className="field-label">Deal Name</span>
            <input
              className="field-input"
              type="text"
              placeholder="Untitled Deal"
              value={dealName}
              onChange={(event: ChangeEvent<HTMLInputElement>) => onDealNameChange(event.target.value)}
            />
          </label>

          <span className={`save-status save-status-${saveStatus}`}>
            {SAVE_STATUS_LABEL[saveStatus]}
            {lastSavedLabel && ` · ${lastSavedLabel}`}
          </span>
        </div>

        <div className="deal-bar-actions">
          <button type="button" className="btn btn-ghost btn-sm" onClick={onOpenLibrary}>
            Deal Library
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onNewDeal}>
            New Deal
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={onSaveDeal}
            disabled={isSaving}
          >
            {isSaving ? 'Saving…' : isSavedDeal ? 'Update Deal' : 'Save Deal'}
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}
    </section>
  );
}
