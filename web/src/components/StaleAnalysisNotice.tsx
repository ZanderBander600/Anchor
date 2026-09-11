/**
 * D5.8B -- the one way Anchor says an analytical result is out of date.
 *
 * A persisted AI report or sensitivity run stays on screen after the analyst
 * edits an underwriting assumption: it is real work, produced from real inputs,
 * and useful as reference. What it is not is *current*. This is the notice that
 * says so, and it is one component rather than three so the three surfaces that
 * need it cannot drift into three different-looking answers to the same
 * question.
 *
 * **Stale is not an error.** The result was valid when it ran and is still a
 * faithful record of the inputs it ran against; only the assumptions have moved.
 * So this is warning-toned, not negative-toned, and it never uses the words
 * "invalid", "wrong" or "failed" -- those belong to `error-banner`, which
 * renders separately and can appear at the same time as this. A refused re-run
 * beside a stale result is genuinely two facts, and the analyst is shown two.
 *
 * **Textual, never colour alone.** The words "Out of date" are rendered, so the
 * state survives a monochrome display, a colour-vision difference and a screen
 * reader. `role="status"` rather than `role="alert"`: this is a standing
 * condition of what is on screen, not an interruption, and it should not seize
 * focus or talk over the analyst mid-task.
 */

export interface StaleAnalysisNoticeProps {
  /** What changed and what to do about it. One sentence, no jargon. */
  message: string;
}

/** The label, fixed across every surface so "out of date" always looks and
 * reads the same wherever it appears. */
export const STALE_LABEL = 'Out of date';

export function StaleAnalysisNotice({ message }: StaleAnalysisNoticeProps) {
  return (
    <div className="stale-notice" role="status">
      <span className="stale-notice-label">{STALE_LABEL}</span>
      <p className="stale-notice-message">{message}</p>
    </div>
  );
}

/** The two sentences this gate ships, kept beside the component that renders
 * them so the wording is reviewed in one place rather than at each call site.
 *
 * Each is one string literal rather than two joined with `+`, for the reason
 * `leaseLevelSensitivity.ts` gives for the same choice: this module is asserted
 * to contain no binary arithmetic operator at all, and the audit that forbids
 * browser math cannot tell a concatenated sentence from a sum. Writing the
 * prose whole means the guardrail needs no exception carved into it. */
// prettier-ignore
export const STALE_AI_MESSAGE =
  'Underwriting assumptions have changed since this analysis was generated. Re-analyze the deal and regenerate the analysis to update it.';

// prettier-ignore
export const STALE_SENSITIVITY_MESSAGE =
  'Underwriting assumptions have changed since this sensitivity was run. Run the sensitivity again to update these results.';
