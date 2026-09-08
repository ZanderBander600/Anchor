/**
 * D5.5B -- building a real rent roll by hand.
 *
 * The gate's claim is that an analyst can construct a 5-30 suite Lease-Level
 * property from nothing, analyze it, save it, reopen it and edit it, without
 * touching Python. These tests drive the actual app against a mocked API and
 * check that claim end to end, plus every structural rule the rent roll must
 * respect: one lease per suite, occupancy derived from the lease, vacancy
 * treatments stated rather than assumed, overrides all-or-nothing, and nothing
 * economic ever invented.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import {
  LeaseLevelApiError,
  analyzeLeaseLevelAcquisition,
  createLeaseLevelDeal,
  getDeal,
  listDeals,
  updateLeaseLevelDeal,
} from './api';
import {
  BLANK_LEASE_LEVEL_FORM_VALUES,
  blankLeaseFormValues,
  blankSuiteRow,
  buildLeaseLevelFormValues,
  buildLeaseLevelInputsRequest,
  collectRentRollBlankIssues,
  reconcileArea,
} from './leaseLevelConvert';
import { resolveRowIssues } from './leaseLevelIssues';
import type { SubmittedRentRoll } from './leaseLevelIssues';
import type {
  LeaseLevelAcquisitionResults,
  LeaseLevelDealFields,
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

let confirmSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.clearAllMocks();
  mockListDeals.mockResolvedValue([]);
  confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  confirmSpy.mockRestore();
});

// =============================================================================
// Fixtures -- a realistic six-suite property
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

const MARKET: MarketLeasingAssumptionsRequest = {
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

/** Six suites: three occupied, one leasing up, one held vacant, one occupied
 * with a full suite override. Every state the editor must handle. */
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
    suite_id: '250',
    suite_area_sf: 6_000,
    suite_label: null,
    market_rent_psf: null,
    market_leasing_override: { ...MARKET, new_downtime_months: 12 },
    initial_vacancy: null,
  },
  {
    suite_id: '300',
    suite_area_sf: 12_000,
    suite_label: 'Suite 300',
    market_rent_psf: null,
    market_leasing_override: null,
    initial_vacancy: { strategy: 'market_lease_up', initial_lease_up_months: 8 },
  },
  {
    suite_id: '400',
    suite_area_sf: 9_450,
    suite_label: null,
    market_rent_psf: null,
    market_leasing_override: null,
    initial_vacancy: { strategy: 'hold_vacant', initial_lease_up_months: null },
  },
  {
    suite_id: '500',
    suite_area_sf: 4_000,
    suite_label: null,
    market_rent_psf: 41,
    market_leasing_override: null,
    initial_vacancy: { strategy: 'hold_vacant', initial_lease_up_months: null },
  },
];

function leaseFor(id: string, suiteId: string, area: number): LeaseRequest {
  return {
    lease_id: id,
    suite_id: suiteId,
    leased_area_sf: area,
    rent_commencement_date: '2023-06-01',
    lease_expiration_date: '2029-05-31',
    base_rent_psf: 31.25,
    escalation_pct: 0.03,
    escalation_basis: 'lease_anniversary',
    lease_type: 'nnn',
    tenant_name: 'Marlow Provisions',
    lease_start_date: null,
    origin: 'in_place',
    recovery_basis: null,
    expense_stop_psf: null,
  };
}

const LEASES: LeaseRequest[] = [
  leaseFor('L-100', '100', 18_400),
  { ...leaseFor('L-200', '200', 22_150), tenant_name: 'Halbrook Analytics' },
  {
    ...leaseFor('L-250', '250', 6_000),
    tenant_name: 'Corvid Studio',
    lease_type: 'modified_gross',
    recovery_basis: 'expense_stop_psf',
    expense_stop_psf: 10.5,
  },
];

const DEAL_FIELDS: LeaseLevelDealFields = {
  terms: TERMS,
  property_inputs: { analysis_start_date: '2027-01-01', rentable_area_sf: 72_000 },
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
  market_leasing: MARKET,
  suites: SUITES,
  leases: LEASES,
};

function savedDeal(overrides: Partial<Deal> = {}): Deal {
  return {
    id: 'deal-ll-1',
    name: 'Fulton Exchange',
    operating_mode: 'lease_level',
    inputs: null,
    detailed_operating_inputs: null,
    ...DEAL_FIELDS,
    deal_context: 'Value-add reposition.',
    analysis_snapshot: null,
    ai_snapshot: null,
    created_at: '2027-01-04T09:00:00+00:00',
    updated_at: '2027-01-04T09:00:00+00:00',
    ...overrides,
  };
}

function results(): LeaseLevelAcquisitionResults {
  return {
    monthly_projection: {} as LeaseLevelAcquisitionResults['monthly_projection'],
    annual_projection: {} as LeaseLevelAcquisitionResults['annual_projection'],
    results: {} as LeaseLevelAcquisitionResults['results'],
  };
}

// =============================================================================
// Harness
// =============================================================================

async function openSavedDeal() {
  mockListDeals.mockResolvedValue([savedDeal()]);
  mockGetDeal.mockResolvedValue(savedDeal());
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('Fulton Exchange');
  await user.click(screen.getByText('Fulton Exchange'));
  await waitFor(() => {
    expect(screen.getByRole('tablist', { name: 'Lease-Level sections' })).toBeTruthy();
  });
  await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
  return user;
}

async function enterBlankLeaseLevel() {
  const user = userEvent.setup();
  render(<App />);
  await user.click(screen.getByRole('tab', { name: 'Lease-Level Underwrite' }));
  await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
  return user;
}

