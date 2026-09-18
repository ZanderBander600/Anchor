import { useEffect, useRef, useState } from 'react';

import { formatAcquiredOn, formatMonth } from '../assetManagementFormat';
import type { ManagedAsset, PerformanceView } from '../assetManagementTypes';
import type { AssetPerformanceState } from '../useManagedAssets';
import { MonthlyPerformancePanel } from './MonthlyPerformancePanel';
import { MonthlyReportEditor } from './MonthlyReportEditor';

/** Gate AM1 -- one owned asset's workspace.
 *
 * Two tabs, and only two: Overview and Monthly Performance. The design concept
 * also shows Business Plan, Debt & Covenants and Documents; those are
 * deliberately absent, because AM1 renders no dead future tabs (Section 8).
 *
 * The acquisition appears only as quiet provenance -- a "View Acquisition
 * Basis" action. No Quick Underwrite, Detailed Underwrite, Analyze or other
 * acquisition control is reachable from inside Asset Management.
 */

export type AssetTab = 'overview' | 'performance';

const TABS: { id: AssetTab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'performance', label: 'Monthly Performance' },
];

export interface ManagedAssetWorkspaceProps {
  asset: ManagedAsset;
  state: AssetPerformanceState;
  /** Opens the source Deal in the Acquisitions workspace. Provenance only. */
  onViewAcquisitionBasis: (dealId: string) => void;
  /** Permanently removes this asset and its reports, but not its source Deal. */
  onDelete: () => Promise<void>;
}

