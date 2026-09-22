import { formatCurrency } from '../format';
import { RECENT_INVESTMENT_LIMIT } from '../investmentCatalog';
import type { VisibleInvestment } from '../investmentTypes';
import type { Deal } from '../types';
import { assertNeverMode, operatingModeLabel } from '../operatingMode';

/** Which global surface is showing. Phase 7 Gate P7.6 adds the Investment
 * surfaces beside the Deal ones: a Deal and an Investment are different
 * things, each with its own library. */
export type AppView =
  | 'workspace'
  | 'library'
  | 'investment-library'
  | 'new-investment'
  | 'investment'
  // Phase 7 Gate P7.10 Stage 4: the Investment Committee surfaces. A memo is a
  // first-class workspace beside the Deal and Investment ones, never a modal
  // over either.
  | 'memo-library'
  | 'memo';

/** Maximum saved deals surfaced in the sidebar's Recent Deals list. The full
 * list always remains one click away in the Deal Library view -- the sidebar
 * is a shortcut, not a replacement for it.
 *
 * Sprint C Gate C5 cut this from eight to five: a long list of similarly
 * named deals reads as visual noise in a 236px rail, and the "View all"
 * affordance below makes the rest one click away rather than hidden. */
const RECENT_DEAL_LIMIT = 5;

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

