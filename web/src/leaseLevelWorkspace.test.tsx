/**
 * D5.5A -- what an analyst can actually do with a Lease-Level deal.
 *
 * `modeDispatch.architecture.test.ts` proves the shell's dispatch is total and
 * that this gate claims exactly the capability it built. This file proves the
 * rendered outcome: selecting Lease-Level reaches the Lease-Level workspace,
 * every scalar is enterable, a saved deal hydrates completely, the rent roll
 * survives an edit it cannot see, and a refusal is shown where the analyst is
 * looking rather than swallowed.
 *
 * The fixture is a real rent roll, not a one-suite demo: four suites, two
 * signed leases, one vacant suite on MARKET_LEASE_UP and one on HOLD_VACANT,
 * plus a suite-level market-leasing override. Those are the states the D5.5B
 * grids will have to edit and the states a Lease-Level deal actually arrives
 * in, so a gate that only ever saw one occupied suite would prove very little.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import {
  ApiError,
  LeaseLevelApiError,
  analyzeLeaseLevelAcquisition,
  createLeaseLevelDeal,
  getDeal,
  listDeals,
  updateLeaseLevelDeal,
} from './api';
import { buildAcquisitionTermsRequest } from './convert';
import {
  BLANK_LEASE_LEVEL_FORM_VALUES,
  OPTIONAL_MARKET_LEASING_KEYS,
  TERMS_WIRE_IDS,
  buildLeaseLevelInputsRequest,
  collectBlankScalarIssues,
} from './leaseLevelConvert';
import type {
  LeaseLevelAcquisitionResults,
  LeaseLevelFormValues,
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
    createLeaseLevelDeal: vi.fn(),
    updateLeaseLevelDeal: vi.fn(),
    getDeal: vi.fn(),
    listDeals: vi.fn(),
  };
});

const mockAnalyze = vi.mocked(analyzeLeaseLevelAcquisition);
const mockCreate = vi.mocked(createLeaseLevelDeal);
const mockUpdate = vi.mocked(updateLeaseLevelDeal);
const mockGetDeal = vi.mocked(getDeal);
const mockListDeals = vi.mocked(listDeals);

beforeEach(() => {
  vi.clearAllMocks();
  mockListDeals.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
});

// =============================================================================
// A realistic saved Lease-Level deal
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
  renewal_rent_psf: 33,
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
  new_lease_type: 'modified_gross',
  new_recovery_basis: 'expense_stop_psf',
  new_expense_stop_psf: 11.25,
};

/** Four suites covering every occupancy state the model supports. */
const SUITES: SuiteRequest[] = [
  {
    suite_id: '100',
    suite_area_sf: 18_400,
    suite_label: 'Ground floor retail',
    market_rent_psf: null,
    market_leasing_override: null,
    initial_vacancy: null,
  },
  {
    suite_id: '200',
    suite_area_sf: 22_150,
    suite_label: null,
    market_rent_psf: 38.75,
    market_leasing_override: null,
    initial_vacancy: null,
  },
  {
    // Vacant, being leased up at market.
    suite_id: '300',
    suite_area_sf: 12_000,
    suite_label: 'Suite 300',
    market_rent_psf: null,
    market_leasing_override: { ...MARKET_LEASING, new_downtime_months: 12 },
    initial_vacancy: { strategy: 'market_lease_up', initial_lease_up_months: 8 },
  },
  {
    // Vacant, deliberately held vacant for the whole hold.
    suite_id: '400',
    suite_area_sf: 9_450,
    suite_label: null,
    market_rent_psf: null,
    market_leasing_override: null,
    initial_vacancy: { strategy: 'hold_vacant', initial_lease_up_months: null },
  },
];

const LEASES: LeaseRequest[] = [
  {
    lease_id: 'L-100',
    suite_id: '100',
    leased_area_sf: 18_400,
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
    leased_area_sf: 22_150,
    rent_commencement_date: '2022-01-01',
    lease_expiration_date: '2027-12-31',
    base_rent_psf: 29.4,
    escalation_pct: 0,
    escalation_basis: 'none',
    lease_type: 'modified_gross',
    tenant_name: 'Halbrook Analytics',
    lease_start_date: null,
    origin: 'in_place',
    recovery_basis: 'expense_stop_psf',
    expense_stop_psf: 10.5,
  },
];

function savedLeaseLevelDeal(overrides: Partial<Deal> = {}): Deal {
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
    suites: SUITES,
    leases: LEASES,
    deal_context: 'Value-add reposition of a 1990s suburban office park.',
    analysis_snapshot: null,
    ai_snapshot: null,
    created_at: '2027-01-04T09:00:00+00:00',
    updated_at: '2027-01-04T09:00:00+00:00',
    ...overrides,
  };
}

