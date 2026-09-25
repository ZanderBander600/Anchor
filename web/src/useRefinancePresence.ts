/**
 * Refinance & Capital Events V1 Stage 3 -- which surfaces must name the
 * acquisition-financing reference.
 *
 * A Deal's underwriting results, Capital Economics, Owner Summary and an
 * Investment's overview report the Project levered IRR and equity multiple:
 * the acquisition loan held to the sale. When the Base Capital Structure
 * configures a refinance, those figures exclude it, so they may appear only as
 * the labelled reference "Acquisition financing — excludes later capital
 * events" and never as the refinance-adjusted headline (R-P rules 3 to 5).
 *
 * The fact read here is the saved structure's own -- whether it states a
 * capital event -- and the Decision Matrix reads the server's typed
 * per-Strategy statement. Nothing is resolved, sized or computed.
 */

import { createContext, useContext, useEffect, useState } from 'react';
import {
  readCapitalEventPresence,
  readDealCapitalStructure,
  readInvestmentCapitalStructure,
} from './api';

/** Whether the surrounding Deal or Investment's Base Capital Structure
 * configures a refinance. `false` outside any provider, which is every surface
 * without one: presentation is then exactly as it always was. */
export const AcquisitionReferenceContext = createContext<boolean>(false);

export function useAcquisitionReference(): boolean {
  return useContext(AcquisitionReferenceContext);
}

/** Read whether the Base Capital Structure of a Deal or Investment configures
 * a capital event. `token` re-reads it when the caller's saved state or view
 * changes (a structure is saved from another workspace). A failed read reports
 * `false`, which leaves every surface exactly as it was. */
export function useBaseCapitalEvents({
  dealId = null,
  investmentId = null,
  token,
}: {
  dealId?: string | null;
  investmentId?: string | null;
  token: string;
}): boolean {
  const [configured, setConfigured] = useState(false);

  useEffect(() => {
    if (dealId === null && investmentId === null) {
      setConfigured(false);
      return;
    }
    let live = true;
    const request =
      investmentId !== null
        ? readInvestmentCapitalStructure(investmentId)
        : readDealCapitalStructure(dealId as string);
    request
      .then((payload) => {
        if (live) {
          setConfigured((payload.capital_structure.capital_events ?? []).length > 0);
        }
      })
      .catch(() => {
        if (live) {
          setConfigured(false);
        }
      });
    return () => {
      live = false;
    };
  }, [dealId, investmentId, token]);

  return configured;
}

export interface StrategyCapitalEvents {
  /** Strategy ids whose resolved Capital Structure configures a refinance. */
  strategies: ReadonlySet<string>;
  /** The Project matrix metrics those Strategies' figures qualify. */
  metrics: ReadonlySet<string>;
}

const NO_PRESENCE: StrategyCapitalEvents = { strategies: new Set(), metrics: new Set() };

/** The server's typed statement of which Strategies of an Investment are
 * refinance-bearing, and which Project metrics that makes the acquisition-
 * financing reference. Empty until read, and on a failed read. */
export function useStrategyCapitalEvents(investmentId: string | null, token: string): StrategyCapitalEvents {
  const [presence, setPresence] = useState<StrategyCapitalEvents>(NO_PRESENCE);

  useEffect(() => {
    if (investmentId === null) {
      setPresence(NO_PRESENCE);
      return;
    }
    let live = true;
    readCapitalEventPresence(investmentId)
      .then((payload) => {
        if (live) {
          setPresence({
            strategies: new Set(
              payload.strategies.filter((entry) => entry.capital_events_configured).map((entry) => entry.strategy_id),
            ),
            metrics: new Set(payload.acquisition_financing_metrics),
          });
        }
      })
      .catch(() => {
        if (live) {
          setPresence(NO_PRESENCE);
        }
      });
    return () => {
      live = false;
    };
  }, [investmentId, token]);

  return presence;
}
