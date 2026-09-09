/**
 * D5.8 -- the AI Analyst on the Lease-Level workspace.
 *
 * The backend owns grounding; this file owns the two things only the product
 * surface can promise.
 *
 * **The AI Analyst never sees a stale analysis.** Editing an assumption clears
 * the results, and D5.8 clears the report with them. A narrative describing
 * numbers the analyst has since changed reads as current and is not, which is
 * the one genuinely misleading state this workspace could reach. So the tests
 * below drive a real edit and check both that the report disappears and that
 * nothing is sent afterwards.
 *
 * **AI stays optional decision support.** An unconfigured or failing provider
 * surfaces as a message inside the AI panel; the analysis, the results and
 * every other workspace keep working.
 *
 * Driven through `App`, like its D5.7 sibling, because every claim here is
 * about wiring: which request the panel sends, when it is allowed to send one,
 * and what happens to what came back when the deal underneath it moves.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import {
  ApiError,
  analyzeLeaseLevelAcquisition,
  fetchLeaseLevelAIAnalysis,
  getDeal,
  listDeals,
} from './api';
import fixture from './leaseLevelResultsFixture.json';
import type { LeaseLevelAcquisitionResults } from './leaseLevelTypes';
import type { AIAnalysis, Deal } from './types';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    analyzeLeaseLevelAcquisition: vi.fn(),
    fetchLeaseLevelAIAnalysis: vi.fn(),
    getDeal: vi.fn(),
    listDeals: vi.fn(),
  };
});

const mockAnalyze = vi.mocked(analyzeLeaseLevelAcquisition);
const mockAi = vi.mocked(fetchLeaseLevelAIAnalysis);
const mockGetDeal = vi.mocked(getDeal);
const mockListDeals = vi.mocked(listDeals);

const HEALTHY = fixture.healthy as unknown as LeaseLevelAcquisitionResults;

const ANALYSIS: AIAnalysis = {
  executive_summary: 'A stabilised suburban asset with staggered rollover.',
  investment_view: 'Proceed, subject to diligence on the 2029 expiries.',
  strengths: ['Staggered lease expiries limit any single-year rollover.'],
  risks: ['Year 4 carries elevated leasing costs.'],
  return_drivers: ['Exit cap rate is the dominant driver.'],
  downside_analysis: 'Coverage holds above the supplied hurdle throughout.',
  capital_structure_analysis: 'Modest leverage with two interest-only years.',
  break_even_analysis: 'Break-even was not supplied for this Lease-Level analysis.',
  questions_to_investigate: ['Confirm the market rent assumption against comparables.'],
  confidence_notes: ['No standardized sensitivity bundle was supplied.'],
  deal_story: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  mockAnalyze.mockResolvedValue(HEALTHY);
  mockAi.mockResolvedValue(ANALYSIS);
});

afterEach(cleanup);

// =============================================================================
// The deal
// =============================================================================

const TERMS = {
  purchase_price: 30_000_000,
  hold_period: 7,
  exit_cap_rate: 0.0625,
  ltv: 0.6,
  interest_rate: 0.0575,
  amortization: 30,
  acquisition_cost_pct: 0.01,
  financing_fee_pct: 0.01,
  disposition_cost_pct: 0.015,
  annual_capex_reserve: 25_000,
  io_period: 2,
};

const MARKET_LEASING = {
  market_rent_psf: 34,
  market_rent_growth: 0.03,
  renewal_rent_psf: null,
  renewal_rent_spread: 0,
  renewal_term_months: 60,
  successor_escalation_pct: 0.03,
  renewal_downtime_months: 2,
  renewal_free_rent_months: 1,
  new_term_months: 60,
  new_downtime_months: 9,
  new_free_rent_months: 4,
  renewal_ti_psf: 15,
  new_ti_psf: 45,
  leasing_commission_method: 'pct_of_total_contractual_base_rent',
  renewal_lc_pct: 0.02,
  new_lc_pct: 0.04,
  renewal_probability: 0.7,
  renewal_lease_type: 'nnn',
  renewal_recovery_basis: null,
  renewal_expense_stop_psf: null,
  new_lease_type: 'nnn',
  new_recovery_basis: null,
  new_expense_stop_psf: null,
} as const;

function savedDeal(): Deal {
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
    suites: [
      {
        suite_id: '100',
        suite_area_sf: 40_000,
        suite_label: 'Suite 100',
        market_rent_psf: null,
        market_leasing_override: null,
        initial_vacancy: null,
      },
      {
        suite_id: '200',
        suite_area_sf: 22_000,
        suite_label: 'Suite 200',
        market_rent_psf: null,
        market_leasing_override: null,
        initial_vacancy: null,
      },
    ],
    leases: [
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
    ],
    deal_context: null,
    analysis_snapshot: null,
    ai_snapshot: null,
    one_way_sensitivity_snapshot: null,
    two_way_sensitivity_snapshot: null,
    created_at: '2027-01-04T09:00:00+00:00',
    updated_at: '2027-01-04T09:00:00+00:00',
  } as unknown as Deal;
}

// =============================================================================
// Driving the workspace
// =============================================================================

async function openDeal() {
  const deal = savedDeal();
  mockListDeals.mockResolvedValue([deal]);
  mockGetDeal.mockResolvedValue(deal);
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('Fulton Exchange');
  await user.click(screen.getByText('Fulton Exchange'));
  await waitFor(() => {
    expect(mockGetDeal).toHaveBeenCalledWith('deal-ll-1');
  });
  return user;
}

function aiPanel(): HTMLElement {
  const element = document.getElementById('workspace-panel-ai');
  if (element === null) {
    throw new Error('No AI Analyst workspace panel');
  }
  return element;
}

async function openAi(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('tab', { name: 'AI Analyst' }));
}

async function analyze(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /^Analyz/i }));
  await waitFor(() => expect(mockAnalyze).toHaveBeenCalled());
}

async function generate(user: ReturnType<typeof userEvent.setup>) {
  await user.click(within(aiPanel()).getByRole('button', { name: /Generate AI Analysis/i }));
}

/** Edits one assumption on Underwrite -- the smallest real change an analyst
 * can make, and the one that must invalidate everything downstream. */
