import { describe, expect, it } from 'vitest';
import {
  BLANK_FORM_VALUES,
  buildAcquisitionRequest,
  buildApprovedFormValues,
  buildFormValuesFromAcquisitionInputs,
  buildFormValuesFromExcelIntakeReport,
  buildV2ReviewMessage,
  candidateValueToFormValue,
  DEFAULT_FORM_VALUES,
  FormValidationError,
  V2_GOLDEN_FORM_VALUES,
} from './convert';
import type { ExcelIntakeReport } from './types';

describe('buildAcquisitionRequest', () => {
  it('converts the golden-deal defaults to the API decimal contract', () => {
    const request = buildAcquisitionRequest(DEFAULT_FORM_VALUES);

    expect(request).toEqual({
      purchase_price: 50_000_000,
      current_noi: 2_500_000,
      occupancy: 0.95,
      noi_growth: 0.03,
      hold_period: 5,
      exit_cap_rate: 0.055,
      ltv: 0.65,
      interest_rate: 0.0525,
      amortization: 30,
      acquisition_cost_pct: 0,
      financing_fee_pct: 0,
      disposition_cost_pct: 0,
      annual_capex_reserve: 0,
      io_period: 0,
    });
  });

  it('converts the V2 golden-case defaults to the API decimal contract', () => {
    const request = buildAcquisitionRequest(V2_GOLDEN_FORM_VALUES);

    expect(request).toEqual({
      purchase_price: 10_000_000,
      current_noi: 600_000,
      occupancy: 0.95,
      noi_growth: 0.03,
      hold_period: 5,
      exit_cap_rate: 0.065,
      ltv: 0.6,
      interest_rate: 0.05,
      amortization: 30,
      acquisition_cost_pct: 0.02,
      financing_fee_pct: 0.01,
      disposition_cost_pct: 0.025,
      annual_capex_reserve: 50_000,
      io_period: 2,
    });
  });

  it('converts analyst-facing percentages to decimals generally', () => {
    const request = buildAcquisitionRequest({
      ...DEFAULT_FORM_VALUES,
      occupancy: '92.5',
      exitCapRate: '6',
      ltv: '70',
      interestRate: '4.75',
      acquisitionCostPct: '2',
      financingFeePct: '1',
      dispositionCostPct: '2.5',
    });

    expect(request.occupancy).toBeCloseTo(0.925);
    expect(request.exit_cap_rate).toBeCloseTo(0.06);
    expect(request.ltv).toBeCloseTo(0.7);
    expect(request.interest_rate).toBeCloseTo(0.0475);
    expect(request.acquisition_cost_pct).toBeCloseTo(0.02);
    expect(request.financing_fee_pct).toBeCloseTo(0.01);
    expect(request.disposition_cost_pct).toBeCloseTo(0.025);
  });

  it('throws a FormValidationError for a blank required field', () => {
    expect(() =>
      buildAcquisitionRequest({ ...DEFAULT_FORM_VALUES, purchasePrice: '' }),
    ).toThrow(FormValidationError);
  });

  it('throws a FormValidationError for a non-numeric field', () => {
    expect(() =>
      buildAcquisitionRequest({ ...DEFAULT_FORM_VALUES, currentNoi: 'abc' }),
    ).toThrow(FormValidationError);
  });

  it('rejects an entirely blank form (BLANK_FORM_VALUES, U10) rather than treating any field as zero', () => {
    let error: unknown;
    try {
      buildAcquisitionRequest(BLANK_FORM_VALUES);
    } catch (caught) {
      error = caught;
    }

    expect(error).toBeInstanceOf(FormValidationError);
    expect((error as FormValidationError).message).toBe('Purchase Price is required.');
  });

  describe('Underwriting V2 fields (Gate 6)', () => {
    it.each([
      ['acquisitionCostPct', 'Acquisition Costs is required.'],
      ['financingFeePct', 'Financing Fee is required.'],
      ['dispositionCostPct', 'Disposition Costs is required.'],
      ['annualCapexReserve', 'Annual CapEx Reserve is required.'],
      ['ioPeriod', 'Interest-Only Period is required.'],
    ] as const)('a blank %s blocks the request with a clear message', (key, message) => {
      expect(() => buildAcquisitionRequest({ ...V2_GOLDEN_FORM_VALUES, [key]: '' })).toThrow(
        FormValidationError,
      );
      let error: unknown;
      try {
        buildAcquisitionRequest({ ...V2_GOLDEN_FORM_VALUES, [key]: '' });
      } catch (caught) {
        error = caught;
      }
      expect((error as FormValidationError).message).toBe(message);
    });

    it('accepts an explicit 0 for every V2 field (distinct from blank)', () => {
      const request = buildAcquisitionRequest({
        ...V2_GOLDEN_FORM_VALUES,
        acquisitionCostPct: '0',
        financingFeePct: '0',
        dispositionCostPct: '0',
        annualCapexReserve: '0',
        ioPeriod: '0',
      });

      expect(request.acquisition_cost_pct).toBe(0);
      expect(request.financing_fee_pct).toBe(0);
      expect(request.disposition_cost_pct).toBe(0);
      expect(request.annual_capex_reserve).toBe(0);
      expect(request.io_period).toBe(0);
    });

    it('rejects a fractional io_period', () => {
      expect(() =>
        buildAcquisitionRequest({ ...V2_GOLDEN_FORM_VALUES, ioPeriod: '2.5' }),
      ).toThrow(FormValidationError);
      expect(() =>
        buildAcquisitionRequest({ ...V2_GOLDEN_FORM_VALUES, ioPeriod: '2.5' }),
      ).toThrow('Interest-Only Period must be a whole number.');
    });

    it('accepts io_period greater than hold_period -- not a validation rule this layer enforces', () => {
      const request = buildAcquisitionRequest({
        ...V2_GOLDEN_FORM_VALUES,
        holdPeriod: '5',
        ioPeriod: '10',
      });

      expect(request.io_period).toBe(10);
      expect(request.hold_period).toBe(5);
    });
  });
});

