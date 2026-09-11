/**
 * D5.5B -- resolving backend issue paths to the rent-roll row that produced them.
 *
 * This is the only place the frontend interprets an issue `path`, and it is
 * harder than it looks for two reasons discovered by probing the live API rather
 * than by reading the source.
 *
 * **1. The backend uses two path conventions, both real.**
 *
 * ```
 * suites[1].suite_area_sf                              index-keyed
 * suites[1].market_leasing_override.renewal_probability index-keyed
 * leases[1].base_rent_psf                               index-keyed
 * suites[300].initial_vacancy                           SUITE-ID-keyed
 * suites[300].initial_vacancy.initial_lease_up_months   SUITE-ID-keyed
 * suites[100]                                           SUITE-ID-keyed
 * ```
 *
 * The initial-vacancy family and the bare-suite form come from validators that
 * key on `suite_id`; everything else keys on array position. A suite id is very
 * often numeric ("100", "300"), so `suites[100]` is genuinely ambiguous read as
 * text alone. It is resolved below by trying both and preferring the reading
 * that is unambiguous, falling back to the field family only when both resolve
 * and disagree.
 *
 * **2. An index is only meaningful against the array that was submitted.**
 *
 * By the time a 422 comes back the analyst may have added, deleted or reordered
 * rows. Resolving `suites[1]` against *current* state would attach an error to
 * whichever suite happens to sit there now -- silently blaming the wrong space.
 * So the caller captures a {@link SubmittedRentRoll} at submit time, and every
 * index is resolved against that snapshot, into a stable local `rowId`.
 *
 * Anything that cannot be resolved is returned in `unanchored` and rendered in
 * the workspace banner. An issue is never dropped.
 */

import type { LeaseLevelIssue } from './leaseLevelTypes';

/** What was actually sent, recorded at submit time.
 *
 * `suiteRowIds[i]` is the local row that produced `suites[i]`; `leaseRowIds[j]`
 * is the row that produced `leases[j]`. `suiteIds[i]` is that suite's submitted
 * `suite_id`, which is what the suite-id-keyed validators name. */
export interface SubmittedRentRoll {
  suiteRowIds: string[];
  suiteIds: string[];
  leaseRowIds: string[];
}

export const EMPTY_SUBMITTED_RENT_ROLL: SubmittedRentRoll = {
  suiteRowIds: [],
  suiteIds: [],
  leaseRowIds: [],
};

/** Every issue belonging to one row, ready to render. */
export interface RowIssues {
  /** Keyed by the field path relative to the suite or lease, e.g.
   * `suite_area_sf`, `base_rent_psf`, `initial_vacancy.initial_lease_up_months`,
   * `market_leasing_override.renewal_probability`. */
  fields: Map<string, LeaseLevelIssue>;
  /** Issues naming the whole row rather than one field, such as
   * `MULTIPLE_KNOWN_LEASES_IN_SUITE`. */
  rowLevel: LeaseLevelIssue[];
  /** The occupancy/vacancy message shown beside the status control. */
  vacancyMessage?: string;
  hasError: boolean;
  /** True when at least one issue names a field the grid does not show, so the
   * row can flag its Details button rather than hiding the problem. */
  hasDrawerError: boolean;
}

/** The suite and lease fields the grid itself renders. Everything else is only
 * reachable through the drawer, and must be flagged there. */
const GRID_FIELDS = new Set([
  'suite_id',
  'suite_area_sf',
  'market_rent_psf',
  'tenant_name',
  'lease_expiration_date',
  'base_rent_psf',
  'lease_type',
]);

/** Field families the backend keys by `suite_id` rather than by array index.
 * Established by probing the live API; see the module docstring. */
function isSuiteIdKeyedField(field: string): boolean {
  return field === '' || field === 'initial_vacancy' || field.startsWith('initial_vacancy.');
}

interface ParsedPath {
  collection: 'suites' | 'leases';
  key: string;
  field: string;
}

/** Split `suites[300].initial_vacancy.strategy` into its three parts. */
function parsePath(path: string): ParsedPath | null {
  const match = /^(suites|leases)\[([^\]]*)\](?:\.(.*))?$/.exec(path);
  if (match === null) {
    return null;
  }
  return {
    collection: match[1] as 'suites' | 'leases',
    key: match[2],
    field: match[3] ?? '',
  };
}

function emptyRowIssues(): RowIssues {
  return { fields: new Map(), rowLevel: [], hasError: false, hasDrawerError: false };
}

/**
 * Resolve one path to a local row id, or `null`.
 *
 * Tries both readings of the bracketed key and prefers the unambiguous one. When
 * both resolve and disagree, the field family decides -- the only case where
 * this module relies on knowing which validator produced the issue.
 */
function resolveRowId(parsed: ParsedPath, submitted: SubmittedRentRoll): string | null {
  const rowIds = parsed.collection === 'suites' ? submitted.suiteRowIds : submitted.leaseRowIds;

  const index = /^\d+$/.test(parsed.key) ? Number(parsed.key) : null;
  const byIndex = index !== null && index < rowIds.length ? rowIds[index] : null;

  // Only suites are ever addressed by id; a lease is always positional.
  const idPosition =
    parsed.collection === 'suites' ? submitted.suiteIds.indexOf(parsed.key) : -1;
  const byId = idPosition === -1 ? null : submitted.suiteRowIds[idPosition];

  if (byIndex !== null && byId !== null && byIndex !== byId) {
    return isSuiteIdKeyedField(parsed.field) ? byId : byIndex;
  }
  return byId ?? byIndex;
}

/**
 * Group backend issues by the row that produced them.
 *
 * Returns the rows that have issues plus everything that could not be resolved,
 * which the caller must still display. Warnings are grouped too -- they are
 * shown, but they do not mark a row as failing.
 */
export function resolveRowIssues(
  issues: readonly LeaseLevelIssue[],
  submitted: SubmittedRentRoll,
): { byRow: Map<string, RowIssues>; unanchored: LeaseLevelIssue[] } {
  const byRow = new Map<string, RowIssues>();
  const unanchored: LeaseLevelIssue[] = [];

  for (const issue of issues) {
    const parsed = parsePath(issue.path);
    if (parsed === null) {
      unanchored.push(issue);
      continue;
    }
    const rowId = resolveRowId(parsed, submitted);
    if (rowId === null) {
      unanchored.push(issue);
      continue;
    }

    let row = byRow.get(rowId);
    if (row === undefined) {
      row = emptyRowIssues();
      byRow.set(rowId, row);
    }

    if (issue.severity === 'error') {
      row.hasError = true;
    }

    if (parsed.field === '') {
      row.rowLevel.push(issue);
      continue;
    }

    // First issue wins per field: the backend emits in a deterministic order,
    // and showing the first one under an input is more useful than concatenating.
    if (!row.fields.has(parsed.field)) {
      row.fields.set(parsed.field, issue);
    }
    if (parsed.field === 'initial_vacancy' && row.vacancyMessage === undefined) {
      row.vacancyMessage = issue.message;
    }
    if (!GRID_FIELDS.has(parsed.field)) {
      row.hasDrawerError = true;
    }
  }

  return { byRow, unanchored };
}