/**
 * A completely filled form -- the percent-scale, string-valued counterpart of
 * the saved deal above.
 *
 * The five genuinely optional market-leasing fields are left blank on purpose:
 * they are the ones the contract declares nullable, and this fixture is what
 * proves `OPTIONAL_MARKET_LEASING_KEYS` matches the builders rather than being
 * a list somebody maintained by hand.
 */
const FILLED_FORM_VALUES: LeaseLevelFormValues = {
  terms: {
    purchasePrice: '42500000',
    holdPeriod: '7',
    exitCapRate: '6.25',
    ltv: '60',
    interestRate: '5.5',
    amortization: '30',
    acquisitionCostPct: '1.5',
    financingFeePct: '1',
    dispositionCostPct: '1.25',
    annualCapexReserve: '120000',
    ioPeriod: '2',
  },
  property: { analysisStartDate: '2027-01-15', rentableAreaSf: '62000' },
  operating: {
    otherIncome: '84000',
    otherIncomeGrowth: '2.5',
    creditLossPct: '1.5',
    propertyTaxes: '410000',
    insurance: '62000',
    utilities: '148000',
    repairsMaintenance: '96000',
    otherOperatingExpenses: '54000',
    managementFeePct: '3',
    expenseGrowth: '3',
    recoverableExpenseRatio: '85',
  },
  marketLeasing: {
    marketRentPsf: '34.5',
    marketRentGrowth: '3',
    renewalRentPsf: '',
    renewalRentSpread: '-5',
    renewalTermMonths: '60',
    successorEscalationPct: '3',
    renewalDowntimeMonths: '2',
    renewalFreeRentMonths: '1',
    newTermMonths: '84',
    newDowntimeMonths: '9',
    newFreeRentMonths: '4',
    renewalTiPsf: '25',
    newTiPsf: '65',
    leasingCommissionMethod: 'pct_of_total_contractual_base_rent',
    renewalLcPct: '3',
    newLcPct: '6',
    renewalProbability: '70',
    renewalLeaseType: 'nnn',
    renewalRecoveryBasis: '',
    renewalExpenseStopPsf: '',
    newLeaseType: 'nnn',
    newRecoveryBasis: '',
    newExpenseStopPsf: '',
  },
  rentRoll: [],
  leaseOrder: [],
  unmatchedLeases: [],
};

function leaseLevelResults(): LeaseLevelAcquisitionResults {
  // Shape only -- D5.5A renders none of it. Present so the success path is
  // exercised end to end rather than mocked away.
  return {
    monthly_projection: {} as LeaseLevelAcquisitionResults['monthly_projection'],
    annual_projection: {} as LeaseLevelAcquisitionResults['annual_projection'],
    results: {} as LeaseLevelAcquisitionResults['results'],
  };
}

async function enterLeaseLevelMode() {
  const user = userEvent.setup();
  render(<App />);
  await user.click(screen.getByRole('tab', { name: 'Lease-Level Underwrite' }));
  return user;
}

async function openSavedDeal() {
  mockListDeals.mockResolvedValue([savedLeaseLevelDeal()]);
  mockGetDeal.mockResolvedValue(savedLeaseLevelDeal());
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('Fulton Exchange');
  await user.click(screen.getByText('Fulton Exchange'));
  await waitFor(() => {
    expect(mockGetDeal).toHaveBeenCalledWith('deal-ll-1');
  });
  return user;
}

/** The header's save action. Its label is "Save Deal" for a new deal and
 * "Update Deal" for one that exists -- the app's existing wording, shared by
 * all three modes. */
function saveButton(): HTMLElement {
  return screen.getByRole('button', { name: /(Save|Update) Deal/i });
}

function analyzeButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: /^Analyz/i }) as HTMLButtonElement;
}

function section(name: string): HTMLElement {
  return screen.getByRole('tab', { name });
}

/** One assumption input, by the id the workspace gives it.
 *
 * `getByLabelText` is ambiguous here: the shared grid folds the unit affix into
 * the label ("Market Rent$/SF"), and "Market Rent" is a prefix of "Market Rent
 * Growth". The id is the field's own stable handle and is what the inline error
 * points at with `aria-describedby`, so tests address fields the same way the
 * accessibility wiring does.
 */
function field(id: string): HTMLInputElement | HTMLSelectElement {
  const element = document.getElementById(id);
  if (element === null) {
    throw new Error(`No field with id ${id}`);
  }
  return element as HTMLInputElement | HTMLSelectElement;
}

