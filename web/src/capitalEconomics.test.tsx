/**
 * Phase 6 Gate D6.7 -- Capital Economics reporting.
 *
 * The numbers come from `capitalEconomicsFixture.json`: real `POST /analyze`
 * responses captured through the backend, each stored beside the request that
 * produced it. None is hand-written, so every expectation below compares a cell
 * with the engine's own field, passed through the same shared formatter the
 * section uses -- never with a figure this file worked out.
 *
 * What is held closed:
 *
 * - every displayed D6 figure is one named result field, read directly;
 * - no total, difference, ratio or aggregate is computed in the browser -- by
 *   an AST audit with mutant self-tests, and behaviourally, by a result whose
 *   totals deliberately do not reconcile;
 * - an unreported IRR says N/A and gives the engine's own reason;
 * - closing, hold-year and post-hold capital stay in their own places;
 * - the capital channels stay in their own columns;
 * - zero is a figure and `null` is N/A.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import ts from 'typescript';
import { CapitalEconomicsSection } from './components/CapitalEconomicsSection';
import {
  IRR_NOT_REPORTED_REASONS,
  irrNotReportedExplanation,
} from './capitalEconomics';
import { formatCurrency, formatMultiple, formatPercent } from './format';
import { IRR_STATUSES } from './types';
import type { AcquisitionResults } from './types';
import { withLfLineEndings } from './testSourceText';
import fixture from './capitalEconomicsFixture.json';
import sectionRaw from './components/CapitalEconomicsSection.tsx?raw';
import vocabularyRaw from './capitalEconomics.ts?raw';

afterEach(() => {
  cleanup();
});

const SECTION_SOURCE = withLfLineEndings(sectionRaw);
const VOCABULARY_SOURCE = withLfLineEndings(vocabularyRaw);

// =============================================================================
// Fixtures
// =============================================================================

type QuickCase = keyof typeof fixture.quick;

interface Case {
  results: AcquisitionResults;
  purchasePrice: number;
}

function quick(name: QuickCase): Case {
  const entry = fixture.quick[name];
  return {
    results: entry.response as unknown as AcquisitionResults,
    purchasePrice: entry.request.purchase_price,
  };
}

const DETAILED: Case = {
  results: fixture.detailed.v5_mixed.response.results as unknown as AcquisitionResults,
  purchasePrice: fixture.detailed.v5_mixed.request.terms.purchase_price,
};

const LEASE_LEVEL: Case = {
  results: fixture.lease_level.v9_leasing_and_project_capital.response
    .results as unknown as AcquisitionResults,
  purchasePrice: fixture.lease_level.v9_leasing_and_project_capital.request.terms.purchase_price,
};

function show({ results, purchasePrice }: Case, showLeasingCapital = false) {
  return render(
    <CapitalEconomicsSection
      results={results}
      purchasePrice={purchasePrice}
      showLeasingCapital={showLeasingCapital}
    />,
  );
}

function region(name: string): HTMLElement {
  return screen.getByRole('region', { name });
}

/** Label -> value for a ledger (Sources & Uses, Project Returns). */
function ledger(name: string): Record<string, string> {
  const table = within(region(name)).getByRole('table');
  const values: Record<string, string> = {};
  for (const row of Array.from(table.querySelectorAll('tr'))) {
    const header = row.querySelector('th[scope="row"]');
    const cell = row.querySelector('td');
    if (header !== null && cell !== null) {
      values[header.textContent ?? ''] = cell.textContent ?? '';
    }
  }
  return values;
}

function ledgerCell(name: string, label: string): HTMLElement {
  const table = within(region(name)).getByRole('table');
  const header = Array.from(table.querySelectorAll('th[scope="row"]')).find(
    (cell) => cell.textContent === label,
  );
  if (header === undefined) {
    throw new Error(`No ${label} row in ${name}`);
  }
  return header.closest('tr')!.querySelector('td') as HTMLElement;
}

/** The last header row's column names, and every body row's cell text. */
function annualTable(name: string): { columns: string[]; rows: string[][] } {
  const table = within(region(name)).getByRole('table');
  const headRows = table.querySelectorAll('thead tr');
  const columns = Array.from(headRows[headRows.length - 1].querySelectorAll('th')).map(
    (cell) => cell.textContent ?? '',
  );
  const rows = Array.from(table.querySelectorAll('tbody tr')).map((row) =>
    Array.from(row.children).map((cell) => cell.textContent ?? ''),
  );
  return { columns, rows };
}

function money(values: readonly number[]): string[] {
  return values.map((value) => formatCurrency(value));
}

const NOT_APPLICABLE = '—Not applicable';

// =============================================================================
// 1. Every displayed figure is its own deterministic field (Parts T, U, V, AK)
// =============================================================================

