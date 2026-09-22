/**
 * Phase 7 Gate P7.10 Stage 4 -- the institutional report, on screen.
 *
 * One component renders a `MemoReportPackage`, whether it came from the mutable
 * draft or from an immutable published version. Two renderers would be two
 * chances for a draft to look like a published memo; one renderer that reads
 * `origin` cannot drift.
 *
 * **Nothing here computes or formats a figure.** Every value is a string the
 * backend already formatted, and an absent figure arrives as a typed
 * `unavailable` whose label is printed in its place -- never `$0`, never the
 * purchase price, never a blank cell that reads as zero. The component selects
 * and lays out; `web/src/memoArchitecture.test.ts` rejects arithmetic here.
 *
 * **A draft can never pass as published.** A draft package renders a standing
 * `Draft — Not Published` banner, as text rather than colour alone, so the
 * state survives a monochrome display and a screen reader.
 *
 * **A published report is frozen and is never annotated here.** It is the
 * document the committee was issued, read back from storage. Whether today's
 * analysis has moved since is true and worth saying, and the workspace says it
 * *around* this component -- writing it into the document would change the
 * document.
 *
 * **Dense tables scroll inside themselves.** Each financial table sits in its
 * own scroll region with a real `<caption>`, so a wide table never widens the
 * page at 390px and a screen reader still gets the table's name.
 */

import type {
  MemoReportDisclosure,
  MemoReportMetric,
  MemoReportPackage,
  MemoReportSection,
  MemoReportTable,
  MemoReportValuation,
} from '../memoTypes';
import {
  ANALYST_RECOMMENDATION_LABEL,
  COMMITTEE_DECISION_LABEL,
  COMMITTEE_DECISION_UNRECORDED,
  DRAFT_PREVIEW_BANNER,
  UNSOURCED_CLAIM_LABEL,
  valuationRoleLabel,
} from '../memoCatalog';

export interface MemoReportViewProps {
  report: MemoReportPackage;
  /** Shown above the report when the caller has an action to offer, such as the
   * PDF download for a published version. */
  actions?: React.ReactNode;
}

function MetricCard({ metric }: { metric: MemoReportMetric }) {
  return (
    <div className="memo-metric">
      <span className="memo-metric-label">{metric.label}</span>
      {metric.value !== null ? (
        <span className="memo-metric-value">{metric.value}</span>
      ) : (
        <span className="memo-metric-unavailable" title={metric.unavailable?.reason ?? undefined}>
          {metric.unavailable?.label ?? 'Unavailable'}
        </span>
      )}
      {metric.note !== null && <span className="memo-metric-note">{metric.note}</span>}
    </div>
  );
}

