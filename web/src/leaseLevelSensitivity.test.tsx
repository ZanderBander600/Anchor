/**
 * D5.7 -- what an analyst can actually do on the Lease-Level Risk workspace.
 *
 * `modeDispatch.architecture.test.ts` proves the structural claims: the client
 * functions exist, the ladder arithmetic is confined, no preset is reachable and
 * no sensitivity component computes. This file proves the *behaviour* the
 * analyst meets: the eight targets and five metrics are offered, an absolute
 * candidate value reaches the wire absolutely, the matrix is not transposed, an
 * undefined metric reads N/A and a refused run refuses whole.
 *
 * Driven through `App` rather than the component in isolation, because half the
 * gate's promises are about *wiring*: that Risk runs against the assumptions
 * currently on Underwrite, that it uses the same request mapper Analyze uses,
 * that configuring a scenario does not dirty the deal, and that nothing about a
 * sensitivity is persisted.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import {
  LeaseLevelApiError,
  analyzeLeaseLevelAcquisition,
  getDeal,
  listDeals,
  runLeaseLevelOneWaySensitivity,
  runLeaseLevelTwoWaySensitivity,
  updateLeaseLevelDeal,
} from './api';
import {
  LEASE_LEVEL_SENSITIVITY_METRICS,
  LEASE_LEVEL_SENSITIVITY_TARGETS,
} from './leaseLevelSensitivity';
import { generateLadderValues } from './leaseLevelSensitivityLadder';
import type {
  LeaseLevelOneWaySensitivityResult,
  LeaseLevelTwoWaySensitivityResult,
} from './leaseLevelSensitivityTypes';
import type {
  LeaseRequest,
  MarketLeasingAssumptionsRequest,
  SuiteRequest,
} from './leaseLevelTypes';
import type { AcquisitionTermsRequest, Deal } from './types';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    analyzeLeaseLevelAcquisition: vi.fn(),
    updateLeaseLevelDeal: vi.fn(),
    getDeal: vi.fn(),
    listDeals: vi.fn(),
    runLeaseLevelOneWaySensitivity: vi.fn(),
    runLeaseLevelTwoWaySensitivity: vi.fn(),
  };
});

const mockAnalyze = vi.mocked(analyzeLeaseLevelAcquisition);
const mockUpdate = vi.mocked(updateLeaseLevelDeal);
const mockGetDeal = vi.mocked(getDeal);
const mockListDeals = vi.mocked(listDeals);
const mockOneWay = vi.mocked(runLeaseLevelOneWaySensitivity);
const mockTwoWay = vi.mocked(runLeaseLevelTwoWaySensitivity);

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

// =============================================================================
// A saved Lease-Level deal, in three override shapes
//
// The shapes are the point. `market_rent_psf` and `renewal_probability` are
// shadowed by *different* suite overrides, and a fixture with only one kind of
// override could not tell the two rules apart.
// =============================================================================

const TERMS: AcquisitionTermsRequest = {
  purchase_price: 42_500_000,
  hold_period: 7,
  exit_cap_rate: 0.0625,
  ltv: 0.6,
  interest_rate: 0.055,
  amortization: 30,
  acquisition_cost_pct: 0.015,
  financing_fee_pct: 0.01,
  disposition_cost_pct: 0.0125,
  annual_capex_reserve: 120_000,
  io_period: 2,
};

const MARKET_LEASING: MarketLeasingAssumptionsRequest = {
  market_rent_psf: 34.5,
  market_rent_growth: 0.03,
  renewal_rent_psf: null,
  renewal_rent_spread: -0.05,
  renewal_term_months: 60,
  successor_escalation_pct: 0.03,
  renewal_downtime_months: 2,
  renewal_free_rent_months: 1,
  new_term_months: 84,
  new_downtime_months: 9,
  new_free_rent_months: 4,
  renewal_ti_psf: 25,
  new_ti_psf: 65,
  leasing_commission_method: 'pct_of_total_contractual_base_rent',
  renewal_lc_pct: 0.03,
  new_lc_pct: 0.06,
  renewal_probability: 0.7,
  renewal_lease_type: 'nnn',
  renewal_recovery_basis: null,
  renewal_expense_stop_psf: null,
  new_lease_type: 'nnn',
  new_recovery_basis: null,
  new_expense_stop_psf: null,
};

/** No suite override of any kind: every property default is reachable. */
const PLAIN_SUITES: SuiteRequest[] = [
  {
    suite_id: '100',
    suite_area_sf: 40_000,
    suite_label: 'Ground floor',
    market_rent_psf: null,
    market_leasing_override: null,
    initial_vacancy: null,
  },
  {
    suite_id: '200',
    suite_area_sf: 22_000,
    suite_label: null,
    market_rent_psf: null,
    market_leasing_override: null,
    initial_vacancy: null,
  },
];

/** Suite 200 carries only the *scalar* market rent. This shadows Market Rent /
 * SF and must leave Renewal Probability alone. */
const SCALAR_RENT_SUITES: SuiteRequest[] = [
  PLAIN_SUITES[0],
  { ...PLAIN_SUITES[1], market_rent_psf: 38.75 },
];

/** Suite 200 carries the whole market-leasing record. This shadows both. */
const FULL_OVERRIDE_SUITES: SuiteRequest[] = [
  PLAIN_SUITES[0],
  { ...PLAIN_SUITES[1], market_leasing_override: { ...MARKET_LEASING, new_downtime_months: 12 } },
];

const LEASES: LeaseRequest[] = [
  {
    lease_id: 'L-100',
    suite_id: '100',
    leased_area_sf: 40_000,
    rent_commencement_date: '2023-06-01',
    lease_expiration_date: '2029-05-31',
    base_rent_psf: 31.25,
    escalation_pct: 0.03,
    escalation_basis: 'lease_anniversary',
    lease_type: 'nnn',
    tenant_name: 'Marlow Provisions',
    lease_start_date: '2023-06-01',
    origin: 'in_place',
    recovery_basis: null,
    expense_stop_psf: null,
  },
  {
    lease_id: 'L-200',
    suite_id: '200',
    leased_area_sf: 22_000,
    rent_commencement_date: '2022-01-01',
    lease_expiration_date: '2027-12-31',
    base_rent_psf: 29.4,
    escalation_pct: 0,
    escalation_basis: 'none',
    lease_type: 'nnn',
    tenant_name: 'Halbrook Analytics',
    lease_start_date: null,
    origin: 'in_place',
    recovery_basis: null,
    expense_stop_psf: null,
  },
];

function savedDeal(suites: SuiteRequest[] = PLAIN_SUITES): Deal {
  return {
    id: 'deal-ll-1',
    name: 'Fulton Exchange',
    operating_mode: 'lease_level',
    inputs: null,
    detailed_operating_inputs: null,
    terms: TERMS,
    property_inputs: { analysis_start_date: '2027-01-01', rentable_area_sf: 62_000 },
    operating_inputs: {
      other_income: 84_000,
      other_income_growth: 0.025,
      credit_loss_pct: 0.015,
      property_taxes: 410_000,
      insurance: 62_000,
      utilities: 148_000,
      repairs_maintenance: 96_000,
      other_operating_expenses: 54_000,
      management_fee_pct: 0.03,
      expense_growth: 0.03,
      recoverable_expense_ratio: 0.85,
    },
    market_leasing: MARKET_LEASING,
    suites,
    leases: LEASES,
    deal_context: null,
    analysis_snapshot: null,
    ai_snapshot: null,
    created_at: '2027-01-04T09:00:00+00:00',
    updated_at: '2027-01-04T09:00:00+00:00',
  };
}