describe('Sources & Uses at Closing', () => {
  it('reads each line, and both totals, straight off the result', () => {
    const mixed = quick('v5_mixed');
    show(mixed);
    const { results } = mixed;
    expect(ledger('Sources & Uses at Closing')).toEqual({
      'Purchase Price': formatCurrency(mixed.purchasePrice),
      'Acquisition Costs': formatCurrency(results.acquisition_costs),
      'Financing Fees': formatCurrency(results.financing_fee),
      'Closing Project Capital': formatCurrency(results.closing_project_capital),
      'Total Closing Uses': formatCurrency(results.total_closing_uses),
      'Acquisition Debt': formatCurrency(results.loan_amount),
      'Initial Equity': formatCurrency(results.initial_equity),
      'Total Closing Sources': formatCurrency(results.total_closing_sources),
    });
    // The captured reference plan: $250,000 at closing on a $50,000,000 deal.
    expect(ledger('Sources & Uses at Closing')['Closing Project Capital']).toBe('$250,000');
    expect(ledger('Sources & Uses at Closing')['Total Closing Uses']).toBe('$51,275,000');
    expect(ledger('Sources & Uses at Closing')['Total Closing Sources']).toBe('$51,275,000');
  });

  it('keeps future and post-hold Project Capital out of the closing uses (V3, V6)', () => {
    for (const name of ['v3_future_capital', 'v6_post_hold'] as const) {
      const planned = quick(name);
      show(planned);
      const uses = ledger('Sources & Uses at Closing');
      expect(uses['Closing Project Capital']).toBe('$0');
      // The same closing uses as the deal with no plan at all.
      expect(uses['Total Closing Uses']).toBe(
        formatCurrency(quick('v1_empty').results.total_closing_uses),
      );
      expect(
        within(region('Sources & Uses at Closing')).getByText(
          /Project Capital scheduled during or after the hold is not a closing use/,
        ),
      ).toBeTruthy();
      cleanup();
    }
  });

  it('shows Closing Project Capital as a closing use and in Initial Equity (V2)', () => {
    const closing = quick('v2_closing_capital');
    show(closing);
    const uses = ledger('Sources & Uses at Closing');
    expect(uses['Closing Project Capital']).toBe('$250,000');
    expect(uses['Initial Equity']).toBe(formatCurrency(closing.results.initial_equity));
    expect(ledger('Project Returns')['Initial Equity Requirement']).toBe(
      formatCurrency(closing.results.initial_equity),
    );
    expect(ledger('Project Returns')['Total Equity Invested']).toBe(
      formatCurrency(closing.results.total_equity_invested),
    );
    // Nothing further is scheduled, so no note about later capital.
    expect(
      within(region('Sources & Uses at Closing')).queryByText(/not a closing use/),
    ).toBeNull();
  });
});

describe('Project Returns', () => {
  it('reads every figure straight off the result (V5)', () => {
    const { results } = quick('v5_mixed');
    show(quick('v5_mixed'));
    expect(ledger('Project Returns')).toEqual({
      'Initial Equity Requirement': formatCurrency(results.initial_equity),
      'Total Equity Invested': formatCurrency(results.total_equity_invested),
      'Total Cash Returned': formatCurrency(results.total_cash_returned),
      'Total Profit': formatCurrency(results.total_profit),
      'Equity Multiple': formatMultiple(results.equity_multiple),
      'Levered IRR': formatPercent(results.levered_irr),
      'Unlevered IRR': formatPercent(results.unlevered_irr),
    });
    expect(results.levered_irr_status).toBe('defined');
    // A reported IRR carries no status note -- not even "Defined".
    expect(within(region('Project Returns')).queryByText(/is not reported/)).toBeNull();
    expect(within(region('Project Returns')).queryByText(/defined/i)).toBeNull();
  });

  it('says why Total Equity Invested can exceed the Initial Equity Requirement (V10)', () => {
    const additional = quick('v10_additional_equity');
    show(additional);
    expect(additional.results.net_additional_equity_requirement_by_year[0]).toBeGreaterThan(0);
    expect(
      within(region('Project Returns')).getByText(
        'The Initial Equity Requirement plus the Net Additional Equity Requirement in Year 1.',
      ),
    ).toBeTruthy();
  });

  it('says the two are equal when no year needs additional equity (V5)', () => {
    show(quick('v5_mixed'));
    expect(
      within(region('Project Returns')).getByText(
        'Equal to the Initial Equity Requirement: no Net Additional Equity Requirement during the hold.',
      ),
    ).toBeTruthy();
  });
});

describe('Owner Cash Flow', () => {
  it('shows each hold year from the four authoritative series (V5)', () => {
    const { results } = quick('v5_mixed');
    show(quick('v5_mixed'));
    const { columns, rows } = annualTable('Owner Cash Flow');
    expect(columns).toEqual([
      'Year',
      'NOI',
      'Property Cash Flow',
      'Unlevered Owner Cash Flow',
      'Levered Owner Cash Flow',
    ]);
    expect(rows).toEqual(
      results.property_cash_flow_by_year.map((_, index) => [
        `Year ${index + 1}`,
        formatCurrency(results.noi_by_year[index]),
        formatCurrency(results.property_cash_flow_by_year[index]),
        formatCurrency(results.unlevered_owner_cash_flow_by_year[index]),
        formatCurrency(results.levered_owner_cash_flow_by_year[index]),
      ]),
    );
  });

  it('explains the NOI -> Property -> Owner Cash Flow chain once, in one sentence set', () => {
    show(quick('v5_mixed'));
    expect(
      within(region('Owner Cash Flow')).getByText(
        'Property Cash Flow reflects the Recurring CapEx Reserve and, for Lease-Level deals, TI / LC. Owner Cash Flow then reflects Project Capital and Owner Expenses; Levered Owner Cash Flow is after debt service.',
      ),
    ).toBeTruthy();
  });

  it('adds the Net Additional Equity Requirement column only when a year has one (V10)', () => {
    const additional = quick('v10_additional_equity');
    show(additional);
    const { columns, rows } = annualTable('Owner Cash Flow');
    expect(columns[columns.length - 1]).toBe('Net Additional Equity Requirement');
    expect(rows.map((row) => row[row.length - 1])).toEqual(
      money(additional.results.net_additional_equity_requirement_by_year),
    );
    expect(
      within(region('Owner Cash Flow')).getByText(/It is an annual net figure and does not indicate timing within the year\./),
    ).toBeTruthy();
  });

  it('says so in one line, rather than a column of zeros, when no year has one (V1)', () => {
    show(quick('v1_empty'));
    expect(annualTable('Owner Cash Flow').columns).not.toContain(
      'Net Additional Equity Requirement',
    );
    expect(
      within(region('Owner Cash Flow')).getByText(
        'No Net Additional Equity Requirement during the hold.',
      ),
    ).toBeTruthy();
  });
});