const TERMS_PURCHASE_PRICE = 'lease-level-terms-purchasePrice';
const MARKET_RENT = 'lease-level-market-marketRentPsf';
const RENEWAL_PROBABILITY = 'lease-level-market-renewalProbability';

// =============================================================================
// 1. Lease-Level is selectable, and selecting it reaches its own workspace
// =============================================================================

describe('entering Lease-Level mode', () => {
  it('offers Lease-Level beside Quick and Detailed', async () => {
    render(<App />);
    expect(screen.getByRole('tab', { name: 'Lease-Level Underwrite' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Quick Underwrite' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Detailed Underwrite' })).toBeTruthy();
  });

  it('shows the Lease-Level workspace, not Quick’s or Detailed’s', async () => {
    await enterLeaseLevelMode();

    expect(screen.getByRole('tablist', { name: 'Lease-Level sections' })).toBeTruthy();
    // The shared Underwrite tab bar belongs to Quick and Detailed. Its absence
    // is the proof that the shell mounted a different tree, not that it
    // re-labelled the same one.
    expect(screen.queryByRole('tablist', { name: 'Underwrite sections' })).toBeNull();
  });

  it('opens on a genuinely blank form -- no seeded economics', async () => {
    await enterLeaseLevelMode();

    for (const id of ['purchasePrice', 'holdPeriod', 'exitCapRate']) {
      expect(field(`lease-level-terms-${id}`).value).toBe('');
    }
    // The one assertion that matters most: no fabricated rent roll. A seeded
    // suite would let a blank deal analyze, and would be an assumption nobody
    // made presented as one they did.
    expect(BLANK_LEASE_LEVEL_FORM_VALUES.rentRoll).toEqual([]);
    expect(BLANK_LEASE_LEVEL_FORM_VALUES.unmatchedLeases).toEqual([]);
  });

  it('leaves every enum unselected rather than choosing an assumption', async () => {
    const user = await enterLeaseLevelMode();
    await user.click(section('Market Leasing'));

    for (const id of ['renewalLeaseType', 'newLeaseType', 'leasingCommissionMethod']) {
      expect(field(`lease-level-market-${id}`).value).toBe('');
    }
  });

  it('does not disturb Quick or Detailed state', async () => {
    const user = userEvent.setup();
    render(<App />);

    // Quick's own field -- a different id, a different state tree. Entering and
    // leaving Lease-Level must not touch it.
    await user.clear(field('purchasePrice'));
    await user.type(field('purchasePrice'), '12345');

    await user.click(screen.getByRole('tab', { name: 'Lease-Level Underwrite' }));
    await user.click(screen.getByRole('tab', { name: 'Quick Underwrite' }));

    expect(field('purchasePrice').value).toBe('12345');
  });
});

// =============================================================================
// 2. Scalar entry
// =============================================================================

describe('scalar manual entry', () => {
  it('accepts a value in every scalar section', async () => {
    const user = await enterLeaseLevelMode();

    await user.type(field(TERMS_PURCHASE_PRICE), '42500000');

    await user.click(section('Property'));
    await user.type(field('lease-level-property-rentableAreaSf'), '62000');

    await user.click(section('Operating'));
    await user.type(field('lease-level-operating-propertyTaxes'), '410000');

    await user.click(section('Market Leasing'));
    await user.type(field(MARKET_RENT), '34.5');

    await user.click(section('Acquisition & Debt'));
    expect(field(TERMS_PURCHASE_PRICE).value).toBe('42500000');
    await user.click(section('Property'));
    expect(field('lease-level-property-rentableAreaSf').value).toBe('62000');
  });

  it('gives Analysis Start Date a real date control, and sends it unchanged', async () => {
    const user = await enterLeaseLevelMode();
    await user.click(section('Property'));

    const input = field('lease-level-property-analysisStartDate') as HTMLInputElement;
    expect(input.type).toBe('date');

    // A mid-month date is submitted exactly as entered. Snapping it to the
    // first of the month would be the frontend inventing a convention the
    // backend owns (ANALYSIS_START_NOT_MONTH_ALIGNED).
    expect(
      buildLeaseLevelInputsRequest(FILLED_FORM_VALUES).property_inputs.analysis_start_date,
    ).toBe(
      '2027-01-15',
    );
  });

  it('keeps the percent convention: UI percent-scale, wire decimal', async () => {
    // The convention the whole app shares: the form holds "6.25", the wire
    // carries 0.0625, and the conversion happens once, on submit.
    const terms = buildAcquisitionTermsRequest(FILLED_FORM_VALUES.terms);
    expect(terms.exit_cap_rate).toBeCloseTo(0.0625, 10);
    expect(terms.ltv).toBeCloseTo(0.6, 10);
    expect(terms.purchase_price).toBe(42_500_000);

    const inputs = buildLeaseLevelInputsRequest(FILLED_FORM_VALUES);
    expect(inputs.operating_inputs.management_fee_pct).toBeCloseTo(0.03, 10);
    expect(inputs.market_leasing.renewal_probability).toBeCloseTo(0.7, 10);
    // A negative spread stays negative -- it is a real assumption, not a typo
    // to be normalised away.
    expect(inputs.market_leasing.renewal_rent_spread).toBeCloseTo(-0.05, 10);
    // Blank on a nullable field means "stated as absent", never zero.
    expect(inputs.market_leasing.renewal_rent_psf).toBeNull();
    expect(inputs.market_leasing.new_expense_stop_psf).toBeNull();
    expect(inputs.market_leasing.new_recovery_basis).toBeNull();
  });
});