// =============================================================================
// Driving the workspace
// =============================================================================

async function openRisk(suites: SuiteRequest[] = PLAIN_SUITES) {
  const deal = savedDeal(suites);
  mockListDeals.mockResolvedValue([deal]);
  mockGetDeal.mockResolvedValue(deal);
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('Fulton Exchange');
  await user.click(screen.getByText('Fulton Exchange'));
  await waitFor(() => {
    expect(mockGetDeal).toHaveBeenCalledWith('deal-ll-1');
  });
  await user.click(screen.getByRole('tab', { name: 'Risk' }));
  return user;
}

function panel(view: 'one-way' | 'two-way'): HTMLElement {
  const element = document.getElementById(`lease-level-sensitivity-panel-${view}`);
  if (element === null) {
    throw new Error(`No sensitivity panel for ${view}`);
  }
  return element;
}

function control(id: string): HTMLSelectElement | HTMLInputElement {
  const element = document.getElementById(id);
  if (element === null) {
    throw new Error(`No control with id ${id}`);
  }
  return element as HTMLSelectElement | HTMLInputElement;
}

/** The header's save-status label. Its own element rather than a text query:
 * the label shares a span with the "· saved at" timestamp. */
function saveStatusText(): string {
  return document.querySelector('.save-status')?.textContent ?? '';
}

function optionValues(select: HTMLSelectElement): string[] {
  return Array.from(select.options).map((option) => option.value);
}

async function showTwoWay(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('tab', { name: 'Two-Way' }));
}

/** Adds `values` to a candidate editor, one field at a time, exactly as an
 * analyst would: press Add Value, then type into the field that appears. */
async function enterCandidates(
  user: ReturnType<typeof userEvent.setup>,
  scope: HTMLElement,
  legend: string,
  values: string[],
): Promise<void> {
  const addButtons = within(scope).getAllByRole('button', { name: 'Add Value' });
  const add = legend.startsWith('Column') ? addButtons[1] : addButtons[0];
  for (const value of values) {
    await user.click(add);
    const fields = within(scope).getAllByLabelText(new RegExp(`^${legend} \\d+$`));
    await user.type(fields[fields.length - 1], value);
  }
}

async function runIn(user: ReturnType<typeof userEvent.setup>, scope: HTMLElement) {
  await user.click(within(scope).getByRole('button', { name: 'Run Sensitivity' }));
}

function oneWayResult(
  overrides: Partial<LeaseLevelOneWaySensitivityResult> = {},
): LeaseLevelOneWaySensitivityResult {
  return {
    assumption: 'exit_cap_rate',
    metric: 'levered_irr',
    baseline_assumption_value: 0.0625,
    baseline_metric_value: 0.142,
    assumption_values: [0.06, 0.065],
    metric_values: [0.155, 0.128],
    ...overrides,
  };
}

function twoWayResult(
  overrides: Partial<LeaseLevelTwoWaySensitivityResult> = {},
): LeaseLevelTwoWaySensitivityResult {
  return {
    row_assumption: 'exit_cap_rate',
    column_assumption: 'purchase_price',
    metric: 'levered_irr',
    baseline_row_value: 0.0625,
    baseline_column_value: 42_500_000,
    baseline_metric_value: 0.142,
    row_values: [0.06, 0.065],
    column_values: [40_000_000, 42_500_000, 45_000_000],
    matrix: [
      [0.181, 0.162, 0.145],
      [0.152, 0.134, 0.118],
    ],
    ...overrides,
  };
}

/** A refusal the backend words itself. `detail` is a plain string for a
 * shadowed target, an unsupported target and a repeated axis target, and the
 * client surfaces that sentence unchanged. */
function refusal(message: string): LeaseLevelApiError {
  return new LeaseLevelApiError(message, [], []);
}

/** A structured refusal: one candidate scenario cannot be underwritten at all.
 * Built the way the client builds it -- the banner message is the issue's own
 * message -- so the test cannot pass on a message the app never produces. */
function exitNoiRefusal(): LeaseLevelApiError {
  const message =
    'NON_POSITIVE_FORWARD_EXIT_NOI: the forward 12-month exit NOI is not positive.';
  return new LeaseLevelApiError(message, [], [
    { code: 'NON_POSITIVE_FORWARD_EXIT_NOI', path: '', message, severity: 'error' },
  ]);
}

const SHADOW_REFUSAL =
  "SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE: the property-default sensitivity " +
  "target 'market_rent_psf' is shadowed by a suite-specific override on suite(s) 200.";

// =============================================================================
// 1. The Risk workspace exists, and is the sensitivity workspace
// =============================================================================

describe('the Lease-Level Risk workspace', () => {
  it('M1: is no longer a placeholder', async () => {
    await openRisk();

    expect(screen.getByRole('tablist', { name: 'Lease-Level sensitivity views' })).toBeTruthy();
    expect(screen.queryByText(/arrives in a later gate/i)).toBeNull();
  });

  it('offers One-Way and Two-Way, and no Break-Even', async () => {
    await openRisk();

    const views = screen.getByRole('tablist', { name: 'Lease-Level sensitivity views' });
    const labels = within(views)
      .getAllByRole('tab')
      .map((tab) => tab.textContent);
    expect(labels).toEqual(['One-Way', 'Two-Way']);
    // Quick's and Detailed's break-even controls must not appear here: the
    // capability does not exist for Lease-Level.
    expect(within(panel('one-way')).queryByText(/break-?even/i)).toBeNull();
    expect(screen.queryByRole('button', { name: /Solve|Break-Even/i })).toBeNull();
  });

  it('M2: offers no preset button that populates assumptions', async () => {
    await openRisk();

    for (const name of [/Conservative/i, /Upside/i, /Downside/i, /Base Case/i, /Standard/i]) {
      expect(screen.queryByRole('button', { name })).toBeNull();
    }
    // And nothing is pre-populated: the analyst owns every value.
    expect(within(panel('one-way')).queryAllByLabelText(/candidate value \d+$/)).toHaveLength(0);
  });
});

// =============================================================================
// 2. One-way: the offered vocabulary
// =============================================================================