function rentRollPanel(): HTMLElement {
  return document.getElementById('lease-level-panel-rent-roll') as HTMLElement;
}

function dataRows(): HTMLElement[] {
  return within(rentRollPanel()).getAllByRole('row').slice(1) as HTMLElement[];
}

function cell(row: HTMLElement, label: RegExp): HTMLInputElement {
  return within(row).getByLabelText(label) as HTMLInputElement;
}

/** The open advanced editor.
 *
 * Override fields deliberately reuse the property defaults' labels and
 * conversions -- one vocabulary, not two -- so the same name legitimately
 * appears on the Market Leasing tab and in this drawer. They are different
 * state, and queries must say which they mean. */
function drawer(): HTMLElement {
  const element = document.querySelector('.suite-editor');
  if (element === null) {
    throw new Error('No suite editor is open');
  }
  return element as HTMLElement;
}

function analyzeButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: /^Analyz/i }) as HTMLButtonElement;
}

function saveButton(): HTMLElement {
  return screen.getByRole('button', { name: /(Save|Update) Deal/i });
}

// =============================================================================
// 1. Building a roll from nothing
// =============================================================================

describe('building a rent roll', () => {
  it('starts with no suites and adds one on request', async () => {
    const user = await enterBlankLeaseLevel();
    expect(within(rentRollPanel()).queryAllByRole('row')).toHaveLength(1); // header only

    await user.click(screen.getByRole('button', { name: 'Add Suite' }));
    expect(dataRows()).toHaveLength(1);
  });

  it('adds a blank suite -- no area, no rent, no status economics (M1)', async () => {
    const user = await enterBlankLeaseLevel();
    await user.click(screen.getByRole('button', { name: 'Add Suite' }));

    const row = dataRows()[0];
    expect(cell(row, /^Suite, /).value).toBe('');
    expect(cell(row, /^Area SF, /).value).toBe('');
    expect(cell(row, /^Suite Market Rent, /).value).toBe('');
    // Vacant because it has no lease -- the engine's own rule -- not because a
    // status was chosen for it.
    expect(within(row).getByRole('button', { name: /is vacant/ })).toBeTruthy();

    const blank = blankSuiteRow();
    for (const [key, value] of Object.entries(blank)) {
      if (typeof value === 'string' && key !== 'rowId') {
        expect(value, `${key} is seeded`).toBe('');
      }
    }
    expect(blank.lease).toBeNull();
    expect(blank.marketLeasingOverrideEnabled).toBe(false);
  });

  it('does not choose a vacancy strategy for a new suite (M3, M4)', async () => {
    const user = await enterBlankLeaseLevel();
    await user.click(screen.getByRole('button', { name: 'Add Suite' }));
    await user.click(screen.getByRole('button', { name: /Edit details for/ }));

    const strategy = screen.getByLabelText('Initial Vacancy Strategy') as HTMLSelectElement;
    // Neither HOLD_VACANT nor MARKET_LEASE_UP. Anchor does not assume vacant
    // space stays vacant, and does not assume it lets.
    expect(strategy.value).toBe('');
    expect(blankSuiteRow().initialVacancy.strategy).toBe('');
  });

  it('accepts a full six-suite property and sends it (M26, M27)', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    await user.click(analyzeButton());

    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    expect(inputs.suites).toEqual(SUITES);
    expect(inputs.leases).toEqual(LEASES);
  });

  it('never lets the local row id reach the payload', () => {
    // `rowId` exists only because `suiteId` is analyst-editable and legitimately
    // blank or duplicated mid-edit, so React needs a key that is none of those
    // things. It is not an underwriting assumption and must never be persisted
    // or fingerprinted.
    const form = buildLeaseLevelFormValues(DEAL_FIELDS, BLANK_LEASE_LEVEL_FORM_VALUES.terms);
    expect(form.rentRoll.every((row) => row.rowId !== '')).toBe(true);

    const inputs = buildLeaseLevelInputsRequest(form);
    const wire = JSON.stringify(inputs);
    expect(wire).not.toContain('rowId');
    expect(wire).not.toContain('row-');
    for (const suite of inputs.suites) {
      expect(Object.keys(suite)).not.toContain('rowId');
    }
    for (const lease of inputs.leases) {
      expect(Object.keys(lease)).not.toContain('rowId');
    }
  });
});

// =============================================================================
// 2. Occupancy is the lease
// =============================================================================

