/**
 * D5.1B -- the frontend's operating-mode vocabulary.
 *
 * The counterpart to `anchor.contracts`'s `OperatingMode` /
 * `UnsupportedOperatingModeError` on the Python side, and the frontend half of
 * the same sequencing invariant D5.1A applied to the backend:
 *
 *   TOTAL DISPATCH FIRST, THIRD MODE SECOND.
 *
 * Before this module existed, every mode decision in `web/src` was written as
 * `mode === 'detailed' ? … : …` or `if (mode === 'quick') … else …`. Those are
 * not merely terse -- they are *unsafe by construction*, because widening
 * `OperatingMode` produces **no compile error at a ternary**. A third member
 * would have silently joined whichever branch the `else` happened to be, and a
 * Lease-Level deal would have rendered as Quick, with Quick's purchase price
 * and Quick's badge, in a financial application. That is exactly the hazard
 * HD-D4-9 recorded on the backend.
 *
 * Every helper here is a `switch` ending in {@link assertNeverMode}, so the
 * compiler -- not a convention, and not a test -- is what fails the day a
 * fourth mode is added without wiring it up.
 *
 * **This module deliberately grants no capability.** Knowing a mode's *name* is
 * not the same as being able to underwrite it: D5.1B publishes the vocabulary
 * so that Lease-Level data can never be mislabelled, and nothing more. The
 * analyst still cannot select Lease-Level, and no Lease-Level form, client
 * function or result view exists. D5.5A owns user selection.
 *
 * Lives in its own module rather than in `underwrite.ts` because its consumers
 * are not all underwriting-navigation code: the sidebar, the Deal Library and
 * the owner summary all need mode labels, and none of them is part of the
 * Underwrite workspace's tab configuration.
 */

import type { OperatingMode } from './types';

/**
 * The two modes the shared `UnderwriteWorkspace` renders.
 *
 * **Renamed at D5.5A.** This was `ImplementedOperatingMode` -- "the modes the
 * frontend can render at all" -- which stopped being true the moment
 * Lease-Level got a workspace. It never had one *here*: `LeaseLevelWorkspace`
 * is its own component with its own layout, because a rent roll is not a column
 * of scalar assumptions.
 *
 * So the narrow set survives with an honest name. `UnderwriteWorkspace` still
 * serves exactly Quick and Detailed, and still refuses anything else rather
 * than guessing which of the two a third mode resembles.
 */
export type UnderwriteWorkspaceMode = 'quick' | 'detailed';

/**
 * Compile-time exhaustiveness check for a mode `switch`.
 *
 * Reached only when a `switch` has failed to handle a member. TypeScript proves
 * that statically -- if any arm is missing, `value` is not `never` and the call
 * does not type-check -- so the runtime `throw` exists for the JavaScript-only
 * paths (a hand-written API response, a stale bundle) where the type system was
 * never consulted.
 *
 * Deliberately throws rather than returning a default. `default: return quick`
 * is the precise bug this module exists to make impossible.
 */
export function assertNeverMode(value: never): never {
  throw new Error(`Unhandled operating mode: ${String(value)}`);
}

/**
 * Raised when a valid operating mode reaches a surface that has no
 * implementation for it.
 *
 * Mirrors `anchor.contracts.UnsupportedOperatingModeError`, and carries the same
 * distinction: this is *not* "that is not a mode" -- `lease_level` is a real,
 * currently-valid mode -- it is "this surface cannot serve that mode yet".
 * Conflating the two would tell a reader that Lease-Level does not exist, which
 * stopped being true at D5.1A.
 */
export class UnsupportedOperatingModeError extends Error {
  readonly operatingMode: OperatingMode;
  readonly surface: string;

  constructor(operatingMode: OperatingMode, surface: string) {
    super(`Operating mode '${operatingMode}' is not supported by ${surface}.`);
    this.name = 'UnsupportedOperatingModeError';
    this.operatingMode = operatingMode;
    this.surface = surface;
  }
}

/**
 * Narrow a wire mode to the modes this frontend can render, or refuse.
 *
 * The single seam through which the existing Quick/Detailed shell keeps its
 * two-branch shape *honestly*. Before D5.1B those branches were two-way because
 * nobody had considered a third mode; after it, they are two-way because a
 * third mode is explicitly refused one line earlier, by name, naming the
 * surface that refused it.
 *
 * Refusing loudly is the deliberate choice over rendering a fallback. A silent
 * fallback in an underwriting tool means showing one deal's economics under
 * another deal's label, which is worse than showing nothing: the analyst has no
 * way to tell that the numbers on screen answer a different question. This path
 * is unreachable today in any case -- the mode selector offers only the two
 * implemented modes, and the backend refuses to persist a Lease-Level deal at
 * all -- so it is a future-proofing guardrail rather than a live code path.
 */
export function requireUnderwriteWorkspaceMode(
  mode: OperatingMode,
  surface: string,
): UnderwriteWorkspaceMode {
  switch (mode) {
    case 'quick':
      return 'quick';
    case 'detailed':
      return 'detailed';
    case 'lease_level':
      // Lease-Level has a workspace from D5.5A -- just not this one. Routing it
      // here would render a rent-roll deal through the scalar Quick/Detailed
      // shell, which is the fallback this module exists to prevent.
      throw new UnsupportedOperatingModeError(mode, surface);
    default:
      return assertNeverMode(mode);
  }
}

/**
 * The short identity label for a mode, as shown on a deal badge.
 *
 * Total by construction. Replaces `mode === 'detailed' ? 'Detailed' : 'Quick'`,
 * which would have labelled a Lease-Level deal "Quick" -- the most quietly
 * misleading outcome available, since the badge is exactly what an analyst
 * scans to know which engine produced a saved deal's numbers.
 */
export function operatingModeLabel(mode: OperatingMode): string {
  switch (mode) {
    case 'quick':
      return 'Quick';
    case 'detailed':
      return 'Detailed';
    case 'lease_level':
      return 'Lease-Level';
    default:
      return assertNeverMode(mode);
  }
}

/**
 * The long-form label used where a mode names an underwriting approach rather
 * than tagging a row -- the owner-summary identity card, for example.
 */
export function operatingModeUnderwriteLabel(mode: OperatingMode): string {
  switch (mode) {
    case 'quick':
      return 'Quick Underwrite';
    case 'detailed':
      return 'Detailed Underwrite';
    case 'lease_level':
      return 'Lease-Level Underwrite';
    default:
      return assertNeverMode(mode);
  }
}


/**
 * Choose one value per operating mode, exhaustively.
 *
 * The typed alternative to `mode === 'detailed' ? a : b`. Because `choices` is a
 * `Record<OperatingMode, T>`, TypeScript requires an entry for every mode --
 * including any mode added later, which becomes a compile error at each call
 * site rather than a silent fallback to whichever branch the ternary happened
 * to have.
 *
 * Introduced at D5.5A so the app shell can pick a deal name, a save status or a
 * workspace per mode without either a third nested ternary or a restructuring
 * of the Quick and Detailed state the shell already holds.
 */
export function byMode<T>(mode: OperatingMode, choices: Record<OperatingMode, T>): T {
  switch (mode) {
    case 'quick':
      return choices.quick;
    case 'detailed':
      return choices.detailed;
    case 'lease_level':
      return choices.lease_level;
    default:
      return assertNeverMode(mode);
  }
}