describe('Capital Schedule', () => {
  it('puts Closing Project Capital on its own Closing row, never Year 1 (V5)', () => {
    const { results } = quick('v5_mixed');
    show(quick('v5_mixed'));
    const { columns, rows } = annualTable('Capital Schedule');
    expect(columns).toEqual(['Period', 'Recurring CapEx Reserve', 'Project Capital', 'Owner Expenses']);
    expect(rows[0]).toEqual([
      'Closing (T0)',
      NOT_APPLICABLE,
      formatCurrency(results.closing_project_capital),
      NOT_APPLICABLE,
    ]);
    expect(rows.slice(1)).toEqual(
      results.project_capital_by_year.map((_, index) => [
        `Year ${index + 1}`,
        formatCurrency(results.capex_by_year[index]),
        formatCurrency(results.project_capital_by_year[index]),
        formatCurrency(results.owner_expenses_by_year[index]),
      ]),
    );
    // The reference plan, as captured: $250,000 at closing, $1,000,000 in Year
    // 2, and $50,000 + $15,000 of owner expenses in Years 2-3.
    expect(rows[0][2]).toBe('$250,000');
    expect(rows[1][2]).toBe('$0');
    expect(rows[2][2]).toBe('$1,000,000');
    expect(rows.slice(1).map((row) => row[3])).toEqual([
      '$50,000',
      '$65,000',
      '$65,000',
      '$50,000',
      '$50,000',
    ]);
  });

  it('shows owner expenses in every year they fall, with none at closing (V4)', () => {
    const expense = quick('v4_owner_expense');
    show(expense);
    const { rows } = annualTable('Capital Schedule');
    expect(rows[0][3]).toBe(NOT_APPLICABLE);
    expect(rows.slice(1).map((row) => row[3])).toEqual(
      money(expense.results.owner_expenses_by_year),
    );
  });

  it('places future Project Capital in its hold year (V3)', () => {
    const future = quick('v3_future_capital');
    show(future);
    const { rows } = annualTable('Capital Schedule');
    expect(rows.slice(1).map((row) => row[2])).toEqual(
      money(future.results.project_capital_by_year),
    );
    expect(rows[2][2]).toBe('$1,000,000');
  });

  it('collapses to one statement when the Business Plan schedules nothing (V1)', () => {
    show(quick('v1_empty'));
    const schedule = region('Capital Schedule');
    expect(within(schedule).queryByRole('table')).toBeNull();
    expect(
      within(schedule).getByText('The Business Plan schedules no Project Capital or Owner Expenses.'),
    ).toBeTruthy();
    // The rest of the section still reports the owner economics.
    expect(region('Sources & Uses at Closing')).toBeTruthy();
    expect(region('Project Returns')).toBeTruthy();
    expect(within(region('Owner Cash Flow')).getByRole('table')).toBeTruthy();
    expect(screen.queryByText(/No Business Plan/)).toBeNull();
  });
});

// =============================================================================
// 2. Post-hold capital is disclosed, never a hold-year cost (Parts K, L; V6)
// =============================================================================

describe('Post-Hold Project Capital', () => {
  it('is disclosed with its deterministic amount, outside the schedule rows (V6)', () => {
    const postHold = quick('v6_post_hold');
    show(postHold);
    expect(postHold.results.post_hold_project_capital).toBe(500000);
    const disclosure = within(region('Capital Schedule')).getByRole('note', {
      name: 'Post-Hold Project Capital',
    });
    expect(disclosure.textContent).toBe(
      'Post-Hold Project Capital$500,000 is modeled after the current hold and is excluded from seller returns.',
    );
    // Not in any row: every hold year reads the hold-year series, and no cell
    // anywhere in the schedule carries the post-hold amount.
    const { rows } = annualTable('Capital Schedule');
    expect(rows.slice(1).map((row) => row[2])).toEqual(
      money(postHold.results.project_capital_by_year),
    );
    expect(rows.flat()).not.toContain('$500,000');
  });

  it('leaves seller returns exactly as the engine reports them without it', () => {
    const empty = quick('v1_empty').results;
    const postHold = quick('v6_post_hold').results;
    // The engine's own statement: the returns are identical.
    for (const field of [
      'initial_equity',
      'total_equity_invested',
      'total_cash_returned',
      'total_profit',
      'equity_multiple',
      'levered_irr',
      'unlevered_irr',
    ] as const) {
      expect(postHold[field]).toBe(empty[field]);
    }
    show(quick('v1_empty'));
    const without = ledger('Project Returns');
    cleanup();
    show(quick('v6_post_hold'));
    expect(ledger('Project Returns')).toEqual(without);
  });

  it('is omitted when nothing falls after the hold', () => {
    show(quick('v3_future_capital'));
    expect(screen.queryByRole('note', { name: 'Post-Hold Project Capital' })).toBeNull();
  });
});