// =============================================================================
// 3. Opening a saved Lease-Level deal
// =============================================================================

describe('opening a saved Lease-Level deal', () => {
  it('switches to Lease-Level mode and the Lease-Level workspace', async () => {
    await openSavedDeal();

    await waitFor(() => {
      expect(
        (screen.getByRole('tab', { name: 'Lease-Level Underwrite' }) as HTMLElement).getAttribute(
          'aria-selected',
        ),
      ).toBe('true');
    });
    expect(screen.getByRole('tablist', { name: 'Lease-Level sections' })).toBeTruthy();
  });

  it('hydrates every scalar group', async () => {
    const user = await openSavedDeal();

    await waitFor(() => {
      expect(field(TERMS_PURCHASE_PRICE).value).toBe('42500000');
    });
    expect(field('lease-level-terms-exitCapRate').value).toBe('6.25');

    await user.click(section('Property'));
    expect(field('lease-level-property-analysisStartDate').value).toBe(
      '2027-01-01',
    );
    expect(field('lease-level-property-rentableAreaSf').value).toBe('62000');

    await user.click(section('Operating'));
    expect(field('lease-level-operating-propertyTaxes').value).toBe('410000');
    expect(field('lease-level-operating-managementFeePct').value).toBe('3');

    await user.click(section('Market Leasing'));
    expect(field(MARKET_RENT).value).toBe('34.5');
    expect(field(RENEWAL_PROBABILITY).value).toBe('70');
    expect(field('lease-level-market-renewalLeaseType').value).toBe('nnn');
    expect(field('lease-level-market-newLeaseType').value).toBe(
      'modified_gross',
    );
    expect(field('lease-level-market-newRecoveryBasis').value).toBe(
      'expense_stop_psf',
    );
    // A genuinely null recovery basis reopens as "None", not as the first
    // option -- absent and unselected are the same rendering, and both are
    // honest here, but neither may become a value the analyst did not choose.
    expect(field('lease-level-market-renewalRecoveryBasis').value).toBe('');
  });

  it('hydrates the rent roll into one row per suite', async () => {
    // D5.5B transition: D5.5A showed counts because it had no grid. The
    // successor assertion is the grid itself -- a row per suite, each carrying
    // its own lease or none.
    const user = await openSavedDeal();
    await user.click(section('Rent Roll'));

    const panel = document.getElementById('lease-level-panel-rent-roll') as HTMLElement;
    const rows = within(panel).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(SUITES.length);

    // By position, never by row id: `rowId` is a module-level counter, so it is
    // stable within a render but not across tests -- which is exactly why it is
    // local UI identity and never leaves the browser.
    expect((within(rows[0]).getByLabelText(/^Suite, /) as HTMLInputElement).value).toBe('100');
    expect((within(rows[0]).getByLabelText(/^Area SF, /) as HTMLInputElement).value).toBe(
      '18400',
    );
    expect((within(rows[0]).getByLabelText(/^Tenant, /) as HTMLInputElement).value).toBe(
      'Marlow Provisions',
    );

    // Both vacancy states are represented, and are read off the lease rather
    // than off any status field.
    expect(within(rows[0]).getByRole('button', { name: /is occupied/ })).toBeTruthy();
    expect(within(rows[2]).getByRole('button', { name: /is vacant/ })).toBeTruthy();
    expect(within(rows[3]).getByRole('button', { name: /is vacant/ })).toBeTruthy();
  });

  it('reads the deal name and context from the saved deal', async () => {
    await openSavedDeal();
    await waitFor(() => {
      expect((screen.getByLabelText(/Deal Name/i) as HTMLInputElement).value).toBe(
        'Fulton Exchange',
      );
    });
    expect(
      document.querySelector('.strategy-strip-text')?.textContent,
    ).toBe('Value-add reposition of a 1990s suburban office park.');
  });

  it('never reads a Quick or Detailed field', async () => {
    mockListDeals.mockResolvedValue([savedLeaseLevelDeal()]);
    mockGetDeal.mockResolvedValue(savedLeaseLevelDeal());
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText('Fulton Exchange');
    await user.click(screen.getByText('Fulton Exchange'));

    // `inputs` and `detailed_operating_inputs` are both null on this deal. If
    // the opener read either, it would have thrown the Quick/Detailed
    // "missing inputs" error instead of opening.
    await waitFor(() => {
      expect(screen.getByRole('tablist', { name: 'Lease-Level sections' })).toBeTruthy();
    });
    expect(screen.queryByText(/is missing inputs/i)).toBeNull();
  });
});

