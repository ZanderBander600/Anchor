import { useState } from 'react';

import type { AssetClassificationDraft } from '../assetTypes';
import { AssetClassificationText } from './AssetClassification';

/** Gate AM1 -- the Deal-side action that creates a Managed Asset.
 *
 * The one crossing point from Acquisitions into Asset Management. It collects
 * only what a Managed Asset states that the Deal does not: an acquisition date,
 * and optionally a market. The name defaults to the Deal's own, copied at
 * creation -- renaming the Deal afterwards does not rename the asset.
 *
 * Asset Types 1: the classification is not typed here. The server copies the
 * source Deal's saved Asset Type and subtype into the asset, once, so there is
 * one classification source and no hand-typed alternative that could disagree
 * with it. This panel shows what will be copied, read-only.
 *
 * It performs no calculation and captures no fingerprint of its own: the server
 * reads the Deal's authoritative analysis fingerprint and freezes it. The
 * frontend never computes a fingerprint (the same rule the acquisition side
 * already follows).
 */

export interface CreateManagedAssetPanelProps {
  dealName: string;
  /** The classification saved with the Deal -- what the server will copy. */
  savedClassification: AssetClassificationDraft;
  /** The Deal on screen has a classification edit that is not saved yet. */
  hasUnsavedClassification: boolean;
  isOpen: boolean;
  onCancel: () => void;
  onCreate: (request: {
    name: string | null;
    acquisition_date: string;
    market: string | null;
  }) => Promise<void>;
  error: string | null;
}

function today(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(
    now.getDate(),
  ).padStart(2, '0')}`;
}

export function CreateManagedAssetPanel({
  dealName,
  savedClassification,
  hasUnsavedClassification,
  isOpen,
  onCancel,
  onCreate,
  error,
}: CreateManagedAssetPanelProps) {
  const [name, setName] = useState(dealName);
  const [acquisitionDate, setAcquisitionDate] = useState(today);
  const [market, setMarket] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  if (!isOpen) {
    return null;
  }

  const optional = (value: string) => (value.trim() === '' ? null : value.trim());

  return (
    <form
      className="am-panel am-create-asset"
      onSubmit={(event) => {
        event.preventDefault();
        setIsSaving(true);
        void onCreate({
          name: optional(name),
          acquisition_date: acquisitionDate,
          market: optional(market),
        }).finally(() => setIsSaving(false));
      }}
    >
      <h3 className="am-panel-title">Create Managed Asset</h3>
      <p className="am-editor-note">
        Moves this approved acquisition into Asset Management. The acquisition analysis is
        not changed, and its approved basis is captured as it stands now.
      </p>

      {error !== null && (
        <div className="am-error" role="alert">
          {error}
        </div>
      )}

      <div className="am-create-fields">
        <label className="am-field">
          <span className="am-field-label">Asset Name</span>
          <input
            className="am-text-input"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
        </label>
        <label className="am-field">
          <span className="am-field-label">Acquisition Date</span>
          <input
            type="date"
            className="am-text-input"
            value={acquisitionDate}
            onChange={(event) => setAcquisitionDate(event.target.value)}
            required
          />
        </label>
        <div className="am-field am-create-classification">
          <span className="am-field-label">Asset Type (from the Deal)</span>
          <AssetClassificationText
            assetType={savedClassification.assetType === '' ? null : savedClassification.assetType}
            assetSubtype={savedClassification.assetSubtype.trim() || null}
          />
          <span className="am-editor-note">
            {hasUnsavedClassification
              ? 'Copied from the saved Deal. Save the Deal first to include your latest classification change.'
              : 'Copied from the Deal when the asset is created. Later Deal edits do not change it.'}
          </span>
        </div>
        <label className="am-field">
          <span className="am-field-label">Market (optional)</span>
          <input
            className="am-text-input"
            value={market}
            onChange={(event) => setMarket(event.target.value)}
            placeholder="Toronto, ON"
          />
        </label>
      </div>

      <div className="am-editor-actions">
        <button type="button" className="am-secondary-button" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="am-primary-button" disabled={isSaving}>
          {isSaving ? 'Creating…' : 'Create Managed Asset'}
        </button>
      </div>
    </form>
  );
}
