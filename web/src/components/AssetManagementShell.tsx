import { useState } from 'react';

import { formatAcquiredOn } from '../assetManagementFormat';
import type { ManagedAsset } from '../assetManagementTypes';
import type { ManagedAssetsState } from '../useManagedAssets';
import { useAssetPerformance } from '../useManagedAssets';
import { ManagedAssetWorkspace } from './ManagedAssetWorkspace';

/** Gate AM1 -- the Asset Management workspace.
 *
 * A **separate primary workspace** from Acquisitions, not another tab inside a
 * Deal. Its own navigation, its own list, its own asset workspace. While the
 * analyst is here, no Quick Underwrite, Detailed Underwrite, Analyze or other
 * acquisition control is reachable: the acquisition appears only as quiet
 * provenance through "View Acquisition Basis".
 *
 * Three sections, all functional. No dead future tabs are rendered.
 */

export type AssetManagementSection = 'portfolio' | 'assets' | 'reporting';

const SECTIONS: { id: AssetManagementSection; label: string }[] = [
  { id: 'portfolio', label: 'Portfolio Overview' },
  { id: 'assets', label: 'Managed Assets' },
  { id: 'reporting', label: 'Monthly Reporting' },
];

function IconPortfolioPie() {
  return (
    <svg className="nav-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M8 2.2 A5.8 5.8 0 0 1 13.8 8 L8 8 Z" fill="currentColor" />
    </svg>
  );
}

function IconAssets() {
  return (
    <svg className="nav-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <rect x="2" y="3" width="5.4" height="10.4" rx="0.7" />
      <rect x="8.6" y="6" width="5.4" height="7.4" rx="0.7" />
    </svg>
  );
}

