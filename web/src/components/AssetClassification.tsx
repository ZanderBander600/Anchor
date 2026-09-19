import { useEffect, useId, useRef, useState } from 'react';
import type { ChangeEvent, RefObject } from 'react';

import {
  ASSET_SUBTYPE_EXAMPLES,
  ASSET_TYPES,
  ASSET_TYPE_FILTER_OPTIONS,
  ASSET_TYPE_LABELS,
  NOT_SPECIFIED_LABEL,
  assetTypeLabel,
  isAssetType,
  isAssetTypeFilterValue,
} from '../assetTypes';
import type {
  AssetClassificationDraft,
  AssetClassificationIssues,
  AssetType,
  AssetTypeFilterValue,
} from '../assetTypes';

/**
 * Asset Types 1 -- the classification surfaces, shared by every workspace that
 * shows or edits one.
 *
 * - `AssetClassificationField`: the controlled Asset Type select and the
 *   analyst's own Asset Subtype, with the dynamic "Other" requirement and
 *   inline, announced validation.
 * - `DealClassificationStrip`: the compact Underwrite strip, laid out like the
 *   Deal Context strip beside it (its own class names, the same look).
 * - `DealClassificationSummary`: the Overview read.
 * - `AssetClassificationText`: one type/subtype pair in a table row or list.
 * - `AssetTypeFilter`: the library filter, presentation only.
 *
 * Nothing here computes anything or reaches an analysis: classification is
 * non-economic metadata, and editing it marks a Deal dirty and nothing else.
 */

// =============================================================================
// The field
// =============================================================================

export interface AssetClassificationFieldProps {
  draft: AssetClassificationDraft;
  onChange: (draft: AssetClassificationDraft) => void;
  issues: AssetClassificationIssues;
  /** A new Deal must be classified; a legacy "Not specified" Deal need not be. */
  isTypeRequired: boolean;
  /** Focus target for "reveal the first problem". */
  typeSelectRef?: RefObject<HTMLSelectElement | null>;
  disabled?: boolean;
}

export function AssetClassificationField({
  draft,
  onChange,
  issues,
  isTypeRequired,
  typeSelectRef,
  disabled = false,
}: AssetClassificationFieldProps) {
  const id = useId();
  const typeId = `${id}-type`;
  const subtypeId = `${id}-subtype`;
  const typeErrorId = `${id}-type-error`;
  const subtypeHintId = `${id}-subtype-hint`;
  const subtypeErrorId = `${id}-subtype-error`;
  const isOther = draft.assetType === 'other';

  return (
    <div className="asset-classification-field">
      <div className="field">
        <label className="field-label" htmlFor={typeId}>
          Asset Type
          {isTypeRequired && (
            <>
              {' '}
              <span className="asset-classification-required">(required)</span>
            </>
          )}
        </label>
        <select
          id={typeId}
          ref={typeSelectRef}
          className="field-input asset-classification-select"
          value={draft.assetType}
          disabled={disabled}
          aria-required={isTypeRequired || undefined}
          aria-invalid={issues.assetType !== undefined || undefined}
          aria-describedby={issues.assetType !== undefined ? typeErrorId : undefined}
          onChange={(event: ChangeEvent<HTMLSelectElement>) => {
            const next = event.target.value;
            onChange({ ...draft, assetType: isAssetType(next) ? next : '' });
          }}
        >
          <option value="" disabled={isTypeRequired}>
            {isTypeRequired ? 'Choose an asset type…' : NOT_SPECIFIED_LABEL}
          </option>
          {ASSET_TYPES.map((assetType) => (
            <option key={assetType} value={assetType}>
              {ASSET_TYPE_LABELS[assetType]}
            </option>
          ))}
        </select>
        {issues.assetType !== undefined && (
          <p id={typeErrorId} className="field-error" role="alert">
            {issues.assetType}
          </p>
        )}
      </div>

      <div className="field">
        <label className="field-label" htmlFor={subtypeId}>
          {isOther ? 'Describe the Asset Type' : 'Asset Subtype (optional)'}
          {isOther && (
            <>
              {' '}
              <span className="asset-classification-required">(required)</span>
            </>
          )}
        </label>
        <input
          id={subtypeId}
          type="text"
          className="field-input"
          value={draft.assetSubtype}
          disabled={disabled}
          placeholder={isOther ? 'e.g. Cold storage campus' : ASSET_SUBTYPE_EXAMPLES}
          aria-required={isOther || undefined}
          aria-invalid={issues.assetSubtype !== undefined || undefined}
          aria-describedby={
            issues.assetSubtype !== undefined ? `${subtypeHintId} ${subtypeErrorId}` : subtypeHintId
          }
          onChange={(event: ChangeEvent<HTMLInputElement>) =>
            onChange({ ...draft, assetSubtype: event.target.value })
          }
        />
        <p id={subtypeHintId} className="field-hint asset-classification-hint">
          {isOther
            ? 'Required when the Asset Type is Other: say what the asset is, in your own words.'
            : 'Your own description, in your own words. ' + ASSET_SUBTYPE_EXAMPLES + '.'}
        </p>
        {issues.assetSubtype !== undefined && (
          <p id={subtypeErrorId} className="field-error" role="alert">
            {issues.assetSubtype}
          </p>
        )}
      </div>
    </div>
  );
}

