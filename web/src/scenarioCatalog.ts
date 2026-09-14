/**
 * Phase 7 Gate P7.3 -- how a Scenario target reads to an analyst.
 *
 * The backend registry (`SCENARIO_TARGET_REGISTRY`, P7.1) decides which targets
 * exist, in which operating mode, and which operations each one allows. The UI
 * reads that from `GET /scenario-targets`. This module decides presentation
 * only:
 * - the label an analyst reads for each registry token;
 * - how the target's value is typed and shown;
 * - the words for each operation.
 *
 * **Display units, never financial arithmetic.** Rates are typed as percentages
 * and sent as the decimals the registry states (6.50 becomes 0.065). An ADD on a
 * rate is typed in percentage points (+0.50 becomes 0.005). A SCALE is a
 * multiplier, and a market rent is dollars per square foot per year; both are
 * sent as typed. Parsing reuses the shipped `parsePercent` / `parseNumber`, so
 * the percent-to-decimal rule has one home. The reverse conversion, in
 * `scenarioValueToText`, is the one arithmetic expression in the Scenario UI,
 * and `scenarioArchitecture.test.ts` pins it.
 *
 * **Never inferred.** The registry may add a target this module does not know.
 * Such a target is shown by its token, typed and sent on the wire scale exactly
 * as stored, with the registry's own `units` text beside it. It is never guessed
 * to be a percentage.
 */

import { formatDisplayNumber, parseNumber, parsePercent } from './convert';
import type { ScenarioOperation, ScenarioOverride, ScenarioTargetEntry } from './scenarioTypes';

/** How a known target's value reads when an operation states a level or a
 * change in the target's own units (every operation but SCALE). */
export type ScenarioValueKind = 'percent' | 'rent_psf';

export interface ScenarioTargetPresentation {
  label: string;
  kind: ScenarioValueKind;
}

/** Labels and value kinds, keyed by registry token.
 *
 * `tests/test_p7_3_scenario_ui_architecture.py` proves that every registry target
 * has exactly one entry here, and that each kind agrees with the registry's
 * stated `units`. */
export const SCENARIO_TARGET_PRESENTATION: Readonly<Record<string, ScenarioTargetPresentation>> = {
  exit_cap_rate: { label: 'Exit Cap Rate', kind: 'percent' },
  interest_rate: { label: 'Interest Rate', kind: 'percent' },
  ltv: { label: 'Maximum LTV', kind: 'percent' },
  noi_growth: { label: 'NOI Growth', kind: 'percent' },
  revenue_growth: { label: 'Revenue Growth', kind: 'percent' },
  vacancy_credit_loss_pct: { label: 'Vacancy & Credit Loss', kind: 'percent' },
  expense_growth: { label: 'Expense Growth', kind: 'percent' },
  market_rent_psf: { label: 'Market Rent', kind: 'rent_psf' },
  renewal_probability: { label: 'Renewal Probability', kind: 'percent' },
  recoverable_expense_ratio: { label: 'Recoverable Expense Ratio', kind: 'percent' },
};

/** The operation words. Each is shown only for a target whose registry
 * whitelist allows it. */
export const SCENARIO_OPERATION_LABELS: Readonly<Record<ScenarioOperation, string>> = {
  set: 'Set To',
  add: 'Add',
  scale: 'Scale',
  cap_at: 'Cap At',
};

/** The analyst's label for a registry token. An unknown token is shown as
 * itself rather than as an invented name. */
export function scenarioTargetLabel(target: string): string {
  return SCENARIO_TARGET_PRESENTATION[target]?.label ?? target;
}

/** The scale one (target, operation) pair is typed in. */
type ValueScale =
  | 'percent'
  | 'percentage_points'
  | 'multiplier'
  | 'rent_psf'
  | 'rent_psf_change'
  | 'wire';

