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
 * The modes this frontend can actually render a workflow for today.
 *
 * Distinct from {@link OperatingMode}, which is the full wire vocabulary. The
 * gap between the two is the honest statement of where D5 currently stands:
 * the backend parses `lease_level` and refuses every operation on it (D5.1A),
 * and the frontend knows the name without having a workspace behind it.
 *
 * D5.5A adds `'lease_level'` here, at which point every `requireImplementedMode`
 * call site becomes a compile error until it handles the new arm -- which is
 * the point of naming the narrower set at all.
 */
export type ImplementedOperatingMode = 'quick' | 'detailed';

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
export function requireImplementedMode(
  mode: OperatingMode,
  surface: string,
): ImplementedOperatingMode {
  switch (mode) {
    case 'quick':
      return 'quick';
    case 'detailed':
      return 'detailed';
    case 'lease_level':
      // D5.5A adds the Lease-Level workspace and removes this arm. Until then
      // the mode is a name the frontend can render on a badge, not a workflow
      // it can drive.
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