export function ManagedAssetWorkspace({
  asset,
  state,
  onViewAcquisitionBasis,
  onDelete,
}: ManagedAssetWorkspaceProps) {
  const [tab, setTab] = useState<AssetTab>('performance');
  const [view, setView] = useState<PerformanceView>('monthly');
  const [editing, setEditing] = useState<'none' | 'new' | 'existing'>('none');
  const [draftMonth, setDraftMonth] = useState<string>(() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`;
  });
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deleteButton = useRef<HTMLButtonElement>(null);
  const cancelDeleteButton = useRef<HTMLButtonElement>(null);
  const wasConfirmingDelete = useRef(false);

  useEffect(() => {
    if (isConfirmingDelete) {
      cancelDeleteButton.current?.focus();
    } else if (wasConfirmingDelete.current) {
      deleteButton.current?.focus();
    }
    wasConfirmingDelete.current = isConfirmingDelete;
  }, [isConfirmingDelete]);

  const meta = [asset.property_type, `Acquired ${formatAcquiredOn(asset.acquisition_date)}`, asset.market]
    .filter((part): part is string => part !== null && part !== '')
    .join(' · ');

  const selectedReport =
    state.selectedMonth === null
      ? null
      : state.reports.find((report) => report.reporting_month === state.selectedMonth) ?? null;

  const closeEditor = () => {
    setEditing('none');
    setSaveError(null);
  };

  const guard = async (action: () => Promise<void>) => {
    setSaveError(null);
    try {
      await action();
      closeEditor();
    } catch (caught: unknown) {
      setSaveError(caught instanceof Error ? caught.message : 'The report could not be saved.');
    }
  };

  const confirmDelete = async () => {
    setDeleteError(null);
    setIsDeleting(true);
    try {
      await onDelete();
      setIsConfirmingDelete(false);
    } catch (caught: unknown) {
      setDeleteError(caught instanceof Error ? caught.message : 'The managed asset could not be deleted.');
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="am-workspace">
      <header className="am-asset-header">
        <p className="am-breadcrumb">
          Asset Management <span aria-hidden="true">/</span> Managed Assets
        </p>
        <div className="am-asset-identity">
          <h2 className="am-asset-name">{asset.name}</h2>
          <span className="am-owned-badge">Owned Asset</span>
          <div className="am-asset-actions">
            {!isConfirmingDelete && (
              <button
                ref={deleteButton}
                type="button"
                className="am-danger-button"
                onClick={() => {
                  setDeleteError(null);
                  setIsConfirmingDelete(true);
                }}
              >
                Delete Asset
              </button>
            )}
            <button
              type="button"
              className="am-quiet-button"
              onClick={() => onViewAcquisitionBasis(asset.source_deal_id)}
            >
              View Acquisition Basis
            </button>
            <button
              type="button"
              className="am-primary-button"
              onClick={() => {
                setSaveError(null);
                setEditing(selectedReport === null ? 'new' : 'existing');
              }}
            >
              {selectedReport === null ? 'Add Monthly Report' : 'Edit Actuals'}
            </button>
          </div>
        </div>
        {meta !== '' && <p className="am-asset-meta">{meta}</p>}
        {isConfirmingDelete && (
          <div
            className="am-delete-confirm"
            role="group"
            aria-label={`Confirm deleting ${asset.name}`}
          >
            <div>
              <p className="am-delete-question">Permanently delete {asset.name}?</p>
              <p className="am-delete-message">
                This deletes the managed asset and all of its monthly reports. The source
                acquisition and its underwriting will remain. This cannot be undone.
              </p>
              {deleteError !== null && (
                <p className="am-delete-error" role="alert">
                  {deleteError}
                </p>
              )}
            </div>
            <div className="am-delete-actions">
              <button
                type="button"
                className="am-danger-button"
                onClick={() => void confirmDelete()}
                disabled={isDeleting}
              >
                {isDeleting ? 'Deleting…' : 'Delete Asset'}
              </button>
              <button
                ref={cancelDeleteButton}
                type="button"
                className="am-secondary-button"
                onClick={() => {
                  setDeleteError(null);
                  setIsConfirmingDelete(false);
                }}
                disabled={isDeleting}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </header>

      <nav className="am-tabs" aria-label="Managed asset sections">
        {TABS.map((candidate) => (
          <button
            key={candidate.id}
            type="button"
            role="tab"
            id={`am-tab-${candidate.id}`}
            aria-selected={tab === candidate.id}
            aria-controls={`am-panel-${candidate.id}`}
            className={tab === candidate.id ? 'am-tab am-tab-active' : 'am-tab'}
            onClick={() => setTab(candidate.id)}
          >
            {candidate.label}
          </button>
        ))}
      </nav>

      <div className="am-workspace-scroll">
        {state.error !== null && (
          <div className="am-error" role="alert">
            {state.error}
          </div>
        )}

        {tab === 'overview' && (
          <div id="am-panel-overview" role="tabpanel" aria-labelledby="am-tab-overview">
            <section className="am-panel">
              <h3 className="am-panel-title">Asset</h3>
              <dl className="am-detail-list">
                <div>
                  <dt>Name</dt>
                  <dd>{asset.name}</dd>
                </div>
                <div>
                  <dt>Property Type</dt>
                  <dd>{asset.property_type ?? 'Not stated'}</dd>
                </div>
                <div>
                  <dt>Market</dt>
                  <dd>{asset.market ?? 'Not stated'}</dd>
                </div>
                <div>
                  <dt>Acquired</dt>
                  <dd>{formatAcquiredOn(asset.acquisition_date)}</dd>
                </div>
                <div>
                  <dt>Months Reported</dt>
                  <dd>{state.reports.length}</dd>
                </div>
              </dl>
            </section>

            <section className="am-panel">
              <h3 className="am-panel-title">Approved Acquisition Basis</h3>
              <p className="am-provenance">
                This asset was created from a saved acquisition analysis. The approved basis
                was captured when the asset was created; later edits to that deal do not
                change this asset, its approved budgets or its saved reports. Open it with
                View Acquisition Basis above.
              </p>
              {/* The acquisition fingerprint stays on the contract and in the
                * wire response, where it is what actually freezes the basis --
                * but it is an internal digest, not something an asset manager
                * can act on. "View Acquisition Basis" is the human-facing
                * provenance action. It lives once, in the asset header, where it
                * is reachable from both tabs; a second copy here repeated the
                * same route. */}
            </section>
          </div>
        )}

        {tab === 'performance' && (
          <div id="am-panel-performance" role="tabpanel" aria-labelledby="am-tab-performance">
            {editing !== 'none' ? (
              <section className="am-panel">
                <MonthlyReportEditor
                  report={editing === 'existing' ? selectedReport : null}
                  month={draftMonth}
                  onMonthChange={setDraftMonth}
                  onCancel={closeEditor}
                  onCreate={(request) => guard(() => state.saveReport(request))}
                  onUpdate={(request) =>
                    guard(() => state.saveActuals(state.selectedMonth ?? draftMonth, request))
                  }
                  error={saveError}
                />
              </section>
            ) : state.reportsStatus === 'loading' ? (
              // Honest while unresolved: "No reporting yet" is a statement
              // about this asset, and we do not yet know whether it is true.
              <section className="am-panel">
                <h3 className="am-panel-title">Loading monthly reports</h3>
                <p className="am-empty" role="status">
                  Loading this asset&rsquo;s reporting history&hellip;
                </p>
              </section>
            ) : state.reportsStatus === 'ready' && state.reports.length === 0 ? (
              <section className="am-panel">
                <h3 className="am-panel-title">No reporting yet</h3>
                <p className="am-empty">
                  Record this asset&rsquo;s first month by entering its approved budget and the
                  actual results. Budgets are entered explicitly; nothing is derived from the
                  acquisition forecast.
                </p>
                <button
                  type="button"
                  className="am-primary-button"
                  onClick={() => setEditing('new')}
                >
                  Add Monthly Report
                </button>
              </section>
            ) : (
              <>
                <div className="am-month-bar">
                  <label className="am-field am-field-inline">
                    <span className="am-field-label">Reporting Month</span>
                    <select
                      className="am-select"
                      value={state.selectedMonth ?? ''}
                      onChange={(event) => state.selectMonth(event.target.value)}
                    >
                      {state.reports.map((report) => (
                        <option key={report.reporting_month} value={report.reporting_month}>
                          {formatMonth(report.reporting_month)}
                        </option>
                      ))}
                    </select>
                  </label>
                  {/* Plain language about how budgets actually work here. The
                    * previous wording named an "Approved Acquisition Plan"
                    * captured on the acquisition date, which was wrong twice:
                    * the acquisition date is not when the basis was captured,
                    * and a monthly budget is never derived from an acquisition
                    * plan -- it is typed in and then frozen. */}
                  <p className="am-plan-note">
                    Monthly budgets are entered explicitly and lock after first save.
                  </p>
                  <button
                    type="button"
                    className="am-quiet-button"
                    onClick={() => {
                      setSaveError(null);
                      setEditing('new');
                    }}
                  >
                    Add Month
                  </button>
                </div>

                {state.performanceStatus === 'loading' && (
                  <section className="am-panel">
                    <p className="am-empty" role="status">
                      Loading {state.selectedMonth === null ? 'monthly' : formatMonth(state.selectedMonth)}{' '}
                      performance&hellip;
                    </p>
                  </section>
                )}

                {state.performance !== null && (
                  <MonthlyPerformancePanel
                    performance={state.performance}
                    view={view}
                    onViewChange={setView}
                    onEditActuals={() => {
                      setSaveError(null);
                      setEditing('existing');
                    }}
                  />
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