function ReportTable({ table }: { table: MemoReportTable }) {
  const right = new Set(table.align_right);
  const emphasized = new Set(table.emphasize_rows);
  return (
    <div className="memo-report-table">
      {/* The scroll region is focusable and labelled, so a wide table is
        * reachable and announced by keyboard as well as by pointer. */}
      <div className="memo-table-scroll" tabIndex={0} role="group" aria-label={table.caption}>
        <table className="memo-table">
          <caption className="memo-table-caption">{table.caption}</caption>
          <thead>
            <tr>
              {table.headers.map((header, index) => (
                <th
                  key={header}
                  scope="col"
                  className={right.has(index) ? 'memo-cell-figure' : undefined}
                >
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, rowIndex) => (
              <tr
                key={row.join('|')}
                className={emphasized.has(rowIndex) ? 'memo-row-total' : undefined}
              >
                {row.map((cell, index) =>
                  index === 0 ? (
                    <th key={cell} scope="row" className="memo-cell-label">
                      {cell}
                    </th>
                  ) : (
                    <td key={cell} className={right.has(index) ? 'memo-cell-figure' : undefined}>
                      {cell}
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.note !== null && <p className="memo-table-note">{table.note}</p>}
    </div>
  );
}

function Disclosure({ disclosure }: { disclosure: MemoReportDisclosure }) {
  return (
    <div className="memo-disclosure" role="note">
      <p className="memo-disclosure-title">
        {disclosure.title}
        {disclosure.scope !== null && <span className="memo-disclosure-scope"> · {disclosure.scope}</span>}
      </p>
      <p className="memo-disclosure-detail">{disclosure.detail}</p>
    </div>
  );
}

function ValuationRow({ view }: { view: MemoReportValuation }) {
  const role = valuationRoleLabel({
    selected: view.selected,
    consumed: view.consumed,
    systemControlled: view.system_controlled,
  });
  return (
    <tr>
      <th scope="row" className="memo-cell-label">
        {view.label}
        {view.analyst_supplied && (
          <span className="memo-tag memo-tag-analyst">Analyst-Supplied Value</span>
        )}
      </th>
      <td>{view.kind}</td>
      <td>{view.timing}</td>
      <td>{view.scope}</td>
      <td>{role}</td>
      <td className="memo-cell-figure">
        {view.value !== null ? (
          view.value
        ) : (
          <span className="memo-unavailable">
            {view.unavailable?.label ?? 'Unavailable'}
            {view.unavailable !== null && (
              <span className="memo-unavailable-reason"> — {view.unavailable.reason}</span>
            )}
          </span>
        )}
      </td>
    </tr>
  );
}

function Section({ section }: { section: MemoReportSection }) {
  return (
    <section className="memo-report-section">
      <h3 className="memo-report-section-title">{section.title}</h3>
      {section.subtitle !== null && (
        <p className="memo-report-section-subtitle">{section.subtitle}</p>
      )}
      {section.body !== null && <p className="memo-report-body">{section.body}</p>}

      {section.narrative.length > 0 && (
        <ul className="memo-claim-list">
          {section.narrative.map((item) => (
            <li key={item.text} className="memo-claim">
              <p className="memo-claim-text">{item.text}</p>
              {item.labels.length > 0 && (
                <p className="memo-claim-labels">
                  {item.labels.map((label) => (
                    <span key={label} className="memo-tag">
                      {label}
                    </span>
                  ))}
                </p>
              )}
              {item.detail !== null && (
                <p className="memo-claim-detail">
                  <span className="memo-claim-detail-label">Mitigant</span> {item.detail}
                </p>
              )}
              {item.sourced ? (
                <p className="memo-claim-source">
                  <span className="memo-claim-source-label">Source</span>{' '}
                  {item.evidence_labels.join('; ')}
                </p>
              ) : (
                <p className="memo-claim-unsourced">{UNSOURCED_CLAIM_LABEL}</p>
              )}
            </li>
          ))}
        </ul>
      )}

      {section.metrics.length > 0 && (
        <div className="memo-metric-grid">
          {section.metrics.map((metric) => (
            <MetricCard key={metric.label} metric={metric} />
          ))}
        </div>
      )}

      {section.tables.map((table) => (
        <ReportTable key={table.caption} table={table} />
      ))}

      {section.disclosures.map((disclosure) => (
        <Disclosure key={disclosure.title} disclosure={disclosure} />
      ))}
    </section>
  );
}

export function MemoReportView({ report, actions }: MemoReportViewProps) {
  const isDraft = report.origin === 'draft_preview';

  return (
    <article className={isDraft ? 'memo-report memo-report-draft' : 'memo-report'}>
      {isDraft && (
        <p className="memo-report-watermark" role="status">
          <span className="memo-report-status">Draft — Not Published</span>
          {DRAFT_PREVIEW_BANNER}
        </p>
      )}

      {actions !== undefined && <div className="memo-report-actions">{actions}</div>}

      <header className="memo-report-head">
        <p className="memo-report-kind">Investment Committee Memorandum</p>
        <h2 className="memo-report-name">{report.investment_name}</h2>
        {report.asset_type !== null && (
          <p className="memo-report-classification">{report.asset_type}</p>
        )}
        <dl className="memo-report-meta">
          {report.version_number !== null && (
            <div>
              <dt>Version</dt>
              <dd>{report.version_number}</dd>
            </div>
          )}
          {report.published_at !== null && (
            <div>
              <dt>Published</dt>
              <dd>{report.published_at}</dd>
            </div>
          )}
          <div>
            <dt>Generated</dt>
            <dd>{report.generated_at}</dd>
          </div>
          {report.prepared_by !== null && (
            <div>
              <dt>Prepared by</dt>
              <dd>{report.prepared_by}</dd>
            </div>
          )}
        </dl>
      </header>

      {/* The two decision acts, side by side and visibly different (R-F). An
        * analyst recommends; a committee decides. */}
      <div className="memo-decision-pair">
        <div className="memo-decision-card memo-decision-analyst">
          <span className="memo-decision-label">{ANALYST_RECOMMENDATION_LABEL}</span>
          <span className="memo-decision-value">{report.analyst_recommendation}</span>
        </div>
        <div className="memo-decision-card memo-decision-committee">
          <span className="memo-decision-label">{COMMITTEE_DECISION_LABEL}</span>
          <span className="memo-decision-value">
            {report.committee_decision ?? COMMITTEE_DECISION_UNRECORDED}
          </span>
          {report.committee_note !== null && (
            <span className="memo-decision-note">{report.committee_note}</span>
          )}
        </div>
      </div>

      <dl className="memo-context-strip">
        <div>
          <dt>Strategy</dt>
          <dd>{report.strategy_label}</dd>
        </div>
        <div>
          <dt>Scenario</dt>
          <dd>{report.scenario_label}</dd>
        </div>
        <div>
          <dt>Decision perspective</dt>
          <dd>{report.perspective_label}</dd>
        </div>
      </dl>

      {report.decision_ask !== '' && (
        <section className="memo-report-section">
          <h3 className="memo-report-section-title">Decision Requested</h3>
          <p className="memo-report-lead">{report.decision_ask}</p>
        </section>
      )}

      {report.executive_summary !== '' && (
        <section className="memo-report-section">
          <h3 className="memo-report-section-title">Executive Summary</h3>
          <p className="memo-report-summary">{report.executive_summary}</p>
        </section>
      )}

      {report.key_metrics.length > 0 && (
        <section className="memo-report-section">
          <h3 className="memo-report-section-title">Key Decision Metrics</h3>
          <div className="memo-metric-grid memo-metric-grid-key">
            {report.key_metrics.map((metric) => (
              <MetricCard key={metric.label} metric={metric} />
            ))}
          </div>
        </section>
      )}

      {report.disclosures.map((disclosure) => (
        <Disclosure key={disclosure.title} disclosure={disclosure} />
      ))}

      {report.sections.map((section) => (
        <Section key={section.title} section={section} />
      ))}

      {report.valuations.length > 0 && (
        <section className="memo-report-section">
          <h3 className="memo-report-section-title">Valuation Views</h3>
          <div className="memo-report-table">
            <div className="memo-table-scroll" tabIndex={0} role="group" aria-label="Valuation views">
              <table className="memo-table">
                <caption className="memo-table-caption">Views included in this memo</caption>
                <thead>
                  <tr>
                    <th scope="col">View</th>
                    <th scope="col">Basis</th>
                    <th scope="col">Timing</th>
                    <th scope="col">Scope</th>
                    <th scope="col">Role in this memo</th>
                    <th scope="col" className="memo-cell-figure">
                      Value
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {report.valuations.map((view) => (
                    <ValuationRow key={`${view.label}-${view.timing}`} view={view} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}

      {report.evidence.length > 0 && (
        <section className="memo-report-section">
          <h3 className="memo-report-section-title">Evidence and Sources</h3>
          <div className="memo-report-table">
            <div className="memo-table-scroll" tabIndex={0} role="group" aria-label="Source register">
              <table className="memo-table">
                <caption className="memo-table-caption">Source register</caption>
                <thead>
                  <tr>
                    <th scope="col">Source</th>
                    <th scope="col">Kind</th>
                    <th scope="col">Reference</th>
                    <th scope="col">As of</th>
                    <th scope="col">Approval</th>
                    <th scope="col">Supports</th>
                  </tr>
                </thead>
                <tbody>
                  {report.evidence.map((entry) => (
                    <tr key={entry.title}>
                      <th scope="row" className="memo-cell-label">
                        {entry.title}
                      </th>
                      <td>{entry.source_kind}</td>
                      <td>{entry.reference}</td>
                      <td>{entry.as_of_date ?? 'Not stated'}</td>
                      <td>
                        {/* Approval is its own column and its own words. An
                          * unapproved source is never styled into looking
                          * approved, and Anchor has verified neither. */}
                        <span
                          className={
                            entry.approved ? 'memo-tag memo-tag-approved' : 'memo-tag memo-tag-open'
                          }
                        >
                          {entry.approved ? 'Approved' : 'Not approved'}
                        </span>
                      </td>
                      <td>{entry.cited_by.length > 0 ? entry.cited_by.join('; ') : 'Register only'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}

      {report.concluding_statement !== null && (
        <section className="memo-report-section">
          <h3 className="memo-report-section-title">Recommendation</h3>
          <p className="memo-report-summary">{report.concluding_statement}</p>
        </section>
      )}

      <footer className="memo-report-foot">
        <p>{report.confidentiality}</p>
        {report.verification_code !== null && (
          <p className="memo-report-verification">
            Verification code <code>{report.verification_code}</code>
          </p>
        )}
      </footer>
    </article>
  );
}
