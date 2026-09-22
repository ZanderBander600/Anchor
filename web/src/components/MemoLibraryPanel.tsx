/**
 * Phase 7 Gate P7.10 Stage 4 -- the Investment Committee library.
 *
 * Every memo in the product, and every Investment that could start one. Opening
 * it creates nothing: a standalone Deal appears only once it actually has a
 * memo, because asking a Deal whether it has one must not be the act that gives
 * it a hidden Investment.
 *
 * **Two lists, because they are two different things.** A memo in progress is
 * work to return to; an Investment with no memo is work to begin. Mixing them
 * would make an empty product look busy and a busy one look empty.
 *
 * **Freshness is deliberately absent here.** Computing it would run one full
 * analysis per row. It is a per-version question and is answered in the memo
 * workspace, for the one version being read — which is the honest place for it,
 * since a library row can hold several versions with different answers.
 *
 * **Anchor stores no market or location**, so this library shows none. Inventing
 * a market for a row is exactly the fabricated market information the contract
 * forbids.
 */

import { assetTypeLabel } from '../assetTypes';
import type { AssetType } from '../assetTypes';
import { COMMITTEE_LABELS, RECOMMENDATION_LABELS } from '../memoCatalog';
import type { MemoLibraryEntry } from '../memoTypes';

export interface MemoLibraryPanelProps {
  entries: MemoLibraryEntry[];
  isLoading: boolean;
  error: string | null;
  onOpen: (entry: MemoLibraryEntry) => void;
  onRetry: () => void;
}

function classificationOf(entry: MemoLibraryEntry): string {
  if (entry.asset_type === null) {
    return 'Not classified';
  }
  const kind = assetTypeLabel(entry.asset_type as AssetType);
  return entry.asset_subtype === null ? kind : `${kind} — ${entry.asset_subtype}`;
}

function unitsOf(entry: MemoLibraryEntry): string {
  return entry.unit_count === 1 ? '1 Unit' : `${entry.unit_count} Units`;
}

function statusOf(entry: MemoLibraryEntry): string {
  if (entry.latest_version_number !== null && entry.has_draft) {
    return `Published v${entry.latest_version_number} · draft open`;
  }
  if (entry.latest_version_number !== null) {
    return `Published v${entry.latest_version_number}`;
  }
  return 'Draft';
}

function MemoRow({
  entry,
  onOpen,
}: {
  entry: MemoLibraryEntry;
  onOpen: (entry: MemoLibraryEntry) => void;
}) {
  return (
    <tr>
      <th scope="row" className="memo-cell-label">
        <span className="memo-library-name">{entry.name}</span>
        <span className="memo-library-kind">{entry.deal_id !== null ? 'Deal' : 'Investment'}</span>
      </th>
      <td>{classificationOf(entry)}</td>
      <td>{unitsOf(entry)}</td>
      <td>{statusOf(entry)}</td>
      <td>
        {entry.analyst_recommendation === null
          ? 'Not stated'
          : RECOMMENDATION_LABELS[entry.analyst_recommendation]}
      </td>
      <td>
        {/* The committee's own decision, never the analyst's echoed back.
          * "Not yet recorded" is not "Pending": one is an absence, the other is
          * an outcome somebody chose. */}
        {entry.committee_decision === null
          ? 'Not yet recorded'
          : COMMITTEE_LABELS[entry.committee_decision]}
      </td>
      <td>{entry.latest_published_at ?? entry.draft_updated_at ?? 'Not yet saved'}</td>
      <td>
        <button type="button" className="btn btn-secondary btn-xs" onClick={() => onOpen(entry)}>
          Open memo
        </button>
      </td>
    </tr>
  );
}

export function MemoLibraryPanel({
  entries,
  isLoading,
  error,
  onOpen,
  onRetry,
}: MemoLibraryPanelProps) {
  const active = entries.filter((entry) => entry.has_draft || entry.version_count > 0);
  const available = entries.filter((entry) => !entry.has_draft && entry.version_count === 0);

  return (
    <section className="memo-library" aria-labelledby="memo-library-title">
      <header className="memo-library-head">
        <h1 id="memo-library-title" className="memo-library-title">
          Investment Committee
        </h1>
        <p className="memo-library-subtitle">
          Investment Committee memoranda, their analyst recommendation and the committee's own
          decision.
        </p>
      </header>

      {error !== null && (
        <div className="error-banner" role="alert">
          <span>{error}</span>
          <button type="button" className="btn btn-ghost btn-xs" onClick={onRetry}>
            Retry
          </button>
        </div>
      )}

      {isLoading && entries.length === 0 && (
        <p className="memo-empty" role="status">
          Loading memos…
        </p>
      )}

      {!isLoading && entries.length === 0 && error === null && (
        <p className="memo-empty">
          No Investments or Deals yet. Create one to write an Investment Committee memo.
        </p>
      )}

      {active.length > 0 && (
        <div className="memo-library-group">
          <h2 className="memo-library-group-title">In progress</h2>
          <div className="memo-table-scroll" tabIndex={0} role="group" aria-label="Memos in progress">
            <table className="memo-table">
              <caption className="memo-table-caption">Memos with a draft or a published version</caption>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Asset type</th>
                  <th scope="col">Scope</th>
                  <th scope="col">Status</th>
                  <th scope="col">Analyst recommendation</th>
                  <th scope="col">Committee decision</th>
                  <th scope="col">Last activity</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {active.map((entry) => (
                  <MemoRow key={entry.investment_id} entry={entry} onOpen={onOpen} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {available.length > 0 && (
        <div className="memo-library-group">
          <h2 className="memo-library-group-title">Start a memo</h2>
          <ul className="memo-start-list">
            {available.map((entry) => (
              <li key={entry.investment_id} className="memo-start-row">
                <span className="memo-start-identity">
                  <span className="memo-library-name">{entry.name}</span>
                  <span className="memo-library-meta">
                    {classificationOf(entry)} · {unitsOf(entry)}
                  </span>
                </span>
                <button
                  type="button"
                  className="btn btn-secondary btn-xs"
                  onClick={() => onOpen(entry)}
                >
                  Start memo
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
