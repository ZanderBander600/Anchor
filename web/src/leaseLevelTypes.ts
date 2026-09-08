/**
 * D5.5A -- the Lease-Level transport and form contracts.
 *
 * Kept out of `types.ts` deliberately. Lease-Level adds six contracts and five
 * enums to a file that is already the hand-maintained mirror of every other
 * backend shape; folding them in would roughly double it for one mode. Nothing
 * existing moves here — Quick and Detailed types stay exactly where they are.
 *
 * Two layers, and the split matters:
 *
 * * **Transport** types mirror the wire exactly — backend field names,
 *   `snake_case`, enum wire tokens, decimal rates. Never renamed for
 *   convenience: the API is the contract, and a "nicer" client-side spelling is
 *   a second vocabulary that has to be kept in step by hand.
 * * **Form** types are what the analyst edits — strings, percent-scale, keyed in
 *   `camelCase` like every other Anchor form. Conversion happens once, on
 *   submit, through the shared helpers in `convert.ts`.
 *
 * The suite and lease transport types are introduced now, ahead of their
 * editors, because D5.5A must *hold* a loaded rent roll intact through scalar
 * edits even though it cannot yet change one.
 */

import type { AcquisitionResults, AcquisitionTermsRequest } from './types';

// =============================================================================
// Enum wire tokens
//
// The exact strings `anchor.leasing.contracts` serialises. Declared as unions
// rather than TypeScript enums so a value read off an API response is checked
// structurally, matching how every other Anchor transport type is written.
// =============================================================================

export type LeaseType = 'nnn' | 'gross' | 'modified_gross';
export type RecoveryBasis = 'expense_stop_psf';
export type EscalationBasis = 'none' | 'lease_anniversary';
export type LeaseOrigin = 'in_place' | 'successor';
export type LeasingCommissionMethod = 'pct_of_total_contractual_base_rent';
export type InitialVacancyStrategy = 'hold_vacant' | 'market_lease_up';

// =============================================================================
// Transport contracts
// =============================================================================

/** Mirrors ``LeaseLevelPropertyInputs`` in ``anchor/leasing/contracts.py``. */
export interface LeaseLevelPropertyInputsRequest {
  /** ISO-8601 `YYYY-MM-DD`. Sent exactly as entered -- month alignment is a
   * backend rule (`ANALYSIS_START_NOT_MONTH_ALIGNED`), never a client-side
   * correction. */
  analysis_start_date: string;
  rentable_area_sf: number;
}

/** Mirrors ``LeaseLevelOperatingInputs``. Eleven fields, all required on the
 * wire; `credit_loss_pct` has a contract default the backend applies when the
 * key is absent, which this client never relies on. */
export interface LeaseLevelOperatingInputsRequest {
  other_income: number;
  other_income_growth: number;
  credit_loss_pct: number;
  property_taxes: number;
  insurance: number;
  utilities: number;
  repairs_maintenance: number;
  other_operating_expenses: number;
  management_fee_pct: number;
  expense_growth: number;
  recoverable_expense_ratio: number;
}

/** Mirrors ``MarketLeasingAssumptions`` -- twenty-three fields, none optional.
 *
 * `renewal_rent_psf` and the two expense stops are *required but nullable*: on
 * this contract "stated as absent" and "not stated" are different facts, so the
 * key is always sent and `null` is a real value. */
export interface MarketLeasingAssumptionsRequest {
  market_rent_psf: number;
  market_rent_growth: number;
  renewal_rent_psf: number | null;
  renewal_rent_spread: number;
  renewal_term_months: number;
  successor_escalation_pct: number;
  renewal_downtime_months: number;
  renewal_free_rent_months: number;
  new_term_months: number;
  new_downtime_months: number;
  new_free_rent_months: number;
  renewal_ti_psf: number;
  new_ti_psf: number;
  leasing_commission_method: LeasingCommissionMethod;
  renewal_lc_pct: number;
  new_lc_pct: number;
  renewal_probability: number;
  renewal_lease_type: LeaseType;
  renewal_recovery_basis: RecoveryBasis | null;
  renewal_expense_stop_psf: number | null;
  new_lease_type: LeaseType;
  new_recovery_basis: RecoveryBasis | null;
  new_expense_stop_psf: number | null;
}

/** Mirrors ``InitialVacancyAssumptions``. */
export interface InitialVacancyAssumptionsRequest {
  strategy: InitialVacancyStrategy;
  initial_lease_up_months: number | null;
}

/** Mirrors ``Suite``. `market_leasing_override` is all-or-nothing by design --
 * a whole record or `null`, never a partial one. */