describe('one-way sensitivity controls', () => {
  it('offers exactly the eight supported targets, with analyst labels', async () => {
    await openRisk();

    const select = control('lease-level-one-way-assumption') as HTMLSelectElement;
    expect(optionValues(select)).toEqual([
      'purchase_price',
      'exit_cap_rate',
      'ltv',
      'interest_rate',
      'market_rent_psf',
      'renewal_probability',
      'expense_growth',
      'recoverable_expense_ratio',
    ]);
    expect(Array.from(select.options).map((option) => option.textContent)).toEqual([
      'Purchase Price',
      'Exit Cap Rate',
      'LTV',
      'Interest Rate',
      'Market Rent / SF',
      'Renewal Probability',
      'Expense Growth',
      'Recoverable Expense Ratio',
    ]);
  });

  it('M3: offers no target the runner does not support', async () => {
    await openRisk();

    const offered = new Set(
      optionValues(control('lease-level-one-way-assumption') as HTMLSelectElement),
    );
    for (const deferred of [
      'renewal_downtime_months',
      'new_downtime_months',
      'renewal_ti_psf',
      'new_ti_psf',
      'renewal_lc_pct',
      'new_lc_pct',
      'renewal_free_rent_months',
      'renewal_term_months',
      'market_rent_growth',
      'annual_capex_reserve',
      'management_fee_pct',
      'credit_loss_pct',
      'hold_period',
      'suite_market_rent_psf',
    ]) {
      expect(offered.has(deferred), `${deferred} is offered but unsupported`).toBe(false);
    }
    expect(offered.size).toBe(8);
  });

  it('offers exactly the five supported metrics', async () => {
    await openRisk();

    const select = control('lease-level-one-way-metric') as HTMLSelectElement;
    expect(optionValues(select)).toEqual([
      'levered_irr',
      'unlevered_irr',
      'equity_multiple',
      'headline_dscr',
      'exit_value',
    ]);
    expect(Array.from(select.options).map((option) => option.textContent)).toEqual([
      'Levered IRR',
      'Unlevered IRR',
      'Equity Multiple',
      'Headline DSCR',
      'Exit Value',
    ]);
  });

  it('exposes no raw snake_case anywhere in the builder', async () => {
    await openRisk();

    const text = panel('one-way').textContent ?? '';
    for (const wire of [
      'exit_cap_rate',
      'purchase_price',
      'market_rent_psf',
      'renewal_probability',
      'levered_irr',
      'headline_dscr',
    ]) {
      expect(text, `${wire} is shown to the analyst`).not.toContain(wire);
    }
  });
});

// =============================================================================
// 3. One-way: absolute values on the wire
// =============================================================================

describe('one-way candidate values are absolute', () => {
  it('M4: sends a percentage target at the shipped percent convention', async () => {
    const user = await openRisk();
    mockOneWay.mockResolvedValue(oneWayResult());

    await enterCandidates(user, panel('one-way'), 'Exit Cap Rate candidate value', [
      '5.75',
      '6.25',
      '6.75',
    ]);
    await runIn(user, panel('one-way'));

    await waitFor(() => expect(mockOneWay).toHaveBeenCalledTimes(1));
    const controls = mockOneWay.mock.calls[0][2];
    // 6.25 means an exit cap of 6.25%, not 6.25 basis points of movement and
    // not a shift from the baseline 6.25%.
    expect(controls.values).toEqual([0.0575, 0.0625, 0.0675]);
    expect(controls.assumption).toBe('exit_cap_rate');
    expect(controls.metric).toBe('levered_irr');
  });

  it('sends a currency target unchanged, separators stripped', async () => {
    const user = await openRisk();
    mockOneWay.mockResolvedValue(oneWayResult({ assumption: 'purchase_price' }));

    await user.selectOptions(control('lease-level-one-way-assumption'), 'purchase_price');
    await enterCandidates(user, panel('one-way'), 'Purchase Price candidate value', [
      '28000000',
      '30000000',
    ]);
    await runIn(user, panel('one-way'));

    await waitFor(() => expect(mockOneWay).toHaveBeenCalledTimes(1));
    expect(mockOneWay.mock.calls[0][2].values).toEqual([28_000_000, 30_000_000]);
  });

  it('sends a $/SF target at its own scale, never as a percentage', async () => {
    const user = await openRisk();
    mockOneWay.mockResolvedValue(oneWayResult({ assumption: 'market_rent_psf' }));

    await user.selectOptions(control('lease-level-one-way-assumption'), 'market_rent_psf');
    await enterCandidates(user, panel('one-way'), 'Market Rent / SF candidate value', [
      '35',
      '38.5',
    ]);
    await runIn(user, panel('one-way'));

    await waitFor(() => expect(mockOneWay).toHaveBeenCalledTimes(1));
    expect(mockOneWay.mock.calls[0][2].values).toEqual([35, 38.5]);
  });

  it('sends the deal on screen, through the same mapper Analyze uses', async () => {
    const user = await openRisk();
    mockOneWay.mockResolvedValue(oneWayResult());
    mockAnalyze.mockResolvedValue({
      monthly_projection: {} as never,
      annual_projection: {} as never,
      results: {} as never,
    });

    await enterCandidates(user, panel('one-way'), 'Exit Cap Rate candidate value', ['6']);
    await runIn(user, panel('one-way'));
    await waitFor(() => expect(mockOneWay).toHaveBeenCalledTimes(1));

    const [terms, inputs] = mockOneWay.mock.calls[0];
    expect(terms).toEqual(TERMS);
    expect(inputs.market_leasing).toEqual(MARKET_LEASING);
    expect(inputs.suites).toEqual(PLAIN_SUITES);
    expect(inputs.leases).toEqual(LEASES);

    // The same request Analyze would have submitted, field for field.
    await user.click(screen.getByRole('tab', { name: 'Underwrite' }));
    await user.click(screen.getByRole('button', { name: /^Analyz/i }));
    await waitFor(() => expect(mockAnalyze).toHaveBeenCalledTimes(1));
    expect(mockAnalyze.mock.calls[0][0]).toEqual(terms);
    expect(mockAnalyze.mock.calls[0][1]).toEqual(inputs);
  });

  it('M29: needs no prior Analyze', async () => {
    const user = await openRisk();
    mockOneWay.mockResolvedValue(oneWayResult());

    await enterCandidates(user, panel('one-way'), 'Exit Cap Rate candidate value', ['6']);
    await runIn(user, panel('one-way'));

    await waitFor(() => expect(mockOneWay).toHaveBeenCalledTimes(1));
    // No analysis was ever requested, and the API contract does not require one.
    expect(mockAnalyze).not.toHaveBeenCalled();
  });
});

// =============================================================================
// 4. One-way: the result
// =============================================================================

describe('the one-way result table', () => {
  it('renders rows in the candidate order the response carries', async () => {
    const user = await openRisk();
    mockOneWay.mockResolvedValue(
      oneWayResult({
        assumption_values: [0.07, 0.055, 0.0625],
        metric_values: [0.101, 0.19, 0.142],
      }),
    );

    await enterCandidates(user, panel('one-way'), 'Exit Cap Rate candidate value', [
      '7',
      '5.5',
      '6.25',
    ]);
    await runIn(user, panel('one-way'));

    const table = await within(panel('one-way')).findByRole('table');
    const rows = within(table).getAllByRole('row');
    // Header, then the three candidates in submitted order -- not sorted, not
    // reordered, and with no synthetic row inserted among them.
    expect(rows.slice(1).map((row) => within(row).getAllByRole('cell')[0].textContent)).toEqual([
      '10.10%',
      '19.00%',
      '14.20% Base',
    ]);
    expect(rows.slice(1).map((row) => within(row).getByRole('rowheader').textContent)).toEqual([
      '7.00%',
      '5.50%',
      '6.25%',
    ]);
  });

  it('M11: shows an undefined metric as N/A, never as zero', async () => {
    const user = await openRisk();
    mockOneWay.mockResolvedValue(
      oneWayResult({ assumption_values: [0.06, 0.065], metric_values: [null, 0.128] }),
    );

    await enterCandidates(user, panel('one-way'), 'Exit Cap Rate candidate value', ['6', '6.5']);
    await runIn(user, panel('one-way'));

    const table = await within(panel('one-way')).findByRole('table');
    const cells = within(table)
      .getAllByRole('row')
      .slice(1)
      .map((row) => within(row).getAllByRole('cell')[0].textContent);
    expect(cells).toEqual(['N/A', '12.80%']);
    expect(cells).not.toContain('0.00%');
    // And the reason is stated in text, not implied by an empty cell.
    expect(within(panel('one-way')).getByText(/not uniquely defined/i)).toBeTruthy();
  });

  it('shows the baseline the response identifies, and infers none', async () => {
    const user = await openRisk();
    mockOneWay.mockResolvedValue(
      oneWayResult({
        baseline_assumption_value: 0.0625,
        baseline_metric_value: 0.142,
        // No candidate equals the baseline.
        assumption_values: [0.05, 0.06],
        metric_values: [0.21, 0.17],
      }),
    );

    await enterCandidates(user, panel('one-way'), 'Exit Cap Rate candidate value', ['5', '6']);
    await runIn(user, panel('one-way'));

    // The response's own baseline, stated once above the table.
    const line = await within(panel('one-way')).findByText(/^Baseline:/);
    expect(line.textContent).toContain('Exit Cap Rate 6.25%');
    expect(line.textContent).toContain('Levered IRR 14.20%');

    // And no candidate is nominated as "closest to" it.
    const table = within(panel('one-way')).getByRole('table');
    const marked = within(table)
      .getAllByRole('row')
      .filter((row) => (row.textContent ?? '').includes('Base'));
    expect(marked).toHaveLength(0);
  });

  it('formats each metric in its own units', async () => {
    const user = await openRisk();
    mockOneWay.mockResolvedValue(
      oneWayResult({
        metric: 'exit_value',
        assumption_values: [0.06],
        metric_values: [58_400_000],
        baseline_metric_value: 55_000_000,
      }),
    );

    await user.selectOptions(control('lease-level-one-way-metric'), 'exit_value');
    await enterCandidates(user, panel('one-way'), 'Exit Cap Rate candidate value', ['6']);
    await runIn(user, panel('one-way'));

    expect(await within(panel('one-way')).findByText('$58,400,000')).toBeTruthy();
  });
});