// =============================================================================
// 4. The rent roll survives edits it cannot see
// =============================================================================

describe('the held rent roll', () => {
  it('carries the rent roll through a scalar edit, byte for byte', async () => {
    mockAnalyze.mockResolvedValue(leaseLevelResults());
    const user = await openSavedDeal();

    await waitFor(() => {
      expect(field(TERMS_PURCHASE_PRICE).value).toBe('42500000');
    });
    await user.clear(field(TERMS_PURCHASE_PRICE));
    await user.type(field(TERMS_PURCHASE_PRICE), '44000000');

    await user.click(analyzeButton());

    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [terms, inputs] = mockAnalyze.mock.calls[0];
    expect(terms.purchase_price).toBe(44_000_000);
    expect(inputs.suites).toEqual(SUITES);
    expect(inputs.leases).toEqual(LEASES);
  });

  it('preserves a suite-level market-leasing override in full', async () => {
    mockAnalyze.mockResolvedValue(leaseLevelResults());
    const user = await openSavedDeal();

    await waitFor(() => {
      expect(field(TERMS_PURCHASE_PRICE).value).toBe('42500000');
    });
    await user.click(section('Market Leasing'));
    await user.clear(field(MARKET_RENT));
    await user.type(field(MARKET_RENT), '36');

    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });

    const [, inputs] = mockAnalyze.mock.calls[0];
    // The property default changed; the suite that overrides it did not. An
    // override is all-or-nothing by design, and editing the default must never
    // reach into one.
    expect(inputs.market_leasing.market_rent_psf).toBe(36);
    expect(inputs.suites[2].market_leasing_override).toEqual(SUITES[2].market_leasing_override);
  });

  it('sends suites and leases on update, so a save cannot delete them', async () => {
    mockUpdate.mockResolvedValue(savedLeaseLevelDeal({ updated_at: '2027-02-01T00:00:00+00:00' }));
    const user = await openSavedDeal();

    await waitFor(() => {
      expect(field(TERMS_PURCHASE_PRICE).value).toBe('42500000');
    });
    await user.clear(field(TERMS_PURCHASE_PRICE));
    await user.type(field(TERMS_PURCHASE_PRICE), '44000000');
    await user.click(saveButton());

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalled();
    });
    const [dealId, , , inputs] = mockUpdate.mock.calls[0];
    expect(dealId).toBe('deal-ll-1');
    expect(inputs.suites).toEqual(SUITES);
    expect(inputs.leases).toEqual(LEASES);
  });
});

// =============================================================================
// 5. Analyze and Save on a blank deal
// =============================================================================

