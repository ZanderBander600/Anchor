import {
  ASSUMPTIONS_FIELD_GROUPS,
  DETAILED_OPERATING_FIELD_GROUPS,
  TERMS_FIELD_GROUPS,
} from './convert';
import type {
  AcquisitionFormValues,
  AcquisitionTermsFormValues,
  DetailedOperatingFormValues,
  OperatingMode,
} from './types';

/**
 * Sprint C Gate C3 -- the Underwrite workspace's internal navigation.
 *
 * This module is pure configuration: it decides which existing assumption
 * belongs on which tab, and nothing else. It performs no calculation, adds no
 * field, renames no field, and changes no unit or parsing rule. Every label,
 * prefix and suffix is read back out of the existing `*_FIELD_GROUPS`
 * definitions in `convert.ts` rather than retyped, so the tab layout can
 * never drift from the authoritative field configuration.
 */

export type UnderwriteTabId = 'acquisition' | 'operations' | 'debt' | 'exit' | 'results';

export const UNDERWRITE_TABS: { id: UnderwriteTabId; label: string }[] = [
  { id: 'acquisition', label: 'Acquisition' },
  { id: 'operations', label: 'Operations' },
  { id: 'debt', label: 'Debt' },
  { id: 'exit', label: 'Exit' },
  { id: 'results', label: 'Results' },
];

export type ResultsViewId = 'summary' | 'cash-flow' | 'owner-returns' | 'operating-statement';

/** Detailed adds the Operating Statement; Quick has no operating projection,
 * so it has no such view -- the sub-nav is derived from what the mode
 * actually produces rather than showing a dead entry. */
export function resultsViewsFor(mode: OperatingMode): { id: ResultsViewId; label: string }[] {
  const views: { id: ResultsViewId; label: string }[] = [
    { id: 'summary', label: 'Summary' },
    { id: 'cash-flow', label: 'Cash Flow' },
    { id: 'owner-returns', label: 'Owner Returns' },
  ];
  if (mode === 'detailed') {
    views.push({ id: 'operating-statement', label: 'Operating Statement' });
  }
  return views;
}

/** One assumption input, fully resolved: its display configuration comes from
 * `convert.ts`, its value and change handler from the caller's own mode
 * state. Quick and Detailed produce these from their own independent state
 * and never share a value object. */
export interface ResolvedField {
  id: string;
  label: string;
  prefix?: string;
  suffix?: string;
  value: string;
  onChange: (value: string) => void;
}

export interface FieldSection {
  /** Sub-view this section belongs to, for tabs that have internal
   * navigation (Detailed Operations). `null` means the tab shows all of its
   * sections at once. */
  view: string | null;
  title: string;
  fields: ResolvedField[];
}

// ---------------------------------------------------------------------------
// Field-configuration lookup. Flattens the existing groups into a by-key map
// so a tab layout can name a field without restating its label/prefix/suffix.
// ---------------------------------------------------------------------------

interface FieldConfig {
  label: string;
  prefix?: string;
  suffix?: string;
}

function configLookup(
  groups: { fields: { key: string; label: string; prefix?: string; suffix?: string }[] }[],
): Record<string, FieldConfig> {
  const lookup: Record<string, FieldConfig> = {};
  for (const group of groups) {
    for (const field of group.fields) {
      lookup[field.key] = { label: field.label, prefix: field.prefix, suffix: field.suffix };
    }
  }
  return lookup;
}

const QUICK_CONFIG = configLookup(ASSUMPTIONS_FIELD_GROUPS);
const TERMS_CONFIG = configLookup(TERMS_FIELD_GROUPS);
const OPERATING_CONFIG = configLookup(DETAILED_OPERATING_FIELD_GROUPS);

// ---------------------------------------------------------------------------
// Tab layouts.
//
// Hold Period has exactly one authoritative home (Acquisition) rather than
// appearing on both Acquisition and Exit. Financing Fee lives with the rest
// of the debt terms. Annual CapEx Reserve sits with Growth, alongside the
// other forward-looking operating assumptions. No assumption appears twice,
// and every assumption appears exactly once -- see the round-trip tests.
// ---------------------------------------------------------------------------

type QuickKey = keyof AcquisitionFormValues;
type TermsKey = keyof AcquisitionTermsFormValues;
type OperatingKey = keyof DetailedOperatingFormValues;

const QUICK_LAYOUT: {
  tab: UnderwriteTabId;
  view: string | null;
  title: string;
  keys: QuickKey[];
}[] = [
  {
    tab: 'acquisition',
    view: null,
    title: 'Acquisition & Transaction',
    keys: ['purchasePrice', 'holdPeriod', 'acquisitionCostPct'],
  },
  {
    tab: 'operations',
    view: null,
    title: 'Operating Assumptions',
    keys: ['currentNoi', 'occupancy', 'noiGrowth', 'annualCapexReserve'],
  },
  {
    tab: 'debt',
    view: null,
    title: 'Financing',
    keys: ['ltv', 'interestRate', 'amortization', 'ioPeriod', 'financingFeePct'],
  },
  {
    tab: 'exit',
    view: null,
    title: 'Exit',
    keys: ['exitCapRate', 'dispositionCostPct'],
  },
];

