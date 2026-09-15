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
 */

import { useEffect, useRef, useState } from 'react';
import { formatCurrency } from '../format';
import { DELETE_INVESTMENT_CONSEQUENCES } from '../investmentCatalog';
import type { VisibleInvestment } from '../investmentTypes';

export interface InvestmentLibraryPanelProps {
  investments: VisibleInvestment[];
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

export function InvestmentLibraryPanel({
  investments,
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
        <div className="investment-table-scroll" role="region" aria-label="Investments" tabIndex={0}>
          <table className="investment-table investment-library-table">
            <caption className="visually-hidden">Saved investments</caption>
            <thead>
              <tr>
                <th scope="col">Investment</th>
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
              {investments.map((investment) => {
                const isPending = pendingDeleteId === investment.id;
                return (
                  <tr key={investment.id} className={isPending ? 'investment-row-pending' : undefined}>
                    <th scope="row" className="investment-name-cell">
                      {investment.name}
                    </th>
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
