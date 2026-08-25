import { describe, expect, it } from 'vitest';
import { formatCurrency, formatMultiple, formatPercent } from './format';

describe('formatCurrency', () => {
  it('formats a positive amount with thousands separators', () => {
    expect(formatCurrency(50_000_000)).toBe('$50,000,000');
  });

  it('formats a negative amount with a leading minus sign', () => {
    expect(formatCurrency(-1_234_567)).toBe('-$1,234,567');
  });

  it('formats null and undefined as N/A', () => {
    expect(formatCurrency(null)).toBe('N/A');
    expect(formatCurrency(undefined)).toBe('N/A');
  });
});

describe('formatPercent', () => {
  it('formats a decimal fraction as a percentage', () => {
    expect(formatPercent(0.0791)).toBe('7.91%');
  });

  it('formats null as N/A', () => {
    expect(formatPercent(null)).toBe('N/A');
  });
});

describe('formatMultiple', () => {
  it('formats a multiple with two decimals and a trailing x', () => {
    expect(formatMultiple(1.4356)).toBe('1.44x');
  });

  it('formats null as N/A', () => {
    expect(formatMultiple(null)).toBe('N/A');
  });
});
