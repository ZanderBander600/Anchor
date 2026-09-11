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
  byMode,
  operatingModeLabel,
  operatingModeUnderwriteLabel,
  requireUnderwriteWorkspaceMode,
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

/**
 * Renamed at D5.5A from `requireImplementedMode`. The guardrail is unchanged in
 * substance -- it still refuses `lease_level` rather than resolving it to a
 * neighbour -- but what it now means is narrower and more honest: Lease-Level
 * *is* implemented, in `LeaseLevelWorkspace`; it is the shared Quick/Detailed
 * `UnderwriteWorkspace` that cannot render it.
 */
describe('requireUnderwriteWorkspaceMode', () => {
  it('passes through the two modes the shared workspace renders', () => {
    expect(requireUnderwriteWorkspaceMode('quick', 'a surface')).toBe('quick');
    expect(requireUnderwriteWorkspaceMode('detailed', 'a surface')).toBe('detailed');
  });

  it('refuses Lease-Level by name, and names the surface that refused it', () => {
    let caught: unknown;
    try {
      requireUnderwriteWorkspaceMode('lease_level', 'the Underwrite workspace');
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(UnsupportedOperatingModeError);
    const error = caught as UnsupportedOperatingModeError;
    expect(error.operatingMode).toBe('lease_level');
    expect(error.surface).toBe('the Underwrite workspace');
    expect(error.message).toContain('lease_level');
    expect(error.message).toContain('the Underwrite workspace');
  });

  it('never silently resolves Lease-Level to another mode', () => {
    // The mutation this gate exists to prevent: a `default: return 'quick'`.
    let resolved: string | undefined;
    try {
      resolved = requireUnderwriteWorkspaceMode('lease_level', 'a surface');
    } catch {
      resolved = undefined;
    }
    expect(resolved).toBeUndefined();
  });
});

/**
 * D5.5A -- `byMode` is the shell's replacement for the two-way mode ternary.
 * Its whole value is that `Record<OperatingMode, T>` makes an omitted arm a
 * compile error, so the runtime tests below only need to prove it routes to the
 * right arm and never falls back.
 */
describe('byMode', () => {
  it('returns the arm belonging to each mode', () => {
    const choices = { quick: 'Q', detailed: 'D', lease_level: 'L' };
    expect(byMode('quick', choices)).toBe('Q');
    expect(byMode('detailed', choices)).toBe('D');
    expect(byMode('lease_level', choices)).toBe('L');
  });

  it('never answers one mode with another mode’s value', () => {
    const seen = ALL_MODES.map((mode) =>
      byMode(mode, { quick: 'quick', detailed: 'detailed', lease_level: 'lease_level' }),
    );
    expect(seen).toEqual(ALL_MODES);
  });

  it('throws rather than falling back when handed an unknown mode', () => {
    // A JavaScript-only caller, or a stale bundle meeting a mode the compiler
    // never saw. Returning Quick here is the exact hazard HD-D4-9 recorded.
    expect(() =>
      byMode('portfolio' as OperatingMode, {
        quick: 'Q',
        detailed: 'D',
        lease_level: 'L',
      }),
    ).toThrow(/Unhandled operating mode: portfolio/);
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
