import { formatCurrency } from '../format';
import type { Deal } from '../types';

/** Maximum saved deals surfaced in the sidebar's Recent Deals list. The full
 * list always remains one click away in the Deal Library view -- the sidebar
 * is a shortcut, not a replacement for it. */
const RECENT_DEAL_LIMIT = 8;

/** Inline SVG so the shell adds no icon dependency. Every icon is decorative:
 * each nav row also carries a real text label (hidden only in the collapsed
 * rail, where the row keeps an `aria-label`), so nothing here is the sole
 * carrier of meaning. */
function IconLibrary() {
  return (
    <svg className="nav-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <rect x="2" y="2.5" width="4" height="11" rx="1" />
      <rect x="7.5" y="2.5" width="3" height="11" rx="1" />
      <rect x="11.6" y="4" width="2.6" height="9.5" rx="1" transform="rotate(-9 12.9 8.75)" />
    </svg>
  );
}

function IconPlus() {
  return (
    <svg className="nav-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <circle cx="8" cy="8" r="6.1" fill="none" strokeWidth="1.4" stroke="currentColor" />
      <path d="M8 5.2v5.6M5.2 8h5.6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function IconSettings() {
  return (
    <svg className="nav-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <circle cx="8" cy="8" r="2.1" fill="none" strokeWidth="1.4" stroke="currentColor" />
      <circle cx="8" cy="8" r="5.6" fill="none" strokeWidth="1.4" stroke="currentColor" strokeDasharray="2.6 2" />
    </svg>
  );
}

function IconBuilding() {
  return (
    <svg className="nav-icon nav-icon-deal" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <rect x="2.6" y="3" width="6" height="10.4" rx="0.8" />
      <rect x="9.4" y="6.2" width="4" height="7.2" rx="0.8" />
    </svg>
  );
}

/** Detailed Operating Model V2.1 Gate 11 parity with `DealLibraryPanel`:
 * `purchase_price` is shared by `AcquisitionInputs` (Quick) and
 * `AcquisitionTerms` (Detailed) -- read from whichever the deal actually
 * populated, never fabricated for the other mode. This is a read of stored
 * assumptions, not a calculation. */
function purchasePriceOf(deal: Deal): number {
  return deal.operating_mode === 'detailed'
    ? (deal.terms?.purchase_price ?? 0)
    : (deal.inputs?.purchase_price ?? 0);
}

export interface AppSidebarProps {
  deals: Deal[];
  isDealsLoading: boolean;
  /** Id of the deal currently open in the active operating mode, or null for
   * a never-saved working deal. Drives the active-row treatment. */
  activeDealId: string | null;
  /** Which global surface is showing -- the library view or a deal workspace. */
  view: 'workspace' | 'library';
  onOpenLibrary: () => void;
  onNewDeal: () => void;
  onOpenDeal: (deal: Deal) => void;
}

/**
 * The persistent global navigation rail: brand, global actions, a shortcut
 * list of recently updated saved deals, and a Settings placeholder.
 *
 * Performs no calculation and owns no state. The deal list is the caller's
 * existing `savedDeals` (the same state the Deal Library view renders) and
 * every action delegates to the caller's existing handlers -- opening a deal
 * runs the same `handleOpenDeal`, including its unsaved-changes guard. There
 * is deliberately no second deal-library state system.
 *
 * Duplicate and delete are intentionally absent from the deal rows: they stay
 * in the Deal Library view and the deal header's overflow menu rather than
 * crowding a 236px rail.
 */
export function AppSidebar({
  deals,
  isDealsLoading,
  activeDealId,
  view,
  onOpenLibrary,
  onNewDeal,
  onOpenDeal,
}: AppSidebarProps) {
  const recentDeals = deals.slice(0, RECENT_DEAL_LIMIT);

  return (
    <nav className="app-sidebar" aria-label="Anchor navigation">
      <div className="sidebar-brand">
        <img className="sidebar-brand-mark" src="/anchor-mark.png" alt="" />
        <span className="sidebar-brand-word">Anchor</span>
      </div>

      <div className="sidebar-section">
        <button
          type="button"
          className={
            view === 'library' ? 'sidebar-nav-item sidebar-nav-item-active' : 'sidebar-nav-item'
          }
          aria-current={view === 'library' ? 'page' : undefined}
          onClick={onOpenLibrary}
        >
          <IconLibrary />
          <span className="sidebar-nav-label">Deal Library</span>
        </button>

        <button type="button" className="sidebar-nav-item" onClick={onNewDeal}>
          <IconPlus />
          <span className="sidebar-nav-label">New Deal</span>
        </button>
      </div>

      <div className="sidebar-deals">
        <p className="sidebar-section-label">Recent Deals</p>

        {isDealsLoading && recentDeals.length === 0 && (
          <p className="sidebar-deals-status">Loading…</p>
        )}

        {!isDealsLoading && recentDeals.length === 0 && (
          <p className="sidebar-deals-status">No saved deals yet.</p>
        )}

        <ul className="sidebar-deal-list">
          {recentDeals.map((deal) => {
            const isActive = view === 'workspace' && deal.id === activeDealId;
            return (
              <li key={deal.id}>
                <button
                  type="button"
                  className={
                    isActive ? 'sidebar-deal-row sidebar-deal-row-active' : 'sidebar-deal-row'
                  }
                  aria-current={isActive ? 'true' : undefined}
                  onClick={() => onOpenDeal(deal)}
                >
                  <IconBuilding />
                  <span className="sidebar-deal-text">
                    <span className="sidebar-deal-name">{deal.name}</span>
                    <span className="sidebar-deal-meta">
                      {deal.operating_mode === 'detailed' ? 'Detailed' : 'Quick'} ·{' '}
                      {formatCurrency(purchasePriceOf(deal))}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="sidebar-footer">
        {/* Anchor has no settings implementation. This is a non-interactive
         * placeholder that keeps the locked information architecture's bottom
         * anchor present; no settings system is built in Sprint C. */}
        <span className="sidebar-nav-item sidebar-nav-item-disabled" aria-disabled="true">
          <IconSettings />
          <span className="sidebar-nav-label">Settings</span>
        </span>
      </div>
    </nav>
  );
}