// =============================================================================
// 5. Refusals: a run that cannot be answered is refused whole
// =============================================================================

describe('a refused one-way run', () => {
  it('M12: surfaces a backend validation failure rather than N/A', async () => {
    const user = await openRisk();
    mockOneWay.mockRejectedValue(exitNoiRefusal());

    await enterCandidates(user, panel('one-way'), 'Exit Cap Rate candidate value', ['6', '20']);
    await runIn(user, panel('one-way'));

    const alert = await within(panel('one-way')).findByRole('alert');
    expect(alert.textContent).toContain('NON_POSITIVE_FORWARD_EXIT_NOI');
    // Not softened into a table with a gap in it.
    expect(within(panel('one-way')).queryByRole('table')).toBeNull();
    expect(within(panel('one-way')).queryByText('N/A')).toBeNull();
  });

  it('M10: replaces a previous result rather than showing a partial one', async () => {
    const user = await openRisk();
    mockOneWay.mockResolvedValue(oneWayResult());

    await enterCandidates(user, panel('one-way'), 'Exit Cap Rate candidate value', ['6']);
    await runIn(user, panel('one-way'));
    expect(await within(panel('one-way')).findByRole('table')).toBeTruthy();

    mockOneWay.mockRejectedValue(refusal(SHADOW_REFUSAL));
    await runIn(user, panel('one-way'));

    await waitFor(() => {
      expect(within(panel('one-way')).queryByRole('table')).toBeNull();
    });
    expect(within(panel('one-way')).getByRole('alert').textContent).toContain(
      'SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE',
    );
  });

  it('surfaces the repeated-axis refusal the runner already makes', async () => {
    const user = await openRisk();
    mockTwoWay.mockRejectedValue(
      refusal("row_assumption and column_assumption must differ; got 'exit_cap_rate' for both."),
    );

    await showTwoWay(user);
    await user.selectOptions(control('lease-level-two-way-column-assumption'), 'exit_cap_rate');
    await enterCandidates(user, panel('two-way'), 'Row Exit Cap Rate candidate value', ['6']);
    await enterCandidates(user, panel('two-way'), 'Column Exit Cap Rate candidate value', ['6']);
    await runIn(user, panel('two-way'));

    // The frontend does not pre-empt the rule; it submits and reports.
    await waitFor(() => expect(mockTwoWay).toHaveBeenCalledTimes(1));
    expect((await within(panel('two-way')).findByRole('alert')).textContent).toContain(
      'must differ',
    );
  });
});

// =============================================================================
// 6. Shadowing
// =============================================================================

describe('suite overrides that shadow a property default', () => {
  it('M7: says Market Rent is unavailable when a suite carries a scalar rent', async () => {
    const user = await openRisk(SCALAR_RENT_SUITES);

    await user.selectOptions(control('lease-level-one-way-assumption'), 'market_rent_psf');

    const notice = within(panel('one-way')).getByRole('note');
    expect(notice.textContent).toContain('Unavailable for property-wide sensitivity');
    expect(notice.textContent).toContain('200');
    // Textual, not colour-only.
    expect(notice.textContent).toContain('uses a market-rent or full market-leasing override');
  });

  it('M8: leaves Renewal Probability available under a scalar rent override', async () => {
    const user = await openRisk(SCALAR_RENT_SUITES);

    await user.selectOptions(control('lease-level-one-way-assumption'), 'renewal_probability');

    // The two rules are different, and a scalar suite rent is not the one that
    // shadows renewal probability.
    expect(within(panel('one-way')).queryByRole('note')).toBeNull();
    const option = Array.from(
      (control('lease-level-one-way-assumption') as HTMLSelectElement).options,
    ).find((entry) => entry.value === 'renewal_probability');
    expect(option?.textContent).toBe('Renewal Probability');
  });

  it('M9: says Renewal Probability is unavailable under a full suite override', async () => {
    const user = await openRisk(FULL_OVERRIDE_SUITES);

    await user.selectOptions(control('lease-level-one-way-assumption'), 'renewal_probability');

    const notice = within(panel('one-way')).getByRole('note');
    expect(notice.textContent).toContain('Unavailable for property-wide sensitivity');
    expect(notice.textContent).toContain('uses full market-leasing override');
  });

  it('marks a shadowed target in the option list itself', async () => {
    await openRisk(FULL_OVERRIDE_SUITES);

    const labels = new Map(
      Array.from((control('lease-level-one-way-assumption') as HTMLSelectElement).options).map(
        (option) => [option.value, option.textContent],
      ),
    );
    expect(labels.get('market_rent_psf')).toBe('Market Rent / SF — unavailable (suite overrides)');
    expect(labels.get('renewal_probability')).toBe(
      'Renewal Probability — unavailable (suite overrides)',
    );
    // The targets no suite override can reach are untouched.
    expect(labels.get('expense_growth')).toBe('Expense Growth');
    expect(labels.get('exit_cap_rate')).toBe('Exit Cap Rate');
  });

  it('still lets the backend be the authority on a shadowed run', async () => {
    const user = await openRisk(FULL_OVERRIDE_SUITES);
    mockOneWay.mockRejectedValue(refusal(SHADOW_REFUSAL));

    await user.selectOptions(control('lease-level-one-way-assumption'), 'market_rent_psf');
    await enterCandidates(user, panel('one-way'), 'Market Rent / SF candidate value', ['36']);
    await runIn(user, panel('one-way'));

    await waitFor(() => expect(mockOneWay).toHaveBeenCalledTimes(1));
    expect((await within(panel('one-way')).findByRole('alert')).textContent).toContain(
      'SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE',
    );
  });

  it('shadows neither operating target, on any suite shape', async () => {
    const user = await openRisk(FULL_OVERRIDE_SUITES);

    for (const target of ['expense_growth', 'recoverable_expense_ratio', 'purchase_price']) {
      await user.selectOptions(control('lease-level-one-way-assumption'), target);
      expect(within(panel('one-way')).queryByRole('note'), `${target} was refused`).toBeNull();
    }
  });
});