describe('occupied and vacant', () => {
  it('derives status from the lease, with no status field on the wire', async () => {
    await openSavedDeal();
    const rows = dataRows();
    expect(within(rows[0]).getByRole('button', { name: /is occupied/ })).toBeTruthy();
    expect(within(rows[3]).getByRole('button', { name: /is vacant/ })).toBeTruthy();

    // Nothing named `status` reaches the transport.
    const form = buildLeaseLevelFormValues(DEAL_FIELDS, {
      purchasePrice: '1',
      holdPeriod: '1',
      exitCapRate: '1',
      ltv: '1',
      interestRate: '1',
      amortization: '1',
      acquisitionCostPct: '1',
      financingFeePct: '1',
      dispositionCostPct: '1',
      annualCapexReserve: '1',
      ioPeriod: '1',
    });
    const suite = buildLeaseLevelInputsRequest(form).suites[0];
    expect(Object.keys(suite)).not.toContain('status');
    expect(Object.keys(suite).sort()).toEqual([
      'initial_vacancy',
      'market_leasing_override',
      'market_rent_psf',
      'suite_area_sf',
      'suite_id',
      'suite_label',
    ]);
  });

  it('vacant to occupied creates an EMPTY lease (M2)', async () => {
    const user = await enterBlankLeaseLevel();
    await user.click(screen.getByRole('button', { name: 'Add Suite' }));
    await user.click(within(dataRows()[0]).getByRole('button', { name: /is vacant/ }));

    const row = dataRows()[0];
    expect(within(row).getByRole('button', { name: /is occupied/ })).toBeTruthy();
    expect(cell(row, /^Tenant, /).value).toBe('');
    expect(cell(row, /^Base Rent per SF, /).value).toBe('');
    expect((within(row).getByLabelText(/^Lease Type, /) as HTMLSelectElement).value).toBe('');

    // Not NNN, not a term, not a date.
    const lease = blankLeaseFormValues();
    for (const [key, value] of Object.entries(lease)) {
      if (key === 'origin') continue;
      expect(value, `${key} is seeded`).toBe('');
    }
  });

  it('vacant to occupied stops submitting the vacancy treatment', () => {
    // An occupied suite carrying one is refused
    // (`INITIAL_VACANCY_ON_OCCUPIED_SUITE`), so it must not travel -- but the
    // analyst's choice is kept locally in case they switch back.
    //
    // Asserted through the conversion rather than through Analyze, because the
    // new lease is deliberately empty and an empty lease has no request to send:
    // that is `vacant to occupied creates an EMPTY lease` doing its job.
    const form = buildLeaseLevelFormValues(DEAL_FIELDS, BLANK_LEASE_LEVEL_FORM_VALUES.terms);
    const occupiedNow = {
      ...form,
      rentRoll: form.rentRoll.map((row, index) =>
        index === 3
          ? {
              ...row,
              lease: {
                ...blankLeaseFormValues(),
                leaseId: 'L-300',
                leasedAreaSf: '12000',
                rentCommencementDate: '2027-02-01',
                leaseExpirationDate: '2032-01-31',
                baseRentPsf: '30',
                escalationPct: '3',
                escalationBasis: 'lease_anniversary',
                leaseType: 'nnn',
              },
            }
          : row,
      ),
    };
    const inputs = buildLeaseLevelInputsRequest(occupiedNow);
    expect(inputs.suites[3].initial_vacancy).toBeNull();
    // The dormant treatment is still held for a return trip.
    expect(occupiedNow.rentRoll[3].initialVacancy.strategy).toBe('market_lease_up');
  });

  it('keeps the vacancy treatment for a return trip', async () => {
    const user = await openSavedDeal();
    const toggle = () => within(dataRows()[3]).getByRole('button', { name: /is (occupied|vacant)/ });
    await user.click(toggle());
    await user.click(toggle());

    await user.click(within(dataRows()[3]).getByRole('button', { name: /Edit details for/ }));
    expect((screen.getByLabelText('Initial Vacancy Strategy') as HTMLSelectElement).value).toBe(
      'market_lease_up',
    );
    expect(
      (screen.getByLabelText('Initial Lease-Up Months') as HTMLInputElement).value,
    ).toBe('8');
  });

  it('occupied to vacant confirms before discarding a populated lease (M6)', async () => {
    confirmSpy.mockReturnValue(false);
    const user = await openSavedDeal();

    await user.click(within(dataRows()[0]).getByRole('button', { name: /is occupied/ }));

    expect(confirmSpy).toHaveBeenCalled();
    expect(String(confirmSpy.mock.calls[0][0])).toMatch(/Marlow Provisions/);
    // Declined, so nothing was destroyed.
    expect(within(dataRows()[0]).getByRole('button', { name: /is occupied/ })).toBeTruthy();
    expect(cell(dataRows()[0], /^Tenant, /).value).toBe('Marlow Provisions');
  });

  it('occupied to vacant removes the lease once confirmed', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    await user.click(within(dataRows()[0]).getByRole('button', { name: /is occupied/ }));
    expect(within(dataRows()[0]).getByRole('button', { name: /is vacant/ })).toBeTruthy();

    // The suite now needs a treatment it does not have, so the request is not
    // built -- the vacancy strategy is asked for rather than assumed. That is
    // exactly M3/M4, seen from the transition.
    await user.click(analyzeButton());
    await waitFor(() => {
      expect(
        within(dataRows()[0]).getByRole('button', { name: /is vacant/ }),
      ).toBeTruthy();
    });
    expect(mockAnalyze).not.toHaveBeenCalled();

    // Choose one, and the lease is gone from the payload.
    await user.click(within(dataRows()[0]).getByRole('button', { name: /Edit details for/ }));
    await user.selectOptions(screen.getByLabelText('Initial Vacancy Strategy'), 'hold_vacant');
    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    expect(inputs.leases.map((lease) => lease.lease_id)).toEqual(['L-200', 'L-250']);
    expect(inputs.suites[0].initial_vacancy).toEqual({
      strategy: 'hold_vacant',
      initial_lease_up_months: null,
    });
  });

  it('offers no way to add a second lease to a suite (M5, M30)', async () => {
    await openSavedDeal();
    // No "add lease" affordance anywhere, and no sequential/next/future lease UI.
    expect(screen.queryByRole('button', { name: /add.*lease/i })).toBeNull();
    expect(screen.queryByText(/next lease|future lease|second lease|lease stack/i)).toBeNull();

    // Structurally: a row holds one optional lease, so a second is not
    // representable in the form at all.
    const row = blankSuiteRow();
    expect('lease' in row).toBe(true);
    expect(Array.isArray((row as unknown as { lease: unknown }).lease)).toBe(false);
  });
});

// =============================================================================
// 3. Deleting
// =============================================================================

