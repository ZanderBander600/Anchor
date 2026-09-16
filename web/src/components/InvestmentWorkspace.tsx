/**
 * Phase 7 Gate P7.6 -- the visible Investment workspace.
 *
 * One transaction over one or more Deals. The header says so -- the
 * Investment's name, "Investment", its Transaction Price and its Unit count --
 * with Edit Investment and Delete Investment. There is no Quick / Detailed /
 * Lease-Level toggle: no single underwriting mode governs an Investment, and
 * its Units may each be underwritten in a different mode.
 *
 * Three workspaces: **Overview** (structure, shared assumptions and the Base
 * consolidated economics), **Units** (the member Deals, each opened in its own
 * existing Deal workspace), and **Risk** (the Decision Matrix, Strategies and
 * Scenarios across the Units -- the P7.5 surface, in the Investment's scope).
 * Sensitivity and break-even stay Unit-level: they are opened on a Unit.
 *
 * State lives in `useInvestmentWorkspace` and `useInvestmentAnalysis`; the
 * decision tools own theirs (`RiskDecisionWorkspace`). Every panel stays
 * mounted and hidden when inactive, so an open draft -- the details draft, a
 * Strategy draft, a Scenario draft -- survives switching workspaces and a trip
 * into a Unit's underwriting. The decision tools' element ids are namespaced
 * (`decisionIdScope`), so they never collide with the open Deal's own.
 */

import { useEffect, useState } from 'react';
import { formatCurrency } from '../format';
import {
  decisionIdScope,
  DELETE_INVESTMENT_CONSEQUENCES,
  INVESTMENT_LABEL,
  investmentLeaveWarning,
} from '../investmentCatalog';
import type { VisibleInvestment } from '../investmentTypes';
import type { Deal } from '../types';
import { useInvestmentAnalysis } from '../useInvestmentAnalysis';
import { useInvestmentWorkspace } from '../useInvestmentWorkspace';
import { InvestmentOverview } from './InvestmentOverview';
import { InvestmentUnitsPanel } from './InvestmentUnitsPanel';
import { RiskDecisionWorkspace } from './RiskDecisionWorkspace';
import type { DecisionDrafts } from './RiskDecisionWorkspace';
import { SubNav } from './SubNav';

export interface InvestmentWorkspaceProps {
  investmentId: string;
  /** Every visible Investment, to say which Deals already belong to one. */
  investments: VisibleInvestment[];
  /** A new object re-reads the Investment and its Deals. */
  refreshSignal: object;
  onOpenUnit: (deal: Deal) => void;
  onChanged: () => void;
  onDeleted: () => void;
  /** What leaving this Investment for another would discard -- unsaved details,
   * an open Strategy or Scenario draft -- worded for the confirmation, or
   * `null` when nothing would be lost. */
  onUnsavedChange: (warning: string | null) => void;
  /** Whether the workspace is on screen. It stays mounted, hidden, while one
   * of its Units (or another Deal) is open, so every draft survives; while
   * hidden its decision tools request nothing. */
  isShown?: boolean;
}

type InvestmentTabId = 'overview' | 'units' | 'risk';

const INVESTMENT_TABS: { id: InvestmentTabId; label: string; subtitle: string }[] = [
  {
    id: 'overview',
    label: 'Overview',
    subtitle: 'Investment structure, shared assumptions and consolidated project economics.',
  },
  {
    id: 'units',
    label: 'Units',
    subtitle: 'The saved Deals in this transaction. Each Unit keeps its own underwriting.',
  },
  {
    id: 'risk',
    label: 'Risk',
    subtitle:
      'Decision matrix, strategies and scenarios across the Units. Sensitivity and break-even are on each Unit.',
  },
];

const RISK_VIEWS = [
  { id: 'matrix', label: 'Decision Matrix' },
  { id: 'strategies', label: 'Strategies' },
  { id: 'scenarios', label: 'Scenarios' },
  { id: 'capital-structure', label: 'Capital Structure' },
];

/** The Investment's decision tools' id namespace: its Risk tabs and panels
 * never share an id with the open Deal's. */
const RISK_IDS = decisionIdScope(true);

const NO_DRAFTS: DecisionDrafts = { strategy: false, scenario: false, capitalStructure: false };

function unitCount(count: number): string {
  return count === 1 ? '1 Unit' : `${count} Units`;
}