describe('BLANK_FORM_VALUES', () => {
  it('is entirely blank strings, distinct from the golden-deal defaults', () => {
    expect(Object.values(BLANK_FORM_VALUES).every((value) => value === '')).toBe(true);
    expect(BLANK_FORM_VALUES).not.toEqual(DEFAULT_FORM_VALUES);
  });

  it('includes all five V2 fields, blank', () => {
    expect(BLANK_FORM_VALUES.acquisitionCostPct).toBe('');
    expect(BLANK_FORM_VALUES.financingFeePct).toBe('');
    expect(BLANK_FORM_VALUES.dispositionCostPct).toBe('');
    expect(BLANK_FORM_VALUES.annualCapexReserve).toBe('');
    expect(BLANK_FORM_VALUES.ioPeriod).toBe('');
  });
});

describe('candidateValueToFormValue', () => {
  it('passes an absolute-magnitude value through unscaled', () => {
    expect(candidateValueToFormValue('purchase_price', '$1,250,000')).toBe('1250000');
    expect(candidateValueToFormValue('hold_period', '5')).toBe('5');
  });

  it('converts a percent-scale decimal fraction to a percent-scale number', () => {
    expect(candidateValueToFormValue('exit_cap_rate', '0.055')).toBe('5.5');
    expect(candidateValueToFormValue('occupancy', '0.95')).toBe('95');
  });

  it('leaves a percent-scale literal percentage unscaled', () => {
    expect(candidateValueToFormValue('exit_cap_rate', '5.5%')).toBe('5.5');
    expect(candidateValueToFormValue('ltv', '65%')).toBe('65');
  });

  it('treats a bare percent-scale number greater than 1 as already percent-scale', () => {
    expect(candidateValueToFormValue('interest_rate', '5.25')).toBe('5.25');
  });

  it('returns null for an unparseable value', () => {
    expect(candidateValueToFormValue('purchase_price', 'not a number')).toBeNull();
  });
});

describe('buildApprovedFormValues', () => {
  it('converts only the approved fields, excluding unapproved fields entirely', () => {
    const result = buildApprovedFormValues({
      purchase_price: '1000000',
      exit_cap_rate: '5.5%',
    });

    expect(result).toEqual({
      purchasePrice: '1000000',
      exitCapRate: '5.5',
    });
    expect(result).not.toHaveProperty('currentNoi');
    expect(result).not.toHaveProperty('ltv');
  });

  it('excludes a field whose approved value cannot be parsed as a number', () => {
    const result = buildApprovedFormValues({ purchase_price: 'garbage' });

    expect(result).toEqual({});
  });

  it('returns an empty object when nothing was approved', () => {
    expect(buildApprovedFormValues({})).toEqual({});
  });

  it('never produces any of the five V2 form keys -- OM extraction does not cover them (Gate 6)', () => {
    const result = buildApprovedFormValues({
      purchase_price: '1000000',
      exit_cap_rate: '5.5%',
    });

    expect(result).not.toHaveProperty('acquisitionCostPct');
    expect(result).not.toHaveProperty('financingFeePct');
    expect(result).not.toHaveProperty('dispositionCostPct');
    expect(result).not.toHaveProperty('annualCapexReserve');
    expect(result).not.toHaveProperty('ioPeriod');
  });
});