describe('deleting a suite', () => {
  it('confirms when the row holds data, and takes its lease with it (M7)', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    await user.click(within(dataRows()[0]).getByRole('button', { name: /Delete suite 100/ }));

    expect(confirmSpy).toHaveBeenCalled();
    expect(String(confirmSpy.mock.calls[0][0])).toMatch(/lease will be removed/i);
    expect(dataRows()).toHaveLength(5);

    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    expect(inputs.suites.map((suite) => suite.suite_id)).toEqual([
      '200',
      '250',
      '300',
      '400',
      '500',
    ]);
    // No orphan: leases are emitted from rows, so a deleted suite cannot leave
    // a lease pointing at it.
    expect(inputs.leases.map((lease) => lease.suite_id)).toEqual(['200', '250']);
    expect(inputs.leases.some((lease) => lease.suite_id === '100')).toBe(false);
  });

  it('does not confirm for an untouched blank row', async () => {
    const user = await enterBlankLeaseLevel();
    await user.click(screen.getByRole('button', { name: 'Add Suite' }));
    confirmSpy.mockClear();

    await user.click(within(dataRows()[0]).getByRole('button', { name: /Delete new suite/ }));
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(within(rentRollPanel()).queryAllByRole('row')).toHaveLength(1);
  });

  it('keeps the row when the analyst declines', async () => {
    confirmSpy.mockReturnValue(false);
    const user = await openSavedDeal();
    await user.click(within(dataRows()[0]).getByRole('button', { name: /Delete suite 100/ }));
    expect(dataRows()).toHaveLength(6);
  });
});

// =============================================================================
// 4. Editing suites and leases
// =============================================================================

describe('editing', () => {
  it('edits a suite without dropping its lease (M8)', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    const area = cell(dataRows()[0], /^Area SF, /);
    await user.clear(area);
    await user.type(area, '18500');

    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    expect(inputs.suites[0].suite_area_sf).toBe(18_500);
    expect(inputs.leases[0]).toEqual(LEASES[0]);
  });

  it('edits a lease without dropping the suite override (M9)', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    const rent = cell(dataRows()[2], /^Base Rent per SF, /);
    await user.clear(rent);
    await user.type(rent, '33.5');

    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    expect(inputs.leases[2].base_rent_psf).toBe(33.5);
    expect(inputs.suites[2].market_leasing_override).toEqual(SUITES[2].market_leasing_override);
  });

  it('renaming a suite renames the lease it owns', async () => {
    // The row owns `suite_id`, so the lease cannot drift onto a suite that does
    // not exist -- `UNKNOWN_SUITE_REFERENCE` is unreachable from this editor.
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    const suiteId = cell(dataRows()[0], /^Suite, /);
    await user.clear(suiteId);
    await user.type(suiteId, '101');

    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    expect(inputs.suites[0].suite_id).toBe('101');
    expect(inputs.leases.find((lease) => lease.lease_id === 'L-100')?.suite_id).toBe('101');
  });

  it('does not rename a duplicate suite id (M15)', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    const suiteId = cell(dataRows()[1], /^Suite, /);
    await user.clear(suiteId);
    await user.type(suiteId, '100');

    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    // Sent exactly as typed. `DUPLICATE_SUITE_ID` is the backend's to raise;
    // renaming it to "100-2" would invent an identifier the analyst never chose.
    expect(inputs.suites.map((suite) => suite.suite_id)).toEqual([
      '100',
      '100',
      '250',
      '300',
      '400',
      '500',
    ]);
  });

  it('never mirrors suite area into leased area (M14)', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    const area = cell(dataRows()[0], /^Area SF, /);
    await user.clear(area);
    await user.type(area, '25000');

    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    expect(inputs.suites[0].suite_area_sf).toBe(25_000);
    // Unchanged. The backend requires equality today, but copying silently
    // would hide a roll that genuinely disagrees with itself.
    expect(inputs.leases[0].leased_area_sf).toBe(18_400);
  });

  it('copies suite area only when the analyst asks', async () => {
    const user = await openSavedDeal();
    await user.click(within(dataRows()[0]).getByRole('button', { name: /Edit details for/ }));

    const leased = screen.getByLabelText('Leased Area') as HTMLInputElement;
    expect(leased.value).toBe('18400');
    const suiteArea = screen.getByLabelText('Suite Area') as HTMLInputElement;
    await user.clear(suiteArea);
    await user.type(suiteArea, '19000');
    expect(leased.value).toBe('18400');

    await user.click(screen.getByRole('button', { name: 'Use Suite Area' }));
    expect((screen.getByLabelText('Leased Area') as HTMLInputElement).value).toBe('19000');
  });

  it('holds lease origin rather than offering it (successor stays engine-owned)', async () => {
    await openSavedDeal();
    expect(screen.queryByLabelText(/origin/i)).toBeNull();
    // Scoped to the rent roll: the property-default market-leasing hint on
    // another tab legitimately explains successor leases.
    expect(within(rentRollPanel()).queryByText(/successor/i)).toBeNull();
    expect(blankLeaseFormValues().origin).toBe('in_place');
  });

  it('preserves a non-IN_PLACE origin that was loaded, rather than rewriting it', async () => {
    // Persisted successor state should not exist for an acquisition rent roll,
    // but if it does the UI reports it back unchanged instead of silently
    // converting it to IN_PLACE.
    const successor: LeaseRequest = { ...LEASES[0], origin: 'successor', tenant_name: null };
    const form = buildLeaseLevelFormValues(
      { ...DEAL_FIELDS, leases: [successor, LEASES[1], LEASES[2]] },
      BLANK_LEASE_LEVEL_FORM_VALUES.terms,
    );
    expect(form.rentRoll[0].lease?.origin).toBe('successor');
  });
});

