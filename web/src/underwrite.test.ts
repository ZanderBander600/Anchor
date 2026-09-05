import { describe, expect, it, vi } from 'vitest';
import {
  UNDERWRITE_TABS,
  buildDetailedSections,
  buildQuickSections,
  resultsViewsFor,
  sectionsForView,
} from './underwrite';
import {
  ASSUMPTIONS_FIELD_GROUPS,
  BLANK_DETAILED_FORM_VALUES,
  BLANK_FORM_VALUES,
  DETAILED_OPERATING_FIELD_GROUPS,
  TERMS_FIELD_GROUPS,
} from './convert';

function allFieldIds(sections: ReturnType<typeof buildQuickSections>): string[] {
  return Object.values(sections)
    .flat()
    .flatMap((section) => section.fields.map((field) => field.id));
}

describe('Underwrite tab layout', () => {
  const quick = buildQuickSections({ values: BLANK_FORM_VALUES, onFieldChange: vi.fn() });
  const detailed = buildDetailedSections({
    termsValues: BLANK_DETAILED_FORM_VALUES.terms,
    operatingValues: BLANK_DETAILED_FORM_VALUES.operating,
    onTermsFieldChange: vi.fn(),
    onOperatingFieldChange: vi.fn(),
  });

  it('exposes the five locked Underwrite tabs', () => {
    expect(UNDERWRITE_TABS.map((tab) => tab.label)).toEqual([
      'Acquisition',
      'Operations',
      'Debt',
      'Exit',
      'Results',
    ]);
  });

  it('places every one of Quick’s assumptions on exactly one tab', () => {
    const expected = ASSUMPTIONS_FIELD_GROUPS.flatMap((g) => g.fields.map((f) => f.key)).sort();
    const actual = allFieldIds(quick).sort();

    expect(actual).toEqual(expected);
    expect(new Set(actual).size).toBe(actual.length);
  });

  it('places every one of Detailed’s assumptions on exactly one tab', () => {
    const expected = [
      ...TERMS_FIELD_GROUPS.flatMap((g) => g.fields.map((f) => f.key)),
      ...DETAILED_OPERATING_FIELD_GROUPS.flatMap((g) => g.fields.map((f) => f.key)),
    ].sort();
    const actual = allFieldIds(detailed).sort();

    expect(actual).toEqual(expected);
    expect(new Set(actual).size).toBe(actual.length);
  });

  it('gives Hold Period exactly one authoritative home, on Acquisition', () => {
    for (const sections of [quick, detailed]) {
      const tabsWithHoldPeriod = UNDERWRITE_TABS.filter((tab) =>
        sections[tab.id].some((section) => section.fields.some((f) => f.id === 'holdPeriod')),
      ).map((tab) => tab.id);
      expect(tabsWithHoldPeriod).toEqual(['acquisition']);
    }
  });

  it('assigns the expected assumptions to each Detailed tab', () => {
    const idsFor = (tab: 'acquisition' | 'operations' | 'debt' | 'exit') =>
      detailed[tab].flatMap((section) => section.fields.map((f) => f.id)).sort();

    expect(idsFor('acquisition')).toEqual(['acquisitionCostPct', 'holdPeriod', 'purchasePrice']);
    expect(idsFor('debt')).toEqual([
      'amortization',
      'financingFeePct',
      'interestRate',
      'ioPeriod',
      'ltv',
    ]);
    expect(idsFor('exit')).toEqual(['dispositionCostPct', 'exitCapRate']);
    expect(idsFor('operations')).toContain('grossPotentialRent');
    expect(idsFor('operations')).toContain('managementFeePct');
    expect(idsFor('operations')).toContain('annualCapexReserve');
  });

  it('gives Quick the same tabs, carrying its own authoritative inputs', () => {
    const operations = quick.operations.flatMap((s) => s.fields.map((f) => f.id));
    expect(operations).toEqual(['currentNoi', 'occupancy', 'noiGrowth', 'annualCapexReserve']);
    // Quick has no Detailed-only operating inputs, and Detailed has no
    // Quick-only NOI inputs -- neither mode ever fabricates the other's.
    expect(allFieldIds(quick)).not.toContain('grossPotentialRent');
    expect(allFieldIds(detailed)).not.toContain('currentNoi');
    expect(allFieldIds(detailed)).not.toContain('occupancy');
    expect(allFieldIds(detailed)).not.toContain('noiGrowth');
  });

  it('reads labels and affixes from the authoritative field configuration', () => {
    const purchasePrice = quick.acquisition
      .flatMap((s) => s.fields)
      .find((f) => f.id === 'purchasePrice');
    expect(purchasePrice?.label).toBe('Purchase Price');
    expect(purchasePrice?.prefix).toBe('$');

    const ltv = detailed.debt.flatMap((s) => s.fields).find((f) => f.id === 'ltv');
    expect(ltv?.label).toBe('LTV');
    expect(ltv?.suffix).toBe('%');
  });

  it('routes each field’s edits to its own value object', () => {
    const onTermsFieldChange = vi.fn();
    const onOperatingFieldChange = vi.fn();
    const sections = buildDetailedSections({
      termsValues: BLANK_DETAILED_FORM_VALUES.terms,
      operatingValues: BLANK_DETAILED_FORM_VALUES.operating,
      onTermsFieldChange,
      onOperatingFieldChange,
    });

    sections.acquisition.flatMap((s) => s.fields).find((f) => f.id === 'purchasePrice')!.onChange('1');
    expect(onTermsFieldChange).toHaveBeenCalledWith('purchasePrice', '1');
    expect(onOperatingFieldChange).not.toHaveBeenCalled();

    sections.operations
      .flatMap((s) => s.fields)
      .find((f) => f.id === 'grossPotentialRent')!
      .onChange('2');
    expect(onOperatingFieldChange).toHaveBeenCalledWith('grossPotentialRent', '2');
    expect(onTermsFieldChange).toHaveBeenCalledTimes(1);
  });

  it('offers the Operating Statement view only for Detailed', () => {
    expect(resultsViewsFor('quick').map((v) => v.id)).toEqual([
      'summary',
      'cash-flow',
      'owner-returns',
    ]);
    expect(resultsViewsFor('detailed').map((v) => v.id)).toEqual([
      'summary',
      'cash-flow',
      'owner-returns',
      'operating-statement',
    ]);
  });

  it('filters Operations sections to the selected sub-view', () => {
    const revenue = sectionsForView(detailed.operations, 'revenue');
    expect(revenue.map((s) => s.title)).toEqual(['Revenue']);

    const growth = sectionsForView(detailed.operations, 'growth');
    // Reserves (a terms field) and Growth (operating fields) both belong to
    // the Growth sub-view.
    expect(growth.map((s) => s.title).sort()).toEqual(['Growth', 'Reserves']);

    expect(sectionsForView(detailed.operations, null)).toEqual(detailed.operations);
  });
});
