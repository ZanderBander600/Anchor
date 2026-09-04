import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import type { OperatingMode } from '../types';

/** Mirrors the three-state save status the deal header surfaces. "unsaved-deal"
 * means the working deal has never been persisted at all (no id yet), even
 * if its fields are otherwise unchanged since a New Deal reset -- distinct
 * from "unsaved-changes", which means an already-saved/opened deal now
 * differs from its last-saved snapshot.
 *
 * Sprint C Gate C2: moved here verbatim from the retired `DealBar`, whose
 * responsibilities (deal name, save status, Save) this header took over. */
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

export interface DealHeaderProps {
  dealName: string;
  onDealNameChange: (value: string) => void;
  operatingMode: OperatingMode;
  onOperatingModeChange: (mode: OperatingMode) => void;
  isSavedDeal: boolean;
  isSaving: boolean;
  saveStatus: SaveStatus;
  lastSavedAt: string | null;
  error: string | null;
  onSaveDeal: () => void;
  onAnalyze: () => void;
  isAnalyzing: boolean;
  /** Overflow actions, enabled only for an already-saved deal. */
  onDuplicateDeal: () => void;
  onDeleteDeal: () => void;
}

/**
 * The persistent deal-identity header above the workspace navigation: deal
 * name, operating mode, save status, and the two primary actions (Save,
 * Analyze) plus an overflow menu for duplicate/delete.
 *
 * Purely presentational. It performs no validation, no calculation, no dirty
 * computation, and no API call of its own -- `saveStatus` is computed by the
 * caller from its saved-snapshot comparison, and every action delegates to
 * the caller's existing handlers. Analyze runs exactly the same function the
 * assumptions form's own submit button runs.
 *
 * Only fields Anchor's `Deal` contract actually carries are shown. The Sprint
 * C concept image's property photo, city, asset type and building size are
 * deliberately absent -- no production contract supports them.
 */
export function DealHeader({
  dealName,
  onDealNameChange,
  operatingMode,
  onOperatingModeChange,
  isSavedDeal,
  isSaving,
  saveStatus,
  lastSavedAt,
  error,
  onSaveDeal,
  onAnalyze,
  isAnalyzing,
  onDuplicateDeal,
  onDeleteDeal,
}: DealHeaderProps) {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!isMenuOpen) {
      return;
    }
    function handlePointerDown(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsMenuOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsMenuOpen(false);
      }
    }
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isMenuOpen]);

  const lastSavedLabel = saveStatus === 'saved' && lastSavedAt ? formatLastSaved(lastSavedAt) : null;

  return (
    <header className="deal-header">
      <div className="deal-header-row">
        <div className="deal-header-identity">
          <label className="deal-header-name-field">
            <span className="visually-hidden">Deal Name</span>
            <input
              className="deal-header-name-input"
              type="text"
              placeholder="Untitled Deal"
              value={dealName}
              onChange={(event: ChangeEvent<HTMLInputElement>) =>
                onDealNameChange(event.target.value)
              }
            />
          </label>

          {/* Detailed Operating Model V2.1 Gate 6's mode toggle, relocated
           * into the header. Same roles, same accessible names, same
           * `setOperatingMode` handler -- Quick and Detailed remain fully
           * independent workspaces. */}
          <div className="mode-switch" role="tablist" aria-label="Underwriting Mode">
            <button
              type="button"
              role="tab"
              aria-selected={operatingMode === 'quick'}
              className={
                operatingMode === 'quick' ? 'mode-switch-tab mode-switch-tab-active' : 'mode-switch-tab'
              }
              onClick={() => onOperatingModeChange('quick')}
            >
              Quick Underwrite
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={operatingMode === 'detailed'}
              className={
                operatingMode === 'detailed'
                  ? 'mode-switch-tab mode-switch-tab-active'
                  : 'mode-switch-tab'
              }
              onClick={() => onOperatingModeChange('detailed')}
            >
              Detailed Underwrite
            </button>
          </div>
        </div>

        <div className="deal-header-actions">
          {/* Status is never color-only: the dot is paired with its text label. */}
          <span className={`save-status save-status-${saveStatus}`}>
            <span className="save-status-dot" aria-hidden="true" />
            {SAVE_STATUS_LABEL[saveStatus]}
            {lastSavedLabel && ` · ${lastSavedLabel}`}
          </span>

          <div className="deal-header-menu" ref={menuRef}>
            <button
              type="button"
              className="icon-button"
              aria-label="More deal actions"
              aria-haspopup="menu"
              aria-expanded={isMenuOpen}
              onClick={() => setIsMenuOpen((open) => !open)}
            >
              <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                <circle cx="3.2" cy="8" r="1.3" />
                <circle cx="8" cy="8" r="1.3" />
                <circle cx="12.8" cy="8" r="1.3" />
              </svg>
            </button>

            {isMenuOpen && (
              <div className="deal-header-menu-popover" role="menu">
                <button
                  type="button"
                  role="menuitem"
                  className="deal-header-menu-item"
                  disabled={!isSavedDeal}
                  onClick={() => {
                    setIsMenuOpen(false);
                    onDuplicateDeal();
                  }}
                >
                  Duplicate Deal
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className="deal-header-menu-item deal-header-menu-item-danger"
                  disabled={!isSavedDeal}
                  onClick={() => {
                    setIsMenuOpen(false);
                    onDeleteDeal();
                  }}
                >
                  Delete Deal
                </button>
                {!isSavedDeal && (
                  <p className="deal-header-menu-note">Save the deal to enable these actions.</p>
                )}
              </div>
            )}
          </div>

          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onSaveDeal}
            disabled={isSaving}
          >
            {isSaving ? 'Saving…' : isSavedDeal ? 'Update Deal' : 'Save Deal'}
          </button>

          {/* Runs the identical analysis path as the assumptions form's own
           * "Analyze Deal" submit button -- same validation, same endpoint,
           * same downstream state. Relocating the action changes nothing
           * about what it does. */}
          <button
            type="button"
            className="btn btn-primary btn-sm btn-analyze"
            onClick={onAnalyze}
            disabled={isAnalyzing}
            aria-busy={isAnalyzing}
          >
            Analyze
          </button>
        </div>
      </div>

      {error && <div className="error-banner deal-header-error">{error}</div>}
    </header>
  );
}