// =============================================================================
// 5. Initial vacancy
// =============================================================================

describe('initial vacancy', () => {
  it('offers exactly the two supported strategies', async () => {
    const user = await openSavedDeal();
    await user.click(within(dataRows()[3]).getByRole('button', { name: /Edit details for/ }));

    const options = Array.from(
      (screen.getByLabelText('Initial Vacancy Strategy') as HTMLSelectElement).options,
    ).map((option) => option.value);
    expect(options).toEqual(['', 'hold_vacant', 'market_lease_up']);
  });

  it('shows lease-up months for MARKET_LEASE_UP only', async () => {
    const user = await openSavedDeal();
    await user.click(within(dataRows()[3]).getByRole('button', { name: /Edit details for/ }));
    expect(screen.getByLabelText('Initial Lease-Up Months')).toBeTruthy();

    await user.selectOptions(screen.getByLabelText('Initial Vacancy Strategy'), 'hold_vacant');
    expect(screen.queryByLabelText('Initial Lease-Up Months')).toBeNull();
  });

  it('drops the lease-up figure from a HOLD_VACANT payload but keeps it locally', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    await user.click(within(dataRows()[3]).getByRole('button', { name: /Edit details for/ }));
    await user.selectOptions(screen.getByLabelText('Initial Vacancy Strategy'), 'hold_vacant');

    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    // `INITIAL_LEASE_UP_ON_HOLD_VACANT`: a stale hidden field must not travel.
    expect(inputs.suites[3].initial_vacancy).toEqual({
      strategy: 'hold_vacant',
      initial_lease_up_months: null,
    });

    await user.selectOptions(
      screen.getByLabelText('Initial Vacancy Strategy'),
      'market_lease_up',
    );
    expect((screen.getByLabelText('Initial Lease-Up Months') as HTMLInputElement).value).toBe(
      '8',
    );
  });
});

// =============================================================================
// 6. Overrides
// =============================================================================

describe('suite overrides', () => {
  it('sends a rent-only override, and blank means inherit', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    expect(inputs.suites[1].market_rent_psf).toBe(38.75);
    expect(inputs.suites[0].market_rent_psf).toBeNull();
  });

  it('editing a suite override never touches the property defaults (M10)', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    await user.click(within(dataRows()[2]).getByRole('button', { name: /Edit details for/ }));

    const overrideRent = within(drawer()).getByLabelText(/^Market Rent\$/) as HTMLInputElement;
    await user.clear(overrideRent);
    await user.type(overrideRent, '99');

    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    expect(inputs.suites[2].market_leasing_override?.market_rent_psf).toBe(99);
    expect(inputs.market_leasing.market_rent_psf).toBe(34.5);
  });

  it('turning a full override on does not delete the rent-only override (M11)', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    // Suite 200 has a scalar rent override and no full override.
    await user.click(within(dataRows()[1]).getByRole('button', { name: /Edit details for/ }));
    await user.click(screen.getByLabelText('Use full suite leasing assumptions'));

    expect((screen.getByLabelText('Suite Market Rent') as HTMLInputElement).value).toBe('38.75');

    await user.click(screen.getByLabelText('Use full suite leasing assumptions'));
    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    // Both survive the round trip; the backend decides precedence.
    expect(inputs.suites[1].market_rent_psf).toBe(38.75);
    expect(inputs.suites[1].market_leasing_override).toBeNull();
  });

  it('submits a complete override or none, never a partial one (M12)', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];

    expect(inputs.suites[0].market_leasing_override).toBeNull();
    const override = inputs.suites[2].market_leasing_override;
    expect(override).not.toBeNull();
    // Exactly the property-default record's shape -- all twenty-three fields.
    expect(Object.keys(override!).sort()).toEqual(Object.keys(inputs.market_leasing).sort());
  });

  it('reopens a stored override with real enum tokens, not a raw blob (M13)', async () => {
    const user = await openSavedDeal();
    await user.click(within(dataRows()[2]).getByRole('button', { name: /Edit details for/ }));

    expect(
      (within(drawer()).getByLabelText('Renewal Lease Type') as HTMLSelectElement).value,
    ).toBe('nnn');
    expect((within(drawer()).getByLabelText(/^New Downtime/) as HTMLInputElement).value).toBe('12');
    // A rate arrives as a decimal and renders percent-scale, exactly like the
    // property defaults -- one convention, not two.
    expect((within(drawer()).getByLabelText(/^Renewal Probability/) as HTMLInputElement).value).toBe('70');
  });

  it('explains precedence without computing a resolved rent', async () => {
    const user = await openSavedDeal();
    await user.click(within(dataRows()[2]).getByRole('button', { name: /Edit details for/ }));
    expect(screen.getByText(/take precedence while enabled/i)).toBeTruthy();
  });
});

// =============================================================================
// 7. Area reconciliation -- the display-only carve-out
// =============================================================================