// =============================================================================
// 3. IRR status (Parts G, AM)
// =============================================================================

describe('an IRR the engine does not report', () => {
  it('reads N/A with the engine’s reason, and keeps every other return (V7)', () => {
    const signs = quick('v7_multiple_sign_changes');
    expect(signs.results.levered_irr).toBeNull();
    expect(signs.results.levered_irr_status).toBe('multiple_sign_changes');
    show(signs);
    const returns = ledger('Project Returns');
    expect(returns['Levered IRR']).toBe('N/A');
    expect(
      within(region('Project Returns')).getByText(
        'Levered IRR is not reported because the modeled cash-flow pattern changes sign more than once.',
      ),
    ).toBeTruthy();
    // The explanation is wired to the N/A it explains.
    const cell = ledgerCell('Project Returns', 'Levered IRR');
    const note = document.getElementById(cell.getAttribute('aria-describedby') ?? '');
    expect(note?.textContent).toMatch(/^Levered IRR is not reported because/);
    // Equity Multiple, TEI, TCR and Profit are still reported.
    expect(returns['Equity Multiple']).toBe(formatMultiple(signs.results.equity_multiple));
    expect(returns['Total Equity Invested']).toBe(
      formatCurrency(signs.results.total_equity_invested),
    );
    expect(returns['Total Cash Returned']).toBe(formatCurrency(signs.results.total_cash_returned));
    expect(returns['Total Profit']).toBe(formatCurrency(signs.results.total_profit));
    expect(returns['Levered IRR']).not.toBe('0.00%');
  });

  it('gives each status its own reason, keyed on the status rather than on null', () => {
    const base = quick('v5_mixed').results;
    for (const status of IRR_STATUSES) {
      const results: AcquisitionResults = {
        ...base,
        levered_irr: status === 'defined' ? base.levered_irr : null,
        levered_irr_status: status,
      };
      show({ results, purchasePrice: 1 });
      const text = region('Project Returns').textContent ?? '';
      if (status === 'defined') {
        expect(text).not.toContain('is not reported');
      } else {
        expect(ledger('Project Returns')['Levered IRR']).toBe('N/A');
        expect(text).toContain(
          `Levered IRR is not reported because ${IRR_NOT_REPORTED_REASONS[status]}.`,
        );
      }
      cleanup();
    }
  });

  it('explains an unreported Unlevered IRR with its own status (V9)', () => {
    show(LEASE_LEVEL, true);
    expect(LEASE_LEVEL.results.unlevered_irr_status).toBe('multiple_sign_changes');
    expect(ledger('Project Returns')['Unlevered IRR']).toBe('N/A');
    expect(
      within(region('Project Returns')).getByText(
        'Unlevered IRR is not reported because the modeled cash-flow pattern changes sign more than once.',
      ),
    ).toBeTruthy();
  });

  it('has exactly one reason per unreported backend status, each distinct and faithful', () => {
    const unreported = IRR_STATUSES.filter((status) => status !== 'defined');
    expect(Object.keys(IRR_NOT_REPORTED_REASONS).sort()).toEqual([...unreported].sort());
    const reasons = Object.values(IRR_NOT_REPORTED_REASONS);
    expect(new Set(reasons).size).toBe(reasons.length);
    expect(IRR_NOT_REPORTED_REASONS.multiple_sign_changes).toBe(
      'the modeled cash-flow pattern changes sign more than once',
    );
    expect(IRR_NOT_REPORTED_REASONS.root_outside_search_domain).toBe(
      "the return falls outside Anchor's supported search domain",
    );
    expect(IRR_NOT_REPORTED_REASONS.no_positive_cash_flow).toBe(
      'the modeled cash flows contain no positive cash flow',
    );
    expect(IRR_NOT_REPORTED_REASONS.numerical_failure).toBe(
      'the deterministic IRR calculation encountered a numerical issue',
    );
    for (const reason of reasons) {
      expect(reason.toLowerCase()).not.toMatch(/has no irr|no irr exists|alternate|capital call/);
    }
    expect(irrNotReportedExplanation('Levered IRR', 'defined')).toBeNull();
  });

  it('matches the backend IrrStatus members exactly', () => {
    // Mirrors `IrrStatus` in src/anchor/engine/contracts.py, value for value.
    expect([...IRR_STATUSES]).toEqual([
      'defined',
      'no_nonzero_cash_flow',
      'first_nonzero_not_negative',
      'no_positive_cash_flow',
      'multiple_sign_changes',
      'root_outside_search_domain',
      'numerical_failure',
    ]);
  });

  it('keeps the status vocabulary in one frontend module', () => {
    const production = Object.entries(
      import.meta.glob('./**/*.{ts,tsx}', { query: '?raw', eager: true, import: 'default' }) as Record<
        string,
        string
      >,
    ).filter(([path]) => !/\.test\.tsx?$/.test(path));
    for (const status of IRR_STATUSES.filter((value) => value !== 'defined')) {
      const holders = production
        .filter(([, text]) => text.includes(status))
        .map(([path]) => path)
        .sort();
      expect(holders, status).toEqual(['./capitalEconomics.ts', './types.ts']);
    }
  });
});

