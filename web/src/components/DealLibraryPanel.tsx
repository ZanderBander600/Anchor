import { formatCurrency } from '../format';
import type { Deal } from '../types';

export interface DealLibraryPanelProps {
  deals: Deal[];
  isLoading: boolean;
  error: string | null;
  onOpen: (deal: Deal) => void;
  onDuplicate: (deal: Deal) => void;
  onDelete: (deal: Deal) => void;
  onClose: () => void;
}

/** Formats an ISO 8601 ``updated_at`` for display -- falls back to the raw
 * string if the browser can't parse it, rather than showing "Invalid Date". */
function formatUpdatedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/**
 * Lists saved deals and lets the analyst open, duplicate, or delete one.
 * Performs no calculation and never calls `/analyze` -- `purchase_price`
 * is read directly off the deal's stored inputs, not derived. Duplicate
 * and delete are the caller's responsibility (`onDuplicate`/`onDelete`);
 * this component only asks for the one required confirmation before a
 * delete (`window.confirm`, per the app's existing convention of no custom
 * confirmation component) and otherwise renders what `/deals` returned.
 */
export function DealLibraryPanel({
  deals,
  isLoading,
  error,
  onOpen,
  onDuplicate,
  onDelete,
  onClose,
}: DealLibraryPanelProps) {
  function handleDeleteClick(deal: Deal) {
    if (window.confirm(`Delete "${deal.name}"? This cannot be undone.`)) {
      onDelete(deal);
    }
  }

  return (
    <section className="card deal-library-panel">
      <div className="card-title-row deal-library-header">
        <div>
          <h3 className="card-title">Deal Library</h3>
          <p className="card-subtitle">Saved deals, most recently updated first.</p>
        </div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
          Close
        </button>
      </div>

      {isLoading && <div className="sensitivity-status">Loading saved deals…</div>}

      {error && <div className="error-banner">{error}</div>}

      {!isLoading && !error && deals.length === 0 && (
        <div className="empty-state">
          No saved deals yet. Analyze a deal and click <strong>Save Deal</strong> to add one.
        </div>
      )}

      {!isLoading && !error && deals.length > 0 && (
        <ul className="deal-library-list">
          {deals.map((deal) => (
            <li className="deal-library-row" key={deal.id}>
              <div className="deal-library-row-info">
                <span className="deal-library-row-name">{deal.name}</span>
                <span className="deal-library-row-meta">
                  Updated {formatUpdatedAt(deal.updated_at)} &middot; Purchase Price{' '}
                  {formatCurrency(deal.inputs.purchase_price)}
                </span>
              </div>
              <div className="deal-library-row-actions">
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => onOpen(deal)}>
                  Open
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => onDuplicate(deal)}
                >
                  Duplicate
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm deal-library-delete-button"
                  onClick={() => handleDeleteClick(deal)}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
