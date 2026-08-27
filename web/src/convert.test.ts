import { describe, expect, it } from 'vitest';
import {
  buildAcquisitionRequest,
  buildApprovedFormValues,
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