// =============================================================================
// 4. Zero is a figure; null is N/A (Part AN)
// =============================================================================

describe('zero and None', () => {
  it('renders real zeros as $0 and missing values as N/A', () => {
    const { results } = quick('v1_empty');
    show({
      results: { ...results, equity_multiple: null, levered_irr: null, levered_irr_status: 'no_positive_cash_flow' },
      purchasePrice: 50_000_000,
    });
    expect(ledger('Sources & Uses at Closing')['Closing Project Capital']).toBe('$0');
    expect(ledger('Project Returns')['Equity Multiple']).toBe('N/A');
    expect(ledger('Project Returns')['Equity Multiple']).not.toBe('0.00x');
    expect(ledger('Project Returns')['Levered IRR']).toBe('N/A');
  });

  it('renders a zero Equity Multiple as 0.00x, not N/A', () => {
    const { results } = quick('v1_empty');
    show({ results: { ...results, equity_multiple: 0 }, purchasePrice: 1 });
    expect(ledger('Project Returns')['Equity Multiple']).toBe('0.00x');
  });

  it('shows an absent Purchase Price as N/A rather than inventing one', () => {
    show({ results: quick('v5_mixed').results, purchasePrice: null as unknown as number });
    expect(ledger('Sources & Uses at Closing')['Purchase Price']).toBe('N/A');
  });
});

// =============================================================================
// 5. Negative figures: set apart, never alarmist (Parts F, AD; V8)
// =============================================================================

describe('negative figures', () => {
  it('sets a negative Total Profit apart by sign and colour, a positive one by neither (V8)', () => {
    const negative = quick('v8_negative_profit');
    expect(negative.results.total_profit).toBeLessThan(0);
    show(negative);
    const cell = ledgerCell('Project Returns', 'Total Profit');
    expect(cell.textContent).toBe(formatCurrency(negative.results.total_profit));
    expect(cell.textContent!.startsWith('-$')).toBe(true);
    expect(cell.className).toContain('capital-economics-negative');
    cleanup();

    show(quick('v5_mixed'));
    const positive = ledgerCell('Project Returns', 'Total Profit');
    expect(positive.textContent!.startsWith('$')).toBe(true);
    expect(positive.className).not.toContain('capital-economics-negative');
  });

  it('writes a negative owner cash flow with its sign and calls it nothing else (V10)', () => {
    const additional = quick('v10_additional_equity');
    show(additional);
    const table = within(region('Owner Cash Flow')).getByRole('table');
    const yearOne = table.querySelectorAll('tbody tr')[0].querySelectorAll('td');
    const levered = yearOne[3];
    expect(additional.results.levered_owner_cash_flow_by_year[0]).toBeLessThan(0);
    expect(levered.textContent).toBe(
      formatCurrency(additional.results.levered_owner_cash_flow_by_year[0]),
    );
    expect(levered.textContent!.startsWith('-$')).toBe(true);
    expect(levered.className).toContain('capital-economics-negative');
    const text = document.body.textContent!.toLowerCase();
    for (const word of ['capital call', 'loss', 'distress', 'deficit']) {
      expect(text, word).not.toContain(word);
    }
  });
});

// =============================================================================
// 6. Lease-Level: TI, LC, Project Capital and Owner Expenses stay apart (V9)
// =============================================================================

describe('Lease-Level capital coexistence', () => {
  it('reports TI, LC, Project Capital and Owner Expenses in their own columns', () => {
    const { results } = LEASE_LEVEL;
    show(LEASE_LEVEL, true);
    const { columns, rows } = annualTable('Capital Schedule');
    expect(columns).toEqual([
      'Period',
      'Recurring CapEx Reserve',
      'Tenant Improvements',
      'Leasing Commissions',
      'Project Capital',
      'Owner Expenses',
    ]);
    expect(rows.slice(1)).toEqual(
      results.project_capital_by_year.map((_, index) => [
        `Year ${index + 1}`,
        formatCurrency(results.capex_by_year[index]),
        formatCurrency(results.tenant_improvements_by_year[index]),
        formatCurrency(results.leasing_commissions_by_year[index]),
        formatCurrency(results.project_capital_by_year[index]),
        formatCurrency(results.owner_expenses_by_year[index]),
      ]),
    );
    // Year 5 carries all four channels at once -- the case this proves.
    const yearFive = rows[5];
    expect(results.tenant_improvements_by_year[4]).toBeGreaterThan(0);
    expect(results.leasing_commissions_by_year[4]).toBeGreaterThan(0);
    expect(results.project_capital_by_year[4]).toBeGreaterThan(0);
    expect(results.owner_expenses_by_year[4]).toBeGreaterThan(0);
    expect(yearFive).toEqual([
      'Year 5',
      '$0',
      '$814,000',
      formatCurrency(results.leasing_commissions_by_year[4]),
      '$400,000',
      '$50,000',
    ]);
  });

  it('names which cash flow each channel group is reflected in', () => {
    show(LEASE_LEVEL, true);
    const table = within(region('Capital Schedule')).getByRole('table');
    const groups = Array.from(table.querySelectorAll('th[scope="colgroup"]'));
    expect(groups.map((group) => [group.textContent, group.getAttribute('colspan')])).toEqual([
      ['Property-Level CapitalIn Property Cash Flow', '3'],
      ['Business PlanIn Owner Cash Flow', '2'],
    ]);
    expect(
      within(region('Capital Schedule')).getByText(
        'Each channel is reported on its own. Project Capital is never included in Tenant Improvements, Leasing Commissions or the Recurring CapEx Reserve.',
      ),
    ).toBeTruthy();
  });

  it('never merges the channels into one unlabelled capital figure', () => {
    show(LEASE_LEVEL, true);
    const text = document.body.textContent!;
    for (const merged of ['Capital Costs', 'Total Capital', 'Total Project Capital', 'TI/LC + ']) {
      expect(text, merged).not.toContain(merged);
    }
  });
});