async function editAnAssumption(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('tab', { name: 'Underwrite' }));
  const field = document.getElementById(
    'lease-level-terms-purchasePrice',
  ) as HTMLInputElement;
  await user.clear(field);
  await user.type(field, '31000000');
}

// =============================================================================
// 42. The unsupported placeholder is gone
// =============================================================================

describe('the Lease-Level AI Analyst workspace', () => {
  it('42: no longer says the AI Analyst cannot read a Lease-Level analysis', async () => {
    const user = await openDeal();
    await openAi(user);

    expect(aiPanel().textContent).not.toContain('does not yet read');
    expect(aiPanel().textContent).not.toContain('A later gate');
  });

  it('37: offers no generate action before an analysis exists', async () => {
    const user = await openDeal();
    await openAi(user);

    // The AI Analyst interprets verified results; with nothing analyzed there
    // is nothing to interpret, so the action is absent rather than disabled.
    expect(within(aiPanel()).queryByRole('button', { name: /Generate AI Analysis/i })).toBeNull();
    expect(aiPanel().textContent).toContain('Analyze the deal first');
    expect(aiPanel().textContent).toContain('never calculates them');
    expect(mockAi).not.toHaveBeenCalled();
  });

  it('38: Analyze enables the AI Analyst', async () => {
    const user = await openDeal();
    await analyze(user);
    await openAi(user);

    expect(
      within(aiPanel()).getByRole('button', { name: /Generate AI Analysis/i }),
    ).toBeTruthy();
  });

  it('renders the report the backend returned, unchanged', async () => {
    const user = await openDeal();
    await analyze(user);
    await openAi(user);
    await generate(user);

    await waitFor(() => expect(mockAi).toHaveBeenCalledTimes(1));
    expect(await within(aiPanel()).findByText(ANALYSIS.executive_summary)).toBeTruthy();
    expect(within(aiPanel()).getByText(ANALYSIS.strengths[0])).toBeTruthy();
    expect(within(aiPanel()).getByText(ANALYSIS.risks[0])).toBeTruthy();
    // D5.8A: Break-Even Interpretation is no longer among the sections a
    // Lease-Level report offers. It was rendering the model's own wording for
    // "no break-even was supplied" -- honest, but a navigation item whose entire
    // content is a statement of absence is worth less than no item at all, and
    // Lease-Level break-even is unsupported by design. The report itself is
    // unchanged: the backend still returns the field, and this panel simply does
    // not offer a section for it in this mode.
    expect(within(aiPanel()).queryByText(ANALYSIS.break_even_analysis)).toBeNull();
    expect(
      within(aiPanel()).queryByRole('tab', { name: 'Break-Even Interpretation' }),
    ).toBeNull();
  });

  it('sends the current assumptions and the hurdle targets, and nothing else', async () => {
    const user = await openDeal();
    await analyze(user);
    await openAi(user);
    await generate(user);

    await waitFor(() => expect(mockAi).toHaveBeenCalledTimes(1));
    const [terms, inputs, leveredIrr, equityMultiple, headlineDscr, metric, dealContext] =
      mockAi.mock.calls[0];

    expect(terms.purchase_price).toBe(30_000_000);
    expect(inputs.suites).toHaveLength(2);
    expect(inputs.leases).toHaveLength(2);
    expect(typeof leveredIrr).toBe('number');
    expect(typeof equityMultiple).toBe('number');
    expect(typeof headlineDscr).toBe('number');
    expect(metric).toBe('levered_irr');
    expect(dealContext).toBeNull();

    // The client-held results are never shipped back for the model to read:
    // the backend re-runs the one authoritative analysis from these same
    // assumptions, so there is only ever one version of the numbers.
    //
    // Scoped to the two request arguments, not the whole call: `levered_irr`
    // legitimately appears further along as the chosen hurdle *metric*, which
    // is a setting rather than a result.
    const sentRequest = JSON.stringify([mockAi.mock.calls[0][0], mockAi.mock.calls[0][1]]);
    for (const resultField of [
      'levered_irr',
      'unlevered_irr',
      'equity_multiple',
      'headline_dscr',
      'exit_value',
      'net_sale_proceeds',
      'noi_by_year',
      'annual_projection',
      'monthly_projection',
    ]) {
      expect(sentRequest).not.toContain(resultField);
    }
  });
});