describe('buildFormValuesFromAcquisitionInputs', () => {
  it('converts the golden-deal API contract back to the form defaults', () => {
    const values = buildFormValuesFromAcquisitionInputs({
      purchase_price: 50_000_000,
      current_noi: 2_500_000,
      occupancy: 0.95,
      noi_growth: 0.03,
      hold_period: 5,
      exit_cap_rate: 0.055,
      ltv: 0.65,
      interest_rate: 0.0525,
      amortization: 30,
      acquisition_cost_pct: 0,
      financing_fee_pct: 0,
      disposition_cost_pct: 0,
      annual_capex_reserve: 0,
      io_period: 0,
    });

    expect(values).toEqual(DEFAULT_FORM_VALUES);
  });

  it('converts the V2 golden-case API contract back to the V2 form fixture', () => {
    const values = buildFormValuesFromAcquisitionInputs({
      purchase_price: 10_000_000,
      current_noi: 600_000,
      occupancy: 0.95,
      noi_growth: 0.03,
      hold_period: 5,
      exit_cap_rate: 0.065,
      ltv: 0.6,
      interest_rate: 0.05,
      amortization: 30,
      acquisition_cost_pct: 0.02,
      financing_fee_pct: 0.01,
      disposition_cost_pct: 0.025,
      annual_capex_reserve: 50_000,
      io_period: 2,
    });

    expect(values).toEqual(V2_GOLDEN_FORM_VALUES);
  });

  it('always includes all fourteen fields', () => {
    const values = buildFormValuesFromAcquisitionInputs({
      purchase_price: 1,
      current_noi: 0,
      occupancy: 0,
      noi_growth: -0.5,
      hold_period: 1,
      exit_cap_rate: 0.01,
      ltv: 0,
      interest_rate: 0,
      amortization: 1,
      acquisition_cost_pct: 0,
      financing_fee_pct: 0,
      disposition_cost_pct: 0,
      annual_capex_reserve: 0,
      io_period: 0,
    });

    expect(Object.keys(values).sort()).toEqual(
      [
        'purchasePrice',
        'currentNoi',
        'occupancy',
        'noiGrowth',
        'holdPeriod',
        'exitCapRate',
        'ltv',
        'interestRate',
        'amortization',
        'acquisitionCostPct',
        'financingFeePct',
        'dispositionCostPct',
        'annualCapexReserve',
        'ioPeriod',
      ].sort(),
    );
  });

  it('renders a real persisted/parsed zero as "0", never blank', () => {
    const values = buildFormValuesFromAcquisitionInputs({
      purchase_price: 1,
      current_noi: 0,
      occupancy: 0,
      noi_growth: -0.5,
      hold_period: 1,
      exit_cap_rate: 0.01,
      ltv: 0,
      interest_rate: 0,
      amortization: 1,
      acquisition_cost_pct: 0,
      financing_fee_pct: 0,
      disposition_cost_pct: 0,
      annual_capex_reserve: 0,
      io_period: 0,
    });

    expect(values.acquisitionCostPct).toBe('0');
    expect(values.financingFeePct).toBe('0');
    expect(values.dispositionCostPct).toBe('0');
    expect(values.annualCapexReserve).toBe('0');
    expect(values.ioPeriod).toBe('0');
  });

  it('does not leak binary floating-point noise from the percent-scale conversion', () => {
    const values = buildFormValuesFromAcquisitionInputs({
      purchase_price: 1,
      current_noi: 1,
      occupancy: 0.1,
      noi_growth: 0.29,
      hold_period: 1,
      exit_cap_rate: 0.01,
      ltv: 0.7,
      interest_rate: 0.0475,
      amortization: 1,
      acquisition_cost_pct: 0.29,
      financing_fee_pct: 0.1,
      disposition_cost_pct: 0.7,
      annual_capex_reserve: 1,
      io_period: 1,
    });

    expect(values.occupancy).toBe('10');
    expect(values.noiGrowth).toBe('29');
    expect(values.ltv).toBe('70');
    expect(values.interestRate).toBe('4.75');
    expect(values.acquisitionCostPct).toBe('29');
    expect(values.financingFeePct).toBe('10');
    expect(values.dispositionCostPct).toBe('70');
  });

  it('round-trips through buildAcquisitionRequest', () => {
    const request = buildAcquisitionRequest(V2_GOLDEN_FORM_VALUES);
    const roundTripped = buildAcquisitionRequest(buildFormValuesFromAcquisitionInputs(request));

    expect(roundTripped.purchase_price).toBeCloseTo(request.purchase_price);
    expect(roundTripped.current_noi).toBeCloseTo(request.current_noi);
    expect(roundTripped.occupancy).toBeCloseTo(request.occupancy);
    expect(roundTripped.noi_growth).toBeCloseTo(request.noi_growth);
    expect(roundTripped.hold_period).toBeCloseTo(request.hold_period);
    expect(roundTripped.exit_cap_rate).toBeCloseTo(request.exit_cap_rate);
    expect(roundTripped.ltv).toBeCloseTo(request.ltv);
    expect(roundTripped.interest_rate).toBeCloseTo(request.interest_rate);
    expect(roundTripped.amortization).toBeCloseTo(request.amortization);
    expect(roundTripped.acquisition_cost_pct).toBeCloseTo(request.acquisition_cost_pct);
    expect(roundTripped.financing_fee_pct).toBeCloseTo(request.financing_fee_pct);
    expect(roundTripped.disposition_cost_pct).toBeCloseTo(request.disposition_cost_pct);
    expect(roundTripped.annual_capex_reserve).toBeCloseTo(request.annual_capex_reserve);
    expect(roundTripped.io_period).toBeCloseTo(request.io_period);
  });
});

