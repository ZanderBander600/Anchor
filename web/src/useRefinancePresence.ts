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
  unitId = null,
  token,
}: {
  dealId?: string | null;
  investmentId?: string | null;
  /** With an Investment: count only refinances of this Unit or of the whole
   * Investment, so a Unit opened from its Investment is labeled only when a
   * refinance actually replaces its acquisition financing. */
  unitId?: string | null;
  token: string;
}): boolean {
  // The read is kept with the Deal or Investment it describes: a re-read on a
  // new `token` keeps the last answer for the same one until it resolves, and
  // another one's answer is never shown.
  const identity = `${dealId ?? ''}|${investmentId ?? ''}|${unitId ?? ''}`;
  const [configured, setConfigured] = useState<{ identity: string; value: boolean } | null>(null);

  useEffect(() => {
    if (dealId === null && investmentId === null) {
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
          const events = payload.capital_structure.capital_events ?? [];
          setConfigured({
            identity,
            value: events.some(
              (event) => unitId === null || event.scope.kind === 'investment' || event.scope.unit_id === unitId,
            ),
          });
        }
      })
      .catch(() => {
        if (live) {
          setConfigured({ identity, value: false });
        }
      });
    return () => {
      live = false;
    };
  }, [dealId, investmentId, unitId, token, identity]);

  if (dealId === null && investmentId === null) {
    return false;
  }
  return configured !== null && configured.identity === identity && configured.value;
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
  const [presence, setPresence] = useState<{ investmentId: string; value: StrategyCapitalEvents } | null>(null);

  useEffect(() => {
    if (investmentId === null) {
      return;
    }
    let live = true;
    readCapitalEventPresence(investmentId)
      .then((payload) => {
        if (live) {
          setPresence({
            investmentId,
            value: {
              strategies: new Set(
                payload.strategies.filter((entry) => entry.capital_events_configured).map((entry) => entry.strategy_id),
              ),
              metrics: new Set(payload.acquisition_financing_metrics),
            },
          });
        }
      })
      .catch(() => {
        if (live) {
          setPresence({ investmentId, value: NO_PRESENCE });
        }
      });
    return () => {
      live = false;
    };
  }, [investmentId, token]);

  // Another Investment's presence is never shown while this one is read.
  return presence !== null && presence.investmentId === investmentId ? presence.value : NO_PRESENCE;
}