const DETAILED_TERMS_LAYOUT: {
  tab: UnderwriteTabId;
  view: string | null;
  title: string;
  keys: TermsKey[];
}[] = [
  {
    tab: 'acquisition',
    view: null,
    title: 'Acquisition & Transaction',
    keys: ['purchasePrice', 'holdPeriod', 'acquisitionCostPct'],
  },
  {
    tab: 'debt',
    view: null,
    title: 'Financing',
    keys: ['ltv', 'interestRate', 'amortization', 'ioPeriod', 'financingFeePct'],
  },
  {
    tab: 'exit',
    view: null,
    title: 'Exit',
    keys: ['exitCapRate', 'dispositionCostPct'],
  },
  {
    tab: 'operations',
    view: 'growth',
    title: 'Reserves',
    keys: ['annualCapexReserve'],
  },
];

const DETAILED_OPERATING_LAYOUT: {
  tab: UnderwriteTabId;
  view: string;
  title: string;
  keys: OperatingKey[];
}[] = [
  {
    tab: 'operations',
    view: 'revenue',
    title: 'Revenue',
    keys: ['grossPotentialRent', 'otherIncome', 'vacancyCreditLossPct'],
  },
  {
    tab: 'operations',
    view: 'expenses',
    title: 'Operating Expenses',
    keys: [
      'propertyTaxes',
      'insurance',
      'utilities',
      'repairsMaintenance',
      'otherOperatingExpenses',
      'managementFeePct',
    ],
  },
  {
    tab: 'operations',
    view: 'growth',
    title: 'Growth',
    keys: ['revenueGrowth', 'expenseGrowth'],
  },
];

/** Detailed Operations holds 12 assumptions across three distinct concerns,
 * so it gets its own sub-navigation. Quick Operations holds four and does
 * not -- the same architecture, sized to the content. */
export const OPERATIONS_VIEWS: { id: string; label: string }[] = [
  { id: 'revenue', label: 'Revenue' },
  { id: 'expenses', label: 'Expenses' },
  { id: 'growth', label: 'Growth' },
];

export interface QuickSectionSources {
  values: AcquisitionFormValues;
  onFieldChange: (key: QuickKey, value: string) => void;
}

export interface DetailedSectionSources {
  termsValues: AcquisitionTermsFormValues;
  operatingValues: DetailedOperatingFormValues;
  onTermsFieldChange: (key: TermsKey, value: string) => void;
  onOperatingFieldChange: (key: OperatingKey, value: string) => void;
}

/** Resolves Quick's 14 assumptions into per-tab sections. */
export function buildQuickSections(
  sources: QuickSectionSources,
): Record<UnderwriteTabId, FieldSection[]> {
  const byTab = emptyTabMap();
  for (const entry of QUICK_LAYOUT) {
    byTab[entry.tab].push({
      view: entry.view,
      title: entry.title,
      fields: entry.keys.map((key) => ({
        id: key,
        ...QUICK_CONFIG[key],
        value: sources.values[key],
        onChange: (value: string) => sources.onFieldChange(key, value),
      })),
    });
  }
  return byTab;
}

/** Resolves Detailed's 22 assumptions into per-tab sections, keeping each
 * field wired to its own value object -- terms fields never write operating
 * state, and vice versa. */
export function buildDetailedSections(
  sources: DetailedSectionSources,
): Record<UnderwriteTabId, FieldSection[]> {
  const byTab = emptyTabMap();
  for (const entry of DETAILED_TERMS_LAYOUT) {
    byTab[entry.tab].push({
      view: entry.view,
      title: entry.title,
      fields: entry.keys.map((key) => ({
        id: key,
        ...TERMS_CONFIG[key],
        value: sources.termsValues[key],
        onChange: (value: string) => sources.onTermsFieldChange(key, value),
      })),
    });
  }
  for (const entry of DETAILED_OPERATING_LAYOUT) {
    byTab[entry.tab].push({
      view: entry.view,
      title: entry.title,
      fields: entry.keys.map((key) => ({
        id: key,
        ...OPERATING_CONFIG[key],
        value: sources.operatingValues[key],
        onChange: (value: string) => sources.onOperatingFieldChange(key, value),
      })),
    });
  }
  return byTab;
}

function emptyTabMap(): Record<UnderwriteTabId, FieldSection[]> {
  return { acquisition: [], operations: [], debt: [], exit: [], results: [] };
}

/** Sections for one tab, filtered to the active sub-view when that tab has
 * sub-navigation. A section with `view: null` always shows. */
export function sectionsForView(sections: FieldSection[], view: string | null): FieldSection[] {
  if (view === null) {
    return sections;
  }
  return sections.filter((section) => section.view === null || section.view === view);
}
