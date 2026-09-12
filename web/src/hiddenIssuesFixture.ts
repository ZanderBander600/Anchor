/**
 * D5.5D -- the shared rent-roll fixture.
 *
 * Three suites: a Modified Gross lease carrying a real expense stop, a plain
 * NNN lease, and a suite held vacant. The first is what makes the reproduction
 * reachable -- switching its type hides controls over stored data.
 *
 * Extracted so the behaviour tests and the mutation tests describe the same
 * property; two fixtures drifting apart would let a mutant pass in one file
 * while failing in the other.
 */

import type { LeaseLevelAcquisitionResults, LeaseLevelIssue } from './leaseLevelTypes';
import type { Deal } from './types';

export const MARKET = {
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
} as const;

export function savedDeal(): Deal {
  return {
    id: 'deal-1',
    name: 'Fulton Exchange',
    operating_mode: 'lease_level',
    inputs: null,
    detailed_operating_inputs: null,
    terms: {
      purchase_price: 20_000_000,
      hold_period: 5,
      exit_cap_rate: 0.065,
      ltv: 0.6,
      interest_rate: 0.055,
      amortization: 30,
      acquisition_cost_pct: 0,
      financing_fee_pct: 0,
      disposition_cost_pct: 0,
      annual_capex_reserve: 0,
      io_period: 0,
    },
    property_inputs: { analysis_start_date: '2027-01-01', rentable_area_sf: 30_000 },
    operating_inputs: {
      other_income: 50_000,
      other_income_growth: 0.02,
      credit_loss_pct: 0.01,
      property_taxes: 200_000,
      insurance: 30_000,
      utilities: 60_000,
      repairs_maintenance: 40_000,
      other_operating_expenses: 20_000,
      management_fee_pct: 0.03,
      expense_growth: 0.03,
      recoverable_expense_ratio: 0.8,
    },
    market_leasing: { ...MARKET },
    suites: [
      {
        suite_id: '100',
        suite_area_sf: 12_000,
        suite_label: null,
        market_rent_psf: null,
        market_leasing_override: null,
        initial_vacancy: null,
      },
      {
        suite_id: '200',
        suite_area_sf: 10_000,
        suite_label: null,
        market_rent_psf: null,
        market_leasing_override: null,
        initial_vacancy: null,
      },
      {
        suite_id: '300',
        suite_area_sf: 8_000,
        suite_label: null,
        market_rent_psf: null,
        market_leasing_override: null,
        initial_vacancy: { strategy: 'hold_vacant', initial_lease_up_months: null },
      },
    ],
    leases: [
      {
        lease_id: 'L-100',
        suite_id: '100',
        leased_area_sf: 12_000,
        rent_commencement_date: '2024-01-01',
        lease_expiration_date: '2030-12-31',
        base_rent_psf: 28,
        escalation_pct: 0.03,
        escalation_basis: 'lease_anniversary',
        lease_type: 'modified_gross',
        tenant_name: 'Marlow Provisions',
        lease_start_date: null,
        origin: 'in_place',
        recovery_basis: 'expense_stop_psf',
        expense_stop_psf: 9.5,
      },
      {
        lease_id: 'L-200',
        suite_id: '200',
        leased_area_sf: 10_000,
        rent_commencement_date: '2024-01-01',
        lease_expiration_date: '2030-12-31',
        base_rent_psf: 30,
        escalation_pct: 0.03,
        escalation_basis: 'lease_anniversary',
        lease_type: 'nnn',
        tenant_name: 'Halbrook Analytics',
        lease_start_date: null,
        origin: 'in_place',
        recovery_basis: null,
        expense_stop_psf: null,
      },
    ],
    deal_context: null,
    business_plan: { capital_items: [], owner_expense_items: [] },
    analysis_snapshot: null,
    ai_snapshot: null,
    one_way_sensitivity_snapshot: null,
    two_way_sensitivity_snapshot: null,
    created_at: '2027-01-04T09:00:00+00:00',
    updated_at: '2027-01-04T09:00:00+00:00',
  };
}

export function results(): LeaseLevelAcquisitionResults {
  return {
    monthly_projection: {} as LeaseLevelAcquisitionResults['monthly_projection'],
    annual_projection: {} as LeaseLevelAcquisitionResults['annual_projection'],
    results: {} as LeaseLevelAcquisitionResults['results'],
  };
}

/** The issue D5.5C now returns for a lease that kept a stop after switching
 * away from Modified Gross -- verbatim in shape, message shortened. */
export const HIDDEN_RECOVERY_ISSUE: LeaseLevelIssue = {
  code: 'RECOVERY_BASIS_ON_NON_MODIFIED_GROSS',
  path: 'leases[0].recovery_basis',
  message:
    "lease 'L-100' is nnn but carries a recovery basis or expense stop. A lease " +
    'with a contractual expense stop is MODIFIED_GROSS in Anchor, not NNN or GROSS.',
  severity: 'error',
};

