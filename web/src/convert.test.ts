import { describe, expect, it } from 'vitest';
import {
  buildAcquisitionRequest,
  buildApprovedFormValues,
  buildFormValuesFromAcquisitionInputs,
  candidateValueToFormValue,
  DEFAULT_FORM_VALUES,
  FormValidationError,
} from './convert';

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
    });
  });

  it('converts analyst-facing percentages to decimals generally', () => {
    const request = buildAcquisitionRequest({
      ...DEFAULT_FORM_VALUES,
      occupancy: '92.5',
      exitCapRate: '6',
      ltv: '70',
      interestRate: '4.75',
    });

    expect(request.occupancy).toBeCloseTo(0.925);
    expect(request.exit_cap_rate).toBeCloseTo(0.06);
    expect(request.ltv).toBeCloseTo(0.7);
    expect(request.interest_rate).toBeCloseTo(0.0475);
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
    });

    expect(values).toEqual(DEFAULT_FORM_VALUES);
  });

  it('always includes all nine fields', () => {
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
      ].sort(),
    );
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
    });

    expect(values.occupancy).toBe('10');
    expect(values.noiGrowth).toBe('29');
    expect(values.ltv).toBe('70');
    expect(values.interestRate).toBe('4.75');
  });

  it('round-trips through buildAcquisitionRequest', () => {
    const request = buildAcquisitionRequest(DEFAULT_FORM_VALUES);
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
  });
});