export interface SuiteRequest {
  suite_id: string;
  suite_area_sf: number;
  suite_label: string | null;
  market_rent_psf: number | null;
  market_leasing_override: MarketLeasingAssumptionsRequest | null;
  initial_vacancy: InitialVacancyAssumptionsRequest | null;
}

/** Mirrors ``Lease``. */
export interface LeaseRequest {
  lease_id: string;
  suite_id: string;
  leased_area_sf: number;
  rent_commencement_date: string;
  lease_expiration_date: string;
  base_rent_psf: number;
  escalation_pct: number;
  escalation_basis: EscalationBasis;
  lease_type: LeaseType;
  tenant_name: string | null;
  lease_start_date: string | null;
  origin: LeaseOrigin;
  recovery_basis: RecoveryBasis | null;
  expense_stop_psf: number | null;
}

/** The five Lease-Level input objects of a request body.
 *
 * `terms` is deliberately not a member: `AcquisitionTerms` is shared with
 * Detailed and travels beside these, exactly as the backend's
 * `ParsedLeaseLevelInputs` excludes it for the same reason. */
export interface LeaseLevelInputsRequest {
  property_inputs: LeaseLevelPropertyInputsRequest;
  operating_inputs: LeaseLevelOperatingInputsRequest;
  market_leasing: MarketLeasingAssumptionsRequest;
  suites: SuiteRequest[];
  leases: LeaseRequest[];
}

// =============================================================================
// Validation issues
//
// The Lease-Level 422 detail is deliberately NOT the Quick/Detailed
// `ValidationIssue` shape. That one names a flat `field_id`; this one names a
// `path` into a nested, variable-arity rent roll (`suites[2].suite_area_sf`)
// plus a stable `code`. `api.py:_lease_validation_error_detail` says why at
// length: flattening either into the other throws away exactly the part a
// consumer needs to anchor an error to the row that caused it.
//
// One endpoint can return either shape. `terms` is validated by the shared
// `validate_acquisition_terms`, which raises the Quick-shaped error, while
// everything else raises this one -- so the client parses the detail array by
// shape rather than assuming a mode implies a schema.
// =============================================================================

/** Mirrors ``LeaseValidationIssue``. `severity` is `'error'` for every issue
 * the parser raises and for every domain failure; `'warning'` is a convention
 * notice that does not block analysis. */
export interface LeaseLevelIssue {
  code: string;
  /** Dotted/indexed locator: `''` for a whole-submission issue,
   * `market_leasing.renewal_probability` for a scalar,
   * `suites[2].suite_area_sf` for a row field, `leases[0]` for a whole row. */
  path: string;
  message: string;
  severity: 'error' | 'warning';
}

// =============================================================================
// Response contract
//
// Mirrored faithfully now so D5.6 can render it without a second typing pass.
// Every series is `number[]`; a metric the engine could not define arrives as
// `null` and stays `null` -- notably `levered_irr`, which is legitimately
// undefined whenever rollover-year TI/LC give the levered cash flows more than
// one sign change.
// =============================================================================

/** Mirrors ``ModelMonth``. */
export interface ModelMonth {
  period_index: number;
  month_start: string;
  hold_year: number;
  is_forward_exit_month: boolean;
}

/** Mirrors the shipped 26-field ``MonthlyPropertyProjection``.
 *
 * The three audit sub-schedules (`operating_schedule`, `recovery_schedule`,
 * `expense_schedule`) are intentionally not expanded: D5.5A renders nothing,
 * D5.6 renders the series below, and no gate has yet specified a UI for the
 * per-suite audit trail. Typing them would be inventing a contract for a screen
 * nobody has designed. */
export interface MonthlyPropertyProjection {
  months: ModelMonth[];
  rentable_area_sf: number;
  contractual_base_rent: number[];
  free_rent: number[];
  cash_base_rent: number[];
  expense_recovery: number[];
  other_income: number[];
  credit_loss: number[];
  effective_gross_income: number[];
  property_taxes: number[];
  insurance: number[];
  utilities: number[];
  repairs_maintenance: number[];
  other_operating_expenses: number[];
  fixed_operating_expenses: number[];
  management_fee: number[];
  total_operating_expenses: number[];
  noi: number[];
  tenant_improvements: number[];
  leasing_commissions: number[];
  occupied_area_sf: number[];
  vacant_area_sf: number[];
  physical_occupancy: number[];
}

