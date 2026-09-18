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

import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import {
  decisionIdScope,
  INVESTMENT_DIRTY_MESSAGE,
  INVESTMENT_MATRIX_COPY,
  UNIT_OF_INVESTMENT_NOTICE,
  unitDisplayName,
  unitNames,
} from '../investmentCatalog';
import type { InvestmentDecisionScope } from '../investmentCatalog';
import { useCapitalStructure } from '../useCapitalStructure';
import { usePartnership } from '../usePartnership';
import { usePartnerDecisionMatrix } from '../usePartnerDecisionMatrix';
import { usePositionDecisionMatrix } from '../usePositionDecisionMatrix';
import { useDecisionMatrix } from '../useDecisionMatrix';
import { useScenarios } from '../useScenarios';
import { useStrategies } from '../useStrategies';
import type { OperatingMode } from '../types';
import { CapitalStructureWorkspace } from './CapitalStructureWorkspace';
import type { ScopeUnit } from './CapitalStructureEditor';
import { DecisionMatrixPanel } from './DecisionMatrixPanel';
import { PartnerDecisionMatrixPanel } from './PartnerDecisionMatrixPanel';
import { PartnershipWorkspace } from './PartnershipWorkspace';
import { PositionDecisionMatrixPanel } from './PositionDecisionMatrixPanel';
import { ScenarioWorkspace } from './ScenarioWorkspace';
import { StrategyManager } from './StrategyManager';

/** The one Unit a standalone Deal's positions may be scoped to: the Deal
 * itself. It is never offered as a choice -- with one Unit there is nothing to
 * choose -- but it names the scope wherever a result reports one. */
const DEAL_SCOPE_UNIT_NAME = 'This Deal';

/** Each message is one string literal, never joined with `+`. */
// prettier-ignore
const SAVE_BEFORE_CAPITAL_MESSAGE =
  'Save this deal before adding a capital structure.';

// prettier-ignore
const DIRTY_BEFORE_CAPITAL_MESSAGE =
  'Base underwriting has unsaved changes. Save the deal, then edit the capital structure.';

// prettier-ignore
const SAVE_BEFORE_PARTNERSHIP_MESSAGE =
  'Save this deal before adding a partnership.';

// prettier-ignore
const DIRTY_BEFORE_PARTNERSHIP_MESSAGE =
  'Base underwriting has unsaved changes. Save the deal, then edit the partnership.';

/** The visible Investment a Deal belongs to, when it is one of its Units. */
export interface InvestmentMembership {
  investmentName: string;
  onOpen: () => void;
}

/** Which typed perspective the Decision Matrix is showing (DC-3).
 *
 * `project` is the deal's own economics and stays the default and the upstream
 * one. `position` is one capital position's and `partner` is one partner's, over
 * the same variants. The choice lives here, with the surface that shows all
 * three, rather than inside any one perspective's hook. */
export type DecisionPerspectiveChoice = 'project' | 'position' | 'partner';

/** Which decision editors are open, each holding an unsaved draft. */
export interface DecisionDrafts {
  strategy: boolean;
  scenario: boolean;
  /** P7.8B: the Base Capital Structure editor. */
  capitalStructure: boolean;
  /** P7.9 Stage 3: the Base Partnership editor. */
  partnership: boolean;
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
  const [perspective, setPerspective] = useState<DecisionPerspectiveChoice>('project');
  // P7.8B: the Base Capital Structure of this Deal, or of this Investment. It
  // is the Investment's own contract, so a Deal reaches it through the Deal
  // route, which materializes the hidden one-unit Investment on the first
  // non-empty save (Q4) -- and the UI keeps saying "Deal". Read before the
  // Strategies, which copy it when a Strategy states its own structure.
  const capital = useCapitalStructure({
    dealId,
    investmentId: investment?.investmentId ?? null,
    isDirty,
    savedAt,
    isActive: requests,
  });
  // P7.9 Stage 3: the Base Partnership of this Deal, or of this Investment. It
  // is the Investment's own contract, reached the same way the Capital
  // Structure is, and it allocates the Common Equity Cash Flow the structure
  // leaves behind -- so it is read beside it, and downstream of it.
  const partnership = usePartnership({
    dealId,
    investmentId: investment?.investmentId ?? null,
    isDirty,
    savedAt,
    isActive: requests,
  });
  const scenarios = useScenarios({ operatingMode, dealId, isDirty, isActive: requests, investment });
  const strategies = useStrategies({
    operatingMode,
    dealId,
    isDirty,
    savedAt,
    isActive: requests,
    investment,
    baseCapitalStructure: capital.saved,
    basePartnership: partnership.saved,
  });
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
  const hasCapitalDraft = capital.hasDraft;
  const hasPartnershipDraft = partnership.hasDraft;

  /** The Units a position may be scoped to. A standalone Deal has exactly one,
   * so the editor offers no choice; an Investment offers each Unit by name. */
  const capitalUnits: ScopeUnit[] =
    investment === null
      ? dealId === null
        ? []
        : [{ unitId: dealId, name: DEAL_SCOPE_UNIT_NAME }]
      : investment.units.map((unit) => ({ unitId: unit.unitId, name: unitDisplayName(unit) }));
  const capitalUnitNames =
    investment === null
      ? dealId === null
        ? {}
        : { [dealId]: DEAL_SCOPE_UNIT_NAME }
      : unitNames(investment.units);

