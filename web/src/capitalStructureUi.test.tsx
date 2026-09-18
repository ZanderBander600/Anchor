/**
 * Phase 7 Gate P7.8B -- the Capital Structure surfaces, driven directly.
 *
 * The editor, the result surface, the Risk view and the Position matrix take
 * their state as a prop, so these tests hand them state and assert what an
 * analyst sees. No `api.ts` mock is needed: what is proved here is
 * presentation, which is the whole of what this layer is allowed to do.
 *
 * **The result fixture is deliberately not internally consistent.** Its MOIC is
 * not its cash received over its funded amount, its profit is not received less
 * funded, and its Common Equity multiple is not its returned over its invested.
 * Every one of those is a figure the browser could "obviously" re-derive, so a
 * UI that derived any of them would print a different string and fail here --
 * the `investmentWorkspace.test.tsx` technique, applied to the gate where a
 * second arithmetic authority would do the most damage (P-3, P-5).
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  CapitalStructureEditor,
  COMMON_EQUITY_MARKER_MESSAGE,
  EMPTY_STRUCTURE_MESSAGE,
  UNSTATED_CHOICES_TITLE,
} from './components/CapitalStructureEditor';
import {
  CapitalStructureResults,
  NO_FUNDING_REQUIREMENT_MESSAGE,
  NO_POSITION_MESSAGE,
  UNRESOLVED_STRUCTURE_MESSAGE,
} from './components/CapitalStructureResults';
import {
  ANALYSIS_ABSENT_MESSAGE,
  CapitalStructureWorkspace,
  NO_STRUCTURE_MESSAGE,
  STALE_STRUCTURED_MESSAGE,
} from './components/CapitalStructureWorkspace';
import {
  NO_POSITIONS_MESSAGE,
  POSITION_ABSENT_MESSAGE,
  PositionDecisionMatrixPanel,
  RUN_POSITION_MESSAGE,
} from './components/PositionDecisionMatrixPanel';
import { EMPTY_FORM, newPosition } from './capitalStructureForm';
import type { CapitalStructureForm } from './capitalStructureForm';
import type {
  CommonEquityReturns,
  FundingRequirement,
  LegacyAcquisitionLoan,
  PositionDecisionCell,
  PositionDecisionMatrixReport,
  PositionPerspective,
  PositionReturns,
  StructuredCapitalResult,
} from './capitalTypes';
import type { CapitalStructureState } from './useCapitalStructure';
import type { PositionDecisionMatrixState } from './usePositionDecisionMatrix';

afterEach(cleanup);

const DEAL_UNITS = [{ unitId: 'deal-a', name: 'This Deal' }];
const TWO_UNITS = [
  { unitId: 'deal-a', name: 'Harbor One' },
  { unitId: 'deal-b', name: 'Harbor Two' },
];

// =============================================================================
// The editor
// =============================================================================

function editor(form: CapitalStructureForm, onChange = vi.fn(), units = DEAL_UNITS) {
  render(
    <CapitalStructureEditor
      id="capital-editor"
      prefix=""
      form={form}
      onChange={onChange}
      issues={[]}
      saveError={null}
      isSaving={false}
      locked={false}
      lockedReason={null}
      onSave={vi.fn()}
      onCancel={vi.fn()}
      units={units}
    />,
  );
  return onChange;
}

function mezzanine(): CapitalStructureForm {
  return { positions: [newPosition(EMPTY_FORM, 'mezzanine_debt', { kind: 'unit', unitId: 'deal-a' })] };
}

describe('the Capital Structure editor states what the analyst chose', () => {
  it('invents no shortfall resolution and no accrual convention', async () => {
    editor(mezzanine());
    // The engine refuses to assume either (P-14, FR-4), so neither is
    // preselected: both read "Choose…" until the analyst states one.
    const resolution = screen.getByLabelText('If its claim exceeds available cash');
    expect((resolution as HTMLSelectElement).value).toBe('');
    expect(within(resolution).getByText('Choose…')).toBeTruthy();
    // And the editor says so before the round trip rather than letting the
    // backend refuse a body it could have named itself.
    expect(screen.getByText(UNSTATED_CHOICES_TITLE)).toBeTruthy();
  });

  it('gives a position a new identity when its class changes (P-8)', async () => {
    const user = userEvent.setup();
    const form = mezzanine();
    const before = form.positions[0].positionId;
    const onChange = editor(form);

    await user.selectOptions(screen.getByLabelText('Class'), 'senior_debt');

    const next = onChange.mock.calls.at(-1)?.[0] as CapitalStructureForm;
    // A different class is a different economic instrument, so it is not the
    // position the Position matrix has been addressing.
    expect(next.positions[0].positionClass).toBe('senior_debt');
    expect(next.positions[0].positionId).not.toBe(before);
  });

  it('offers a scope only when there is a choice to make', () => {
    editor(mezzanine());
    expect(screen.queryByLabelText('Scope')).toBeNull();
    cleanup();
    editor(mezzanine(), vi.fn(), TWO_UNITS);
    const scope = screen.getByLabelText('Scope');
    expect(within(scope).getByText('Harbor One')).toBeTruthy();
    expect(within(scope).getByText('Whole Investment')).toBeTruthy();
  });

  it('gives Common Equity no funding, no terms and no resolution', () => {
    editor({
      positions: [newPosition(EMPTY_FORM, 'common_equity', { kind: 'unit', unitId: 'deal-a' })],
    });
    expect(screen.getByText(COMMON_EQUITY_MARKER_MESSAGE)).toBeTruthy();
    expect(screen.queryByLabelText('Funding')).toBeNull();
    expect(screen.queryByLabelText('Interest Rate')).toBeNull();
    expect(screen.queryByLabelText('If its claim exceeds available cash')).toBeNull();
  });

  it('says plainly when there is no structured capital', () => {
    editor(EMPTY_FORM);
    expect(screen.getByText(EMPTY_STRUCTURE_MESSAGE)).toBeTruthy();
  });
});

// =============================================================================
// The result surface
// =============================================================================

const SCOPE = { kind: 'unit' as const, unit_id: 'deal-a' };

function position(overrides: Partial<PositionReturns> = {}): PositionReturns {
  return {
    position_id: 'mezzanine-1',
    name: 'Mezzanine Loan',
    position_class: 'mezzanine_debt',
    scope: SCOPE,
    priority: 2,
    status: 'complete',
    unavailable_reason: null,
    unavailable_message: null,
    blocking_requirement_ids: [],
    funding: [],
    funded_amount: 1_500_000,
    debt_schedule: null,
    preferred_schedule: null,
    modeled_payoff_month: 60,
    balance_at_maturity_or_exit: 1_200_000,
    cash_flow_events: [],
    funding_requirements: [],
    annual_cash_flows: [-1_500_000, 180_000],
    irr: 0.12304,
    irr_status: 'defined',
    // Deliberately not `funded_amount * moic`, and profit is not received less
    // funded: a UI that derived either would print a different string.
    total_cash_received: 2_229_000,
    moic: 1.486,
    profit: 700_123,
    valuation_basis: { kind: 'unit_purchase_price', amount: 10_000_000 },
    attachment_basis: 6_000_000,
    detachment_basis: 7_500_000,
    last_dollar_basis: 7_500_000,
    attachment_ltv: 0.6,
    detachment_ltv: 0.75,
    debt_yield_through: 0.0933,
    coverage_by_year: [1.42, 1.51],
    headline_coverage: 1.42,
    minimum_coverage: 1.33,
    ...overrides,
  };
}

const COMMON_EQUITY: CommonEquityReturns = {
  position_id: 'common-equity-1',
  scope: SCOPE,
  status: 'complete',
  cash_flows: [-2_500_000, 300_000],
  unavailable_reason: null,
  unavailable_message: null,
  irr: 0.1842,
  irr_status: 'defined',
  // Again inconsistent on purpose.
  equity_multiple: 1.91,
  total_equity_invested: 2_500_000,
  total_cash_returned: 4_900_000,
  total_profit: 2_350_000,
};

function result(overrides: Partial<StructuredCapitalResult> = {}): StructuredCapitalResult {
  return {
    analysis_scope: 'unit',
    unit_ids: ['deal-a'],
    hold_period: 5,
    status: 'complete',
    legacy_acquisition_loans: [],
    positions: [position()],
    funding_requirements: [],
    common_equity: COMMON_EQUITY,
    ...overrides,
  };
}

describe('the structured result reports the engine’s figures and derives none', () => {
  it('prints each backend field exactly, inconsistencies included', () => {
    render(<CapitalStructureResults result={result()} unitNames={{ 'deal-a': 'Harbor One' }} />);
    expect(screen.getByText('$1,500,000')).toBeTruthy();
    expect(screen.getByText('12.30%')).toBeTruthy();
    expect(screen.getByText('1.49x')).toBeTruthy();
    // $700,123 is not $2,229,000 less $1,500,000. The backend said it, so it is
    // what is shown.
    expect(screen.getByText('$700,123')).toBeTruthy();
  });

  it('keeps returns and structural metrics apart when a claim went unmet', () => {
    const blocked = position({
      status: 'unresolved_funding',
      unavailable_reason: 'unresolved_funding_requirement',
      unavailable_message: 'A contractual claim could not be met from eligible cash.',
      annual_cash_flows: null,
      irr: null,
      irr_status: null,
      total_cash_received: null,
      moic: null,
      profit: null,
    });
    render(<CapitalStructureResults result={result({ positions: [blocked], status: 'unresolved_funding' })} />);

    // The returns are N/A with the backend's own reason...
    expect(screen.getAllByText('N/A').length).toBeGreaterThanOrEqual(1);
    expect(
      screen.getAllByText('A contractual claim could not be met from eligible cash.').length,
    ).toBeGreaterThanOrEqual(1);
    // ...while the structural metrics stand: they are contractual underwriting
    // facts and do not depend on what the cash settlement did.
    expect(screen.getByText('60.00%')).toBeTruthy();
    expect(screen.getByText('75.00%')).toBeTruthy();
    expect(screen.getByText('1.42x')).toBeTruthy();
    // And an unresolved structure is reported as analysed, not as an error.
    expect(screen.getByText(UNRESOLVED_STRUCTURE_MESSAGE)).toBeTruthy();
  });

  it('reports a Funding Requirement as the deterministic fact it is', () => {
    const requirement: FundingRequirement = {
      requirement_id: 'req-1',
      position_id: 'mezzanine-1',
      scope: SCOPE,
      period: { kind: 'hold_year', hold_year: 2 },
      claim_amount: 180_000,
      cash_available: 120_000,
      claim_paid_from_cash: 120_000,
      amount: 60_000,
      equity_contribution: 60_000,
      unpaid_claim_amount: 0,
      resolution: 'common_equity_contribution',
      status: 'resolved',
      explanation: 'Common Equity contributed the shortfall.',
    };
    render(<CapitalStructureResults result={result({ funding_requirements: [requirement] })} />);
    expect(screen.getByText('Year 2')).toBeTruthy();
    expect(screen.getByText('Resolved')).toBeTruthy();
    expect(screen.getByText('Common Equity contributed the shortfall.')).toBeTruthy();
  });

  it('says so when every claim was met, and when there is no position', () => {
    render(<CapitalStructureResults result={result()} />);
    expect(screen.getByText(NO_FUNDING_REQUIREMENT_MESSAGE)).toBeTruthy();
    cleanup();
    render(<CapitalStructureResults result={result({ positions: [] })} />);
    expect(screen.getByText(NO_POSITION_MESSAGE)).toBeTruthy();
  });
});

// =============================================================================
// The Risk view
// =============================================================================

function capitalState(overrides: Partial<CapitalStructureState> = {}): CapitalStructureState {
  return {
    saved: { positions: [] },
    draft: null,
    shown: { positions: [] },
    investmentId: 'inv-1',
    listStatus: 'ready',
    loadError: null,
    isSaving: false,
    saveError: null,
    saveIssues: [],
    hasDraft: false,
    isDirtyDraft: false,
    analysis: null,
    analysisError: null,
    analysisIssues: [],
    isAnalyzing: false,
    isAnalysisCurrent: false,
    canSave: false,
    canAnalyze: true,
    edit: vi.fn(),
    change: vi.fn(),
    cancel: vi.fn(),
    save: vi.fn(),
    analyze: vi.fn(),
    retryLoad: vi.fn(),
    ...overrides,
  };
}

function workspace(state: CapitalStructureState, blockedReason: string | null = null) {
  render(
    <CapitalStructureWorkspace
      state={state}
      prefix=""
      units={DEAL_UNITS}
      unitNames={{ 'deal-a': 'This Deal' }}
      blockedReason={blockedReason}
      isInvestment={false}
    />,
  );
}

describe('the Capital Structure Risk view', () => {
  it('is simple until the analyst opts in', () => {
    workspace(capitalState());
    expect(screen.getByText(NO_STRUCTURE_MESSAGE)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Add Capital Structure' })).toBeTruthy();
    expect(screen.getByText(ANALYSIS_ABSENT_MESSAGE)).toBeTruthy();
  });

  it('blocks editing while the base underwriting is unsaved, and says why', () => {
    workspace(capitalState(), 'Save this deal before adding a capital structure.');
    expect(
      (screen.getByRole('button', { name: 'Add Capital Structure' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByText('Save this deal before adding a capital structure.')).toBeTruthy();
  });

  it('keeps an out-of-date analysis on screen and marks it, never silently reusing it', () => {
    workspace(
      capitalState({
        analysis: {
          investment_id: 'inv-1',
          strategy_id: 'base',
          scenario_id: 'base',
          root_kind: 'hidden_unit',
          unit_ids: ['deal-a'],
          hold_period: 5,
          capital_structure: { positions: [] },
          capital_structure_source: 'base',
          project_source_fingerprint: 'p',
          structured_source_fingerprint: 's',
          project_cache_status: 'bypassed',
          result: result(),
        },
        isAnalysisCurrent: false,
      }),
    );
    expect(screen.getByText(STALE_STRUCTURED_MESSAGE)).toBeTruthy();
    expect(screen.getByText('Out of date')).toBeTruthy();
  });
});

// =============================================================================
// The POSITION perspective
// =============================================================================

function cell(overrides: Partial<PositionDecisionCell> = {}): PositionDecisionCell {
  return {
    strategy_id: 'base',
    scenario_id: 'base',
    status: 'valid',
    applicability: 'present',
    issues: [],
    project_source_fingerprint: 'p',
    source_fingerprint: 's',
    hold_period: 5,
    position_status: 'complete',
    unavailable_reason: null,
    unavailable_message: null,
    metrics: [{ metric: 'position_irr', value: 0.12304, irr_status: 'defined', reason: null, message: null }],
    deltas: [],
    ...overrides,
  };
}

const PERSPECTIVE: PositionPerspective = {
  position_id: 'mezzanine-1',
  name: 'Mezzanine Loan',
  position_class: 'mezzanine_debt',
  scope: SCOPE,
  is_common_equity_marker: false,
  present_in_base: true,
  strategy_ids: ['base'],
};

function report(cells: PositionDecisionCell[]): PositionDecisionMatrixReport {
  return {
    investment_id: 'inv-1',
    root_kind: 'hidden_unit',
    unit_ids: ['deal-a'],
    position: PERSPECTIVE,
    matrix: {
      perspective: 'position',
      position_id: 'mezzanine-1',
      position_name: 'Mezzanine Loan',
      position_class: 'mezzanine_debt',
      scope: SCOPE,
      is_common_equity_marker: false,
      strategies: [
        { strategy_id: 'base', name: 'Base', is_base: true, hold_period: 5 },
        { strategy_id: 'str-1', name: 'Hold Longer', is_base: false, hold_period: 7 },
      ],
      scenarios: [{ scenario_id: 'base', name: 'Base', is_base: true }],
      metrics: [
        {
          metric: 'position_irr',
          label: 'IRR',
          unit: 'rate',
          direction: 'higher_is_better',
          horizon_dependent: false,
        },
      ],
      omitted_metrics: [],
      hold_periods: [5, 7],
      cross_scenario_figures: false,
      cells,
      strategy_figures: [],
      matrix_fingerprint: 'f',
      matrix_fingerprint_reason: null,
    },
  };
}

function positionState(
  overrides: Partial<PositionDecisionMatrixState> = {},
): PositionDecisionMatrixState {
  return {
    positions: [PERSPECTIVE],
    listStatus: 'ready',
    listError: null,
    retryList: vi.fn(),
    selectedPositionId: 'mezzanine-1',
    selectPosition: vi.fn(),
    report: null,
    error: null,
    isCurrent: true,
    hasRun: false,
    isRunning: false,
    canRun: true,
    run: vi.fn(),
    ...overrides,
  };
}

describe('the POSITION perspective of the Decision Matrix', () => {
  it('offers the addressable positions by name, and runs nothing until asked', () => {
    render(<PositionDecisionMatrixPanel state={positionState()} ids="" isDirty={false} />);
    // By role, not by label: the panel's own heading is also "Position", so a
    // label query names both the section and the select.
    expect(within(screen.getByRole('combobox')).getByText('Mezzanine Loan')).toBeTruthy();
    expect(screen.getByText(RUN_POSITION_MESSAGE)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Run Position Matrix' })).toBeTruthy();
  });

  it('says a Strategy does not hold the position, which is not zero (P-9, DC-2)', () => {
    render(
      <PositionDecisionMatrixPanel
        state={positionState({
          report: report([
            cell(),
            cell({ strategy_id: 'str-1', applicability: 'not_present', metrics: [], position_status: null }),
          ]),
          hasRun: true,
        })}
        ids=""
        isDirty={false}
      />,
    );
    expect(screen.getByText(POSITION_ABSENT_MESSAGE)).toBeTruthy();
    // The cell that does hold it still reports its figure.
    expect(screen.getByText('12.30%')).toBeTruthy();
  });

  it('shows an invalid variant’s reasons and leaves every other cell standing', () => {
    render(
      <PositionDecisionMatrixPanel
        state={positionState({
          report: report([
            cell(),
            cell({
              strategy_id: 'str-1',
              status: 'invalid',
              issues: [{ source: 'strategy', code: 'incomplete_domain', message: 'Amortization is required.', field: null }],
              metrics: [],
            }),
          ]),
          hasRun: true,
        })}
        ids=""
        isDirty={false}
      />,
    );
    expect(screen.getByText('Invalid variant')).toBeTruthy();
    expect(screen.getByText('Amortization is required.')).toBeTruthy();
    expect(screen.getByText('12.30%')).toBeTruthy();
  });

  it('says when there is no position to compare', () => {
    render(
      <PositionDecisionMatrixPanel
        state={positionState({ positions: [], selectedPositionId: null })}
        ids=""
        isDirty={false}
      />,
    );
    expect(screen.getByText(NO_POSITIONS_MESSAGE)).toBeTruthy();
  });
});

describe('the Acquisition Loans table puts each header over its figures', () => {
  const LOAN: LegacyAcquisitionLoan = {
    position_id: 'deal-a-acquisition-loan',
    position_class: 'senior_debt',
    scope: { kind: 'unit', unit_id: 'deal-a' },
    priority: 1,
    shortfall_resolution: 'common_equity_contribution',
    loan_amount: 6_500_000,
    annual_debt_service: [420_000, 420_000],
    remaining_loan_balance: 6_012_450,
    modeled_payoff_month: 60,
    interest_rate: 0.0625,
    amortization: 30,
    io_period: 2,
    hold_period: 5,
  };

  function loansTable(): HTMLTableElement {
    render(
      <CapitalStructureResults
        result={result({ legacy_acquisition_loans: [LOAN] })}
        unitNames={{ 'deal-a': 'Harbor One' }}
      />,
    );
    const heading = screen.getByRole('heading', { name: 'Acquisition Loans' });
    const section = heading.closest('section') as HTMLElement;
    return within(section).getByRole('table') as HTMLTableElement;
  }

  it('carries its own alignment hook beside the shared table class', () => {
    // The hook is what lets the stylesheet right-align these headers without
    // touching the three tables that carry text columns.
    const table = loansTable();
    expect(table.classList.contains('capital-result-table')).toBe(true);
    expect(table.classList.contains('capital-loan-table')).toBe(true);
  });

  it('leads with Unit and then names only figures', () => {
    // The alignment rule turns on the column order: the one label column first,
    // every numeric column after it. A text column added in the middle would
    // silently be right-aligned, so the order is pinned here.
    const headers = [...loansTable().querySelectorAll('thead th')].map(
      (cell) => cell.textContent?.trim(),
    );
    expect(headers).toEqual([
      'Unit',
      'Priority',
      'Loan Amount',
      'Interest Rate',
      'Amortization',
      'Interest-Only',
      'Remaining Balance',
    ]);
  });

  it('keeps the Unit label column on the left and every figure on the right', () => {
    const table = loansTable();
    const row = within(table).getByRole('row', { name: /Harbor One/ });
    // The Unit is a row header, which the shared rule left-aligns; the figures
    // are ordinary cells, which the shared rule right-aligns. The header rule
    // added by this correction is what puts the column headings over them.
    expect(within(row).getByRole('rowheader').textContent).toContain('Harbor One');
    const figures = [...row.querySelectorAll('td')].map((cell) => cell.textContent?.trim());
    expect(figures).toEqual(['1', '$6,500,000', '6.25%', '30 yrs', '2 yrs', '$6,012,450']);
  });

  it('leaves the other Capital Structure tables on the shared class alone', () => {
    render(
      <CapitalStructureResults
        result={result({ legacy_acquisition_loans: [LOAN] })}
        unitNames={{ 'deal-a': 'Harbor One' }}
      />,
    );
    const tables = [...document.querySelectorAll('table.capital-result-table')];
    expect(tables.length).toBeGreaterThan(1);
    const hooked = tables.filter((table) => table.classList.contains('capital-loan-table'));
    expect(hooked).toHaveLength(1);
  });

  it('still scrolls inside its own region rather than widening the page', () => {
    const table = loansTable();
    expect(table.closest('.table-scroll')).not.toBeNull();
  });
});