// =============================================================================
// 7. One vocabulary in every mode (Parts P, AI)
// =============================================================================

describe('cross-mode vocabulary', () => {
  it('renders Sources & Uses, Project Returns and Owner Cash Flow identically with or without leasing capital', () => {
    const texts = (showLeasingCapital: boolean) => {
      show(quick('v5_mixed'), showLeasingCapital);
      const captured = ['Sources & Uses at Closing', 'Project Returns', 'Owner Cash Flow'].map(
        (name) => region(name).textContent,
      );
      cleanup();
      return captured;
    };
    expect(texts(true)).toEqual(texts(false));
  });

  it('uses the same labels for Quick, Detailed and Lease-Level results', () => {
    const labels = (entry: Case, leasing: boolean) => {
      show(entry, leasing);
      const captured = {
        sources: Object.keys(ledger('Sources & Uses at Closing')),
        returns: Object.keys(ledger('Project Returns')),
        owner: annualTable('Owner Cash Flow').columns,
      };
      cleanup();
      return captured;
    };
    const quickLabels = labels(quick('v5_mixed'), false);
    expect(labels(DETAILED, false)).toEqual(quickLabels);
    const leaseLevelLabels = labels(LEASE_LEVEL, true);
    expect(leaseLevelLabels.sources).toEqual(quickLabels.sources);
    expect(leaseLevelLabels.returns).toEqual(quickLabels.returns);
    // V9 has a Net Additional Equity Requirement; V5 does not.
    expect(leaseLevelLabels.owner).toEqual([
      ...quickLabels.owner,
      'Net Additional Equity Requirement',
    ]);
  });
});

// =============================================================================
// 8. Nothing is recomputed in the browser (Part AJ) -- behavioural proof
//
// A result whose totals deliberately do not reconcile. Were any cell a browser
// sum, difference or ratio, it would show the arithmetic answer instead of the
// field, and these assertions would fail.
// =============================================================================

function nonReconciling(): Case {
  const base = quick('v5_mixed').results;
  return {
    purchasePrice: 7_001,
    results: {
      ...base,
      acquisition_costs: 7_002,
      financing_fee: 7_003,
      closing_project_capital: 7_004,
      total_closing_uses: 9_100_001,
      loan_amount: 7_005,
      initial_equity: 7_006,
      total_closing_sources: 9_100_002,
      total_equity_invested: 7_007,
      total_cash_returned: 7_008,
      total_profit: 9_100_003,
      equity_multiple: 4.56,
      noi_by_year: [11, 12, 13, 14, 15],
      property_cash_flow_by_year: [21, 22, 23, 24, 25],
      unlevered_owner_cash_flow_by_year: [31, 32, 33, 34, 35],
      levered_owner_cash_flow_by_year: [-41, 42, 43, 44, 45],
      net_additional_equity_requirement_by_year: [0, 0, 0, 0, 9_100_004],
      capex_by_year: [51, 52, 53, 54, 55],
      tenant_improvements_by_year: [61, 62, 63, 64, 65],
      leasing_commissions_by_year: [71, 72, 73, 74, 75],
      project_capital_by_year: [81, 82, 83, 84, 85],
      owner_expenses_by_year: [91, 92, 93, 94, 95],
      post_hold_project_capital: 9_100_005,
    },
  };
}

describe('a result whose figures do not reconcile', () => {
  it('shows every total as the engine reported it, never as a browser sum', () => {
    show(nonReconciling(), true);
    expect(ledger('Sources & Uses at Closing')).toEqual({
      'Purchase Price': '$7,001',
      'Acquisition Costs': '$7,002',
      'Financing Fees': '$7,003',
      'Closing Project Capital': '$7,004',
      'Total Closing Uses': '$9,100,001',
      'Acquisition Debt': '$7,005',
      'Initial Equity': '$7,006',
      'Total Closing Sources': '$9,100,002',
    });
    const returns = ledger('Project Returns');
    expect(returns['Total Equity Invested']).toBe('$7,007');
    expect(returns['Total Cash Returned']).toBe('$7,008');
    expect(returns['Total Profit']).toBe('$9,100,003');
    expect(returns['Equity Multiple']).toBe('4.56x');
  });

  it('shows every annual cell as its own series element', () => {
    show(nonReconciling(), true);
    expect(annualTable('Owner Cash Flow').rows).toEqual([
      ['Year 1', '$11', '$21', '$31', '-$41', '$0'],
      ['Year 2', '$12', '$22', '$32', '$42', '$0'],
      ['Year 3', '$13', '$23', '$33', '$43', '$0'],
      ['Year 4', '$14', '$24', '$34', '$44', '$0'],
      ['Year 5', '$15', '$25', '$35', '$45', '$9,100,004'],
    ]);
    const schedule = annualTable('Capital Schedule').rows;
    expect(schedule[0]).toEqual([
      'Closing (T0)',
      NOT_APPLICABLE,
      NOT_APPLICABLE,
      NOT_APPLICABLE,
      '$7,004',
      NOT_APPLICABLE,
    ]);
    expect(schedule.slice(1)).toEqual([
      ['Year 1', '$51', '$61', '$71', '$81', '$91'],
      ['Year 2', '$52', '$62', '$72', '$82', '$92'],
      ['Year 3', '$53', '$63', '$73', '$83', '$93'],
      ['Year 4', '$54', '$64', '$74', '$84', '$94'],
      ['Year 5', '$55', '$65', '$75', '$85', '$95'],
    ]);
    expect(screen.getByRole('note', { name: 'Post-Hold Project Capital' }).textContent).toContain(
      '$9,100,005 is modeled after the current hold',
    );
  });

  it('reads the Total Equity Invested note from the requirement series, not the cash flows', () => {
    // Year 1's levered owner cash flow is negative here, but its Net Additional
    // Equity Requirement is zero -- so a note derived from the cash flows would
    // name Year 1, and the authoritative one names only Year 5.
    show(nonReconciling(), true);
    expect(
      within(region('Project Returns')).getByText(
        'The Initial Equity Requirement plus the Net Additional Equity Requirement in Year 5.',
      ),
    ).toBeTruthy();
  });
});

