/**
 * Phase 7 Gate P7.5 -- the decision half of the Risk workspace: the Decision
 * Matrix, the Strategies and the Scenarios.
 *
 * One component per open Deal -- or, since P7.6, per visible Investment (the
 * owner keys it by mode and Deal id, or by the Investment), holding the three
 * dedicated hooks so the Matrix, the Strategy manager and the Scenario manager
 * read one set of saved Strategies and Scenarios -- never three copies that
 * could disagree. The owner only chooses which view is on screen.
 *
 * **One implementation, two scopes.** A Deal's decision tools address the Deal
 * alone; a visible Investment's address its Units, through the
 * Investment-scoped routes, and its matrix cells are consolidated. A Deal that
 * is itself a Unit of a visible Investment has its decision set on that
 * Investment: this workspace says so, offers to open it, and requests nothing
 * the Deal-scoped routes would refuse.
 *
 * Each view is an ARIA tab panel, always mounted, hidden when inactive: an open
 * Strategy or Scenario draft survives switching views. A visible Investment's
 * workspace also stays mounted while one of its Units is open, so its element
 * ids are namespaced (`decisionIdScope`) and never collide with the Deal's.
 */

import { useEffect } from 'react';
import type { ReactNode } from 'react';
import {
  decisionIdScope,
  INVESTMENT_MATRIX_COPY,
  UNIT_OF_INVESTMENT_NOTICE,
  unitNames,
} from '../investmentCatalog';
import type { InvestmentDecisionScope } from '../investmentCatalog';
import { useDecisionMatrix } from '../useDecisionMatrix';
import { useScenarios } from '../useScenarios';
import { useStrategies } from '../useStrategies';
import type { OperatingMode } from '../types';
import { DecisionMatrixPanel } from './DecisionMatrixPanel';
import { ScenarioWorkspace } from './ScenarioWorkspace';
import { StrategyManager } from './StrategyManager';

/** The visible Investment a Deal belongs to, when it is one of its Units. */
export interface InvestmentMembership {
  investmentName: string;
  onOpen: () => void;
}

/** Which decision editors are open, each holding an unsaved draft. */
export interface DecisionDrafts {
  strategy: boolean;
  scenario: boolean;
}

export interface RiskDecisionWorkspaceProps {
  /** The open Deal's operating mode; `null` for a visible Investment. */
  operatingMode: OperatingMode | null;
  /** The open Deal's saved id, or `null` for a Deal that has never been saved. */
  dealId: string | null;
  /** Whether the base underwriting (or the Investment) has unsaved edits. */
  isDirty: boolean;
  /** The Deal's `updated_at` as of its last Save or Open. A new save moves it. */
  savedAt: string | null;
  /** Whether the Risk workspace is on screen. Nothing is requested before it is. */
  isActive: boolean;
  /** Which Risk view is selected. */
  view: string;
  /** P7.6: a visible Investment's decision scope, instead of a Deal's. */
  investment?: InvestmentDecisionScope | null;
  /** P7.6: set when the open Deal is a Unit of a visible Investment. */
  memberOf?: InvestmentMembership | null;
  /** P7.6: told whenever a Strategy or Scenario editor opens or closes, so an
   * owner that could unmount this workspace can ask before a draft is lost. */
  onDraftsChange?: (drafts: DecisionDrafts) => void;
}

function UnitOfInvestment({ membership }: { membership: InvestmentMembership }) {
  return (
    <section className="scenario-panel investment-unit-notice" aria-label="Decision tools">
      <p className="scenario-blocked" role="note">
        {UNIT_OF_INVESTMENT_NOTICE}
      </p>
      <div>
        <button type="button" className="btn btn-secondary btn-sm" onClick={membership.onOpen}>
          {`Open ${membership.investmentName}`}
        </button>
      </div>
    </section>
  );
}

export function RiskDecisionWorkspace({
  operatingMode,
  dealId,
  isDirty,
  savedAt,
  isActive,
  view,
  investment = null,
  memberOf = null,
  onDraftsChange,
}: RiskDecisionWorkspaceProps) {
  const requests = isActive && memberOf === null;
  const scenarios = useScenarios({ operatingMode, dealId, isDirty, isActive: requests, investment });
  const strategies = useStrategies({ operatingMode, dealId, isDirty, savedAt, isActive: requests, investment });
  const matrix = useDecisionMatrix({
    dealId,
    isDirty,
    savedAt,
    strategies: strategies.strategies,
    scenarios: scenarios.scenarios,
    isReady: scenarios.listStatus === 'ready' && strategies.listStatus === 'ready',
    investment,
  });
  const listError = strategies.loadError ?? scenarios.loadError;
  const scopeId = investment?.investmentId ?? dealId;
  const ids = decisionIdScope(investment !== null);
  const hasStrategyDraft = strategies.editor !== null;
  const hasScenarioDraft = scenarios.editor !== null;

  useEffect(() => {
    onDraftsChange?.({ strategy: hasStrategyDraft, scenario: hasScenarioDraft });
  }, [hasStrategyDraft, hasScenarioDraft, onDraftsChange]);

  function panel(id: 'matrix' | 'strategies' | 'scenarios', content: ReactNode) {
    return (
      <div id={`${ids}risk-panel-${id}`} role="tabpanel" aria-labelledby={`${ids}risk-tab-${id}`} hidden={view !== id}>
        {memberOf === null ? content : <UnitOfInvestment membership={memberOf} />}
      </div>
    );
  }

  return (
    <>
      {panel(
        'matrix',
        <DecisionMatrixPanel
          matrix={matrix}
          dealId={dealId}
          investmentId={investment?.investmentId ?? null}
          copy={investment === null ? undefined : INVESTMENT_MATRIX_COPY}
          unitNames={investment === null ? undefined : unitNames(investment.units)}
          isDirty={isDirty}
          strategies={strategies.strategies}
          scenarios={scenarios.scenarios}
          isLoading={
            scopeId !== null &&
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
        />,
      )}
      {panel('strategies', <StrategyManager state={strategies} />)}
      {panel('scenarios', <ScenarioWorkspace state={scenarios} />)}
    </>
  );
}