function IconReport() {
  return (
    <svg className="nav-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <rect x="3" y="2" width="10" height="12" rx="1.2" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M5.6 6h4.8M5.6 8.6h4.8M5.6 11.2h3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

export interface AssetManagementShellProps {
  state: ManagedAssetsState;
  /** Deals that could still become Managed Assets, for the empty state's
   * guidance. Never an acquisition control -- just a count. */
  dealCount: number;
  onViewAcquisitionBasis: (dealId: string) => void;
  /** Returns to the Acquisitions workspace. */
  onOpenAcquisitions: () => void;
}

export function AssetManagementShell({
  state,
  dealCount,
  onViewAcquisitionBasis,
  onOpenAcquisitions,
}: AssetManagementShellProps) {
  const [section, setSection] = useState<AssetManagementSection>('assets');
  const [openAssetId, setOpenAssetId] = useState<string | null>(null);

  const openAsset = state.assets.find((asset) => asset.id === openAssetId) ?? null;
  const performance = useAssetPerformance(openAsset?.id ?? null);

  const openManagedAsset = (asset: ManagedAsset) => {
    setOpenAssetId(asset.id);
    setSection('assets');
  };

  return (
    <div className="app-shell am-shell">
      <nav className="app-sidebar am-sidebar" aria-label="Asset Management navigation">
        <div className="sidebar-brand">
          <img className="sidebar-brand-mark" src="/anchor-mark.png" alt="" />
          <span className="sidebar-brand-word">Anchor</span>
        </div>

        {/* The primary application-level distinction. */}
        <div className="sidebar-section am-workspace-switch">
          <button
            type="button"
            className="sidebar-nav-item"
            aria-label="Acquisitions"
            onClick={onOpenAcquisitions}
          >
            <IconAssets />
            <span className="sidebar-nav-label">Acquisitions</span>
          </button>
          <button
            type="button"
            className="sidebar-nav-item sidebar-nav-item-active"
            aria-current="page"
            aria-label="Asset Management"
          >
            <IconPortfolioPie />
            <span className="sidebar-nav-label">Asset Management</span>
          </button>
        </div>

        <div className="sidebar-section">
          {SECTIONS.map((candidate) => (
            <button
              key={candidate.id}
              type="button"
              className={
                section === candidate.id && openAssetId === null
                  ? 'sidebar-nav-item sidebar-nav-item-active'
                  : 'sidebar-nav-item'
              }
              aria-current={section === candidate.id && openAssetId === null ? 'page' : undefined}
              // The label is hidden in the collapsed rail below 1024px, so the
              // icon-only button needs a name of its own.
              aria-label={candidate.label}
              onClick={() => {
                setSection(candidate.id);
                setOpenAssetId(null);
              }}
            >
              {candidate.id === 'portfolio' && <IconPortfolioPie />}
              {candidate.id === 'assets' && <IconAssets />}
              {candidate.id === 'reporting' && <IconReport />}
              <span className="sidebar-nav-label">{candidate.label}</span>
            </button>
          ))}
        </div>

        <div className="sidebar-deals">
          <p className="sidebar-section-label">Managed Assets</p>
          {state.isLoading && state.assets.length === 0 && (
            <p className="sidebar-deals-status">Loading…</p>
          )}
          {!state.isLoading && state.assets.length === 0 && (
            <p className="sidebar-deals-status">No managed assets yet.</p>
          )}
          <ul className="sidebar-deal-list" aria-label="Managed Assets">
            {state.assets.map((asset) => (
              <li key={asset.id}>
                <button
                  type="button"
                  className={
                    asset.id === openAssetId
                      ? 'sidebar-deal-row sidebar-deal-row-active'
                      : 'sidebar-deal-row'
                  }
                  aria-current={asset.id === openAssetId ? 'true' : undefined}
                  onClick={() => openManagedAsset(asset)}
                >
                  <IconAssets />
                  <span className="sidebar-deal-text">
                    <span className="sidebar-deal-name">{asset.name}</span>
                    <span className="sidebar-deal-meta">
                      {asset.property_type ?? 'Owned asset'} ·{' '}
                      {formatAcquiredOn(asset.acquisition_date)}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </nav>

      <div className="app-main am-main">
        {state.error !== null && (
          <div className="am-error" role="alert">
            {state.error}
          </div>
        )}

        {openAsset !== null ? (
          <ManagedAssetWorkspace
            key={openAsset.id}
            asset={openAsset}
            state={performance}
            onViewAcquisitionBasis={onViewAcquisitionBasis}
          />
        ) : section === 'portfolio' ? (
          <PortfolioOverview assets={state.assets} onOpen={openManagedAsset} />
        ) : section === 'reporting' ? (
          <MonthlyReportingIndex assets={state.assets} onOpen={openManagedAsset} />
        ) : (
          <ManagedAssetList
            assets={state.assets}
            isLoading={state.isLoading}
            dealCount={dealCount}
            onOpen={openManagedAsset}
            onOpenAcquisitions={onOpenAcquisitions}
          />
        )}
      </div>
    </div>
  );
}

function ManagedAssetList({
  assets,
  isLoading,
  dealCount,
  onOpen,
  onOpenAcquisitions,
}: {
  assets: ManagedAsset[];
  isLoading: boolean;
  dealCount: number;
  onOpen: (asset: ManagedAsset) => void;
  onOpenAcquisitions: () => void;
}) {
  return (
    <div className="am-page">
      <header className="am-page-head">
        <h2 className="am-page-title">Managed Assets</h2>
        <p className="am-page-subtitle">
          Buildings under management. Each one was created from an approved acquisition and
          reports its own monthly results.
        </p>
      </header>

      {isLoading && assets.length === 0 && <p className="am-empty">Loading…</p>}

      {!isLoading && assets.length === 0 && (
        <section className="am-panel">
          <h3 className="am-panel-title">No managed assets yet</h3>
          <p className="am-empty">
            {dealCount === 0
              ? 'Save and analyze an acquisition first. A managed asset is created from an approved acquisition.'
              : 'Open a saved acquisition and choose “Create Managed Asset” to begin reporting on it.'}
          </p>
          <button type="button" className="am-quiet-button" onClick={onOpenAcquisitions}>
            Go to Acquisitions
          </button>
        </section>
      )}

      {assets.length > 0 && (
        <div className="am-table-scroll">
          <table className="am-table">
            <thead>
              <tr>
                <th scope="col" className="am-col-line">
                  Asset
                </th>
                <th scope="col">Property Type</th>
                <th scope="col">Market</th>
                <th scope="col">Acquired</th>
                <th scope="col" />
              </tr>
            </thead>
            <tbody>
              {assets.map((asset) => (
                <tr key={asset.id}>
                  <th scope="row" className="am-col-line">
                    {asset.name}
                  </th>
                  <td>{asset.property_type ?? '—'}</td>
                  <td>{asset.market ?? '—'}</td>
                  <td>{formatAcquiredOn(asset.acquisition_date)}</td>
                  <td>
                    <button
                      type="button"
                      className="am-quiet-button"
                      onClick={() => onOpen(asset)}
                    >
                      Open
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function PortfolioOverview({
  assets,
  onOpen,
}: {
  assets: ManagedAsset[];
  onOpen: (asset: ManagedAsset) => void;
}) {
  return (
    <div className="am-page">
      <header className="am-page-head">
        <h2 className="am-page-title">Portfolio Overview</h2>
        <p className="am-page-subtitle">
          Assets under management. Portfolio-level consolidated performance is not part of
          this release, so nothing here is aggregated across assets.
        </p>
      </header>

      <div className="am-cards">
        <section className="am-card" aria-label="Managed assets">
          <h3 className="am-card-label">Managed Assets</h3>
          <p className="am-card-value">{assets.length}</p>
          <p className="am-card-plan">Owned and reporting</p>
        </section>
      </div>

      {assets.length === 0 ? (
        <p className="am-empty">No managed assets yet.</p>
      ) : (
        <section className="am-panel">
          <h3 className="am-panel-title">Assets</h3>
          <ul className="am-asset-links">
            {assets.map((asset) => (
              <li key={asset.id}>
                <button type="button" className="am-quiet-button" onClick={() => onOpen(asset)}>
                  {asset.name}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function MonthlyReportingIndex({
  assets,
  onOpen,
}: {
  assets: ManagedAsset[];
  onOpen: (asset: ManagedAsset) => void;
}) {
  return (
    <div className="am-page">
      <header className="am-page-head">
        <h2 className="am-page-title">Monthly Reporting</h2>
        <p className="am-page-subtitle">
          Choose an asset to record a month&rsquo;s approved budget and actual results, or to
          review a month already reported.
        </p>
      </header>

      {assets.length === 0 ? (
        <p className="am-empty">No managed assets yet.</p>
      ) : (
        <div className="am-table-scroll">
          <table className="am-table">
            <thead>
              <tr>
                <th scope="col" className="am-col-line">
                  Asset
                </th>
                <th scope="col">Market</th>
                <th scope="col" />
              </tr>
            </thead>
            <tbody>
              {assets.map((asset) => (
                <tr key={asset.id}>
                  <th scope="row" className="am-col-line">
                    {asset.name}
                  </th>
                  <td>{asset.market ?? '—'}</td>
                  <td>
                    <button
                      type="button"
                      className="am-quiet-button"
                      onClick={() => onOpen(asset)}
                    >
                      Open Monthly Performance
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