/** Mirrors ``AnnualOperatingProjection``. */
export interface AnnualOperatingProjection {
  contractual_base_rent_by_year: number[];
  free_rent_by_year: number[];
  cash_base_rent_by_year: number[];
  expense_recovery_by_year: number[];
  other_income_by_year: number[];
  credit_loss_by_year: number[];
  effective_gross_income_by_year: number[];
  property_taxes_by_year: number[];
  insurance_by_year: number[];
  utilities_by_year: number[];
  repairs_maintenance_by_year: number[];
  other_operating_expenses_by_year: number[];
  fixed_operating_expenses_by_year: number[];
  management_fee_by_year: number[];
  total_operating_expenses_by_year: number[];
  noi_by_year: number[];
  tenant_improvements_by_year: number[];
  leasing_commissions_by_year: number[];
  occupied_area_sf_at_year_end: number[];
  vacant_area_sf_at_year_end: number[];
  physical_occupancy_at_year_end: number[];
  average_physical_occupancy_over_year: number[];
  exit_noi: number;
  going_in_cap_rate: number;
  exit_window_leasing_costs: number;
}

/** Mirrors ``LeaseLevelAcquisitionResults`` -- the three authoritative surfaces
 * `POST /analyze` returns for `operating_mode: "lease_level"`. `results` is the
 * same generic `AcquisitionResults` Quick and Detailed produce. */
export interface LeaseLevelAcquisitionResults {
  monthly_projection: MonthlyPropertyProjection;
  annual_projection: AnnualOperatingProjection;
  results: AcquisitionResults;
}

// =============================================================================
// Form state
//
// Strings, percent-scale, `camelCase` -- the same shape `AcquisitionFormValues`
// and `DetailedOperatingFormValues` already use, so the shared field grid,
// parsers and blank-form conventions all apply unchanged.
//
// Enum fields are `string` rather than their wire union precisely so an
// unselected control can hold `''`. A select that defaulted to its first option
// would be choosing an underwriting assumption -- NNN over Gross, say -- on the
// analyst's behalf, silently.
// =============================================================================

export interface LeaseLevelPropertyFormValues {
  analysisStartDate: string;
  rentableAreaSf: string;
}

export interface LeaseLevelOperatingFormValues {
  otherIncome: string;
  otherIncomeGrowth: string;
  creditLossPct: string;
  propertyTaxes: string;
  insurance: string;
  utilities: string;
  repairsMaintenance: string;
  otherOperatingExpenses: string;
  managementFeePct: string;
  expenseGrowth: string;
  recoverableExpenseRatio: string;
}

export interface MarketLeasingFormValues {
  marketRentPsf: string;
  marketRentGrowth: string;
  renewalRentPsf: string;
  renewalRentSpread: string;
  renewalTermMonths: string;
  successorEscalationPct: string;
  renewalDowntimeMonths: string;
  renewalFreeRentMonths: string;
  newTermMonths: string;
  newDowntimeMonths: string;
  newFreeRentMonths: string;
  renewalTiPsf: string;
  newTiPsf: string;
  leasingCommissionMethod: string;
  renewalLcPct: string;
  newLcPct: string;
  renewalProbability: string;
  renewalLeaseType: string;
  renewalRecoveryBasis: string;
  renewalExpenseStopPsf: string;
  newLeaseType: string;
  newRecoveryBasis: string;
  newExpenseStopPsf: string;
}

// =============================================================================
// D5.5B -- the editable rent roll
//
// The transport keeps two flat arrays, `suites` and `leases`, exactly as the
// engine contract defines them. The *form* keeps one row per suite with its
// lease folded in, because D4 acquisition supports at most one known lease per
// suite, so a suite-centric row matches the capability exactly and spares the
// analyst maintaining two tables cross-referenced by hand on `suite_id`.
//
// This is UI composition only. Nothing about the wire contract changes, and
// `buildLeaseLevelInputsRequest` unfolds these rows back into the two arrays.
// =============================================================================

/** One lease, as the analyst edits it.
 *
 * `suite_id` is deliberately absent: the row owns it, so a lease cannot come to
 * reference a suite that is not its own, and `UNKNOWN_SUITE_REFERENCE` becomes
 * unreachable by construction rather than by validation.
 *
 * `origin` is *held*, not edited. `SUCCESSOR` marks a lease the rollover engine
 * generated -- an assumption about what follows an expiry, never a signed
 * tenancy -- so offering it as a choice would invite an analyst to hand-enter a
 * derived state. It is carried through unchanged so loaded data is never
 * silently rewritten. */