// =============================================================================
// 9. Nothing is recomputed in the browser -- structural proof (Parts AJ, AK)
// =============================================================================

const ARITHMETIC = new Set<ts.SyntaxKind>([
  ts.SyntaxKind.PlusToken,
  ts.SyntaxKind.MinusToken,
  ts.SyntaxKind.AsteriskToken,
  ts.SyntaxKind.SlashToken,
  ts.SyntaxKind.PercentToken,
  ts.SyntaxKind.AsteriskAsteriskToken,
  ts.SyntaxKind.PlusEqualsToken,
  ts.SyntaxKind.MinusEqualsToken,
  ts.SyntaxKind.AsteriskEqualsToken,
  ts.SyntaxKind.SlashEqualsToken,
  ts.SyntaxKind.PercentEqualsToken,
  ts.SyntaxKind.AsteriskAsteriskEqualsToken,
]);

/** Calls that aggregate, round or re-parse a figure. Formatting belongs to the
 * shared `format.ts`; aggregation belongs to the engine. */
const FORBIDDEN_CALLS = new Set(['reduce', 'reduceRight', 'toFixed', 'parseFloat', 'parseInt', 'Number']);

function parse(fileName: string, text: string): ts.SourceFile {
  return ts.createSourceFile(
    fileName,
    text,
    ts.ScriptTarget.Latest,
    true,
    fileName.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
}

function walk(node: ts.Node, visit: (node: ts.Node) => void): void {
  visit(node);
  node.forEachChild((child) => walk(child, visit));
}

/** Every expression that computes: arithmetic, increment, negation of a
 * non-literal, `Math`, and the aggregating or re-parsing calls. */
function computationSites(fileName: string, text: string): string[] {
  const source = parse(fileName, text);
  const sites: string[] = [];
  walk(source, (node) => {
    if (ts.isBinaryExpression(node) && ARITHMETIC.has(node.operatorToken.kind)) {
      sites.push(node.getText(source));
    }
    if (ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node)) {
      const op = node.operator;
      const negation =
        ts.isPrefixUnaryExpression(node) &&
        (op === ts.SyntaxKind.MinusToken || op === ts.SyntaxKind.PlusToken) &&
        !ts.isNumericLiteral(node.operand);
      if (op === ts.SyntaxKind.PlusPlusToken || op === ts.SyntaxKind.MinusMinusToken || negation) {
        sites.push(node.getText(source));
      }
    }
    if (ts.isIdentifier(node) && node.text === 'Math') {
      sites.push('Math');
    }
    if (ts.isCallExpression(node)) {
      const callee = node.expression;
      const name = ts.isPropertyAccessExpression(callee)
        ? callee.name.text
        : ts.isIdentifier(callee)
          ? callee.text
          : '';
      if (FORBIDDEN_CALLS.has(name)) {
        sites.push(node.getText(source));
      }
    }
  });
  return sites;
}

/** Every `results.<field>` the section reads, plus any read that escapes that
 * form -- an element access or a destructuring of `results`. */
function resultReads(text: string): { fields: string[]; escapes: string[] } {
  const source = parse('section.tsx', text);
  const fields = new Set<string>();
  const escapes: string[] = [];
  walk(source, (node) => {
    if (
      ts.isPropertyAccessExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === 'results'
    ) {
      fields.add(node.name.text);
    }
    if (
      ts.isElementAccessExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === 'results'
    ) {
      escapes.push(node.getText(source));
    }
    if (
      ts.isVariableDeclaration(node) &&
      ts.isObjectBindingPattern(node.name) &&
      node.initializer !== undefined &&
      ts.isIdentifier(node.initializer) &&
      node.initializer.text === 'results'
    ) {
      escapes.push(node.getText(source));
    }
  });
  return { fields: [...fields].sort(), escapes };
}

/** The deterministic fields the section displays or decides on -- each a
 * named, authoritative `AcquisitionResults` field. */