// =============================================================================
// 39-41. Staleness -- M14
// =============================================================================

describe('a Lease-Level analysis that has gone stale', () => {
  it('M14/39: editing an assumption clears the AI report with the results', async () => {
    const user = await openDeal();
    await analyze(user);
    await openAi(user);
    await generate(user);
    expect(await within(aiPanel()).findByText(ANALYSIS.executive_summary)).toBeTruthy();

    await editAnAssumption(user);
    await openAi(user);

    // The narrative is gone, and so is the offer to produce one -- the results
    // it described went with the edit.
    expect(within(aiPanel()).queryByText(ANALYSIS.executive_summary)).toBeNull();
    expect(aiPanel().textContent).toContain('Analyze the deal first');
    expect(
      within(aiPanel()).queryByRole('button', { name: /Generate AI Analysis/i }),
    ).toBeNull();
  });

  it('M14/40: never submits a stale analysis after an edit', async () => {
    const user = await openDeal();
    await analyze(user);
    await openAi(user);
    await editAnAssumption(user);
    await openAi(user);

    // There is nothing to press, so nothing can be sent.
    expect(
      within(aiPanel()).queryByRole('button', { name: /Generate AI Analysis/i }),
    ).toBeNull();
    expect(mockAi).not.toHaveBeenCalled();
  });

  it('M14/39a: the previous report does not reappear when results come back', async () => {
    // The mutation this exists for: an edit that clears `results` but leaves
    // `aiAnalysis` standing looks fine while the panel is gated shut -- and
    // then puts the *old* narrative back on screen the moment a fresh Analyze
    // reopens it, beside numbers it was never written about. So the check is
    // made after the gate reopens, which is the only place the defect shows.
    const user = await openDeal();
    await analyze(user);
    await openAi(user);
    await generate(user);
    expect(await within(aiPanel()).findByText(ANALYSIS.executive_summary)).toBeTruthy();

    await editAnAssumption(user);
    await analyze(user);
    await openAi(user);

    // Re-analysed, so the panel is open again -- and empty. The analyst is
    // asked to generate a new interpretation rather than shown the old one.
    expect(
      within(aiPanel()).getByRole('button', { name: /Generate AI Analysis/i }),
    ).toBeTruthy();
    expect(within(aiPanel()).queryByText(ANALYSIS.executive_summary)).toBeNull();
    expect(within(aiPanel()).queryByText(ANALYSIS.risks[0])).toBeNull();
    // Only the first generate ever ran: nothing was regenerated behind the
    // analyst's back, and nothing was kept from before the edit.
    expect(mockAi).toHaveBeenCalledTimes(1);
  });

  it('41: re-analysis restores the AI Analyst', async () => {
    const user = await openDeal();
    await analyze(user);
    await editAnAssumption(user);
    await analyze(user);
    await openAi(user);
    await generate(user);

    await waitFor(() => expect(mockAi).toHaveBeenCalledTimes(1));
    expect(await within(aiPanel()).findByText(ANALYSIS.executive_summary)).toBeTruthy();

    // And the request carried the edited assumption, not the one the first
    // analysis ran on.
    expect(mockAi.mock.calls[0][0].purchase_price).toBe(31_000_000);
  });
});