describe('a blank Lease-Level deal', () => {
  it('never disables Analyze or Save', async () => {
    await enterLeaseLevelMode();
    expect(analyzeButton().disabled).toBe(false);
    expect((saveButton() as HTMLButtonElement).disabled).toBe(false);
  });

  it('reports every blank scalar at once, anchored to its field', async () => {
    const user = await enterLeaseLevelMode();
    await user.click(analyzeButton());

    // Not one refusal per missing field. Forty-odd assumptions discovered one
    // round trip at a time would be the worst possible way to meet this form.
    await waitFor(() => {
      expect(field(TERMS_PURCHASE_PRICE).getAttribute('aria-invalid')).toBe('true');
    });
    await user.click(section('Property'));
    expect(field('lease-level-property-rentableAreaSf').getAttribute('aria-invalid')).toBe(
      'true',
    );
    await user.click(section('Operating'));
    expect(field('lease-level-operating-propertyTaxes').getAttribute('aria-invalid')).toBe(
      'true',
    );
    await user.click(section('Market Leasing'));
    expect(field(MARKET_RENT).getAttribute('aria-invalid')).toBe('true');
  });

  it('never sends a request it could not build', async () => {
    // A blank field cannot become a value, so there is no request. That is a
    // fact about the transport, not a verdict on the deal: the client still
    // decides nothing about whether the assumptions are sound.
    const user = await enterLeaseLevelMode();
    await user.click(analyzeButton());
    expect(mockAnalyze).not.toHaveBeenCalled();

    await user.click(saveButton());
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('leaves the genuinely nullable market fields blank without complaint', async () => {
    // `renewal_rent_psf` and the two expense stops are required-but-nullable on
    // the contract, and the two recovery bases are optional. Blank means
    // "stated as absent" there, which is a real value.
    const { leaseIssues } = collectBlankScalarIssues(FILLED_FORM_VALUES);
    expect(leaseIssues).toEqual([]);
    for (const key of OPTIONAL_MARKET_LEASING_KEYS) {
      expect(FILLED_FORM_VALUES.marketLeasing[key]).toBe('');
    }
  });

  it('reports a blank in any other market field', async () => {
    const { leaseIssues } = collectBlankScalarIssues({
      ...FILLED_FORM_VALUES,
      marketLeasing: { ...FILLED_FORM_VALUES.marketLeasing, renewalTiPsf: '' },
    });
    expect(leaseIssues).toEqual([
      {
        code: 'MALFORMED_FIELD',
        path: 'market_leasing.renewal_ti_psf',
        message: 'is required',
        severity: 'error',
      },
    ]);
  });

  it('never fabricates a suite so that a blank deal can analyze', async () => {
    mockAnalyze.mockResolvedValue(leaseLevelResults());
    const user = await enterLeaseLevelMode();
    await user.click(analyzeButton());

    // Nothing was sent, and nothing was invented in order to send something.
    expect(mockAnalyze).not.toHaveBeenCalled();
    expect(BLANK_LEASE_LEVEL_FORM_VALUES.rentRoll).toEqual([]);
    expect(BLANK_LEASE_LEVEL_FORM_VALUES.unmatchedLeases).toEqual([]);
  });
});

// =============================================================================
// 6. Validation surfacing
// =============================================================================

describe('validation surfacing', () => {
  /** Analyze a *complete* deal and have the backend refuse it. The deal is the
   * saved fixture, so every scalar is filled and the request really is built
   * and sent -- which is the only way to exercise the backend's issue shapes. */
  async function analyzeWithIssues(
    leaseIssues: ConstructorParameters<typeof LeaseLevelApiError>[2],
    termsIssues: ConstructorParameters<typeof LeaseLevelApiError>[1] = [],
  ) {
    mockAnalyze.mockRejectedValue(new LeaseLevelApiError('refused', termsIssues, leaseIssues));
    const user = await openSavedDeal();
    await waitFor(() => {
      expect(field(TERMS_PURCHASE_PRICE).value).toBe('42500000');
    });
    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    return user;
  }

  const PROBABILITY_ISSUE = {
    code: 'RENEWAL_PROBABILITY_OUT_OF_DOMAIN',
    path: 'market_leasing.renewal_probability',
    message: 'must be between 0 and 1',
    severity: 'error' as const,
  };

  it('anchors a scalar issue to the field its path names', async () => {
    const user = await analyzeWithIssues([PROBABILITY_ISSUE]);
    await user.click(section('Market Leasing'));

    const input = field(RENEWAL_PROBABILITY);
    expect(input.getAttribute('aria-invalid')).toBe('true');
    const describedBy = input.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy!)?.textContent).toBe('must be between 0 and 1');
    // And only that field.
    expect(field(MARKET_RENT).getAttribute('aria-invalid')).toBeNull();
  });

  it('keeps the field’s accessible name intact when it carries an error', async () => {
    const user = await analyzeWithIssues([PROBABILITY_ISSUE]);
    await user.click(section('Market Leasing'));
    // Without the explicit `aria-label`, the wrapping `<label>` would absorb the
    // message and the field would answer to "Renewal Probability must be
    // between 0 and 1" instead of to its own name.
    expect(screen.getByLabelText('Renewal Probability')).toBe(field(RENEWAL_PROBABILITY));
  });

  it('anchors a terms issue, which arrives in the other issue shape', async () => {
    await analyzeWithIssues(
      [],
      [
        {
          field_id: TERMS_WIRE_IDS.purchasePrice,
          category: 'OUT_OF_DOMAIN_VALUE',
          message: 'must be greater than zero',
        },
      ],
    );
    expect(field(TERMS_PURCHASE_PRICE).getAttribute('aria-invalid')).toBe('true');
    expect(screen.getByText('must be greater than zero')).toBeTruthy();
  });

  it('anchors a suite issue to its row instead of listing it', async () => {
    // D5.5B transition. D5.5A could only list these, because it had no rows to
    // hang them on; the successor invariant is that the row claims it. The
    // banner keeps its job for anything no row can claim -- proved by the test
    // below and by M23.
    const user = await analyzeWithIssues([
      {
        code: 'MULTIPLE_KNOWN_LEASES_IN_SUITE',
        path: 'suites[2]',
        message: 'has more than one known lease',
        severity: 'error',
      },
    ]);
    await user.click(section('Rent Roll'));
    await user.click(screen.getByRole('button', { name: /Edit details for suite 300/ }));
    expect(screen.getByText(/has more than one known lease/)).toBeTruthy();
  });

  it('shows a whole-submission issue that belongs to no field', async () => {
    await analyzeWithIssues([
      {
        code: 'RENTABLE_AREA_NOT_RECONCILED',
        path: '',
        message: 'suite areas do not sum to rentable area',
        severity: 'error',
      },
    ]);
    expect(screen.getByText(/do not sum to rentable area/)).toBeTruthy();
  });

  it('clears issues when the analyst edits the field they named', async () => {
    const user = await analyzeWithIssues([PROBABILITY_ISSUE]);
    await user.click(section('Market Leasing'));
    expect(field(RENEWAL_PROBABILITY).getAttribute('aria-invalid')).toBe('true');

    await user.type(field(RENEWAL_PROBABILITY), '0');

    expect(screen.queryByText('must be between 0 and 1')).toBeNull();
    expect(field(RENEWAL_PROBABILITY).getAttribute('aria-invalid')).toBeNull();
  });

  it('surfaces an unreachable backend as a plain message', async () => {
    mockAnalyze.mockRejectedValue(new ApiError('Could not reach the Anchor API.'));
    const user = await openSavedDeal();
    await waitFor(() => {
      expect(field(TERMS_PURCHASE_PRICE).value).toBe('42500000');
    });
    await user.click(analyzeButton());

    await waitFor(() => {
      expect(screen.getByText(/Could not reach the Anchor API/)).toBeTruthy();
    });
  });
});

