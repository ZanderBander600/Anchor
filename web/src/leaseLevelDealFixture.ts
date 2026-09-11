/**
 * D5.8A/D5.8B -- the one saved Lease-Level deal the analytical-state suites
 * drive, and the three analytical artifacts they produce from it.
 *
 * Named without `.test.` because two test files import it:
 * `leaseLevelAnalysisPersistence.test.tsx` (does completed work survive
 * navigation, a refresh and a restart?) and `leaseLevelStaleAnalysis.test.tsx`
 * (once it has survived, does it say whether it is still current?). Those are
 * different claims about the same deal, and a copy of this fixture in each file
 * could drift on the one detail both depend on -- that Deal A's purchase price
 * is exactly 30,000,000, so a test can edit it and put it back.
 *
 * It holds data and one clone helper. Every mock, every driver and every
 * assertion stays in the file that makes the claim: the wiring is what differs
 * between the two suites, and sharing it would couple them where they are
 * genuinely separate.
 */

import type {
  LeaseLevelOneWaySensitivityResult,
  LeaseLevelTwoWaySensitivityResult,
} from './leaseLevelSensitivityTypes';
import type { AIAnalysis, Deal } from './types';

/** A structural copy, so nothing a test hands to the app can be mutated back
 * into the fixture -- or into the fake store -- by reference. */
export function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

// =============================================================================
// The deal, and the three artifacts produced from it
// =============================================================================

export const TERMS = {
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

export const MARKET_LEASING = {
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

export function makeDeal(id: string, name: string): Deal {
  return {
    id,
    name,
    operating_mode: 'lease_level',
    inputs: null,
    detailed_operating_inputs: null,
    terms: { ...TERMS },
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

export const ANALYSIS: AIAnalysis = {
  executive_summary: 'A stabilised suburban asset with staggered rollover.',
  investment_view: 'Proceed, subject to diligence on the 2029 expiries.',
  strengths: ['Staggered lease expiries limit any single-year rollover.'],
  risks: ['Year 1 levered cash flow is negative on lease-up capital.'],
  return_drivers: ['Exit cap rate is the dominant driver.'],
  downside_analysis: 'Coverage holds above the supplied hurdle throughout.',
  capital_structure_analysis: 'Modest leverage with two interest-only years.',
  break_even_analysis: 'Break-even was not supplied for this Lease-Level analysis.',
  questions_to_investigate: ['Confirm the market rent assumption against comparables.'],
  confidence_notes: ['No standardized sensitivity bundle was supplied.'],
  deal_story: null,
};

/** The one-way answer. `metric_values[1]` is `null` on purpose: it must read
 * `N/A` after a restore, never `0.00%`. */
export const ONE_WAY_RESULT: LeaseLevelOneWaySensitivityResult = {
  assumption: 'exit_cap_rate',
  metric: 'levered_irr',
  // The middle candidate IS the baseline, so the Base highlight has a row to
  // sit on and a restore that lost it would be visible.
  baseline_assumption_value: 0.0625,
  baseline_metric_value: 0.142,
  assumption_values: [0.06, 0.0625, 0.07],
  metric_values: [0.1553, 0.142, null],
};

/** 2 rows x 3 columns -- non-square, so a transposed restore is a shape error
 * rather than a silent reorientation. */
export const TWO_WAY_RESULT: LeaseLevelTwoWaySensitivityResult = {
  row_assumption: 'exit_cap_rate',
  column_assumption: 'purchase_price',
  metric: 'levered_irr',
  baseline_row_value: 0.0625,
  baseline_column_value: 30_000_000,
  baseline_metric_value: 0.142,
  row_values: [0.06, 0.065],
  column_values: [29_000_000, 30_000_000, 31_000_000],
  matrix: [
    [0.181, 0.162, 0.145],
    [0.152, 0.134, 0.118],
  ],
};

/**
 * The durable side of the world.
 *
 * `getDeal` serves from here and the three snapshot writers are the only things
 * that put anything in it. Deep-cloned on the way out so nothing the app is
 * handed can be mutated back into "storage" by reference -- which would let a
 * purely in-memory implementation appear to persist.
 */
