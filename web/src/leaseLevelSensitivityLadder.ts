/**
 * D5.7 -- the candidate-ladder convenience, and the only arithmetic this gate
 * adds to the browser.
 *
 * **What it is.** A typing aid. Entering `5.75 6.00 6.25 6.50 6.75` by hand is
 * five fields of tedium an analyst repeats all day, so a centre, a step and a
 * count may *populate* those five fields. That is the whole of it.
 *
 * **What it is not.** It is not a preset, not a scenario package, and not a
 * relative shock. The values it produces are ordinary absolute candidate values
 * that land in visible, editable inputs; the analyst can change any of them, add
 * more, or delete them, and what the API receives is whatever those inputs hold
 * at the moment Run is pressed. Nothing downstream knows a ladder was ever
 * involved, and no ladder parameter is ever submitted.
 *
 * **Why the arithmetic is confined here.** `centre + step * offset` is genuine
 * arithmetic, and Anchor's rule is that the browser performs no financial
 * calculation. The D5.0 review approved exactly this one carve-out, so it lives
 * alone in a module that imports nothing financial, is reachable only from the
 * candidate editor, and is unreachable from every result surface. The
 * architecture audit in `modeDispatch.architecture.test.ts` asserts that
 * boundary directly: this file is the sole permitted site, and the sensitivity
 * components contain no arithmetic at all.
 *
 * It never touches a metric, a baseline, or a response.
 */

import { formatDisplayNumber } from './convert';

/** The largest ladder the generator will produce in one press.
 *
 * **Not a limit on the sensitivity run.** The analyst may add as many candidate
 * values as they like, by hand or by generating twice; nothing caps the number
 * of values submitted, the grid size, or the suite count. This bounds only the
 * loop below, so a mistyped count cannot ask the browser to build a
 * ten-thousand-field editor.
 */
export const MAX_LADDER_COUNT = 25;

/**
 * `count` absolute values centred on `center`, `step` apart.
 *
 * `center: 6.5, step: 0.25, count: 5` produces
 * `['6', '6.25', '6.5', '6.75', '7']` -- display-scale strings, exactly as if
 * they had been typed, because that is what they become.
 *
 * Returned as strings through `formatDisplayNumber`, the shipped display
 * rounding, so binary-float noise never reaches an input as
 * `6.750000000000001`. An even `count` is centred the same way and simply has
 * no value sitting on the centre itself; nothing is snapped, sorted or
 * deduplicated afterwards.
 *
 * Returns `[]` for a non-finite input or a count outside `1..MAX_LADDER_COUNT`,
 * so a half-typed control populates nothing rather than something arbitrary.
 */
export function generateLadderValues(center: number, step: number, count: number): string[] {
  if (!Number.isFinite(center) || !Number.isFinite(step) || !Number.isInteger(count)) {
    return [];
  }
  if (count < 1 || count > MAX_LADDER_COUNT) {
    return [];
  }

  const values: string[] = [];
  for (let index = 0; index < count; index += 1) {
    const offset = index - (count - 1) / 2;
    values.push(formatDisplayNumber(center + step * offset));
  }
  return values;
}

/**
 * The three generator fields, held as the strings the analyst typed.
 *
 * State for the *control*, never for the run: no ladder parameter is ever
 * submitted, saved or compared. Lives here beside the generator so the candidate
 * editor exports only its component.
 */
export interface LadderDraft {
  center: string;
  step: string;
  count: string;
}

/** A generator with nothing entered yet. `count` carries a starting value
 * because a count of nothing generates nothing; the centre and step are the
 * analyst's, and no candidate value exists until they press Fill. */
export const BLANK_LADDER_DRAFT: LadderDraft = { center: '', step: '', count: '5' };
