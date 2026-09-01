import type { ChangeEvent } from 'react';

export interface DealBarProps {
  dealName: string;
  onDealNameChange: (value: string) => void;
  isSavedDeal: boolean;
  isSaving: boolean;
  error: string | null;
  successMessage: string | null;
  onSaveDeal: () => void;
  onOpenLibrary: () => void;
  onNewDeal: () => void;
}

/**
 * The deal-identity strip: a name field, Save/Update Deal, and navigation
 * to the Deal Library or a fresh New Deal. Persists only the nine
 * assumptions already on the form via the existing conversion/validation
 * path (``buildAcquisitionRequest``) -- this component performs no
 * validation, calculation, or `/analyze` call of its own.
 */
export function DealBar({
  dealName,
  onDealNameChange,
  isSavedDeal,
  isSaving,
  error,
  successMessage,
  onSaveDeal,
  onOpenLibrary,
  onNewDeal,
}: DealBarProps) {
  return (
    <section className="card deal-bar">
      <div className="deal-bar-row">
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
      {!error && successMessage && <div className="success-banner">{successMessage}</div>}
    </section>
  );
}