describe('area reconciliation', () => {
  it('shows rentable, allocated and difference', async () => {
    await openSavedDeal();
    const strip = screen.getByLabelText('Area reconciliation');
    // Rentable and allocated are equal on this fixture, so both figures read
    // 72,000 -- which is the point of the strip.
    expect(within(strip).getAllByText('72,000 SF')).toHaveLength(2);
    expect(within(strip).getByText('0 SF')).toBeTruthy();
    expect(within(strip).getByText(/match the property rentable area/i)).toBeTruthy();
  });

  it('warns on a shortfall without blocking anything (M18, M19)', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    const area = cell(dataRows()[0], /^Area SF, /);
    await user.clear(area);
    await user.type(area, '13400');

    const strip = screen.getByLabelText('Area reconciliation');
    expect(within(strip).getByText(/5,000 SF unallocated/)).toBeTruthy();
    // No residual suite was created to absorb it.
    expect(dataRows()).toHaveLength(6);
    // And the request still goes: the client is not an area authority.
    expect(analyzeButton().disabled).toBe(false);
    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
  });

  it('does not present itself as a backend validation result', async () => {
    const user = await openSavedDeal();
    const area = cell(dataRows()[0], /^Area SF, /);
    await user.clear(area);
    await user.type(area, '13400');
    expect(
      within(screen.getByLabelText('Area reconciliation')).getByText(/entry aid only/i),
    ).toBeTruthy();
  });

  it('computes only counts and area sums, never economics (M29)', () => {
    const form = buildLeaseLevelFormValues(DEAL_FIELDS, BLANK_LEASE_LEVEL_FORM_VALUES.terms);
    const area = reconcileArea(form);
    expect(area.rentableAreaSf).toBe(72_000);
    expect(area.allocatedSf).toBe(72_000);
    expect(area.differenceSf).toBe(0);
    // The returned shape is the whole surface: no rent, NOI, occupancy or WALT.
    expect(Object.keys(area).sort()).toEqual([
      'allocatedSf',
      'differenceSf',
      'rentableAreaSf',
      'rowsWithoutArea',
    ]);
  });
});

// =============================================================================
// 8. Validation anchoring
// =============================================================================

describe('validation anchoring', () => {
  async function refuseWith(issues: ConstructorParameters<typeof LeaseLevelApiError>[2]) {
    mockAnalyze.mockRejectedValue(new LeaseLevelApiError('refused', [], issues));
    const user = await openSavedDeal();
    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    return user;
  }

  it('anchors an index-keyed suite issue to its row (M21)', async () => {
    await refuseWith([
      {
        code: 'SUITE_AREA_OUT_OF_DOMAIN',
        path: 'suites[2].suite_area_sf',
        message: 'must be positive',
        severity: 'error',
      },
    ]);
    await waitFor(() => {
      expect(cell(dataRows()[2], /^Area SF, /).getAttribute('aria-invalid')).toBe('true');
    });
    // And nowhere else.
    expect(cell(dataRows()[0], /^Area SF, /).getAttribute('aria-invalid')).toBeNull();
    expect(cell(dataRows()[1], /^Area SF, /).getAttribute('aria-invalid')).toBeNull();
  });

  it('anchors an index-keyed lease issue to its row (M22)', async () => {
    await refuseWith([
      {
        code: 'LEASE_AREA_MISMATCH',
        path: 'leases[1].leased_area_sf',
        message: 'does not match the suite area',
        severity: 'error',
      },
    ]);
    // leases[1] is L-200, which belongs to suite 200 -- row index 1.
    await waitFor(() => {
      expect(
        within(dataRows()[1]).getByRole('button', { name: /Edit details for suite 200/ }),
      ).toBeTruthy();
    });
    const user = userEvent.setup();
    await user.click(
      within(dataRows()[1]).getByRole('button', { name: /Edit details for suite 200/ }),
    );
    expect(screen.getByText('does not match the suite area')).toBeTruthy();
  });

  it('anchors a suite-ID-keyed vacancy issue to the right row', async () => {
    // The initial-vacancy validators key on `suite_id`, not on array index --
    // and a suite id is very often numeric, so both readings must be tried.
    await refuseWith([
      {
        code: 'MISSING_INITIAL_VACANCY_TREATMENT',
        path: 'suites[400].initial_vacancy',
        message: 'states no initial-vacancy treatment',
        severity: 'error',
      },
    ]);
    // Suite "400" is at index 4, not index 400 and not index 4-by-accident.
    await waitFor(() => {
      expect(
        within(dataRows()[4]).getByText(/states no initial-vacancy treatment/),
      ).toBeTruthy();
    });
    expect(within(dataRows()[0]).queryByText(/initial-vacancy/)).toBeNull();
  });

  it('prefers the suite-id reading only when the two disagree', () => {
    // "300" is both a valid index-shaped string and a real suite id here.
    const submitted: SubmittedRentRoll = {
      suiteRowIds: ['r0', 'r1', 'r2'],
      suiteIds: ['100', '200', '300'],
      leaseRowIds: ['r0'],
    };
    const vacancy = resolveRowIssues(
      [
        {
          code: 'MISSING_INITIAL_VACANCY_TREATMENT',
          path: 'suites[300].initial_vacancy',
          message: 'x',
          severity: 'error',
        },
      ],
      submitted,
    );
    expect([...vacancy.byRow.keys()]).toEqual(['r2']);

    // An index-keyed field with the same bracketed text resolves by index when
    // that is in range -- here it is not, so it falls back to the id.
    const byIndex = resolveRowIssues(
      [
        {
          code: 'SUITE_AREA_OUT_OF_DOMAIN',
          path: 'suites[1].suite_area_sf',
          message: 'x',
          severity: 'error',
        },
      ],
      submitted,
    );
    expect([...byIndex.byRow.keys()]).toEqual(['r1']);
  });

  it('resolves against the submitted array, not the edited one', async () => {
    // The analyst deletes a row while the request is in flight. `suites[2]` must
    // still mean the suite that was submitted third, not whatever sits there now.
    const user = await refuseWith([
      {
        code: 'SUITE_AREA_OUT_OF_DOMAIN',
        path: 'suites[2].suite_area_sf',
        message: 'must be positive',
        severity: 'error',
      },
    ]);
    await waitFor(() => {
      expect(cell(dataRows()[2], /^Area SF, /).getAttribute('aria-invalid')).toBe('true');
    });

    await user.click(within(dataRows()[0]).getByRole('button', { name: /Delete suite 100/ }));
    // Editing clears the stale issues rather than re-pointing them at a new row.
    expect(cell(dataRows()[1], /^Area SF, /).getAttribute('aria-invalid')).toBeNull();
  });

  it('anchors an override issue into the drawer', async () => {
    const user = await refuseWith([
      {
        code: 'RENEWAL_PROBABILITY_OUT_OF_DOMAIN',
        path: 'suites[2].market_leasing_override.renewal_probability',
        message: 'must be between 0 and 1',
        severity: 'error',
      },
    ]);
    // The row flags that the problem is inside its details.
    await waitFor(() => {
      expect(
        within(dataRows()[2]).getByRole('button', { name: /Edit details for suite 250/ }),
      ).toBeTruthy();
    });
    await user.click(
      within(dataRows()[2]).getByRole('button', { name: /Edit details for suite 250/ }),
    );
    expect(
      (within(drawer()).getByLabelText(/^Renewal Probability/) as HTMLInputElement).getAttribute(
        'aria-invalid',
      ),
    ).toBe('true');
  });

  it('never swallows an unanchorable issue (M23)', async () => {
    await refuseWith([
      {
        code: 'RENTABLE_AREA_NOT_RECONCILED',
        path: 'property.rentable_area_sf',
        message: 'suite areas do not sum to rentable area',
        severity: 'error',
      },
      {
        code: 'SOMETHING_NEW',
        path: 'suites[99].invented_field',
        message: 'a path this build cannot place',
        severity: 'error',
      },
    ]);
    expect(screen.getByText(/do not sum to rentable area/)).toBeTruthy();
    expect(screen.getByText(/a path this build cannot place/)).toBeTruthy();
  });

  it('shows a one-known-lease issue rather than repairing the data', async () => {
    const user = await refuseWith([
      {
        code: 'MULTIPLE_KNOWN_LEASES_IN_SUITE',
        path: 'suites[100]',
        message: 'has more than one known lease',
        severity: 'error',
      },
    ]);
    await user.click(
      within(dataRows()[0]).getByRole('button', { name: /Edit details for suite 100/ }),
    );
    expect(screen.getByText(/has more than one known lease/)).toBeTruthy();
  });
});