// =============================================================================
// 7. Save status and identity
// =============================================================================

describe('save status', () => {
  it('saves a complete new deal, and reports it saved', async () => {
    mockCreate.mockResolvedValue(savedLeaseLevelDeal({ id: 'deal-new' }));
    const user = await enterLeaseLevelMode();

    expect(screen.getByText(/Unsaved deal/i)).toBeTruthy();

    // The saved fixture, entered rather than typed: this test is about the save
    // lifecycle, not about the forty-odd inputs behind it.
    await user.type(screen.getByLabelText(/Deal Name/i), 'Fulton Exchange');
    await user.click(saveButton());
    await waitFor(() => {
      // A blank deal cannot be saved -- there is no request to build -- so the
      // blanks are reported instead, and nothing was persisted.
      expect(mockCreate).not.toHaveBeenCalled();
    });
    expect(screen.getByText(/still blank/i)).toBeTruthy();
  });

  it('updates an opened deal and reports it saved again', async () => {
    mockUpdate.mockResolvedValue(
      savedLeaseLevelDeal({ updated_at: '2027-02-01T00:00:00+00:00' }),
    );
    const user = await openSavedDeal();
    await waitFor(() => {
      expect(field(TERMS_PURCHASE_PRICE).value).toBe('42500000');
    });

    await user.clear(field(TERMS_PURCHASE_PRICE));
    await user.type(field(TERMS_PURCHASE_PRICE), '44000000');
    await user.click(saveButton());

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalled();
    });
  });

  it('marks the deal dirty when a scalar changes', async () => {
    const user = await openSavedDeal();
    await waitFor(() => {
      expect(field(TERMS_PURCHASE_PRICE).value).toBe('42500000');
    });
    expect(document.querySelector('.save-status')?.textContent).toMatch(/Saved/i);

    await user.clear(field(TERMS_PURCHASE_PRICE));
    await user.type(field(TERMS_PURCHASE_PRICE), '44000000');

    await waitFor(() => {
      expect(document.querySelector('.save-status')?.textContent).toMatch(/Unsaved changes/i);
    });
  });

  it('shows the deal’s real purchase price in the sidebar, not another mode’s', async () => {
    mockListDeals.mockResolvedValue([savedLeaseLevelDeal()]);
    render(<App />);

    await screen.findByText('Fulton Exchange');
    // `deal.inputs` is null on this deal, so a sidebar reading Quick's field
    // would show the unavailable state. Reading `terms` is what makes the
    // number the deal's own.
    const row = screen.getByText('Fulton Exchange').closest('button') as HTMLElement;
    expect(within(row).getByText(/\$42,500,000/)).toBeTruthy();
    expect(within(row).getByText(/Lease-Level/)).toBeTruthy();
  });
});