// =============================================================================
// Underwrite strip
// =============================================================================

export interface DealClassificationStripProps {
  draft: AssetClassificationDraft;
  onChange: (draft: AssetClassificationDraft) => void;
  issues: AssetClassificationIssues;
  isTypeRequired: boolean;
  /** A fresh token from the caller opens the strip and focuses the type
   * select -- used when a Save is stopped by a classification problem. `null`
   * until the first such request. */
  revealSignal: object | null;
  disabled?: boolean;
}

function classificationSummary(draft: AssetClassificationDraft): string {
  const subtype = draft.assetSubtype.trim();
  if (draft.assetType === '') {
    return NOT_SPECIFIED_LABEL;
  }
  return subtype ? `${ASSET_TYPE_LABELS[draft.assetType]} · ${subtype}` : ASSET_TYPE_LABELS[draft.assetType];
}

/**
 * The compact classification strip inside Underwrite, above Deal Context.
 *
 * Collapsed, it reads one line ("Multifamily · Garden apartments") with an
 * Edit toggle. It starts open whenever the Deal has no type yet -- a new Deal,
 * which must be classified, or a legacy "Not specified" one -- so the choice is
 * in front of the analyst rather than behind a button. The editor stays
 * mounted while collapsed, like the Deal Context strip's, so a half-typed
 * subtype survives collapsing it.
 */
