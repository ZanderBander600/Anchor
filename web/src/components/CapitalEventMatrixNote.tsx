/**
 * Refinance & Capital Events V1 Stage 3 -- the note a Position or Partner
 * Decision Matrix carries when a Strategy's Capital Structure includes a
 * refinance (R-P rules 2 and 5; Section 13.3's Scenario disclosure).
 *
 * It reads the server's typed per-Strategy statement and renders nothing when
 * no Strategy is refinance-bearing, so every other matrix is unchanged.
 */

import { MATRIX_REFINANCE_NOTE, SCENARIO_RATE_LIMITATION } from '../refinanceCatalog';
import { useStrategyCapitalEvents } from '../useRefinancePresence';

export function CapitalEventMatrixNote({ investmentId, token }: { investmentId: string | null; token: string }) {
  const presence = useStrategyCapitalEvents(investmentId, token);
  // Position and Partner figures include each Strategy's refinance whatever
  // this read says, so the note is informative only: it is shown for a settled
  // answer that a Strategy is refinance-bearing, and never inferred otherwise.
  if (presence.status !== 'ready' || presence.strategies.size === 0) {
    return null;
  }
  return (
    <p className="refinance-reference-notice" role="note">
      {`${MATRIX_REFINANCE_NOTE} ${SCENARIO_RATE_LIMITATION}`}
    </p>
  );
}