describe('buildFormValuesFromExcelIntakeReport (Underwriting V2 Gate 6)', () => {
  it('populates all fourteen fields normally when nothing was defaulted', () => {
    const report: ExcelIntakeReport = {
      inputs: buildAcquisitionRequest(V2_GOLDEN_FORM_VALUES),
      defaulted_v2_field_ids: [],
    };

    expect(buildFormValuesFromExcelIntakeReport(report)).toEqual(V2_GOLDEN_FORM_VALUES);
  });

  it('leaves exactly the defaulted V2 fields blank, populating everything else normally', () => {
    const report: ExcelIntakeReport = {
      inputs: buildAcquisitionRequest(DEFAULT_FORM_VALUES),
      defaulted_v2_field_ids: [
        'acquisition_cost_pct',
        'financing_fee_pct',
        'disposition_cost_pct',
        'annual_capex_reserve',
        'io_period',
      ],
    };

    const values = buildFormValuesFromExcelIntakeReport(report);

    expect(values.purchasePrice).toBe('50000000');
    expect(values.currentNoi).toBe('2500000');
    expect(values.acquisitionCostPct).toBe('');
    expect(values.financingFeePct).toBe('');
    expect(values.dispositionCostPct).toBe('');
    expect(values.annualCapexReserve).toBe('');
    expect(values.ioPeriod).toBe('');
  });

  it('blanks only the fields actually reported as defaulted, leaving present V2 fields populated', () => {
    const report: ExcelIntakeReport = {
      inputs: buildAcquisitionRequest(V2_GOLDEN_FORM_VALUES),
      defaulted_v2_field_ids: ['io_period'],
    };

    const values = buildFormValuesFromExcelIntakeReport(report);

    expect(values.acquisitionCostPct).toBe('2');
    expect(values.financingFeePct).toBe('1');
    expect(values.dispositionCostPct).toBe('2.5');
    expect(values.annualCapexReserve).toBe('50000');
    expect(values.ioPeriod).toBe('');
  });
});

describe('buildV2ReviewMessage (Underwriting V2 Gate 6)', () => {
  it('returns null when nothing was defaulted', () => {
    expect(buildV2ReviewMessage([])).toBeNull();
  });

  it('names every defaulted field by its display label, in canonical order', () => {
    const message = buildV2ReviewMessage(['io_period', 'acquisition_cost_pct']);

    expect(message).not.toBeNull();
    expect(message).toContain('Acquisition Costs');
    expect(message).toContain('Interest-Only Period');
    expect(message?.indexOf('Acquisition Costs')).toBeLessThan(
      message?.indexOf('Interest-Only Period') ?? -1,
    );
  });

  it('never implies the workbook extraction failed', () => {
    const message = buildV2ReviewMessage(['io_period']);

    expect(message?.toLowerCase()).not.toContain('missing from');
    expect(message?.toLowerCase()).not.toContain('failed');
    expect(message?.toLowerCase()).not.toContain('error');
  });
});
