/**
 * D5.5E -- thousands grouping is presentation, and only presentation.
 *
 * Human Pass #1 asked for `30000000` to read as `30,000,000`. The whole risk in
 * granting that is that a formatter quietly becomes a calculator: rounds a
 * decimal, drops a trailing zero, normalises a sign. These tests exist to prove
 * it does none of those things, and that the string the wire receives is the
 * string it received before this module existed.
 */

import { describe, expect, it } from 'vitest';
import { groupDigits, groupsThousands, stripGroups } from './numberFormat';

// =============================================================================
// 1. The requested behaviour
// =============================================================================

describe('grouping', () => {
  it.each([
    ['30000000', '30,000,000'],
    ['100000', '100,000'],
    ['20000', '20,000'],
    ['1234567.89', '1,234,567.89'],
    ['1000', '1,000'],
    ['999', '999'],
    ['0', '0'],
  ])('%s displays as %s', (raw, shown) => {
    expect(groupDigits(raw)).toBe(shown);
  });

  it('groups from the right, whatever the length', () => {
    expect(groupDigits('1')).toBe('1');
    expect(groupDigits('12')).toBe('12');
    expect(groupDigits('123')).toBe('123');
    expect(groupDigits('1234')).toBe('1,234');
    expect(groupDigits('12345')).toBe('12,345');
    expect(groupDigits('123456')).toBe('123,456');
    expect(groupDigits('1234567')).toBe('1,234,567');
  });

  it('never groups the fraction', () => {
    // 0.123456 is not 0.123,456.
    expect(groupDigits('0.123456')).toBe('0.123456');
    expect(groupDigits('12345.678901')).toBe('12,345.678901');
  });

  it('keeps the sign', () => {
    expect(groupDigits('-1234567')).toBe('-1,234,567');
    expect(groupDigits('-5.5')).toBe('-5.5');
  });
});

// =============================================================================
// 2. It is not arithmetic
// =============================================================================

describe('the value is never altered', () => {
  it('does not round', () => {
    expect(groupDigits('1234567.89')).toBe('1,234,567.89');
    expect(groupDigits('0.005')).toBe('0.005');
    expect(groupDigits('1234.999999999')).toBe('1,234.999999999');
  });

  it('preserves trailing zeros a number would lose', () => {
    // `Number('1.50').toString()` is '1.5'. A formatter that parsed would eat
    // the analyst's precision; this one never parses.
    expect(groupDigits('1.50')).toBe('1.50');
    expect(groupDigits('1000.00')).toBe('1,000.00');
    expect(groupDigits('0.10')).toBe('0.10');
  });

  it('preserves a trailing decimal point mid-entry', () => {
    // Typing "1234." must not become "1234" and jump the caret.
    expect(groupDigits('1234.')).toBe('1,234.');
  });

  it('preserves leading zeros rather than normalising them', () => {
    expect(groupDigits('007')).toBe('007');
  });

  it('round-trips every value back to exactly what was typed', () => {
    for (const raw of [
      '30000000',
      '1234567.89',
      '1.50',
      '0',
      '007',
      '-1234567',
      '1234.',
      '0.000001',
      '999999999999',
    ]) {
      expect(stripGroups(groupDigits(raw)), `round trip for ${raw}`).toBe(raw);
    }
  });
});

// =============================================================================
// 3. It refuses to interpret what it does not understand
// =============================================================================

describe('non-numeric text', () => {
  it('is returned untouched rather than repaired', () => {
    for (const raw of ['', 'abc', '1e5', '1..2', '--1', '1 000', '£30000']) {
      expect(groupDigits(raw)).toBe(raw);
    }
  });

  it('does not silently accept a malformed value as a number', () => {
    // The existing conversion still refuses these by name on submit; grouping
    // has no opinion about them.
    expect(groupDigits('abc')).toBe('abc');
  });
});

describe('stripGroups', () => {
  it('removes separators so state never holds one', () => {
    expect(stripGroups('30,000,000')).toBe('30000000');
    expect(stripGroups('1,234,567.89')).toBe('1234567.89');
    expect(stripGroups('30000000')).toBe('30000000');
  });
});

// =============================================================================
// 4. Which fields group
// =============================================================================

describe('groupsThousands', () => {
  it('groups currency and area', () => {
    expect(groupsThousands({ prefix: '$' })).toBe(true);
    expect(groupsThousands({ suffix: 'SF' })).toBe(true);
    expect(groupsThousands({ prefix: '$', suffix: '/SF' })).toBe(true);
  });

  it('does not group percentages, months or years', () => {
    expect(groupsThousands({ suffix: '%' })).toBe(false);
    expect(groupsThousands({ suffix: 'mo' })).toBe(false);
    expect(groupsThousands({ suffix: 'yrs' })).toBe(false);
    expect(groupsThousands({})).toBe(false);
  });

  it('is derived from display metadata, not a list of field names', () => {
    // A field added to any contract inherits the right behaviour from the
    // prefix/suffix it already declares.
    expect(groupsThousands({ prefix: '$', suffix: 'anything' })).toBe(true);
    expect(groupsThousands({ prefix: undefined, suffix: undefined })).toBe(false);
  });
});