// =============================================================================
// 7. Two-way
// =============================================================================

describe('two-way sensitivity', () => {
  async function runGrid(user: ReturnType<typeof userEvent.setup>) {
    await showTwoWay(user);
    await enterCandidates(user, panel('two-way'), 'Row Exit Cap Rate candidate value', [
      '6',
      '6.5',
    ]);
    await enterCandidates(user, panel('two-way'), 'Column Purchase Price candidate value', [
      '40000000',
      '42500000',
      '45000000',
    ]);
    await runIn(user, panel('two-way'));
  }

  it('M13: submits rows as rows and columns as columns', async () => {
    const user = await openRisk();
    mockTwoWay.mockResolvedValue(twoWayResult());

    await runGrid(user);

    await waitFor(() => expect(mockTwoWay).toHaveBeenCalledTimes(1));
    const controls = mockTwoWay.mock.calls[0][2];
    expect(controls.row_assumption).toBe('exit_cap_rate');
    expect(controls.row_values).toEqual([0.06, 0.065]);
    expect(controls.column_assumption).toBe('purchase_price');
    expect(controls.column_values).toEqual([40_000_000, 42_500_000, 45_000_000]);
    expect(controls.metric).toBe('levered_irr');
  });

  it('M13: renders the matrix in the response’s orientation', async () => {
    const user = await openRisk();
    mockTwoWay.mockResolvedValue(twoWayResult());

    await runGrid(user);

    const table = await within(panel('two-way')).findByRole('table');
    const headers = within(table)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent);
    expect(headers.slice(1)).toEqual(['$40,000,000', '$42,500,000', '$45,000,000']);

    const bodyRows = within(table).getAllByRole('row').slice(1);
    expect(bodyRows.map((row) => within(row).getByRole('rowheader').textContent)).toEqual([
      '6.00%',
      '6.50%',
    ]);
    // matrix[row][column], cell for cell.
    expect(
      bodyRows.map((row) =>
        within(row)
          .getAllByRole('cell')
          .map((cell) => cell.textContent),
      ),
    ).toEqual([
      ['18.10%', '16.20%', '14.50%'],
      ['15.20%', '13.40%', '11.80%'],
    ]);
  });

  it('renders exactly the dimensions the response carries', async () => {
    const user = await openRisk();
    mockTwoWay.mockResolvedValue(twoWayResult());

    await runGrid(user);

    const table = await within(panel('two-way')).findByRole('table');
    const bodyRows = within(table).getAllByRole('row').slice(1);
    expect(bodyRows).toHaveLength(2);
    for (const row of bodyRows) {
      expect(within(row).getAllByRole('cell')).toHaveLength(3);
    }
  });

  it('M11: shows an undefined cell as N/A', async () => {
    const user = await openRisk();
    mockTwoWay.mockResolvedValue(
      twoWayResult({
        matrix: [
          [0.181, null, 0.145],
          [0.152, 0.134, 0.118],
        ],
      }),
    );

    await runGrid(user);

    const table = await within(panel('two-way')).findByRole('table');
    const firstRow = within(table).getAllByRole('row')[1];
    expect(within(firstRow).getAllByRole('cell').map((cell) => cell.textContent)).toEqual([
      '18.10%',
      'N/A',
      '14.50%',
    ]);
  });

  it('M10: fails the whole grid rather than part of it', async () => {
    const user = await openRisk();
    mockTwoWay.mockRejectedValue(exitNoiRefusal());

    await runGrid(user);

    expect((await within(panel('two-way')).findByRole('alert')).textContent).toContain(
      'NON_POSITIVE_FORWARD_EXIT_NOI',
    );
    expect(within(panel('two-way')).queryByRole('table')).toBeNull();
  });

  it('refuses a shadowed row target and a shadowed column target alike', async () => {
    const user = await openRisk(FULL_OVERRIDE_SUITES);
    mockTwoWay.mockRejectedValue(refusal(SHADOW_REFUSAL));

    await showTwoWay(user);
    await user.selectOptions(control('lease-level-two-way-row-assumption'), 'market_rent_psf');
    const notes = within(panel('two-way')).getAllByRole('note');
    expect(notes[0].textContent).toContain('Unavailable for property-wide sensitivity');

    await user.selectOptions(
      control('lease-level-two-way-column-assumption'),
      'renewal_probability',
    );
    expect(within(panel('two-way')).getAllByRole('note')).toHaveLength(2);

    await enterCandidates(user, panel('two-way'), 'Row Market Rent / SF candidate value', ['36']);
    await enterCandidates(user, panel('two-way'), 'Column Renewal Probability candidate value', [
      '65',
    ]);
    await runIn(user, panel('two-way'));

    expect((await within(panel('two-way')).findByRole('alert')).textContent).toContain(
      'SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE',
    );
  });

  it('names the baseline the response identifies', async () => {
    const user = await openRisk();
    mockTwoWay.mockResolvedValue(twoWayResult());

    await runGrid(user);

    const line = await within(panel('two-way')).findByText(/^Baseline:/);
    expect(line.textContent).toContain('Exit Cap Rate 6.25%');
    expect(line.textContent).toContain('Purchase Price $42,500,000');
    expect(line.textContent).toContain('Levered IRR 14.20%');
  });
});

// =============================================================================
// 8. The ladder
// =============================================================================

