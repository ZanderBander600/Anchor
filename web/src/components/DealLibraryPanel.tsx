import { formatCurrency } from '../format';
import type { Deal } from '../types';

export interface DealLibraryPanelProps {
  deals: Deal[];
  isLoading: boolean;
  error: string | null;
  onOpen: (deal: Deal) => void;
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
 * Lists saved deals and lets the analyst open one back into the
 * underwriting workspace. Performs no calculation and never calls
 * `/analyze` -- `purchase_price` is read directly off the deal's stored
 * inputs, not derived. Opening a deal is the caller's responsibility
 * (`onOpen`); this component only renders what `/deals` already returned.
 */
export function DealLibraryPanel({ deals, isLoading, error, onOpen, onClose }: DealLibraryPanelProps) {
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
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => onOpen(deal)}>
                Open
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