export function InvestmentWorkspace({
  investmentId,
  investments,
  refreshSignal,
  onOpenUnit,
  onChanged,
  onDeleted,
  onUnsavedChange,
  isShown = true,
}: InvestmentWorkspaceProps) {
  const workspace = useInvestmentWorkspace({ investmentId, refreshSignal, onChanged, onDeleted });
  const analysis = useInvestmentAnalysis({
    investmentId,
    stateToken: workspace.stateToken,
    isBlocked: workspace.isEconomicBlocked,
  });
  const [tab, setTab] = useState<InvestmentTabId>('overview');
  const [riskView, setRiskView] = useState('matrix');
  const [drafts, setDrafts] = useState<DecisionDrafts>(NO_DRAFTS);
  const hasUnsaved = workspace.isDirty || workspace.isMembershipChanging;
  const leaveWarning = investmentLeaveWarning({
    details: hasUnsaved,
    strategyDraft: drafts.strategy,
    scenarioDraft: drafts.scenario,
    capitalStructureDraft: drafts.capitalStructure,
  });

  useEffect(() => {
    onUnsavedChange(leaveWarning);
  }, [leaveWarning, onUnsavedChange]);

  const investment = workspace.investment;

  if (investment === null) {
    return (
      <div className="workspace-scroll">
        {workspace.status === 'error' ? (
          <div className="error-banner scenario-error" role="alert">
            <span>{workspace.loadError}</span>
            <button type="button" className="btn btn-ghost btn-xs" onClick={workspace.retryLoad}>
              Retry
            </button>
          </div>
        ) : (
          <p className="scenario-muted" role="status">
            Loading investment…
          </p>
        )}
      </div>
    );
  }

  return (
    <>
      <header className="deal-header investment-header">
        <div className="deal-header-row">
          <div className="investment-header-identity">
            <h1 className="investment-header-name">{investment.name}</h1>
            <span className="investment-kind-tag">{INVESTMENT_LABEL}</span>
            <dl className="investment-header-figures">
              <div>
                <dt>Transaction Price</dt>
                <dd>{formatCurrency(investment.transaction_price)}</dd>
              </div>
              <div>
                <dt>Units</dt>
                <dd>{unitCount(investment.units.length)}</dd>
              </div>
            </dl>
          </div>
          <div className="deal-header-actions">
            {hasUnsaved && (
              <span className="save-status save-status-unsaved-changes">
                <span className="save-status-dot" aria-hidden="true" />
                Unsaved changes
              </span>
            )}
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={workspace.requestDelete}
              disabled={workspace.isConfirmingDelete}
            >
              Delete Investment
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                workspace.startEdit();
                setTab('overview');
              }}
              disabled={workspace.isEditing}
            >
              Edit Investment
            </button>
          </div>
        </div>
        {workspace.isConfirmingDelete && (
          <div className="investment-confirm investment-delete-confirm" role="group" aria-label={`Confirm deleting ${investment.name}`}>
            <p className="investment-confirm-text">{DELETE_INVESTMENT_CONSEQUENCES}</p>
            <div className="investment-confirm-actions">
              <button
                type="button"
                className="btn btn-danger btn-sm"
                onClick={() => void workspace.confirmDelete()}
                disabled={workspace.isDeleting}
              >
                {workspace.isDeleting ? 'Deleting…' : 'Delete Investment'}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={workspace.cancelDelete}
                disabled={workspace.isDeleting}
                autoFocus
              >
                Cancel
              </button>
            </div>
            {workspace.deleteError !== null && (
              <p className="investment-inline-error" role="alert">
                {workspace.deleteError}
              </p>
            )}
          </div>
        )}
      </header>

      <div className="workspace-nav" role="tablist" aria-label="Investment workspace">
        {INVESTMENT_TABS.map((entry) => (
          <button
            key={entry.id}
            id={`investment-tab-${entry.id}`}
            type="button"
            role="tab"
            aria-selected={tab === entry.id}
            aria-controls={`investment-panel-${entry.id}`}
            className={tab === entry.id ? 'workspace-tab workspace-tab-active' : 'workspace-tab'}
            onClick={() => setTab(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <div className="workspace-scroll">
        {INVESTMENT_TABS.map((entry) => (
          <section
            key={entry.id}
            id={`investment-panel-${entry.id}`}
            role="tabpanel"
            aria-labelledby={`investment-tab-${entry.id}`}
            hidden={tab !== entry.id}
            className="workspace-panel"
          >
            <div className="workspace-panel-head">
              <h2 className="workspace-title">{entry.label}</h2>
              <p className="workspace-subtitle">{entry.subtitle}</p>
            </div>
            <div className="workspace-body">
              {entry.id === 'overview' && <InvestmentOverview workspace={workspace} analysis={analysis} />}
              {entry.id === 'units' && (
                <InvestmentUnitsPanel workspace={workspace} investments={investments} onOpenUnit={onOpenUnit} />
              )}
              {entry.id === 'risk' && workspace.scope !== null && (
                <div className="risk-workspace">
                  <SubNav
                    items={RISK_VIEWS}
                    active={riskView}
                    onSelect={setRiskView}
                    label="Investment risk views"
                    idFor={(id) => `${RISK_IDS}risk-tab-${id}`}
                    controlsFor={(id) => `${RISK_IDS}risk-panel-${id}`}
                  />
                  <RiskDecisionWorkspace
                    key={investmentId}
                    operatingMode={null}
                    dealId={null}
                    isDirty={workspace.isEconomicBlocked}
                    savedAt={null}
                    isActive={isShown && tab === 'risk'}
                    view={riskView}
                    investment={workspace.scope}
                    onDraftsChange={setDrafts}
                  />
                </div>
              )}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
