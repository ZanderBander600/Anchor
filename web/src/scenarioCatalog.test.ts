/**
 * Phase 7 Gate P7.3 -- Scenario target presentation and display units.
 *
 * The analyst types a rate as a percentage and never as the wire decimal. The
 * conversion is display units only, and these tests pin it in both directions,
 * including float noise, negative changes and the target this module does not
 * know.
 */

import { describe, expect, it } from 'vitest';
import { FormValidationError } from './convert';
import {
  describeScenarioOverride,
  SCENARIO_OPERATION_LABELS,
  SCENARIO_TARGET_PRESENTATION,
  scenarioTargetLabel,
  scenarioValueFormat,
  scenarioValueToText,
  scenarioValueToWire,
  sharesValueScale,
} from './scenarioCatalog';
import type { ScenarioOperation } from './scenarioTypes';

describe('labels', () => {
  it('gives every registry target an institutional label', () => {
    expect(
      Object.fromEntries(
        Object.entries(SCENARIO_TARGET_PRESENTATION).map(([token, entry]) => [token, entry.label]),
      ),
    ).toEqual({
      exit_cap_rate: 'Exit Cap Rate',
      interest_rate: 'Interest Rate',
      ltv: 'Maximum LTV',
      noi_growth: 'NOI Growth',
      revenue_growth: 'Revenue Growth',
      vacancy_credit_loss_pct: 'Vacancy & Credit Loss',
      expense_growth: 'Expense Growth',
      market_rent_psf: 'Market Rent',
      renewal_probability: 'Renewal Probability',
      recoverable_expense_ratio: 'Recoverable Expense Ratio',
    });
  });

  it('never shows an operation as its wire token', () => {
    expect(SCENARIO_OPERATION_LABELS).toEqual({
      set: 'Set To',
      add: 'Add',
      scale: 'Scale',
      cap_at: 'Cap At',
    });
  });

  it('shows a token it does not know as itself rather than inventing a name', () => {
    expect(scenarioTargetLabel('some_future_target')).toBe('some_future_target');
  });
});

describe('typed value to wire value', () => {
  const cases: [string, ScenarioOperation, string, number][] = [
    ['exit_cap_rate', 'set', '6.5', 0.065],
    ['exit_cap_rate', 'add', '0.5', 0.005],
    ['interest_rate', 'add', '-0.25', -0.0025],
    ['ltv', 'cap_at', '55', 0.55],
    ['renewal_probability', 'set', '70', 0.7],
    ['exit_cap_rate', 'scale', '1.1', 1.1],
    ['market_rent_psf', 'scale', '0.9', 0.9],
    ['market_rent_psf', 'set', '32.5', 32.5],
    ['market_rent_psf', 'add', '-2', -2],
    ['market_rent_psf', 'cap_at', '40', 40],
    ['some_future_target', 'set', '0.3', 0.3],
  ];

  it.each(cases)('%s %s %s -> %s', (target, operation, text, wire) => {
    expect(scenarioValueToWire(target, operation, text, 'Value')).toBeCloseTo(wire, 12);
  });

  it('checks presence and parsing only, naming the field', () => {
    expect(() => scenarioValueToWire('exit_cap_rate', 'set', '  ', 'Exit Cap Rate value')).toThrow(
      new FormValidationError('Exit Cap Rate value is required.'),
    );
    expect(() => scenarioValueToWire('exit_cap_rate', 'set', 'abc', 'Exit Cap Rate value')).toThrow(
      'Exit Cap Rate value must be a valid number.',
    );
  });

  it('never clips or corrects an out-of-domain value: that is the backend’s call', () => {
    expect(scenarioValueToWire('renewal_probability', 'set', '150', 'Value')).toBe(1.5);
    expect(scenarioValueToWire('exit_cap_rate', 'set', '-4', 'Value')).toBe(-0.04);
  });
});

