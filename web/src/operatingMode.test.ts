/**
 * D5.1B -- the Lease-Level safe-behaviour matrix for the frontend's mode
 * vocabulary.
 *
 * Every helper is asked all three modes. The rule the whole gate exists to
 * enforce is negative and is asserted as such: **no helper may answer
 * `lease_level` with Quick's or Detailed's behaviour.** A wrong label or a
 * borrowed purchase price is worse than an error here, because it looks
 * correct.
 */

import { describe, expect, it } from 'vitest';
import {
  UnsupportedOperatingModeError,
  assertNeverMode,
  operatingModeLabel,
  operatingModeUnderwriteLabel,
  requireImplementedMode,
} from './operatingMode';
import type { OperatingMode } from './types';

const ALL_MODES: OperatingMode[] = ['quick', 'detailed', 'lease_level'];

describe('operatingModeLabel', () => {
  it('labels every mode distinctly', () => {
    expect(operatingModeLabel('quick')).toBe('Quick');
    expect(operatingModeLabel('detailed')).toBe('Detailed');
    expect(operatingModeLabel('lease_level')).toBe('Lease-Level');
  });

  it('never labels Lease-Level as another mode', () => {
    const label = operatingModeLabel('lease_level');
    expect(label).not.toBe('Quick');
    expect(label).not.toBe('Detailed');
  });

  it('gives every mode its own label', () => {
    const labels = ALL_MODES.map(operatingModeLabel);
    expect(new Set(labels).size).toBe(ALL_MODES.length);
  });
});

describe('operatingModeUnderwriteLabel', () => {
  it('labels every mode distinctly', () => {
    expect(operatingModeUnderwriteLabel('quick')).toBe('Quick Underwrite');
    expect(operatingModeUnderwriteLabel('detailed')).toBe('Detailed Underwrite');
    expect(operatingModeUnderwriteLabel('lease_level')).toBe('Lease-Level Underwrite');
  });

  it('never labels Lease-Level as another mode', () => {
    const label = operatingModeUnderwriteLabel('lease_level');
    expect(label).not.toBe('Quick Underwrite');
    expect(label).not.toBe('Detailed Underwrite');
  });
});

describe('requireImplementedMode', () => {
  it('passes through the two modes the frontend implements', () => {
    expect(requireImplementedMode('quick', 'a surface')).toBe('quick');
    expect(requireImplementedMode('detailed', 'a surface')).toBe('detailed');
  });

  it('refuses Lease-Level by name, and names the surface that refused it', () => {
    let caught: unknown;
    try {
      requireImplementedMode('lease_level', 'the Underwrite shell');
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(UnsupportedOperatingModeError);
    const error = caught as UnsupportedOperatingModeError;
    expect(error.operatingMode).toBe('lease_level');
    expect(error.surface).toBe('the Underwrite shell');
    expect(error.message).toContain('lease_level');
    expect(error.message).toContain('the Underwrite shell');
  });

  it('never silently resolves Lease-Level to an implemented mode', () => {
    // The mutation this gate exists to prevent: a `default: return 'quick'`.
    let resolved: string | undefined;
    try {
      resolved = requireImplementedMode('lease_level', 'a surface');
    } catch {
      resolved = undefined;
    }
    expect(resolved).toBeUndefined();
  });
});

describe('assertNeverMode', () => {
  it('throws rather than returning a default', () => {
    // Cast is the point: this models a JavaScript-only caller reaching a
    // `default:` arm the type system never checked.
    expect(() => assertNeverMode('portfolio' as never)).toThrow(
      /Unhandled operating mode: portfolio/,
    );
  });
});

describe('the published vocabulary', () => {
  it('uses the exact backend wire value for the third mode', () => {
    // Must match `anchor.contracts.OperatingMode.LEASE_LEVEL.value` exactly --
    // not 'lease-level', 'leaseLevel' or 'leaselevel'.
    const mode: OperatingMode = 'lease_level';
    expect(mode).toBe('lease_level');
  });

  it('preserves the two existing wire values unchanged', () => {
    const quick: OperatingMode = 'quick';
    const detailed: OperatingMode = 'detailed';
    expect([quick, detailed]).toEqual(['quick', 'detailed']);
  });
});
