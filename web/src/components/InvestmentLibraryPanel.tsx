/**
 * Phase 7 Gate P7.6 -- the Investment Library.
 *
 * Every visible Investment (`GET /investments`), most recently updated first:
 * its name, its Transaction Price, its Unit count and when it was last
 * updated. Open or delete. There is no duplicate: visible Investment
 * duplication is not available in P7.6.
 *
 * Deleting asks for an intentional, inline confirmation that says exactly what
 * happens: the Units are released as standalone Deals, unchanged, and what the
 * Investment itself owns is deleted. Focus goes to the safe choice. The Deal
 * Library is separate and unchanged: a Deal and an Investment are different
 * things.
 *
 * Asset Types 1: an Investment states no classification of its own. Its
 * "Asset Types" column lists the distinct types of the Deals it holds -- one
 * name when they agree, every name when they differ, "Not specified" for an
 * unclassified Unit -- and the Asset Type filter keeps an Investment when *any*
 * of its Units matches. No single type is ever chosen to stand for a
 * multi-asset Investment, and nothing is written.
 */

import { useEffect, useRef, useState } from 'react';
import { formatCurrency } from '../format';
import { DELETE_INVESTMENT_CONSEQUENCES } from '../investmentCatalog';
import type { VisibleInvestment } from '../investmentTypes';
import { assetTypeLabel, distinctAssetTypes, matchesAssetTypeFilter } from '../assetTypes';
import type { AssetType, AssetTypeFilterValue } from '../assetTypes';
import type { Deal } from '../types';
import { AssetTypeFilter } from './AssetClassification';

export interface InvestmentLibraryPanelProps {
  investments: VisibleInvestment[];
  /** Asset Types 1: the saved Deals, to read each Unit's classification from.
   * Read only; a Unit missing from the list reads as "Not specified". */
  deals: Deal[];
  isLoading: boolean;
  error: string | null;
  onOpen: (investmentId: string) => void;
  /** Deletes the Investment; rejects with the backend's reason. */
  onDelete: (investmentId: string) => Promise<void>;
  onNew: () => void;
  onClose: () => void;
}

/** An ISO 8601 `updated_at` for display, or the raw text rather than
 * "Invalid Date". */
function formatUpdatedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function unitCount(count: number): string {
  return count === 1 ? '1 Unit' : `${count} Units`;
}

/** Every Unit's type, one entry per Unit, `null` for an unclassified one. */
function unitAssetTypes(investment: VisibleInvestment, deals: Deal[]): (AssetType | null)[] {
  return investment.units.map(
    (unit) => deals.find((deal) => deal.id === unit.unit_id)?.asset_type ?? null,
  );
}

