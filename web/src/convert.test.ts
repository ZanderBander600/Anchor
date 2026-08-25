import { describe, expect, it } from 'vitest';
import { buildAcquisitionRequest, DEFAULT_FORM_VALUES, FormValidationError } from './convert';

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
