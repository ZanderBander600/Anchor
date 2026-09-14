/**
 * Phase 7 Gate P7.5 -- the decision half of the Risk workspace: the Decision
 * Matrix, the Strategies and the Scenarios.
 *
 * One component per open Deal (the owner keys it by mode and Deal id), holding
 * the three dedicated hooks so the Matrix, the Strategy manager and the
 * Scenario manager read one set of saved Strategies and Scenarios -- never three
 * copies that could disagree. `App.tsx` only chooses which view is on screen.
 *
 * Each view is an ARIA tab panel, always mounted, hidden when inactive: an open
 * Strategy or Scenario draft survives switching views.
 */

import { useDecisionMatrix } from '../useDecisionMatrix';
import { useScenarios } from '../useScenarios';
import { useStrategies } from '../useStrategies';
import type { OperatingMode } from '../types';
import { DecisionMatrixPanel } from './DecisionMatrixPanel';
import { ScenarioWorkspace } from './ScenarioWorkspace';
import { StrategyManager } from './StrategyManager';

export interface RiskDecisionWorkspaceProps {
  operatingMode: OperatingMode;
  /** The open Deal's saved id, or `null` for a Deal that has never been saved. */
  dealId: string | null;
  /** Whether the base underwriting has unsaved edits. */
  isDirty: boolean;
  /** The Deal's `updated_at` as of its last Save or Open. A new save moves it. */
  savedAt: string | null;
  /** Whether the Risk workspace is on screen. Nothing is requested before it is. */
  isActive: boolean;
  /** Which Risk view is selected. */
  view: string;
}

export function RiskDecisionWorkspace({
  operatingMode,
  dealId,
  isDirty,
  savedAt,
  isActive,
  view,
}: RiskDecisionWorkspaceProps) {
  const scenarios = useScenarios({ operatingMode, dealId, isDirty, isActive });
  const strategies = useStrategies({ operatingMode, dealId, isDirty, savedAt, isActive });
  const matrix = useDecisionMatrix({
    dealId,
    isDirty,
    savedAt,
    strategies: strategies.strategies,
    scenarios: scenarios.scenarios,
    isReady: scenarios.listStatus === 'ready' && strategies.listStatus === 'ready',
  });
  const listError = strategies.loadError ?? scenarios.loadError;

  return (
    <>
      <div
        id="risk-panel-matrix"
        role="tabpanel"
        aria-labelledby="risk-tab-matrix"
        hidden={view !== 'matrix'}
      >
        <DecisionMatrixPanel
          matrix={matrix}
          dealId={dealId}
          isDirty={isDirty}
          strategies={strategies.strategies}
          scenarios={scenarios.scenarios}
          isLoading={
            dealId !== null &&
            listError === null &&
            (scenarios.listStatus !== 'ready' || strategies.listStatus !== 'ready')
          }
          loadError={listError}
          retryLoad={() => {
            if (strategies.listStatus === 'error') {
              strategies.retryLoad();
            }
            if (scenarios.listStatus === 'error') {
              scenarios.retryLoad();
            }
          }}
        />
      </div>
      <div
        id="risk-panel-strategies"
        role="tabpanel"
        aria-labelledby="risk-tab-strategies"
        hidden={view !== 'strategies'}
      >
        <StrategyManager state={strategies} />
      </div>
      <div
        id="risk-panel-scenarios"
        role="tabpanel"
        aria-labelledby="risk-tab-scenarios"
        hidden={view !== 'scenarios'}
      >
        <ScenarioWorkspace state={scenarios} />
      </div>
    </>
  );
}
