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

export function useValuationChoices(investmentId: string | null): ValuationChoices {
  const [state, setState] = useState<ValuationChoices>(NONE);

  useEffect(() => {
    if (investmentId === null) {
      setState(NONE);
      return;
    }
    let live = true;
    setState({ status: 'loading', choices: [] });
    readValuationTimepoints(investmentId)
      .then((timepoints) => {
        if (live) {
          setState({
            status: 'ready',
            choices: timepoints.map((timepoint) => ({
              timepointId: timepoint.timepoint_id,
              label: timepoint.label,
              modelMonth: timepoint.model_month,
            })),
          });
        }
      })
      .catch(() => {
        if (live) {
          setState({ status: 'error', choices: [] });
        }
      });
    return () => {
      live = false;
    };
  }, [investmentId]);

  return state;
}