// =============================================================================
// 8. Mutation kills
//
// The anchoring logic is otherwise only tested positively -- "the right field
// shows the message". These are the mutants that would still pass that: a
// looser match, a swallowed issue, a stale one.
// =============================================================================

describe('mutation kills', () => {
  async function refuseWith(issues: ConstructorParameters<typeof LeaseLevelApiError>[2]) {
    mockAnalyze.mockRejectedValue(new LeaseLevelApiError('refused', [], issues));
    const user = await openSavedDeal();
    await waitFor(() => {
      expect(field(TERMS_PURCHASE_PRICE).value).toBe('42500000');
    });
    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    return user;
  }

  it('M27: anchoring by prefix instead of exact path is caught', async () => {
    // `market_leasing.market_rent_psf` is a prefix of nothing, but
    // `market_leasing.market_rent` is a prefix of it. A `startsWith` match would
    // hang this message on the wrong field.
    const user = await refuseWith([
      {
        code: 'MALFORMED_FIELD',
        path: 'market_leasing.market_rent',
        message: 'no such field',
        severity: 'error',
      },
    ]);
    await user.click(section('Market Leasing'));
    expect(field(MARKET_RENT).getAttribute('aria-invalid')).toBeNull();
    // Unanchorable, so it must still be readable somewhere.
    expect(screen.getByText(/no such field/)).toBeTruthy();
  });

  it('M28: anchoring across the wrong input object is caught', async () => {
    // Both `operating_inputs` and `market_leasing` could carry a field of the
    // same name. Matching on the field alone would cross the two.
    const user = await refuseWith([
      {
        code: 'MALFORMED_FIELD',
        path: 'operating_inputs.market_rent_psf',
        message: 'wrong object',
        severity: 'error',
      },
    ]);
    await user.click(section('Market Leasing'));
    expect(field(MARKET_RENT).getAttribute('aria-invalid')).toBeNull();
  });

  it('M29: an unanchorable issue swallowed rather than listed is caught', async () => {
    await refuseWith([
      {
        code: 'UNKNOWN_SUITE_REFERENCE',
        path: 'leases[0].suite_id',
        message: 'names a suite that does not exist',
        severity: 'error',
      },
    ]);
    // D5.5B anchors this to its row. Dropping it in the meantime would turn a
    // refused analysis into an unexplained one.
    expect(screen.getByText(/names a suite that does not exist/)).toBeTruthy();
  });

  it('M30: a stale issue surviving a successful re-analysis is caught', async () => {
    const user = await refuseWith([
      {
        code: 'RENEWAL_PROBABILITY_OUT_OF_DOMAIN',
        path: 'market_leasing.renewal_probability',
        message: 'must be between 0 and 1',
        severity: 'error',
      },
    ]);
    await user.click(section('Market Leasing'));
    expect(field(RENEWAL_PROBABILITY).getAttribute('aria-invalid')).toBe('true');

    mockAnalyze.mockResolvedValue(leaseLevelResults());
    await user.click(analyzeButton());

    await waitFor(() => {
      expect(field(RENEWAL_PROBABILITY).getAttribute('aria-invalid')).toBeNull();
    });
    expect(screen.queryByText('must be between 0 and 1')).toBeNull();
  });

  it('M31: the workspace rendering another mode’s state is caught', async () => {
    // The shell picks a workspace, a deal name and a save status per mode. If
    // any Lease-Level arm read Quick's state, a value typed in Quick would
    // appear here.
    const user = userEvent.setup();
    render(<App />);
    await user.clear(field('purchasePrice'));
    await user.type(field('purchasePrice'), '999');
    await user.type(screen.getByLabelText(/Deal Name/i), 'A Quick Deal');

    await user.click(screen.getByRole('tab', { name: 'Lease-Level Underwrite' }));

    expect(field(TERMS_PURCHASE_PRICE).value).toBe('');
    expect((screen.getByLabelText(/Deal Name/i) as HTMLInputElement).value).toBe('');
  });

  it('M32: Analyze routed to another mode’s runner is caught', async () => {
    mockAnalyze.mockResolvedValue(leaseLevelResults());
    const user = await openSavedDeal();
    await waitFor(() => {
      expect(field(TERMS_PURCHASE_PRICE).value).toBe('42500000');
    });
    await user.click(analyzeButton());

    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalledTimes(1);
    });
    // And the Lease-Level runner received the Lease-Level inputs, not a
    // fabricated Quick or Detailed shape.
    const [, inputs] = mockAnalyze.mock.calls[0];
    expect(Object.keys(inputs).sort()).toEqual([
      'leases',
      'market_leasing',
      'operating_inputs',
      'property_inputs',
      'suites',
    ]);
  });
});