export function InvestmentLibraryPanel({
  investments,
  deals,
  isLoading,
  error,
  onOpen,
  onDelete,
  onNew,
  onClose,
}: InvestmentLibraryPanelProps) {
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const [filter, setFilter] = useState<AssetTypeFilterValue>('all');
  const shown = investments.filter((investment) =>
    matchesAssetTypeFilter(unitAssetTypes(investment, deals), filter),
  );

  useEffect(() => {
    if (pendingDeleteId !== null) {
      cancelButton.current?.focus();
    }
  }, [pendingDeleteId]);

  async function confirmDelete(investmentId: string) {
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await onDelete(investmentId);
      setPendingDeleteId(null);
    } catch (failure) {
      setDeleteError(failure instanceof Error ? failure.message : 'The investment could not be deleted.');
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <section className="card deal-library-panel investment-library-panel" aria-labelledby="investment-library-title">
      <div className="card-title-row deal-library-header">
        <div>
          <h3 className="card-title" id="investment-library-title">
            Investment Library
          </h3>
          <p className="card-subtitle">
            Investments, most recently updated first. An Investment is one transaction over one or
            more Deals; each Deal keeps its own underwriting.
          </p>
        </div>
        <div className="investment-library-actions">
          <button type="button" className="btn btn-primary btn-sm" onClick={onNew}>
            New Investment
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            Close
          </button>
        </div>
      </div>

      {isLoading && investments.length === 0 && (
        <div className="sensitivity-status" role="status">
          Loading investments…
        </div>
      )}

      {error !== null && <div className="error-banner" role="alert">{error}</div>}

      {!isLoading && error === null && investments.length === 0 && (
        <div className="empty-state">
          No investments yet. Create one with <strong>New Investment</strong> from saved deals.
        </div>
      )}

      {investments.length > 0 && (
        <AssetTypeFilter
          value={filter}
          onChange={setFilter}
          shown={shown.length}
          total={investments.length}
          noun="investments"
        />
      )}

      {investments.length > 0 && shown.length === 0 && (
        <div className="empty-state asset-type-filter-empty">
          No investments hold a Unit of this asset type.{' '}
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setFilter('all')}>
            Show all asset types
          </button>
        </div>
      )}

      {shown.length > 0 && (
        <div className="investment-table-scroll" role="region" aria-label="Investments" tabIndex={0}>
          <table className="investment-table investment-library-table">
            <caption className="visually-hidden">Saved investments</caption>
            <thead>
              <tr>
                <th scope="col">Investment</th>
                <th scope="col">Asset Types</th>
                <th scope="col" className="investment-num">
                  Transaction Price
                </th>
                <th scope="col" className="investment-num">
                  Units
                </th>
                <th scope="col">Updated</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.map((investment) => {
                const isPending = pendingDeleteId === investment.id;
                const types = distinctAssetTypes(unitAssetTypes(investment, deals));
                return (
                  <tr key={investment.id} className={isPending ? 'investment-row-pending' : undefined}>
                    <th scope="row" className="investment-name-cell">
                      {investment.name}
                    </th>
                    <td className="investment-asset-types">
                      {types.length > 1 && <span className="visually-hidden">Mixed: </span>}
                      {types.map((assetType, position) => (
                        <span key={assetType ?? 'not-specified'}>
                          {/* Real text between chips, so they read as a list. */}
                          {position > 0 && <span className="visually-hidden">, </span>}
                          <span
                            className={
                              assetType === null
                                ? 'asset-type-chip asset-classification-empty'
                                : 'asset-type-chip'
                            }
                          >
                            {assetTypeLabel(assetType)}
                          </span>
                        </span>
                      ))}
                    </td>
                    <td className="investment-num">{formatCurrency(investment.transaction_price)}</td>
                    <td className="investment-num">{unitCount(investment.units.length)}</td>
                    <td className="investment-muted">{formatUpdatedAt(investment.updated_at)}</td>
                    <td className="investment-actions-cell">
                      {isPending ? (
                        <div className="investment-confirm" role="group" aria-label={`Confirm deleting ${investment.name}`}>
                          <p className="investment-confirm-text">{DELETE_INVESTMENT_CONSEQUENCES}</p>
                          <div className="investment-confirm-actions">
                            <button
                              type="button"
                              className="btn btn-danger btn-xs"
                              onClick={() => void confirmDelete(investment.id)}
                              disabled={isDeleting}
                            >
                              {isDeleting ? 'Deleting…' : 'Delete Investment'}
                            </button>
                            <button
                              ref={cancelButton}
                              type="button"
                              className="btn btn-ghost btn-xs"
                              onClick={() => {
                                setPendingDeleteId(null);
                                setDeleteError(null);
                              }}
                              disabled={isDeleting}
                            >
                              Cancel
                            </button>
                          </div>
                          {deleteError !== null && (
                            <p className="investment-inline-error" role="alert">
                              {deleteError}
                            </p>
                          )}
                        </div>
                      ) : (
                        <div className="investment-row-actions">
                          <button
                            type="button"
                            className="btn btn-secondary btn-xs"
                            onClick={() => onOpen(investment.id)}
                            aria-label={`Open ${investment.name}`}
                          >
                            Open
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost btn-xs"
                            onClick={() => {
                              setDeleteError(null);
                              setPendingDeleteId(investment.id);
                            }}
                            disabled={pendingDeleteId !== null}
                            aria-label={`Delete ${investment.name}`}
                          >
                            Delete
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