// =============================================================================
// 45-47. Provider failure, and what this workspace deliberately does not do
// =============================================================================

describe('what the Lease-Level AI Analyst deliberately does not do', () => {
  it('45: reports an unconfigured provider without breaking the analysis', async () => {
    mockAi.mockRejectedValue(new ApiError('The AI Analyst is not configured.'));
    const user = await openDeal();
    await analyze(user);
    await openAi(user);
    await generate(user);

    expect(await within(aiPanel()).findByText(/not configured/i)).toBeTruthy();
    // The deal itself is untouched: results are still there and the action is
    // still offered, because AI is optional decision support.
    expect(
      within(aiPanel()).getByRole('button', { name: /Generate AI Analysis/i }),
    ).toBeTruthy();
  });

  it('45a: reports a failing provider the same way', async () => {
    mockAi.mockRejectedValue(new ApiError('The AI Analyst request failed.'));
    const user = await openDeal();
    await analyze(user);
    await openAi(user);
    await generate(user);

    expect(await within(aiPanel()).findByText(/request failed/i)).toBeTruthy();
  });

  it('46: adds no break-even surface to the Lease-Level AI workspace', async () => {
    const user = await openDeal();
    await analyze(user);
    await openAi(user);

    // No break-even control, tab or panel exists in this mode -- the absence is
    // the honest answer, and a disabled affordance would imply otherwise.
    expect(within(aiPanel()).queryByRole('button', { name: /break.?even/i })).toBeNull();
    expect(within(aiPanel()).queryByRole('tab', { name: /break.?even/i })).toBeNull();
  });

  it('47: triggers no sensitivity run when an analysis is generated', async () => {
    const user = await openDeal();
    await analyze(user);
    await openAi(user);
    await generate(user);

    await waitFor(() => expect(mockAi).toHaveBeenCalledTimes(1));
    // Exactly one analysis, from Analyze. Generating a narrative ran nothing
    // else: sensitivity stays analyst-directed in Risk.
    expect(mockAnalyze).toHaveBeenCalledTimes(1);
  });
});