/** P7.6: an Investment -- several buildings held as one transaction. */
function IconPortfolio() {
  return (
    <svg className="nav-icon nav-icon-deal" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <rect x="1.8" y="5" width="4" height="8.4" rx="0.7" />
      <rect x="6.3" y="2.6" width="4" height="10.8" rx="0.7" />
      <rect x="10.8" y="6.4" width="3.4" height="7" rx="0.7" />
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
function purchasePriceOf(deal: Deal): number | null {
  switch (deal.operating_mode) {
    case 'quick':
      return deal.inputs?.purchase_price ?? null;
    case 'detailed':
      return deal.terms?.purchase_price ?? null;
    case 'lease_level':
      // D5.5A: a Lease-Level deal has `terms`, so its purchase price is its
      // own. Until D5.4 persisted one there was nothing to read and this
      // returned `null`; reading Quick's `inputs` would have shown a number
      // from a contract this deal does not populate, which is the substitution
      // the D5.1B guardrail was written to prevent. `terms` is the shared
      // `AcquisitionTerms` Detailed reads on the line above -- one contract,
      // one field, read the same way in both modes.
      return deal.terms?.purchase_price ?? null;
    default:
      return assertNeverMode(deal.operating_mode);
  }
}

export interface AppSidebarProps {
  deals: Deal[];
  isDealsLoading: boolean;
  /** Id of the deal currently open in the active operating mode, or null for
   * a never-saved working deal. Drives the active-row treatment. */
  activeDealId: string | null;
  /** Which global surface is showing -- a library, a deal workspace, or (P7.6)
   * an Investment surface. */
  view: AppView;
  onOpenLibrary: () => void;
  onNewDeal: () => void;
  onOpenDeal: (deal: Deal) => void;
  /** P7.6: the visible Investments, most recently updated first. The
   * Investment group is shown when its navigation is wired. */
  investments?: VisibleInvestment[];
  isInvestmentsLoading?: boolean;
  /** The Investment open in the Investment workspace, or `null`. */
  activeInvestmentId?: string | null;
  onOpenInvestmentLibrary?: () => void;
  onNewInvestment?: () => void;
  onOpenInvestment?: (investmentId: string) => void;
  /** P7.10 Stage 4: opens the Investment Committee library. Optional so every
   * existing render site keeps working unchanged; the entry simply does not
   * appear when it is absent. */
  onOpenMemoLibrary?: () => void;
  /** Gate AM1: switches to the Asset Management workspace. Optional so every
   * existing render site of this component keeps working unchanged; the
   * workspace switch simply does not appear when it is absent. */
  onOpenAssetManagement?: () => void;
  /** How many buildings are under management, shown beside the switch so the
   * analyst can see there is something there before going. */
  managedAssetCount?: number;
}

/** P7.10 Stage 4: the Investment Committee decision package. */
function IconMemo() {
  return (
    <svg className="nav-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <rect x="3" y="1.8" width="10" height="12.4" rx="1.1" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <path d="M5.6 5.4h4.8M5.6 8h4.8M5.6 10.6h3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

/** Gate AM1: the owned-asset side of the product. */
function IconAssetManagement() {
  return (
    <svg className="nav-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M8 2.2 A5.8 5.8 0 0 1 13.8 8 L8 8 Z" fill="currentColor" />
    </svg>
  );
}

function investmentMeta(investment: VisibleInvestment): string {
  const units = investment.units.length === 1 ? '1 Unit' : `${investment.units.length} Units`;
  return `${units} · ${formatCurrency(investment.transaction_price)}`;
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
  investments = [],
  isInvestmentsLoading = false,
  activeInvestmentId = null,
  onOpenInvestmentLibrary,
  onNewInvestment,
  onOpenInvestment,
  onOpenMemoLibrary,
  onOpenAssetManagement,
  managedAssetCount = 0,
}: AppSidebarProps) {
  const recentInvestments = investments.slice(0, RECENT_INVESTMENT_LIMIT);
  const activeInvestment = investments.find((investment) => investment.id === activeInvestmentId);
  const shownInvestments =
    activeInvestment && !recentInvestments.includes(activeInvestment)
      ? [...recentInvestments, activeInvestment]
      : recentInvestments;
  // Never hide the deal the analyst currently has open: if it falls outside
  // the most-recent window, it is appended rather than dropped, so the rail
  // always shows where you are.
  const mostRecent = deals.slice(0, RECENT_DEAL_LIMIT);
  const activeDeal = deals.find((deal) => deal.id === activeDealId);
  const recentDeals =
    activeDeal && !mostRecent.includes(activeDeal) ? [...mostRecent, activeDeal] : mostRecent;
  const hasMore = deals.length > recentDeals.length;

  return (
    <nav className="app-sidebar" aria-label="Anchor navigation">
      <div className="sidebar-brand">
        <img className="sidebar-brand-mark" src="/anchor-mark.png" alt="" />
        <span className="sidebar-brand-word">Anchor</span>
      </div>

      {/* Gate AM1 -- the primary application-level distinction. Acquisitions
        * and Asset Management are different products over the same building:
        * one underwrites a purchase, the other reports on what is already
        * owned. The switch sits above every Deal workspace tab, never beside
        * Underwrite/Risk/AI Analyst. */}
      {onOpenAssetManagement !== undefined && (
        <div className="sidebar-section sidebar-workspace-switch">
          <button
            type="button"
            className="sidebar-nav-item sidebar-nav-item-active"
            aria-current="page"
            aria-label="Acquisitions"
          >
            <IconLibrary />
            <span className="sidebar-nav-label">Acquisitions</span>
          </button>
          <button
            type="button"
            className="sidebar-nav-item"
            aria-label="Asset Management"
            onClick={onOpenAssetManagement}
          >
            <IconAssetManagement />
            <span className="sidebar-nav-label">Asset Management</span>
            {managedAssetCount > 0 && (
              <span className="sidebar-nav-count">{managedAssetCount}</span>
            )}
          </button>
        </div>
      )}

      <div className="sidebar-section">
        <button
          type="button"
          className={
            view === 'library' ? 'sidebar-nav-item sidebar-nav-item-active' : 'sidebar-nav-item'
          }
          aria-current={view === 'library' ? 'page' : undefined}
          aria-label="Deal Library"
          onClick={onOpenLibrary}
        >
          <IconLibrary />
          <span className="sidebar-nav-label">Deal Library</span>
        </button>

        {/* The name is stated on the button, as on every other rail item:
          * below 1024px the rail hides `.sidebar-nav-label`, which removes the
          * text -- and with it the name -- from the accessibility tree. */}
        <button
          type="button"
          className="sidebar-nav-item"
          aria-label="New Deal"
          onClick={onNewDeal}
        >
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
                      {operatingModeLabel(deal.operating_mode)} ·{' '}
                      {formatCurrency(purchasePriceOf(deal))}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>

        {hasMore && (
          <button type="button" className="sidebar-view-all" onClick={onOpenLibrary}>
            View all {deals.length} deals
          </button>
        )}
      </div>

      {onOpenInvestmentLibrary !== undefined && (
        <div className="sidebar-investments">
          <div className="sidebar-section">
            <button
              type="button"
              className={
                view === 'investment-library'
                  ? 'sidebar-nav-item sidebar-nav-item-active'
                  : 'sidebar-nav-item'
              }
              aria-current={view === 'investment-library' ? 'page' : undefined}
              aria-label="Investment Library"
              onClick={onOpenInvestmentLibrary}
            >
              <IconPortfolio />
              <span className="sidebar-nav-label">Investment Library</span>
            </button>
            <button
              type="button"
              className={
                view === 'new-investment' ? 'sidebar-nav-item sidebar-nav-item-active' : 'sidebar-nav-item'
              }
              aria-current={view === 'new-investment' ? 'page' : undefined}
              aria-label="New Investment"
              onClick={onNewInvestment}
            >
              <IconPlus />
              <span className="sidebar-nav-label">New Investment</span>
            </button>
            {onOpenMemoLibrary !== undefined && (
            <button
              type="button"
              className={
                view === 'memo-library' || view === 'memo'
                  ? 'sidebar-nav-item sidebar-nav-item-active'
                  : 'sidebar-nav-item'
              }
              aria-current={view === 'memo-library' || view === 'memo' ? 'page' : undefined}
              aria-label="Investment Committee"
              onClick={onOpenMemoLibrary}
            >
              <IconMemo />
              <span className="sidebar-nav-label">Investment Committee</span>
            </button>
            )}
          </div>

          <p className="sidebar-section-label">Recent Investments</p>
          {isInvestmentsLoading && shownInvestments.length === 0 && (
            <p className="sidebar-deals-status">Loading…</p>
          )}
          {!isInvestmentsLoading && shownInvestments.length === 0 && (
            <p className="sidebar-deals-status">No investments yet.</p>
          )}
          <ul className="sidebar-deal-list" aria-label="Recent Investments">
            {shownInvestments.map((investment) => {
              const isActive = view === 'investment' && investment.id === activeInvestmentId;
              return (
                <li key={investment.id}>
                  <button
                    type="button"
                    className={isActive ? 'sidebar-deal-row sidebar-deal-row-active' : 'sidebar-deal-row'}
                    aria-current={isActive ? 'true' : undefined}
                    onClick={() => onOpenInvestment?.(investment.id)}
                  >
                    <IconPortfolio />
                    <span className="sidebar-deal-text">
                      <span className="sidebar-deal-name">{investment.name}</span>
                      <span className="sidebar-deal-meta">{investmentMeta(investment)}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

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