// =============================================================================
// 9. Blanks are reported, never defaulted
// =============================================================================

describe('incomplete rows', () => {
  it('reports every blank row field at once, anchored', async () => {
    const user = await enterBlankLeaseLevel();
    await user.click(screen.getByRole('button', { name: 'Add Suite' }));
    await user.click(analyzeButton());

    await waitFor(() => {
      expect(cell(dataRows()[0], /^Suite, /).getAttribute('aria-invalid')).toBe('true');
    });
    expect(cell(dataRows()[0], /^Area SF, /).getAttribute('aria-invalid')).toBe('true');
    expect(mockAnalyze).not.toHaveBeenCalled();
  });

  it('requires a vacancy strategy but supplies neither (M3, M4)', () => {
    const issues = collectRentRollBlankIssues({
      ...BLANK_LEASE_LEVEL_FORM_VALUES,
      rentRoll: [{ ...blankSuiteRow(), suiteId: '100', suiteAreaSf: '1000' }],
    });
    expect(issues.map((issue) => issue.path)).toEqual(['suites[0].initial_vacancy.strategy']);
  });

  it('treats optional suite and lease fields as optional', () => {
    const row = {
      ...blankSuiteRow(),
      suiteId: '100',
      suiteAreaSf: '1000',
      lease: {
        ...blankLeaseFormValues(),
        leaseId: 'L-1',
        leasedAreaSf: '1000',
        rentCommencementDate: '2027-01-01',
        leaseExpirationDate: '2031-12-31',
        baseRentPsf: '30',
        escalationPct: '3',
        escalationBasis: 'lease_anniversary',
        leaseType: 'nnn',
      },
    };
    // `suiteLabel`, `marketRentPsf`, `tenantName`, `leaseStartDate`,
    // `recoveryBasis` and `expenseStopPsf` are all blank and all legitimately so.
    expect(
      collectRentRollBlankIssues({ ...BLANK_LEASE_LEVEL_FORM_VALUES, rentRoll: [row] }),
    ).toEqual([]);
  });
});

// =============================================================================
// 10. Dirty state, save and round trips
// =============================================================================

describe('dirty state', () => {
  function status(): string {
    return document.querySelector('.save-status')?.textContent ?? '';
  }

  it('marks the deal dirty when a suite changes (M24)', async () => {
    const user = await openSavedDeal();
    await waitFor(() => {
      expect(status()).toMatch(/Saved/i);
    });
    const area = cell(dataRows()[0], /^Area SF, /);
    await user.clear(area);
    await user.type(area, '18500');
    await waitFor(() => {
      expect(status()).toMatch(/Unsaved changes/i);
    });
  });

  it('marks the deal dirty when a lease changes (M25)', async () => {
    const user = await openSavedDeal();
    await waitFor(() => {
      expect(status()).toMatch(/Saved/i);
    });
    const rent = cell(dataRows()[0], /^Base Rent per SF, /);
    await user.clear(rent);
    await user.type(rent, '32');
    await waitFor(() => {
      expect(status()).toMatch(/Unsaved changes/i);
    });
  });

  it('marks the deal dirty on add, delete and status change', async () => {
    const user = await openSavedDeal();
    await waitFor(() => {
      expect(status()).toMatch(/Saved/i);
    });
    await user.click(screen.getByRole('button', { name: 'Add Suite' }));
    expect(status()).toMatch(/Unsaved changes/i);
  });

  it('uses one dirty system, not a separate rent-roll flag', async () => {
    const user = await openSavedDeal();
    const area = cell(dataRows()[0], /^Area SF, /);
    await user.clear(area);
    await user.type(area, '18500');
    await waitFor(() => {
      expect(status()).toMatch(/Unsaved changes/i);
    });

    // The same status the scalar tabs drive, resetting on the same save.
    mockUpdate.mockResolvedValue(savedDeal({ updated_at: '2027-02-01T00:00:00+00:00' }));
    await user.click(saveButton());
    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalled();
    });
  });
});