describe('the candidate ladder', () => {
  it('M5: writes visible, absolute values into the editable fields', async () => {
    const user = await openRisk();

    await user.type(control('lease-level-one-way-ladder-center'), '6.5');
    await user.type(control('lease-level-one-way-ladder-step'), '0.25');
    await user.click(within(panel('one-way')).getByRole('button', { name: 'Fill Values' }));

    const fields = within(panel('one-way')).getAllByLabelText(
      /^Exit Cap Rate candidate value \d+$/,
    ) as HTMLInputElement[];
    expect(fields.map((field) => field.value)).toEqual(['6', '6.25', '6.5', '6.75', '7']);
  });

  it('M6: sends the edited values, not the generated ones', async () => {
    const user = await openRisk();
    mockOneWay.mockResolvedValue(oneWayResult());

    await user.type(control('lease-level-one-way-ladder-center'), '6.5');
    await user.type(control('lease-level-one-way-ladder-step'), '0.25');
    await user.click(within(panel('one-way')).getByRole('button', { name: 'Fill Values' }));

    const fields = within(panel('one-way')).getAllByLabelText(
      /^Exit Cap Rate candidate value \d+$/,
    ) as HTMLInputElement[];
    await user.clear(fields[0]);
    await user.type(fields[0], '5.25');
    await user.click(
      within(panel('one-way')).getByRole('button', { name: 'Remove Exit Cap Rate candidate value 5' }),
    );

    await runIn(user, panel('one-way'));

    await waitFor(() => expect(mockOneWay).toHaveBeenCalledTimes(1));
    // The edit and the deletion both survive; the ladder is not re-derived.
    expect(mockOneWay.mock.calls[0][2].values).toEqual([0.0525, 0.0625, 0.065, 0.0675]);
  });

  it('M4: generates absolute values, never a shock around the baseline', () => {
    // The generator knows nothing about the deal: same inputs, same output,
    // whatever the baseline exit cap happens to be.
    expect(generateLadderValues(6.5, 0.25, 5)).toEqual(['6', '6.25', '6.5', '6.75', '7']);
    expect(generateLadderValues(30_000_000, 1_000_000, 3)).toEqual([
      '29000000',
      '30000000',
      '31000000',
    ]);
    // A degenerate control populates nothing rather than something arbitrary.
    expect(generateLadderValues(Number.NaN, 0.25, 5)).toEqual([]);
    expect(generateLadderValues(6.5, 0.25, 0)).toEqual([]);
    expect(generateLadderValues(6.5, 0.25, 2.5)).toEqual([]);
  });

  it('keeps both axes when a two-way grid is filled in one turn', async () => {
    // Found in the browser. Both Fill buttons pressed inside one React batch
    // used to read the same configuration, so the second axis discarded the
    // first. The configuration setter takes an updater, so each change applies
    // to whatever the configuration actually is at that moment.
    const user = await openRisk();
    await showTwoWay(user);

    const set = (id: string, value: string) => {
      const element = control(id) as HTMLInputElement;
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        'value',
      )!.set!;
      setter.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
    };
    set('lease-level-two-way-row-ladder-center', '6.25');
    set('lease-level-two-way-row-ladder-step', '0.25');
    set('lease-level-two-way-column-ladder-center', '78000000');
    set('lease-level-two-way-column-ladder-step', '3000000');

    const fills = within(panel('two-way')).getAllByRole('button', { name: 'Fill Values' });
    // One turn, both presses -- exactly what the browser did.
    fills[0].click();
    fills[1].click();

    await waitFor(() => {
      expect(
        within(panel('two-way')).getAllByLabelText(/^Row Exit Cap Rate candidate value \d+$/),
      ).toHaveLength(5);
    });
    expect(
      within(panel('two-way')).getAllByLabelText(/^Column Purchase Price candidate value \d+$/),
    ).toHaveLength(5);
  });

  it('does not hide its values behind a summary control', async () => {
    const user = await openRisk();

    await user.type(control('lease-level-one-way-ladder-center'), '6.5');
    await user.type(control('lease-level-one-way-ladder-step'), '0.25');
    await user.click(within(panel('one-way')).getByRole('button', { name: 'Fill Values' }));

    const text = panel('one-way').textContent ?? '';
    for (const shorthand of ['±10%', 'Low / Base / High', '5 steps']) {
      expect(text).not.toContain(shorthand);
    }
    expect(
      within(panel('one-way')).getAllByLabelText(/^Exit Cap Rate candidate value \d+$/),
    ).toHaveLength(5);
  });
});

// =============================================================================
// 9. State: transient, and nobody else's business
// =============================================================================

describe('sensitivity state', () => {
  it('M15: configuring a sensitivity does not dirty the deal', async () => {
    const user = await openRisk();

    expect(saveStatusText()).toMatch(/^Saved/);

    await user.selectOptions(control('lease-level-one-way-metric'), 'equity_multiple');
    await user.selectOptions(control('lease-level-one-way-assumption'), 'ltv');
    await enterCandidates(user, panel('one-way'), 'LTV candidate value', ['55', '65']);
    await user.type(control('lease-level-one-way-ladder-center'), '60');
    await showTwoWay(user);

    // A question about the deal is not a change to it.
    expect(saveStatusText()).toMatch(/^Saved/);
    expect(saveStatusText()).not.toContain('Unsaved');
  });

  it('an underwriting edit still dirties the deal', async () => {
    const user = await openRisk();

    await user.click(screen.getByRole('tab', { name: 'Underwrite' }));
    const purchasePrice = document.getElementById(
      'lease-level-terms-purchasePrice',
    ) as HTMLInputElement;
    await user.clear(purchasePrice);
    await user.type(purchasePrice, '44000000');

    expect(saveStatusText()).toContain('Unsaved changes');
  });

  it('M16: persists nothing about a sensitivity', async () => {
    const user = await openRisk();
    mockOneWay.mockResolvedValue(oneWayResult());
    mockUpdate.mockResolvedValue(savedDeal());

    await enterCandidates(user, panel('one-way'), 'Exit Cap Rate candidate value', ['6', '6.5']);
    await runIn(user, panel('one-way'));
    await waitFor(() => expect(mockOneWay).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole('button', { name: /(Save|Update) Deal/i }));
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));

    const saved = JSON.stringify(mockUpdate.mock.calls[0]);
    for (const leaked of [
      'sensitivity',
      'assumption_values',
      'row_values',
      'column_values',
      'metric_values',
      'ladder',
    ]) {
      expect(saved, `the save payload carries ${leaked}`).not.toContain(leaked);
    }
  });

  it('keeps a configuration across a trip to Underwrite and back', async () => {
    const user = await openRisk();

    await user.selectOptions(control('lease-level-one-way-assumption'), 'ltv');
    await enterCandidates(user, panel('one-way'), 'LTV candidate value', ['55']);

    await user.click(screen.getByRole('tab', { name: 'Underwrite' }));
    await user.click(screen.getByRole('tab', { name: 'Risk' }));

    expect((control('lease-level-one-way-assumption') as HTMLSelectElement).value).toBe('ltv');
    expect(
      (
        within(panel('one-way')).getByLabelText('LTV candidate value 1') as HTMLInputElement
      ).value,
    ).toBe('55');
  });
});

// =============================================================================
// 10. Call count, limits and neighbouring modes
// =============================================================================

describe('what this workspace deliberately does not do', () => {
  it('M20: makes one API call per run, with no cache and no batching', async () => {
    const user = await openRisk();
    mockOneWay.mockResolvedValue(oneWayResult());

    await enterCandidates(user, panel('one-way'), 'Exit Cap Rate candidate value', ['6']);
    await runIn(user, panel('one-way'));
    await waitFor(() => expect(mockOneWay).toHaveBeenCalledTimes(1));

    // The identical run again is sent again. Nothing is remembered, so the
    // backend's `1 + N` re-underwrites happen every time it is asked.
    await runIn(user, panel('one-way'));
    await waitFor(() => expect(mockOneWay).toHaveBeenCalledTimes(2));
  });

  it('M19: imposes no grid limit', async () => {
    const user = await openRisk();
    mockTwoWay.mockResolvedValue(twoWayResult());

    await showTwoWay(user);
    await user.type(control('lease-level-two-way-row-ladder-center'), '6.5');
    await user.type(control('lease-level-two-way-row-ladder-step'), '0.1');
    await user.clear(control('lease-level-two-way-row-ladder-count'));
    await user.type(control('lease-level-two-way-row-ladder-count'), '9');
    await user.click(
      within(panel('two-way')).getAllByRole('button', { name: 'Fill Values' })[0],
    );

    expect(
      within(panel('two-way')).getAllByLabelText(/^Row Exit Cap Rate candidate value \d+$/),
    ).toHaveLength(9);

    await enterCandidates(user, panel('two-way'), 'Column Purchase Price candidate value', [
      '40000000',
      '42500000',
      '45000000',
      '47500000',
      '50000000',
      '52500000',
      '55000000',
    ]);
    await runIn(user, panel('two-way'));

    await waitFor(() => expect(mockTwoWay).toHaveBeenCalledTimes(1));
    // 9 x 7 = 63 cells. Nothing capped, truncated or warned about.
    expect(mockTwoWay.mock.calls[0][2].row_values).toHaveLength(9);
    expect(mockTwoWay.mock.calls[0][2].column_values).toHaveLength(7);
  });

  it('M17/M18: leaves Quick and Detailed Risk exactly as they were', async () => {
    const user = userEvent.setup();
    mockListDeals.mockResolvedValue([]);
    render(<App />);

    await user.click(screen.getByRole('tab', { name: 'Risk' }));
    // Quick's Risk is untouched: it still waits for an analysis and then shows
    // its own preset views. The Lease-Level builder is nowhere near it.
    expect(screen.getByText('Analyze the deal to view risk analysis.')).toBeTruthy();
    expect(screen.queryByRole('tablist', { name: 'Lease-Level sensitivity views' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Run Sensitivity' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Add Value' })).toBeNull();
  });
});

