/**
 * Phase 7 Gate P7.6 -- a backend refusal of a visible Investment, as an
 * analyst reads it.
 *
 * Each issue names the Unit it concerns (by its Deal's name, never an opaque
 * id), gives the analyst's reading of the rule where there is one ("Unit
 * purchase-price allocations do not reconcile…"), and keeps the backend's own
 * message beneath it, with any quoted Unit id replaced by that Unit's name. The
 * meaning is the backend's; only the presentation is added.
 */

import { describeInvestmentIssue } from '../investmentCatalog';
import type { InvestmentIssue, InvestmentVariantIssue } from '../investmentTypes';

export interface InvestmentIssueListProps {
  issues: readonly (InvestmentIssue | InvestmentVariantIssue)[];
  /** Each Unit's id, mapped to the name an analyst knows it by. */
  names: Readonly<Record<string, string>>;
  id?: string;
}

export function InvestmentIssueList({ issues, names, id }: InvestmentIssueListProps) {
  if (issues.length === 0) {
    return null;
  }
  return (
    <ul id={id} className="investment-issues" role="alert">
      {issues.map((issue, position) => {
        const text = describeInvestmentIssue(issue, names);
        return (
          <li key={`${issue.code}-${position}`}>
            {text.unit !== null && <strong className="investment-issue-unit">{`${text.unit}: `}</strong>}
            {text.lead !== null && <span className="investment-issue-lead">{`${text.lead} `}</span>}
            <span className="investment-issue-message">{text.message}</span>
          </li>
        );
      })}
    </ul>
  );
}
