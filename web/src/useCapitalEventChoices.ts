/**
 * Refinance & Capital Events V1 Stage 3 -- the valuations a refinance's LTV
 * constraint may reference.
 *
 * Reads the Investment's authored P7.10 valuation definitions, by label, for
 * the one selector that offers them: the LTV constraint's. It resolves no value
 * -- a definition is referenced, never copied into the event, and the engine
 * resolves it fresh for each executing variant (Section 8.1). A Deal with no
 * Investment yet has no valuation to reference, which is a stated state, not an
 * error: DSCR and fixed-cap sizing need none.
 */

import { useEffect, useState } from 'react';
import { readValuationTimepoints } from './api';

export interface ValuationChoice {
  timepointId: string;
  label: string;
  modelMonth: number;
}

export type ValuationChoiceStatus = 'none' | 'loading' | 'ready' | 'error';

export interface ValuationChoices {
  status: ValuationChoiceStatus;
  choices: ValuationChoice[];
}

const NONE: ValuationChoices = { status: 'none', choices: [] };
const LOADING: ValuationChoices = { status: 'loading', choices: [] };

export function useValuationChoices(investmentId: string | null): ValuationChoices {
  // Each read is kept with the Investment it was read for, so a stale read is
  // never shown for another Investment and nothing is reset from an effect.
  const [loaded, setLoaded] = useState<{ investmentId: string; choices: ValuationChoices } | null>(null);

  useEffect(() => {
    if (investmentId === null) {
      return;
    }
    let live = true;
    readValuationTimepoints(investmentId)
      .then((timepoints) => {
        if (live) {
          setLoaded({
            investmentId,
            choices: {
              status: 'ready',
              choices: timepoints.map((timepoint) => ({
                timepointId: timepoint.timepoint_id,
                label: timepoint.label,
                modelMonth: timepoint.model_month,
              })),
            },
          });
        }
      })
      .catch(() => {
        if (live) {
          setLoaded({ investmentId, choices: { status: 'error', choices: [] } });
        }
      });
    return () => {
      live = false;
    };
  }, [investmentId]);

  if (investmentId === null) {
    return NONE;
  }
  return loaded !== null && loaded.investmentId === investmentId ? loaded.choices : LOADING;
}