// =============================================================================
// 11. The published vocabulary matches the backend's
// =============================================================================

describe('the target and metric tables', () => {
  it('publishes exactly the eight D4.6B targets, in the runner’s order', () => {
    expect(LEASE_LEVEL_SENSITIVITY_TARGETS.map((target) => target.id)).toEqual([
      'purchase_price',
      'exit_cap_rate',
      'ltv',
      'interest_rate',
      'market_rent_psf',
      'renewal_probability',
      'expense_growth',
      'recoverable_expense_ratio',
    ]);
  });

  it('encodes the two shadow rules asymmetrically, as the runner does', () => {
    const rules = new Map(
      LEASE_LEVEL_SENSITIVITY_TARGETS.map((target) => [target.id, target.shadowRule]),
    );
    expect(rules.get('market_rent_psf')).toBe('rent_or_full_override');
    expect(rules.get('renewal_probability')).toBe('full_override_only');
    for (const unreachable of [
      'purchase_price',
      'exit_cap_rate',
      'ltv',
      'interest_rate',
      'expense_growth',
      'recoverable_expense_ratio',
    ] as const) {
      expect(rules.get(unreachable), `${unreachable} claims a shadow rule`).toBeNull();
    }
  });

  it('publishes exactly the five shipped metrics', () => {
    expect(LEASE_LEVEL_SENSITIVITY_METRICS.map((metric) => metric.id)).toEqual([
      'levered_irr',
      'unlevered_irr',
      'equity_multiple',
      'headline_dscr',
      'exit_value',
    ]);
  });
});


// =============================================================================
// 12. D5.7A -- baseline stated once, axes stated directionally
//
// Presentation only. Every figure in this section is still the response's, and
// each test is written so that the mutation it names fails it.
// =============================================================================

