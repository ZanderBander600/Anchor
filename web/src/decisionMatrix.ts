/**
 * Phase 7 Gate P7.5 -- how the Decision Matrix reads to an analyst.
 *
 * **Formatting only.** Every figure the matrix shows -- a cell's metric, its
 * Delta vs Base Scenario, a Worst Case, a Range -- is one field of the backend
 * decision package, formatted here. This module subtracts nothing, compares no
 * two figures, sorts nothing by value, and ranks nothing: those are cross-cell
 * figures, and Q22 / DC-5 reserve them for the backend.
 *
 * **A rate difference is in percentage points.** A Delta or a Range of an IRR
 * arrives as a decimal difference (`-0.03`). It is written with the ordinary
 * percent formatter and labelled `pts` -- "-3.00 pts" -- never as a relative
 * change. The string replacement below is presentation, not arithmetic.
 *
 * **Honest figures (DC-2).** A figure the backend could not compute is `N/A`
 * with the backend's reason; an IRR's reason is worded by
 * `irrNotReportedExplanation`, the one frontend home of that vocabulary.
 */

import { irrNotReportedExplanation } from './capitalEconomics';
import type { DecisionMetricSpec, DecisionMetricUnit } from './decisionTypes';
import { formatCurrency, formatMultiple, formatPercent } from './format';
import { SAVE_BEFORE_STRATEGIES_MESSAGE } from './strategyCatalog';
import type { IrrStatus } from './types';

/** One backend value in its metric's own unit. */
export function formatMetricValue(unit: DecisionMetricUnit, value: number): string {
  switch (unit) {
    case 'rate':
      return formatPercent(value);
    case 'multiple':
      return formatMultiple(value);
    case 'currency':
      return formatCurrency(value);
  }
}

/** One backend difference -- a Delta vs Base Scenario or a Range spread -- in
 * its metric's unit. A rate difference reads in percentage points. */
export function formatDifference(unit: DecisionMetricUnit, value: number): string {
  switch (unit) {
    case 'rate':
      return formatPercent(value).replace('%', ' pts');
    case 'multiple':
      return formatMultiple(value);
    case 'currency':
      return formatCurrency(value);
  }
}

/** A backend Delta with its sign always shown: "+3.00 pts", "-$450,000". */
export function formatSignedDifference(unit: DecisionMetricUnit, value: number): string {
  const text = formatDifference(unit, value);
  return value > 0 ? `+${text}` : text;
}

/** Why a figure is `N/A`, in words: the IRR vocabulary for an IRR the engine
 * did not define, otherwise the backend's own reason. */
export function notAvailableText(
  spec: DecisionMetricSpec,
  figure: { irr_status: IrrStatus | null; message: string | null },
): string {
  if (figure.irr_status !== null) {
    const explanation = irrNotReportedExplanation(spec.label, figure.irr_status);
    if (explanation !== null) {
      return explanation;
    }
  }
  return figure.message ?? `${spec.label} is not available.`;
}

export const NOT_AVAILABLE = 'N/A';
export const INVALID_VARIANT = 'Invalid variant';

/** The implicit axes, as the analyst reads them. */
export const BASE_STRATEGY_LABEL = 'Base Strategy';
export const BASE_SCENARIO_LABEL = 'Base';

/** Each message is one literal, never joined with `+`: see
 * `StaleAnalysisNotice.tsx`. */
// prettier-ignore
export const EMPTY_MATRIX_MESSAGE =
  'Add a Strategy or Scenario to compare alternative decisions and market views.';

// prettier-ignore
export const UNSAVED_MATRIX_MESSAGE =
  'Save this deal before comparing strategies and scenarios.';

// prettier-ignore
export const STALE_MATRIX_MESSAGE =
  'The saved underwriting, strategies or scenarios changed after this matrix ran. Refresh Matrix to update it.';

// prettier-ignore
export const DIRTY_MATRIX_MESSAGE =
  'Base underwriting has unsaved changes. Save the deal, then Refresh Matrix.';

/** Phase 7 Gate P7.6: the words one matrix surface uses, so the same
 * component reads a Deal's matrix or a visible Investment's. The Deal's are
 * these; the Investment's live with its own copy (`investmentCatalog.ts`). */
export interface DecisionMatrixCopy {
  subtitle: string;
  unsaved: string;
  dirty: string;
  stale: string;
  /** Why Run / Refresh is unavailable while there are unsaved changes. */
  blocked: string;
  caption: string;
}

export const DEAL_MATRIX_COPY: DecisionMatrixCopy = {
  subtitle:
    'Each strategy (what you choose) under each scenario (what may happen). Every cell is a complete deterministic analysis of the saved underwriting.',
  unsaved: UNSAVED_MATRIX_MESSAGE,
  dirty: DIRTY_MATRIX_MESSAGE,
  stale: STALE_MATRIX_MESSAGE,
  blocked: SAVE_BEFORE_STRATEGIES_MESSAGE,
  caption:
    'Project results of each strategy under each scenario, with the backend’s Delta vs Base, Worst Case and Range',
};

/** P7.6: an invalid variant cell of a visible Investment roots each issue's
 * location at its Unit (`units[<unit_id>].<field>`), so the Unit is never
 * hidden. The Unit's id, read off that location; `null` when it names none. */
export function issueUnitId(field: string | null): string | null {
  const match = field === null ? null : /^units\[([^\]]+)\]/.exec(field);
  return match === null ? null : match[1];
}
