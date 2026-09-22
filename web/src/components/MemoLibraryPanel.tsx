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


import { describeEntry } from '../memoLibraryRow';
import type { MemoLibraryRow } from '../memoLibraryRow';
import type { MemoLibraryEntry } from '../memoTypes';

export interface MemoLibraryPanelProps {
  entries: MemoLibraryEntry[];
  isLoading: boolean;
  error: string | null;
  onOpen: (entry: MemoLibraryEntry) => void;
  onRetry: () => void;
}

function MemoRow({ row, onOpen }: { row: MemoLibraryRow; onOpen: (entry: MemoLibraryEntry) => void }) {
  return (
    <tr>
      <th scope="row" className="memo-cell-label">
        <span className="memo-library-name">{row.name}</span>
        <span className="memo-library-kind">{row.kind}</span>
      </th>
      <td>{row.classification}</td>
      <td>{row.units}</td>
      <td>{row.status}</td>
      <td>{row.recommendation}</td>
      <td>{row.decision}</td>
      <td>{row.activity}</td>
      <td>
        <button type="button" className="btn btn-secondary btn-xs" onClick={() => onOpen(row.entry)}>
          {row.action}
        </button>
      </td>
    </tr>
  );
}

/**
 * The same row as a card, for phone width.
 *
 * Every field the table shows is here, labelled, stacked and wrapping: nothing
 * is dropped to make it fit, because a status an analyst cannot see is a status
 * the library did not report. The name is the heading and is never truncated --
 * two memos on neighbouring properties must not read as the same memo.
 *
 * Only one presentation is ever live: the stylesheet gives the other
 * `display: none`, which removes it from the accessibility tree and from tab
 * order, so there is exactly one reachable action per memo at any width.
 */
function MemoCard({ row, onOpen }: { row: MemoLibraryRow; onOpen: (entry: MemoLibraryEntry) => void }) {
  const facts: { label: string; value: string }[] = [
    { label: 'Asset type', value: row.classification },
    { label: 'Scope', value: row.units },
    { label: 'Status', value: row.status },
    { label: 'Analyst recommendation', value: row.recommendation },
    { label: 'Committee decision', value: row.decision },
    ...(row.cell === null ? [] : [{ label: 'Decision cell', value: row.cell }]),
    { label: 'Last activity', value: row.activity },
  ];

  return (
    <li className="memo-library-card">
      <h3 className="memo-library-card-name">
        {row.name} <span className="memo-library-kind">{row.kind}</span>
      </h3>
      <dl className="memo-library-card-facts">
        {facts.map((fact) => (
          <div key={fact.label} className="memo-library-card-fact">
            <dt>{fact.label}</dt>
            <dd>{fact.value}</dd>
          </div>
        ))}
      </dl>
      <button
        type="button"
        className="btn btn-secondary btn-sm memo-library-card-action"
        onClick={() => onOpen(row.entry)}
      >
        {row.action}
        <span className="visually-hidden"> — {row.name}</span>
      </button>
    </li>
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
  // Described once; the table and the cards below both render these.
  const activeRows = active.map(describeEntry);

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

      {activeRows.length > 0 && (
        <div className="memo-library-group">
          <h2 className="memo-library-group-title">In progress</h2>
          {/* Phone width: the same rows as cards. Which of the two is live is
            * the stylesheet's decision, and `display: none` takes the other out
            * of the accessibility tree and out of tab order entirely. */}
          <ul className="memo-library-cards" aria-label="Memos in progress">
            {activeRows.map((row) => (
              <MemoCard key={row.entry.investment_id} row={row} onOpen={onOpen} />
            ))}
          </ul>
          <div className="memo-table-scroll" tabIndex={0} role="group" aria-label="Memos in progress, as a table">
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
                {activeRows.map((row) => (
                  <MemoRow key={row.entry.investment_id} row={row} onOpen={onOpen} />
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
                    {describeEntry(entry).classification} · {describeEntry(entry).units}
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