describe('D5.7A: the one-way baseline is stated once', () => {
  /** The one-way panel's baseline context line. */
  function baselineLines(): HTMLElement[] {
    return within(panel('one-way')).queryAllByText(/^Baseline:/);
  }

  /** The candidate rows, header excluded. */
  function candidateRows(): HTMLElement[] {
    return within(within(panel('one-way')).getByRole('table'))
      .getAllByRole('row')
      .slice(1);
  }

  async function runSeries(values: string[]) {
    const user = await openRisk();
    await enterCandidates(user, panel('one-way'), 'Exit Cap Rate candidate value', values);
    await runIn(user, panel('one-way'));
    await within(panel('one-way')).findByRole('table');
  }

  it('M1: states the baseline once, above the table, and adds no baseline row', async () => {
    mockOneWay.mockResolvedValue(
      oneWayResult({
        metric: 'equity_multiple',
        baseline_assumption_value: 0.0625,
        baseline_metric_value: 2.52,
        assumption_values: [0.0575, 0.06, 0.0625, 0.065, 0.0675],
        metric_values: [2.8, 2.66, 2.52, 2.4, 2.29],
      }),
    );
    await runSeries(['5.75', '6', '6.25', '6.5', '6.75']);

    // Exactly one baseline statement in the whole panel.
    const lines = baselineLines();
    expect(lines).toHaveLength(1);
    expect(lines[0].textContent).toBe('Baseline: Exit Cap Rate 6.25% · Equity Multiple 2.52x');

    // And it is above the table, not inside it.
    const table = within(panel('one-way')).getByRole('table');
    expect(within(table).queryAllByText(/^Baseline:/)).toHaveLength(0);
    expect(
      lines[0].compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    // Five candidates in, five rows out: no sixth, synthetic, baseline row.
    expect(candidateRows()).toHaveLength(5);
  });

  it('M2/M3/M7: keeps the candidate series whole, once each, in response order', async () => {
    mockOneWay.mockResolvedValue(
      oneWayResult({
        metric: 'equity_multiple',
        baseline_assumption_value: 0.0625,
        baseline_metric_value: 2.52,
        assumption_values: [0.0575, 0.06, 0.0625, 0.065, 0.0675],
        metric_values: [2.8, 2.66, 2.52, 2.4, 2.29],
      }),
    );
    await runSeries(['5.75', '6', '6.25', '6.5', '6.75']);

    // The baseline candidate is neither dropped nor duplicated, and nothing is
    // sorted by value or by performance.
    expect(candidateRows().map((row) => within(row).getByRole('rowheader').textContent)).toEqual([
      '5.75%',
      '6.00%',
      '6.25%',
      '6.50%',
      '6.75%',
    ]);
    expect(candidateRows().map((row) => within(row).getAllByRole('cell')[0].textContent)).toEqual([
      '2.80x',
      '2.66x',
      '2.52x Base',
      '2.40x',
      '2.29x',
    ]);
  });

  it('marks the exact baseline candidate Base and no other', async () => {
    mockOneWay.mockResolvedValue(
      oneWayResult({
        metric: 'equity_multiple',
        baseline_assumption_value: 0.0625,
        baseline_metric_value: 2.52,
        assumption_values: [0.0575, 0.06, 0.0625, 0.065, 0.0675],
        metric_values: [2.8, 2.66, 2.52, 2.4, 2.29],
      }),
    );
    await runSeries(['5.75', '6', '6.25', '6.5', '6.75']);

    const marked = candidateRows().filter((row) => (row.textContent ?? '').includes('Base'));
    expect(marked).toHaveLength(1);
    expect(within(marked[0]).getByRole('rowheader').textContent).toBe('6.25%');
  });

  it('M4: marks no candidate when none equals the baseline exactly', async () => {
    mockOneWay.mockResolvedValue(
      oneWayResult({
        baseline_assumption_value: 0.0625,
        baseline_metric_value: 0.142,
        // Two candidates straddle the baseline; neither is it.
        assumption_values: [0.062, 0.063],
        metric_values: [0.1431, 0.1409],
      }),
    );
    await runSeries(['6.2', '6.3']);

    // The context line still names the baseline the response gave.
    expect(baselineLines()[0].textContent).toBe(
      'Baseline: Exit Cap Rate 6.25% · Levered IRR 14.20%',
    );
    // But nothing nearby is promoted into standing for it.
    expect(candidateRows().filter((row) => (row.textContent ?? '').includes('Base'))).toHaveLength(
      0,
    );
    expect(candidateRows()).toHaveLength(2);
  });

  it('M5: reads the baseline metric from the response, never from the candidates', async () => {
    mockOneWay.mockResolvedValue(
      oneWayResult({
        baseline_assumption_value: 0.0625,
        // Deliberately not the mean, the median, the midpoint or any candidate.
        baseline_metric_value: 0.0777,
        assumption_values: [0.06, 0.0625, 0.065],
        metric_values: [0.155, 0.128, 0.101],
      }),
    );
    await runSeries(['6', '6.25', '6.5']);

    expect(baselineLines()[0].textContent).toBe(
      'Baseline: Exit Cap Rate 6.25% · Levered IRR 7.77%',
    );
    // The baseline candidate keeps its own metric: the context line did not
    // overwrite the row, and the row did not overwrite the context line.
    expect(candidateRows()[1].textContent).toContain('12.80%');
  });

  it('M6: shows an undefined baseline metric as N/A, never as zero', async () => {
    mockOneWay.mockResolvedValue(
      oneWayResult({
        baseline_assumption_value: 0.0625,
        baseline_metric_value: null,
        assumption_values: [0.06, 0.0625],
        metric_values: [0.155, 0.128],
      }),
    );
    await runSeries(['6', '6.25']);

    const line = baselineLines()[0].textContent ?? '';
    expect(line).toBe('Baseline: Exit Cap Rate 6.25% · Levered IRR N/A');
    expect(line).not.toContain('0.00%');
    expect(line).not.toContain('0.00x');
  });

  it('sends the same request it always did', async () => {
    mockOneWay.mockResolvedValue(oneWayResult());
    await runSeries(['5.75', '6.25', '6.75']);

    await waitFor(() => expect(mockOneWay).toHaveBeenCalledTimes(1));
    // Nothing about the new presentation reached the wire: no baseline flag, no
    // request for a baseline scenario, no extra candidate.
    expect(mockOneWay.mock.calls[0][2]).toEqual({
      assumption: 'exit_cap_rate',
      metric: 'levered_irr',
      values: [0.0575, 0.0625, 0.0675],
    });
  });
});

describe('D5.7A: the two-way corner names each axis and its direction', () => {
  async function runDefaultGrid(user: ReturnType<typeof userEvent.setup>) {
    await showTwoWay(user);
    await enterCandidates(user, panel('two-way'), 'Row Exit Cap Rate candidate value', [
      '6',
      '6.5',
    ]);
    await enterCandidates(user, panel('two-way'), 'Column Purchase Price candidate value', [
      '40000000',
      '42500000',
      '45000000',
    ]);
    await runIn(user, panel('two-way'));
    await within(panel('two-way')).findByRole('table');
  }

  /** The matrix's upper-left header cell. */
  function corner(): HTMLElement {
    const table = within(panel('two-way')).getByRole('table');
    return within(table).getAllByRole('columnheader')[0];
  }

  /** Its two lines, top to bottom. */
  function cornerLines(): string[] {
    return Array.from(corner().querySelectorAll('.sensitivity-axis-line')).map((line) =>
      (line.textContent ?? '').trim(),
    );
  }

  it('M8/M9: puts the column assumption first with a right arrow, the row assumption below with a down arrow', async () => {
    const user = await openRisk();
    mockTwoWay.mockResolvedValue(twoWayResult());

    await runDefaultGrid(user);

    const [first, second] = cornerLines();
    // Column above row -- the approved order -- and each arrow on its own axis.
    expect(first).toContain('Purchase Price');
    expect(first).toContain('→');
    expect(first).not.toContain('↓');
    expect(second).toContain('Exit Cap Rate');
    expect(second).toContain('↓');
    expect(second).not.toContain('→');
    expect(first).not.toContain('Exit Cap Rate');
    expect(second).not.toContain('Purchase Price');
  });

  it('M14: says which axis is which in words, not by arrow alone', async () => {
    const user = await openRisk();
    mockTwoWay.mockResolvedValue(twoWayResult());

    await runDefaultGrid(user);

    const [first, second] = cornerLines();
    expect(first).toContain('Column assumption: Purchase Price');
    expect(second).toContain('Row assumption: Exit Cap Rate');
    // The arrows are decoration on top of that, and are hidden from assistive
    // technology so they are never read as content.
    const arrows = Array.from(corner().querySelectorAll('.sensitivity-axis-arrow'));
    expect(arrows).toHaveLength(2);
    for (const arrow of arrows) {
      expect(arrow.getAttribute('aria-hidden')).toBe('true');
    }
  });

  it('M10: takes both labels from the response, for any pair of axes', async () => {
    const user = await openRisk();
    mockTwoWay.mockResolvedValue(
      twoWayResult({
        row_assumption: 'renewal_probability',
        column_assumption: 'market_rent_psf',
        baseline_row_value: 0.7,
        baseline_column_value: 34,
        row_values: [0.65, 0.75],
        column_values: [32, 34, 36],
      }),
    );

    await showTwoWay(user);
    await user.selectOptions(control('lease-level-two-way-row-assumption'), 'renewal_probability');
    await user.selectOptions(control('lease-level-two-way-column-assumption'), 'market_rent_psf');
    await enterCandidates(user, panel('two-way'), 'Row Renewal Probability candidate value', [
      '65',
      '75',
    ]);
    await enterCandidates(user, panel('two-way'), 'Column Market Rent / SF candidate value', [
      '32',
      '34',
      '36',
    ]);
    await runIn(user, panel('two-way'));
    await within(panel('two-way')).findByRole('table');

    const [first, second] = cornerLines();
    expect(first).toBe('Column assumption: Market Rent / SF →');
    expect(second).toBe('Row assumption: Renewal Probability ↓');
    // Nothing is left over from the default pair.
    expect(corner().textContent).not.toContain('Purchase Price');
    expect(corner().textContent).not.toContain('Exit Cap Rate');
  });

  it('M11/M12/M13: leaves the matrix, its baseline cell and its values alone', async () => {
    const user = await openRisk();
    mockTwoWay.mockResolvedValue(twoWayResult({ baseline_row_value: 0.065 }));

    await runDefaultGrid(user);

    const table = within(panel('two-way')).getByRole('table');
    // Column values are still the columns...
    expect(
      within(table)
        .getAllByRole('columnheader')
        .slice(1)
        .map((cell) => cell.textContent),
    ).toEqual(['$40,000,000', '$42,500,000', '$45,000,000']);
    // ...and row values are still the rows.
    const bodyRows = within(table).getAllByRole('row').slice(1);
    expect(bodyRows.map((row) => within(row).getByRole('rowheader').textContent)).toEqual([
      '6.00%',
      '6.50%',
    ]);
    // Cell for cell, matrix[row][column] as the response sent it.
    expect(
      bodyRows.map((row) =>
        within(row)
          .getAllByRole('cell')
          .map((cell) => cell.textContent),
      ),
    ).toEqual([
      ['18.10%', '16.20%', '14.50%'],
      ['15.20%', '13.40% (Base)', '11.80%'],
    ]);
    // The baseline sits at 6.50% x $42,500,000 -- the response's own
    // intersection -- and nowhere else.
    const marked = bodyRows.flatMap((row) =>
      within(row)
        .getAllByRole('cell')
        .filter((cell) => (cell.textContent ?? '').includes('(Base)')),
    );
    expect(marked).toHaveLength(1);
    expect(marked[0].textContent).toContain('13.40%');
  });

  it('keeps the baseline context line and the caption it already had', async () => {
    const user = await openRisk();
    mockTwoWay.mockResolvedValue(twoWayResult());

    await runDefaultGrid(user);

    const line = within(panel('two-way')).getByText(/^Baseline:/);
    expect(line.textContent).toBe(
      'Baseline: Exit Cap Rate 6.25%, Purchase Price $42,500,000, Levered IRR 14.20%',
    );
    // The caption still describes the orientation the same way round.
    expect(
      within(panel('two-way')).getByText(
        'Levered IRR: Exit Cap Rate (rows) × Purchase Price (columns)',
      ),
    ).toBeTruthy();
  });
});