  /** Why the analyst cannot change the structure right now, or `null`. The
   * structure is authored against the *saved* underwriting, so an unsaved base
   * blocks it for the same reason it blocks a Strategy. */
  const capitalBlockedReason =
    investment !== null
      ? isDirty
        ? INVESTMENT_DIRTY_MESSAGE
        : null
      : dealId === null
        ? SAVE_BEFORE_CAPITAL_MESSAGE
        : isDirty
          ? DIRTY_BEFORE_CAPITAL_MESSAGE
          : null;

  /** Why the analyst cannot change the Partnership right now, or `null`. It is
   * authored against the *saved* underwriting for the same reason the structure
   * is. */
  const partnershipBlockedReason =
    investment !== null
      ? isDirty
        ? INVESTMENT_DIRTY_MESSAGE
        : null
      : dealId === null
        ? SAVE_BEFORE_PARTNERSHIP_MESSAGE
        : isDirty
          ? DIRTY_BEFORE_PARTNERSHIP_MESSAGE
          : null;

  /** The saved economic state a Position matrix belongs to. A structured cell
   * is invalidated by the capital structure it ran, by a Strategy's overlays --
   * its root overlays included, which is where a Strategy states its own
   * structure -- and by a Scenario's overrides. A rename moves none of them. */
  const positionStateToken = JSON.stringify([
    investment === null ? dealId : investment.investmentId,
    investment === null ? savedAt : investment.stateToken,
    strategies.strategies.map((record) => [
      record.strategy.strategy_id,
      record.strategy.overlays,
      record.strategy.root_overlays ?? null,
    ]),
    scenarios.scenarios.map((record) => [record.scenario.scenario_id, record.scenario.overrides]),
    capital.saved.positions,
  ]);

  // The positions belong to the Investment: a visible one, or the Deal's hidden
  // wrapper once a structure, Strategy or Scenario has created it.
  const positionMatrix = usePositionDecisionMatrix({
    investmentId: investment?.investmentId ?? capital.investmentId,
    isDirty,
    stateToken: positionStateToken,
    isActive: requests && view === 'matrix' && perspective === 'position',
  });

  /** The saved economic state a Partner matrix belongs to: everything a
   * structured cell is invalidated by, plus the saved Base Partnership. A
   * Strategy's own Partnership already travels in its root overlays above. */
  const partnerStateToken = JSON.stringify([positionStateToken, partnership.saved]);

  // The partners belong to the Investment: a visible one, or the Deal's hidden
  // wrapper once a Partnership, structure, Strategy or Scenario has created it.
  const partnerMatrix = usePartnerDecisionMatrix({
    investmentId: investment?.investmentId ?? partnership.investmentId ?? capital.investmentId,
    isDirty,
    stateToken: partnerStateToken,
    isActive: requests && view === 'matrix' && perspective === 'partner',
  });

  useEffect(() => {
    onDraftsChange?.({
      strategy: hasStrategyDraft,
      scenario: hasScenarioDraft,
      capitalStructure: hasCapitalDraft,
      partnership: hasPartnershipDraft,
    });
  }, [
    hasStrategyDraft,
    hasScenarioDraft,
    hasCapitalDraft,
    hasPartnershipDraft,
    onDraftsChange,
  ]);

  function panel(
    id: 'matrix' | 'strategies' | 'scenarios' | 'capital-structure' | 'partnership',
    content: ReactNode,
  ) {
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
        <>
          {/* DC-3: one comparison surface, three typed perspectives. PROJECT is
            * the deal's own economics; POSITION(position_id) is one capital
            * position's; PARTNER(partner_id) is one partner's share of the
            * Common Equity the structure leaves behind. They are never mixed in
            * one table -- a Project IRR, a mezzanine IRR and an LP's IRR are
            * different claims on different cash (NS-1). */}
          <div
            className="strategy-mode decision-perspective"
            role="radiogroup"
            aria-label="Decision matrix perspective"
          >
            {(
              [
                { value: 'project', label: 'Project' },
                { value: 'position', label: 'Position' },
                { value: 'partner', label: 'Partner' },
              ] as const
            ).map((option) => (
              <label
                key={option.value}
                className={
                  perspective === option.value
                    ? 'strategy-mode-option strategy-mode-option-active'
                    : 'strategy-mode-option'
                }
              >
                <input
                  type="radio"
                  name={`${ids}decision-perspective`}
                  value={option.value}
                  checked={perspective === option.value}
                  onChange={() => setPerspective(option.value)}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
          {perspective === 'partner' ? (
            <PartnerDecisionMatrixPanel state={partnerMatrix} ids={ids} isDirty={isDirty} />
          ) : perspective === 'position' ? (
            <PositionDecisionMatrixPanel state={positionMatrix} ids={ids} isDirty={isDirty} />
          ) : (
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
            />
          )}
        </>,
      )}
      {panel('strategies', <StrategyManager state={strategies} />)}
      {panel('scenarios', <ScenarioWorkspace state={scenarios} />)}
      {panel(
        'capital-structure',
        <CapitalStructureWorkspace
          state={capital}
          prefix={ids}
          units={capitalUnits}
          unitNames={capitalUnitNames}
          blockedReason={capitalBlockedReason}
          isInvestment={investment !== null}
        />,
      )}
      {panel(
        'partnership',
        <PartnershipWorkspace
          state={partnership}
          prefix={ids}
          blockedReason={partnershipBlockedReason}
          isInvestment={investment !== null}
        />,
      )}
    </>
  );
}