const EXPECTED_RESULT_FIELDS = [
  'acquisition_costs',
  'capex_by_year',
  'closing_project_capital',
  'equity_multiple',
  'financing_fee',
  'initial_equity',
  'leasing_commissions_by_year',
  'levered_irr',
  'levered_irr_status',
  'levered_owner_cash_flow_by_year',
  'loan_amount',
  'net_additional_equity_requirement_by_year',
  'noi_by_year',
  'owner_expenses_by_year',
  'post_hold_project_capital',
  'project_capital_by_year',
  'property_cash_flow_by_year',
  'tenant_improvements_by_year',
  'total_cash_returned',
  'total_closing_sources',
  'total_closing_uses',
  'total_equity_invested',
  'total_profit',
  'unlevered_irr',
  'unlevered_irr_status',
  'unlevered_owner_cash_flow_by_year',
];

describe('the Capital Economics source computes nothing', () => {
  it('has exactly one arithmetic expression: the display-only year label', () => {
    expect(computationSites('section.tsx', SECTION_SOURCE)).toEqual([]);
    expect(computationSites('vocabulary.ts', VOCABULARY_SOURCE)).toEqual(['index + 1']);
    const label = VOCABULARY_SOURCE.slice(VOCABULARY_SOURCE.indexOf('export function holdYearLabel'));
    expect(label.slice(0, label.indexOf('\n}\n'))).toContain('`Year ${index + 1}`');
  });

  it('reads exactly the intended result fields, and only by name', () => {
    const { fields, escapes } = resultReads(SECTION_SOURCE);
    expect(fields).toEqual(EXPECTED_RESULT_FIELDS);
    expect(escapes).toEqual([]);
    // The raw cash-flow series and debt service are never in reach: with them,
    // Owner Cash Flow or the Net Additional Equity Requirement could be rebuilt.
    for (const field of ['levered_cash_flows', 'unlevered_cash_flows', 'annual_debt_service']) {
      expect(fields).not.toContain(field);
    }
  });

  // Each mutant is applied to the real source and shown to be caught -- the
  // audit is proved to have teeth rather than asserted to.
  const MUTANTS: [string, string, string][] = [
    [
      'M1: Sources & Uses total rebuilt in the browser',
      'formatCurrency(results.total_closing_uses)',
      'formatCurrency(results.acquisition_costs + results.financing_fee + results.closing_project_capital)',
    ],
    [
      'M2: Total Profit recomputed as TCR - TEI',
      'formatCurrency(results.total_profit)',
      'formatCurrency(results.total_cash_returned - results.total_equity_invested)',
    ],
    [
      'Equity Multiple recomputed as TCR / TEI',
      'formatMultiple(results.equity_multiple)',
      'formatMultiple(results.total_cash_returned / results.total_equity_invested)',
    ],
    [
      'Total Closing Sources rebuilt from debt and equity',
      'formatCurrency(results.total_closing_sources)',
      'formatCurrency(results.loan_amount + results.initial_equity)',
    ],
    [
      'project capital summed into a total',
      'const titleId = useId();\n  const schedulesNothing',
      'const titleId = useId();\n  const totalCapital = results.project_capital_by_year.reduce((sum, value) => sum, 0);\n  const schedulesNothing',
    ],
    [
      'Additional Equity derived from the Equity Cash Flow',
      '<MoneyCell value={results.net_additional_equity_requirement_by_year[index]} />',
      '<MoneyCell value={Math.max(-results.levered_cash_flows[index], 0)} />',
    ],
  ];

  for (const [name, target, replacement] of MUTANTS) {
    it(`catches ${name}`, () => {
      expect(SECTION_SOURCE, `${name}: target text is gone`).toContain(target);
      const mutated = SECTION_SOURCE.replace(target, replacement);
      const caughtByArithmetic = computationSites('mutant.tsx', mutated).length > 0;
      const caughtByFields =
        JSON.stringify(resultReads(mutated).fields) !== JSON.stringify(EXPECTED_RESULT_FIELDS);
      expect(caughtByArithmetic || caughtByFields, name).toBe(true);
    });
  }

  it('catches a compound-assignment total and a destructured read', () => {
    const summed = SECTION_SOURCE.replace(
      'const titleId = useId();\n  const schedulesNothing',
      'const titleId = useId();\n  let total = 0;\n  for (const value of results.owner_expenses_by_year) total += value;\n  const schedulesNothing',
    );
    expect(computationSites('mutant.tsx', summed)).toContain('total += value');
    const destructured = SECTION_SOURCE.replace(
      'const titleId = useId();\n  const schedulesNothing',
      'const titleId = useId();\n  const { total_profit } = results;\n  const schedulesNothing',
    );
    expect(resultReads(destructured).escapes).toHaveLength(1);
  });
});

// =============================================================================
// 10. Accessibility (Part AF)
// =============================================================================

describe('table semantics', () => {
  it('gives every table column and row headers, and names the regions', () => {
    show(LEASE_LEVEL, true);
    for (const name of ['Sources & Uses at Closing', 'Project Returns', 'Owner Cash Flow', 'Capital Schedule']) {
      const table = within(region(name)).getByRole('table');
      expect(table.querySelectorAll('th[scope="row"]').length, name).toBeGreaterThan(0);
    }
    for (const name of ['Owner Cash Flow', 'Capital Schedule']) {
      const table = within(region(name)).getByRole('table');
      expect(table.querySelectorAll('th[scope="col"]').length, name).toBeGreaterThan(0);
    }
    expect(screen.getByRole('region', { name: 'Capital Economics' })).toBeTruthy();
  });
});
