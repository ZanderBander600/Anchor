/**
 * Demo polish -- a validator's message, as an analyst reads it.
 *
 * The backend validators state an offending value with Python's `repr`, so a
 * value an override produced can read `-0.0049999999999999975`. This rewrites
 * only how the numbers inside such a message are shown: a percent field's value
 * and bounds as percents, a dollar field's as currency, and anything else
 * without floating-point noise. The words, the field and the rule stay exactly
 * as the validator wrote them. Nothing here judges a value or decides validity:
 * the message is already the backend's verdict.
 */

import { formatCurrency, formatPercent } from './format';

/** Fields the wire carries as fractions and the forms show as percents. */
const PERCENT_FIELD = /(^|_)(occupancy|ltv|probability)$|_(pct|growth|rate|spread)$/;

/** Fields the wire carries as whole dollars. */
const CURRENCY_FIELDS = new Set([
  'purchase_price',
  'current_noi',
  'annual_capex_reserve',
  'gross_potential_rent',
  'other_income',
  'property_taxes',
  'insurance',
  'utilities',
  'repairs_maintenance',
  'other_operating_expenses',
  'amount',
]);

const NUMBER = String.raw`-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?`;

/** `field: value N must be ...` (Quick / Detailed) and `field N must be ...`
 * (Lease-Level). The rule runs to the end of its sentence. */
const STATEMENT = new RegExp(
  String.raw`\b([a-z][a-z0-9_]*)(: value | )(${NUMBER})((?: must be| exceeds| produces)(?:[^.]|\.(?=\d))*)?`,
  'g',
);

/** A number carrying more decimal places than any assumption is typed with. */
const NOISY_NUMBER = /-?\d+\.\d{7,}(?:[eE][-+]?\d+)?/g;

function withoutNoise(text: string): string {
  return String(Number(Number(text).toPrecision(12)));
}

function percentText(text: string): string {
  const value = Number(text);
  return formatPercent(value, Number.isInteger(Number((value * 100).toPrecision(12))) ? 0 : 2);
}

function valueText(field: string, text: string): string {
  if (PERCENT_FIELD.test(field)) {
    return formatPercent(Number(text));
  }
  if (field.endsWith('_psf')) {
    return `$${Number(text).toFixed(2)}`;
  }
  if (CURRENCY_FIELDS.has(field)) {
    return formatCurrency(Number(text));
  }
  return withoutNoise(text);
}

function ruleText(field: string, rule: string): string {
  const convert = PERCENT_FIELD.test(field)
    ? percentText
    : CURRENCY_FIELDS.has(field)
      ? (text: string) => formatCurrency(Number(text))
      : null;
  if (convert === null) {
    return rule;
  }
  return rule.replace(new RegExp(String.raw`(?<![\w.])${NUMBER}(?![\w.])`, 'g'), convert);
}

export function readableIssueMessage(message: string): string {
  return message
    .replace(
      STATEMENT,
      (whole, field: string, separator: string, number: string, rule: string | undefined) =>
        rule === undefined && separator === ' '
          ? whole
          : `${field}${separator}${valueText(field, number)}${rule === undefined ? '' : ruleText(field, rule)}`,
    )
    .replace(NOISY_NUMBER, withoutNoise);
}