export interface LeaseFormValues {
  leaseId: string;
  leasedAreaSf: string;
  tenantName: string;
  leaseStartDate: string;
  rentCommencementDate: string;
  leaseExpirationDate: string;
  baseRentPsf: string;
  escalationPct: string;
  escalationBasis: string;
  leaseType: string;
  recoveryBasis: string;
  expenseStopPsf: string;
  /** Held verbatim from whatever was loaded; `'in_place'` for a lease the
   * analyst creates. Never presented as an editable control. */
  origin: LeaseOrigin;
}

/** How one vacant suite is underwritten.
 *
 * `initialLeaseUpMonths` is kept even while the strategy is `hold_vacant`, where
 * the contract requires it absent. Holding it locally means toggling the
 * strategy twice does not destroy a number the analyst typed; the conversion
 * drops it on the way out, so a stale value can never reach the wire. */
export interface InitialVacancyFormValues {
  strategy: string;
  initialLeaseUpMonths: string;
}

/**
 * One rent-roll row: a suite, and the one lease it may carry.
 *
 * **Occupancy has no field of its own.** A row is occupied exactly when
 * `lease !== null`, which is the same rule the engine applies (a vacant suite is
 * a suite no lease covers, never a synthetic vacant-lease row). An
 * `occupied: true` flag would be a second authority that could disagree with the
 * lease it describes.
 *
 * Three pieces of state are deliberately kept while inactive, because the
 * contract cannot represent them and losing them would punish an analyst for
 * toggling a control: `initialVacancy` while the row is occupied,
 * `initialLeaseUpMonths` while the strategy is `hold_vacant`, and
 * `marketLeasingOverride` while `marketLeasingOverrideEnabled` is false. The
 * conversion submits `null` for each, so no dormant value ever reaches the wire.
 */
export interface SuiteRowFormValues {
  /** Local UI identity. Never submitted, never persisted, never fingerprinted,
   * and never an underwriting assumption -- it exists only because `suiteId` is
   * an analyst-editable field that is legitimately blank or duplicated while a
   * row is being typed, and React needs a stable key that is none of those
   * things. */
  rowId: string;
  suiteId: string;
  suiteAreaSf: string;
  suiteLabel: string;
  marketRentPsf: string;
  lease: LeaseFormValues | null;
  initialVacancy: InitialVacancyFormValues;
  marketLeasingOverrideEnabled: boolean;
  marketLeasingOverride: MarketLeasingFormValues;
}

/**
 * Everything a Lease-Level deal holds while it is being edited.
 *
 * **Changed at D5.5B.** D5.5A held `suites` and `leases` as transport values and
 * passed them through untouched, because it had no editor and converting a
 * loaded rent roll into strings and back would have risked altering it on a
 * screen that never showed it. D5.5B has the editor, so the rows become form
 * values -- and the protection D5.5A bought with pass-through is now bought by a
 * stronger, directly tested claim: a loaded deal opened and saved with no edits
 * round-trips byte-identically through the form.
 */
export interface LeaseLevelFormValues {
  terms: import('./types').AcquisitionTermsFormValues;
  property: LeaseLevelPropertyFormValues;
  operating: LeaseLevelOperatingFormValues;
  marketLeasing: MarketLeasingFormValues;
  rentRoll: SuiteRowFormValues[];
  /** Lease ids in the order the loaded deal carried them.
   *
   * The transport's `leases` array order is independent of `suites` order and
   * the backend preserves it exactly (verified against the live API), so folding
   * leases into suite rows and unfolding them in row order would silently
   * reorder a saved rent roll on open-and-save. This replays the loaded order;
   * leases not named here -- new ones, and ones whose id was retyped -- follow in
   * row order. It carries no economics and is never submitted. */
  leaseOrder: string[];
  /** Leases a loaded deal carried that no suite row could claim: a second lease
   * on one suite, or one naming a suite that is not in the roll.
   *
   * Neither can be created here and neither can be saved through the D5.4
   * endpoints, which refuse both -- so this is corrupt or externally-written
   * data. It is resubmitted **verbatim** rather than dropped, so the backend
   * still reports `MULTIPLE_KNOWN_LEASES_IN_SUITE` or
   * `UNKNOWN_SUITE_REFERENCE` on it. Quietly discarding the extra lease would
   * repair persisted data behind the analyst's back and hide a real defect. */
  unmatchedLeases: LeaseRequest[];
}

/** A saved Lease-Level deal as `GET /deals/{id}` returns it. */
export interface LeaseLevelDealFields {
  terms: AcquisitionTermsRequest;
  property_inputs: LeaseLevelPropertyInputsRequest;
  operating_inputs: LeaseLevelOperatingInputsRequest;
  market_leasing: MarketLeasingAssumptionsRequest;
  suites: SuiteRequest[];
  leases: LeaseRequest[];
}