export function DealClassificationStrip({
  draft,
  onChange,
  issues,
  isTypeRequired,
  revealSignal,
  disabled = false,
}: DealClassificationStripProps) {
  const [isEditing, setIsEditing] = useState(draft.assetType === '');
  const typeSelect = useRef<HTMLSelectElement>(null);
  const editorId = useId();
  const hasIssues = issues.assetType !== undefined || issues.assetSubtype !== undefined;
  // The signal the strip was mounted with has already been answered (or
  // belongs to another deal): the strip is keyed by deal identity and remounts
  // on the first Save, and replaying the stale request would reopen it and
  // take focus away from wherever the analyst is. Only a new token reveals.
  const answeredSignal = useRef(revealSignal);

  useEffect(() => {
    if (revealSignal === null || revealSignal === answeredSignal.current) {
      return;
    }
    answeredSignal.current = revealSignal;
    setIsEditing(true);
    // After the editor is un-hidden, so the focus lands on a visible control.
    const frame = window.requestAnimationFrame(() => typeSelect.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [revealSignal]);

  return (
    <section className="deal-classification-strip" aria-label="Deal classification">
      <div className="deal-classification-strip-row">
        <span className="deal-classification-strip-label">Asset Type</span>
        <p
          className={
            draft.assetType === ''
              ? 'deal-classification-strip-text deal-classification-strip-text-empty'
              : 'deal-classification-strip-text'
          }
        >
          {draft.assetType === '' && isTypeRequired
            ? 'Not chosen yet. Choose the Asset Type before saving.'
            : classificationSummary(draft)}
        </p>
        <button
          type="button"
          className="btn btn-ghost btn-xs"
          aria-expanded={isEditing}
          aria-controls={editorId}
          onClick={() => setIsEditing((open) => !open)}
          // Collapsing would hide a problem the analyst still has to fix.
          disabled={isEditing && hasIssues}
        >
          {isEditing ? 'Done' : 'Edit'}
        </button>
      </div>

      <div id={editorId} className="deal-classification-strip-editor" hidden={!isEditing}>
        <AssetClassificationField
          draft={draft}
          onChange={onChange}
          issues={issues}
          isTypeRequired={isTypeRequired}
          typeSelectRef={typeSelect}
          disabled={disabled}
        />
      </div>
    </section>
  );
}

// =============================================================================
// Overview read
// =============================================================================

export function DealClassificationSummary({ draft }: { draft: AssetClassificationDraft }) {
  const subtype = draft.assetSubtype.trim();
  return (
    <section className="card deal-classification-summary" aria-label="Asset classification">
      <dl className="deal-classification-summary-list">
        <div>
          <dt>Asset Type</dt>
          <dd className={draft.assetType === '' ? 'asset-classification-empty' : undefined}>
            {draft.assetType === '' ? NOT_SPECIFIED_LABEL : ASSET_TYPE_LABELS[draft.assetType]}
          </dd>
        </div>
        <div>
          <dt>{draft.assetType === 'other' ? 'Description' : 'Asset Subtype'}</dt>
          <dd className={subtype === '' ? 'asset-classification-empty' : undefined}>
            {subtype === '' ? '—' : subtype}
          </dd>
        </div>
      </dl>
    </section>
  );
}

// =============================================================================
// One pair in a row or list
// =============================================================================

/**
 * The type and, beneath or beside it, the analyst's subtype. "Not specified"
 * reads as muted text rather than as a type, so a legacy record is never
 * mistaken for a classified one. `legacyNote` is shown only for a record that
 * has no type but kept older free text (a Managed Asset's retired property
 * type): it is exposed honestly, labelled as what it is, and never promoted to
 * a type.
 */
/** Real text between type and subtype, so the pair reads as two words to
 * assistive technology: a visible " · " inline, a visually hidden ", " when
 * stacked (the stack itself separates them for sighted readers). */
function Separator({ layout }: { layout: 'stacked' | 'inline' }) {
  return layout === 'inline' ? (
    <span className="asset-classification-separator"> · </span>
  ) : (
    <span className="visually-hidden">, </span>
  );
}

export function AssetClassificationText({
  assetType,
  assetSubtype,
  legacyNote,
  layout = 'stacked',
}: {
  assetType: AssetType | null;
  assetSubtype: string | null;
  legacyNote?: string | null;
  layout?: 'stacked' | 'inline';
}) {
  const className =
    layout === 'inline' ? 'asset-classification-text asset-classification-inline' : 'asset-classification-text';
  if (assetType === null) {
    return (
      <span className={className}>
        <span className="asset-classification-empty">{NOT_SPECIFIED_LABEL}</span>
        {legacyNote ? (
          <>
            <Separator layout={layout} />
            <span className="asset-classification-subtype">Recorded as “{legacyNote}”</span>
          </>
        ) : null}
      </span>
    );
  }
  return (
    <span className={className}>
      <span className="asset-classification-type">{assetTypeLabel(assetType)}</span>
      {assetSubtype ? (
        <>
          <Separator layout={layout} />
          <span className="asset-classification-subtype">{assetSubtype}</span>
        </>
      ) : null}
    </span>
  );
}

// =============================================================================
// Library filter
// =============================================================================

/**
 * One controlled select: every record, one type, or the legacy "Not
 * specified" records. It only narrows what is shown; it writes nothing.
 * `shown`/`total` drive the polite status line that announces the result.
 */
export function AssetTypeFilter({
  value,
  onChange,
  shown,
  total,
  noun,
}: {
  value: AssetTypeFilterValue;
  onChange: (value: AssetTypeFilterValue) => void;
  shown: number;
  total: number;
  /** Plural noun for the status line, e.g. "deals". */
  noun: string;
}) {
  const id = useId();
  return (
    <div className="asset-type-filter">
      <label className="asset-type-filter-label" htmlFor={id}>
        Asset Type
      </label>
      <select
        id={id}
        className="field-input asset-type-filter-select"
        value={value}
        onChange={(event: ChangeEvent<HTMLSelectElement>) => {
          const next = event.target.value;
          onChange(isAssetTypeFilterValue(next) ? next : 'all');
        }}
      >
        {ASSET_TYPE_FILTER_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <span className="asset-type-filter-status" role="status" aria-live="polite">
        {value === 'all' ? `${total} ${noun}` : `Showing ${shown} of ${total} ${noun}`}
      </span>
    </div>
  );
}