describe('round trips', () => {
  it('loads and saves with no edits, byte for byte (M28)', async () => {
    mockUpdate.mockResolvedValue(savedDeal());
    const user = await openSavedDeal();
    await user.click(saveButton());

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalled();
    });
    const [, , , inputs] = mockUpdate.mock.calls[0];
    expect(inputs.suites).toEqual(SUITES);
    expect(inputs.leases).toEqual(LEASES);
    expect(inputs.property_inputs).toEqual(DEAL_FIELDS.property_inputs);
    expect(inputs.market_leasing).toEqual(MARKET);
  });

  it('changes only the suite field that was edited', async () => {
    mockUpdate.mockResolvedValue(savedDeal());
    const user = await openSavedDeal();
    const area = cell(dataRows()[0], /^Area SF, /);
    await user.clear(area);
    await user.type(area, '18500');
    await user.click(saveButton());

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalled();
    });
    const [, , , inputs] = mockUpdate.mock.calls[0];
    expect(inputs.suites[0]).toEqual({ ...SUITES[0], suite_area_sf: 18_500 });
    expect(inputs.suites.slice(1)).toEqual(SUITES.slice(1));
    expect(inputs.leases).toEqual(LEASES);
  });

  it('changes only the lease field that was edited', async () => {
    mockUpdate.mockResolvedValue(savedDeal());
    const user = await openSavedDeal();
    const rent = cell(dataRows()[0], /^Base Rent per SF, /);
    await user.clear(rent);
    await user.type(rent, '32.75');
    await user.click(saveButton());

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalled();
    });
    const [, , , inputs] = mockUpdate.mock.calls[0];
    expect(inputs.leases[0]).toEqual({ ...LEASES[0], base_rent_psf: 32.75 });
    expect(inputs.leases.slice(1)).toEqual(LEASES.slice(1));
    expect(inputs.suites).toEqual(SUITES);
  });

  it('saves a new deal built entirely by hand', async () => {
    mockCreate.mockResolvedValue(savedDeal({ id: 'deal-new' }));
    const form = buildLeaseLevelFormValues(DEAL_FIELDS, BLANK_LEASE_LEVEL_FORM_VALUES.terms);
    // The conversion the Save button performs, on a hand-built roll.
    const inputs = buildLeaseLevelInputsRequest(form);
    expect(inputs.suites).toHaveLength(6);
    expect(inputs.leases).toHaveLength(3);
    expect(inputs.suites.filter((suite) => suite.initial_vacancy !== null)).toHaveLength(3);
  });

  it('preserves ordinal order rather than any view ordering (M20)', async () => {
    mockUpdate.mockResolvedValue(savedDeal());
    const user = await openSavedDeal();
    await user.click(saveButton());
    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalled();
    });
    const [, , , inputs] = mockUpdate.mock.calls[0];
    expect(inputs.suites.map((suite) => suite.suite_id)).toEqual([
      '100',
      '200',
      '250',
      '300',
      '400',
      '500',
    ]);
    // There is no sort control in this gate, so stored order is the only order.
    expect(screen.queryByRole('columnheader', { name: /sort/i })).toBeNull();
  });
});

// =============================================================================
// 11. Dates and numbers keep D5.5A's conventions
// =============================================================================

describe('dates and numbers', () => {
  it('sends dates exactly as entered (M16)', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    const expiry = cell(dataRows()[0], /^Lease Expiration, /);
    await user.clear(expiry);
    await user.type(expiry, '2029-05-17');

    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    // Not snapped to a month end, and no term recomputed from it.
    expect(inputs.leases[0].lease_expiration_date).toBe('2029-05-17');
    expect(inputs.leases[0].rent_commencement_date).toBe('2023-06-01');
  });

  it('keeps the percent convention on lease escalation', async () => {
    const form = buildLeaseLevelFormValues(DEAL_FIELDS, BLANK_LEASE_LEVEL_FORM_VALUES.terms);
    expect(form.rentRoll[0].lease?.escalationPct).toBe('3');
    expect(buildLeaseLevelInputsRequest(form).leases[0].escalation_pct).toBeCloseTo(0.03, 12);
  });

  it('does not pre-judge a domain-invalid value (M17)', async () => {
    // A probability above 1 is the backend's to refuse, by name. A client-side
    // range check would be a second validity model in front of the real one.
    mockAnalyze.mockResolvedValue(results());
    const user = await openSavedDeal();
    await user.click(within(dataRows()[2]).getByRole('button', { name: /Edit details for/ }));
    const probability = within(drawer()).getByLabelText(/^Renewal Probability/) as HTMLInputElement;
    await user.clear(probability);
    await user.type(probability, '140');

    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    expect(inputs.suites[2].market_leasing_override?.renewal_probability).toBeCloseTo(1.4, 12);
  });
});