function valueScale(target: string, operation: ScenarioOperation): ValueScale {
  const presentation = SCENARIO_TARGET_PRESENTATION[target];
  if (presentation === undefined) {
    return 'wire';
  }
  if (operation === 'scale') {
    return 'multiplier';
  }
  if (presentation.kind === 'percent') {
    return operation === 'add' ? 'percentage_points' : 'percent';
  }
  return operation === 'add' ? 'rent_psf_change' : 'rent_psf';
}

/** Whether two operations on one target are typed in the same scale. When
 * they are not, the editor clears the value on the switch rather than letting
 * "6.5" silently change meaning from a percentage to a multiplier. */
export function sharesValueScale(
  target: string,
  first: ScenarioOperation,
  second: ScenarioOperation,
): boolean {
  return valueScale(target, first) === valueScale(target, second);
}

/** What the value field shows around the number, and one phrase saying what
 * the number means. */
export interface ScenarioValueFormat {
  prefix: string | null;
  suffix: string | null;
  hint: string;
}

/** The value field's presentation for one (target, operation). `entry` is the
 * registry's catalog entry, whose `units` text is shown verbatim for a target
 * this module does not know. */
export function scenarioValueFormat(
  target: string,
  operation: ScenarioOperation,
  entry: ScenarioTargetEntry | undefined,
): ScenarioValueFormat {
  switch (valueScale(target, operation)) {
    case 'percent':
      return {
        prefix: null,
        suffix: '%',
        hint: operation === 'cap_at' ? 'Upper limit, in percent' : 'In percent',
      };
    case 'percentage_points':
      return { prefix: null, suffix: '% pts', hint: 'Percentage points: 0.50 adds 50 bps' };
    case 'multiplier':
      return { prefix: null, suffix: 'x', hint: 'Multiplier: 0.90 is 10% lower' };
    case 'rent_psf':
      return {
        prefix: '$',
        suffix: '/SF/yr',
        hint: operation === 'cap_at' ? 'Upper limit, $ per SF per year' : '$ per SF per year',
      };
    case 'rent_psf_change':
      return { prefix: '$', suffix: '/SF/yr', hint: 'Change in $ per SF per year' };
    case 'wire':
      return { prefix: null, suffix: null, hint: entry?.units ?? 'Value as stored' };
  }
}

/** The typed text as the wire value, or a `FormValidationError` naming the
 * field. It checks presence and parsing only; whether the value is a valid
 * assumption is the backend's decision. */
export function scenarioValueToWire(
  target: string,
  operation: ScenarioOperation,
  text: string,
  fieldLabel: string,
): number {
  switch (valueScale(target, operation)) {
    case 'percent':
    case 'percentage_points':
      return parsePercent(fieldLabel, text);
    case 'multiplier':
    case 'rent_psf':
    case 'rent_psf_change':
    case 'wire':
      return parseNumber(fieldLabel, text);
  }
}

/** A stored wire value as the text the value field shows. */
export function scenarioValueToText(
  target: string,
  operation: ScenarioOperation,
  value: number,
): string {
  switch (valueScale(target, operation)) {
    case 'percent':
    case 'percentage_points':
      return formatDisplayNumber(value * 100);
    case 'multiplier':
    case 'rent_psf':
    case 'rent_psf_change':
      return formatDisplayNumber(value);
    case 'wire':
      return String(value);
  }
}

/** One override as a short phrase, e.g. "Exit Cap Rate: Add +0.5% pts". An ADD
 * always shows its sign. */
export function describeScenarioOverride(override: ScenarioOverride): string {
  const text = scenarioValueToText(override.target, override.operation, override.value);
  const signed = override.operation === 'add' && !text.startsWith('-') ? `+${text}` : text;
  const { prefix, suffix } = scenarioValueFormat(override.target, override.operation, undefined);
  const figure = `${prefix ?? ''}${signed}${suffix ?? ''}`;
  return `${scenarioTargetLabel(override.target)}: ${SCENARIO_OPERATION_LABELS[override.operation]} ${figure}`;
}