describe('wire value to typed value', () => {
  it('shows rates as percentages without binary float noise', () => {
    expect(scenarioValueToText('exit_cap_rate', 'set', 0.065)).toBe('6.5');
    expect(scenarioValueToText('exit_cap_rate', 'set', 0.07)).toBe('7');
    expect(scenarioValueToText('noi_growth', 'set', 0.1)).toBe('10');
    expect(scenarioValueToText('exit_cap_rate', 'add', 0.005)).toBe('0.5');
    expect(scenarioValueToText('ltv', 'cap_at', 0.55)).toBe('55');
  });

  it('shows multipliers and rents as they are stored', () => {
    expect(scenarioValueToText('market_rent_psf', 'scale', 0.9)).toBe('0.9');
    expect(scenarioValueToText('market_rent_psf', 'set', 32.5)).toBe('32.5');
    expect(scenarioValueToText('some_future_target', 'set', 0.123456789)).toBe('0.123456789');
  });

  it('round-trips what the analyst typed', () => {
    for (const [target, operation, text] of [
      ['exit_cap_rate', 'set', '7.25'],
      ['interest_rate', 'add', '-0.75'],
      ['vacancy_credit_loss_pct', 'add', '2'],
      ['market_rent_psf', 'scale', '0.85'],
    ] as [string, ScenarioOperation, string][]) {
      const wire = scenarioValueToWire(target, operation, text, 'Value');
      expect(scenarioValueToText(target, operation, wire)).toBe(text);
    }
  });
});

describe('the value field', () => {
  it('says an ADD on a rate is in percentage points', () => {
    const format = scenarioValueFormat('exit_cap_rate', 'add', undefined);
    expect(format.suffix).toBe('% pts');
    expect(format.hint).toMatch(/percentage points/i);
  });

  it('marks a SCALE as a multiplier and a market rent in $/SF/yr', () => {
    expect(scenarioValueFormat('market_rent_psf', 'scale', undefined).suffix).toBe('x');
    expect(scenarioValueFormat('market_rent_psf', 'set', undefined)).toMatchObject({
      prefix: '$',
      suffix: '/SF/yr',
    });
    expect(scenarioValueFormat('ltv', 'cap_at', undefined)).toMatchObject({ suffix: '%' });
  });

  it('shows the registry’s own units for a target it does not know', () => {
    expect(
      scenarioValueFormat('some_future_target', 'set', {
        target: 'some_future_target',
        allowed_operations: ['set'],
        units: 'months of delay',
      }),
    ).toEqual({ prefix: null, suffix: null, hint: 'months of delay' });
  });

  it('clears a value only when the operation changes its units', () => {
    expect(sharesValueScale('exit_cap_rate', 'set', 'set')).toBe(true);
    expect(sharesValueScale('ltv', 'cap_at', 'cap_at')).toBe(true);
    expect(sharesValueScale('market_rent_psf', 'set', 'cap_at')).toBe(true);
    expect(sharesValueScale('exit_cap_rate', 'set', 'add')).toBe(false);
    expect(sharesValueScale('exit_cap_rate', 'set', 'scale')).toBe(false);
  });
});

describe('override summaries', () => {
  it('reads each override the way an analyst would say it', () => {
    expect(
      describeScenarioOverride({ unit_id: 'd', target: 'exit_cap_rate', operation: 'add', value: 0.005 }),
    ).toBe('Exit Cap Rate: Add +0.5% pts');
    expect(
      describeScenarioOverride({ unit_id: 'd', target: 'interest_rate', operation: 'add', value: -0.0025 }),
    ).toBe('Interest Rate: Add -0.25% pts');
    expect(
      describeScenarioOverride({ unit_id: 'd', target: 'ltv', operation: 'cap_at', value: 0.55 }),
    ).toBe('Maximum LTV: Cap At 55%');
    expect(
      describeScenarioOverride({ unit_id: 'd', target: 'market_rent_psf', operation: 'scale', value: 0.9 }),
    ).toBe('Market Rent: Scale 0.9x');
    expect(
      describeScenarioOverride({ unit_id: 'd', target: 'market_rent_psf', operation: 'set', value: 32.5 }),
    ).toBe('Market Rent: Set To $32.5/SF/yr');
  });
});
