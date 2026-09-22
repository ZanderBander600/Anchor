/**
 * Phase 7 Gate P7.10 Stage 4 -- one library row, described once.
 *
 * **Correction 1 of the second independent review.** The Investment Committee
 * library is a navigation and status surface, so at phone width it is a list of
 * cards rather than a table an analyst has to scroll sideways to read. Both
 * presentations render *this*, which is why it is its own module: one place
 * decides a row's status, recommendation, decision and selected cell, and the
 * two presentations cannot drift into disagreeing about the same memo.
 *
 * It computes nothing. Every value here is a stored fact relabelled through the
 * product's existing vocabulary.
 */

import { assetTypeLabel } from './assetTypes';
import type { AssetType } from './assetTypes';
import {
  BASE_SCENARIO_KEY,
  BASE_SCENARIO_NAME,
  BASE_STRATEGY_KEY,
  BASE_STRATEGY_NAME,
  COMMITTEE_LABELS,
  displayDate,
  PERSPECTIVE_LABELS,
  RECOMMENDATION_LABELS,
} from './memoCatalog';
import type { MemoLibraryEntry } from './memoTypes';

/**
 * One library row, described once.
 *
 * **Correction 1 of the second Stage 4 review.** The library is a navigation
 * and status surface, so at phone width it is a list of cards rather than a
 * table an analyst has to scroll sideways to read. Both presentations render
 * *this*, so there is one place where a row's status, recommendation, decision
 * and selected cell are decided, and no chance of the two drifting into
 * disagreeing about the same memo.
 */
export interface MemoLibraryRow {
  entry: MemoLibraryEntry;
  name: string;
  /** "Deal" or "Investment": what this memo is written about. */
  kind: string;
  classification: string;
  units: string;
  status: string;
  recommendation: string;
  decision: string;
  /** The Strategy and Scenario the memo is written from, named, never keyed. */
  cell: string | null;
  activity: string;
  action: string;
}

export function describeEntry(entry: MemoLibraryEntry): MemoLibraryRow {
  const started = entry.has_draft || entry.version_count > 0;
  return {
    entry,
    name: entry.name,
    kind: entry.deal_id !== null ? 'Deal' : 'Investment',
    classification: classificationOf(entry),
    units: unitsOf(entry),
    status: statusOf(entry),
    recommendation:
      entry.analyst_recommendation === null
        ? 'Not stated'
        : RECOMMENDATION_LABELS[entry.analyst_recommendation],
    // The committee's own decision, never the analyst's echoed back.
    // "Not yet recorded" is not "Pending": one is an absence, the other is an
    // outcome somebody chose.
    decision:
      entry.committee_decision === null
        ? 'Not yet recorded'
        : COMMITTEE_LABELS[entry.committee_decision],
    cell: cellOf(entry),
    activity: displayDate(entry.latest_published_at ?? entry.draft_updated_at) ?? 'Not yet saved',
    action: started ? 'Open memo' : 'Start memo',
  };
}

/** The decision cell, by the names the reserved Base keys carry.
 *
 * Only the Base pair can be named from a library row, because a row carries the
 * selected *ids* and not an authored Strategy's name. An authored cell is
 * therefore described as authored rather than printed as its key -- the
 * workspace, which has the Strategy list, names it in full. */
function cellOf(entry: MemoLibraryEntry): string | null {
  if (entry.strategy_id === null || entry.scenario_id === null) {
    return null;
  }
  const strategy = entry.strategy_id === BASE_STRATEGY_KEY ? BASE_STRATEGY_NAME : 'Custom Strategy';
  const scenario = entry.scenario_id === BASE_SCENARIO_KEY ? BASE_SCENARIO_NAME : 'Custom Scenario';
  const perspective =
    entry.perspective === null ? null : PERSPECTIVE_LABELS[entry.perspective];
  return perspective === null ? `${strategy} · ${scenario}` : `${strategy} · ${scenario} · ${perspective}`;
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
