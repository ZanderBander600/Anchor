/**
 * Asset Types 1 -- the controlled Asset Type vocabulary and the analyst-authored
 * Asset Subtype, on the frontend.
 *
 * Mirrors `anchor.asset_types` exactly: the same ten wire values, the same
 * product labels and the same subtype rules. The wire value is the one
 * canonical representation -- the database, the API and this file all use it --
 * and `tests/test_asset_types_1_architecture.py` holds the labels here to the
 * Python ones, so the two cannot drift. The backend remains the authority: it
 * re-validates every write, and this module only lets the form say what is
 * wrong before a round trip.
 *
 * Classification is non-economic metadata. Nothing here reaches an analysis,
 * a fingerprint or the AI Analyst, and nothing here computes a figure.
 */

/** The controlled Asset Type wire values, in vocabulary order. */
export const ASSET_TYPES = [
  'multifamily',
  'office',
  'industrial',
  'retail',
  'hospitality',
  'self_storage',
  'manufactured_housing',
  'mixed_use',
  'land_development',
  'other',
] as const;

export type AssetType = (typeof ASSET_TYPES)[number];

/** The product label of every controlled type. */
export const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  multifamily: 'Multifamily',
  office: 'Office',
  industrial: 'Industrial',
  retail: 'Retail',
  hospitality: 'Hospitality',
  self_storage: 'Self-Storage',
  manufactured_housing: 'Manufactured Housing',
  mixed_use: 'Mixed-Use',
  land_development: 'Land/Development',
  other: 'Other',
};

/** The longest subtype accepted, in characters, after trimming -- the same
 * limit the backend enforces. */
export const ASSET_SUBTYPE_MAX_LENGTH = 80;

/** How a record with no controlled classification is presented. Display only;
 * never sent and never stored. */
export const NOT_SPECIFIED_LABEL = 'Not specified';

/** Example subtypes shown as guidance. Examples only: the subtype is free text
 * and is never matched against them. */
export const ASSET_SUBTYPE_EXAMPLES = 'e.g. Garden apartments, Medical office, Last-mile warehouse';

export function isAssetType(value: unknown): value is AssetType {
  return typeof value === 'string' && (ASSET_TYPES as readonly string[]).includes(value);
}

export function assetTypeLabel(assetType: AssetType | null | undefined): string {
  return assetType ? ASSET_TYPE_LABELS[assetType] : NOT_SPECIFIED_LABEL;
}

/** The classification a Deal or Managed Asset carries on the wire. */
export interface AssetClassificationFields {
  asset_type: AssetType | null;
  asset_subtype: string | null;
}

/** The form's own state: the select's value (`''` until one is chosen) and the
 * subtype exactly as typed. */
export interface AssetClassificationDraft {
  assetType: AssetType | '';
  assetSubtype: string;
}

export const BLANK_CLASSIFICATION_DRAFT: AssetClassificationDraft = { assetType: '', assetSubtype: '' };

export function classificationDraftOf(
  fields: Partial<AssetClassificationFields> | null | undefined,
): AssetClassificationDraft {
  return {
    assetType: fields?.asset_type ?? '',
    assetSubtype: fields?.asset_subtype ?? '',
  };
}

export function isSameClassificationDraft(
  a: AssetClassificationDraft,
  b: AssetClassificationDraft,
): boolean {
  return a.assetType === b.assetType && a.assetSubtype.trim() === b.assetSubtype.trim();
}

/** Inline issues for the two fields. Empty when the draft may be saved. */
export interface AssetClassificationIssues {
  assetType?: string;
  assetSubtype?: string;
}

/** Characters, not UTF-16 code units, so an accented or emoji subtype is
 * measured the way the backend measures it. */
function characterCount(text: string): number {
  return Array.from(text).length;
}

/**
 * The issues that stop a draft being saved.
 *
 * `requireType` is true for a Deal that has never been saved: a new Deal must
 * be classified. A legacy Deal that is "Not specified" may still be saved
 * without one -- nothing is inferred for it -- and gains a type the moment the
 * analyst chooses one.
 */
export function classificationIssues(
  draft: AssetClassificationDraft,
  { requireType }: { requireType: boolean },
): AssetClassificationIssues {
  const issues: AssetClassificationIssues = {};
  const subtype = draft.assetSubtype.trim();
  if (draft.assetType === '') {
    if (requireType) {
      issues.assetType = 'Choose an Asset Type.';
    } else if (subtype !== '') {
      issues.assetType = 'Choose an Asset Type before describing a subtype.';
    }
  }
  if (characterCount(subtype) > ASSET_SUBTYPE_MAX_LENGTH) {
    issues.assetSubtype = `Keep the description to ${ASSET_SUBTYPE_MAX_LENGTH} characters or fewer.`;
  } else if (draft.assetType === 'other' && subtype === '') {
    issues.assetSubtype = 'Describe the asset type. This is required when the Asset Type is Other.';
  }
  return issues;
}

export function hasClassificationIssues(issues: AssetClassificationIssues): boolean {
  return issues.assetType !== undefined || issues.assetSubtype !== undefined;
}

/** The two wire fields for a draft: the subtype trimmed, blank meaning absent. */
export function classificationRequest(draft: AssetClassificationDraft): AssetClassificationFields {
  const subtype = draft.assetSubtype.trim();
  return {
    asset_type: draft.assetType === '' ? null : draft.assetType,
    asset_subtype: subtype === '' ? null : subtype,
  };
}

// =============================================================================
// Filtering -- presentation only; nothing is written
// =============================================================================

/** A library filter: every record, one controlled type, or the legacy records
 * with no classification. */
export type AssetTypeFilterValue = 'all' | AssetType | 'not_specified';

export const ASSET_TYPE_FILTER_OPTIONS: { value: AssetTypeFilterValue; label: string }[] = [
  { value: 'all', label: 'All asset types' },
  ...ASSET_TYPES.map((assetType) => ({ value: assetType, label: ASSET_TYPE_LABELS[assetType] })),
  { value: 'not_specified', label: NOT_SPECIFIED_LABEL },
];

export function isAssetTypeFilterValue(value: string): value is AssetTypeFilterValue {
  return value === 'all' || value === 'not_specified' || isAssetType(value);
}

/**
 * Whether a record whose assets carry `assetTypes` passes `filter`.
 *
 * One record may hold several assets -- an Investment over several Units -- so
 * this takes every type the record contains (`null` for an unclassified one)
 * and matches when *any* of them does. It never picks one type to stand for the
 * whole record.
 */
export function matchesAssetTypeFilter(
  assetTypes: readonly (AssetType | null)[],
  filter: AssetTypeFilterValue,
): boolean {
  if (filter === 'all') {
    return true;
  }
  if (filter === 'not_specified') {
    return assetTypes.some((assetType) => assetType === null);
  }
  return assetTypes.includes(filter);
}

/**
 * The distinct types a multi-asset record holds, in vocabulary order, with
 * `null` ("Not specified") last. Used to label an Investment honestly: it lists
 * what its Units are rather than inventing one type for all of them.
 */
export function distinctAssetTypes(assetTypes: readonly (AssetType | null)[]): (AssetType | null)[] {
  const present = new Set(assetTypes);
  const ordered: (AssetType | null)[] = ASSET_TYPES.filter((assetType) => present.has(assetType));
  if (present.has(null)) {
    ordered.push(null);
  }
  return ordered;
}
