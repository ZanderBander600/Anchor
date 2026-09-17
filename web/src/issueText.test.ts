import { describe, expect, it } from 'vitest';
import { readableIssueMessage } from './issueText';

describe('readableIssueMessage', () => {
  it.each([
    [
      'exit_cap_rate: value -0.0049999999999999975 must be greater than 0.',
      'exit_cap_rate: value -0.50% must be greater than 0%.',
    ],
    [
      'noi_growth: value -1.0000000000000002 must be greater than -1.',
      'noi_growth: value -100.00% must be greater than -100%.',
    ],
    [
      'ltv: value 1.05 must be between 0 and 1, inclusive.',
      'ltv: value 105.00% must be between 0% and 100%, inclusive.',
    ],
    [
      'purchase_price: value -250000.00000000003 must be greater than 0.',
      'purchase_price: value -$250,000 must be greater than $0.',
    ],
    [
      'renewal_rent_spread -1.0500000000000003 must be greater than -1.',
      'renewal_rent_spread -105.00% must be greater than -100%.',
    ],
    [
      'suites[1].market_rent_psf -0.5000000000000001 must be greater than or equal to 0.',
      'suites[1].market_rent_psf $-0.50 must be greater than or equal to 0.',
    ],
    [
      'hold_period: value 2.5000000000000004 must be a whole number of years.',
      'hold_period: value 2.5 must be a whole number of years.',
    ],
  ])('%s', (raw, shown) => {
    expect(readableIssueMessage(raw)).toBe(shown);
  });

  it('removes float noise from a number in any other sentence', () => {
    expect(readableIssueMessage('free rent 3.0000000000000004 exceeds the 2.9999999999999996 available.')).toBe(
      'free rent 3 exceeds the 3 available.',
    );
  });

  it('leaves words, ids and ordinary numbers exactly as written', () => {
    for (const text of [
      'The saved underwriting changed while the decision matrix was running. Run it again.',
      'Scenario 3e471bc78f64441e977dd392c9bb7c32 names unit 12.',
      'hold_period must be at least 1 year; got 0.',
      'escalation_pct 0.03 must be 0.0 when the lease is flat.',
    ]) {
      expect(readableIssueMessage(text)).toBe(
        text === 'escalation_pct 0.03 must be 0.0 when the lease is flat.'
          ? 'escalation_pct 3.00% must be 0% when the lease is flat.'
          : text,
      );
    }
  });
});
