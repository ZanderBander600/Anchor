import type { ReactNode } from 'react';
import { AssumptionFieldGrid } from './AssumptionFieldGrid';
import { LiveCaseRail } from './LiveCaseRail';
import { StrategyStrip } from './StrategyStrip';
import { SubNav } from './SubNav';
import { OPERATIONS_VIEWS, UNDERWRITE_TABS, resultsViewsFor, sectionsForView } from '../underwrite';
import type { FieldSection, ResultsViewId, UnderwriteTabId } from '../underwrite';
import type { AcquisitionResults, OperatingMode } from '../types';

export interface UnderwriteWorkspaceProps {
  operatingMode: OperatingMode;
  /** Assumption sections for every tab, already resolved against this
   * mode's own state by `buildQuickSections`/`buildDetailedSections`. */
  sections: Record<UnderwriteTabId, FieldSection[]>;
  dealContext: string;
  onDealContextChange: (value: string) => void;
  isSubmitting: boolean;

  activeTab: UnderwriteTabId;
  onTabChange: (tab: UnderwriteTabId) => void;
  operationsView: string;
  onOperationsViewChange: (view: string) => void;
  resultsView: ResultsViewId;
  onResultsViewChange: (view: ResultsViewId) => void;

  /** The current authoritative analysis, or null. Drives both the Live Case
   * rail and whether the Results tab has anything to show. */
  results: AcquisitionResults | null;
  /** The content of each Results sub-view, supplied by the caller so this
   * component never needs to know about the individual result components or
   * about Detailed's operating projection. */
  resultsViews: Partial<Record<ResultsViewId, ReactNode>>;
}

function panelId(prefix: string, id: string): string {
  return `underwrite-${prefix}-panel-${id}`;
}

function tabId(prefix: string, id: string): string {
  return `underwrite-${prefix}-tab-${id}`;
}

/**
 * Sprint C Gate C3 -- the Underwrite workspace.
 *
 * Replaces the C2 vertical stack (Deal Context textarea -> every assumption
 * -> the full results surfaces) with deliberate navigation: five tabs, a
 * compact strategy strip, a persistent Live Case rail, and results behind
 * their own sub-navigation.
 *
 * Quick and Detailed render through this one component. They differ only in
 * the `sections` handed to it, in whether Operations has sub-navigation, and
 * in whether Results offers an Operating Statement -- so the two modes
 * cannot visually drift apart and there is no duplicated component tree.
 * Their STATE remains completely independent: each mode resolves its own
 * sections from its own values and handlers.
 *
 * Every tab and sub-view stays MOUNTED, with the inactive ones `hidden` --
 * the same pattern `WorkspacePanel` uses one level up. That is what makes
 * C3.17's guarantee structural rather than something each tab must remember
 * to support: an unsaved value cannot be lost to a tab switch because the
 * input is never torn down. Hidden panels occupy no layout, so this costs
 * nothing against the "one viewport per tab" scroll target.
 *
 * There is no Analyze button here. Gate C3 removed the form-level Analyze in
 * favour of the always-visible one in the persistent deal header, so the
 * action has exactly one home. Analyze behavior itself is unchanged.
 */
export function UnderwriteWorkspace({
  operatingMode,
  sections,
  dealContext,
  onDealContextChange,
  isSubmitting,
  activeTab,
  onTabChange,
  operationsView,
  onOperationsViewChange,
  resultsView,
  onResultsViewChange,
  results,
  resultsViews,
}: UnderwriteWorkspaceProps) {
  // Detailed Operations carries 12 assumptions across three distinct concerns
  // and earns sub-navigation; Quick Operations carries four and does not.
  // The same architecture, sized to the content.
  const hasOperationsSubNav = operatingMode === 'detailed';
  const availableResultsViews = resultsViewsFor(operatingMode);

  return (
    <div className="underwrite">
      <StrategyStrip value={dealContext} onChange={onDealContextChange} />

      <SubNav
        items={UNDERWRITE_TABS}
        active={activeTab}
        onSelect={(id) => onTabChange(id as UnderwriteTabId)}
        label="Underwrite sections"
        idFor={(id) => tabId('section', id)}
        controlsFor={(id) => panelId('section', id)}
      />

      <div className="underwrite-body">
        <div className="underwrite-editor">
          {UNDERWRITE_TABS.map((tab) => {
            const isActive = tab.id === activeTab;

            if (tab.id === 'results') {
              return (
                <div
                  key={tab.id}
                  id={panelId('section', tab.id)}
                  role="tabpanel"
                  aria-labelledby={tabId('section', tab.id)}
                  hidden={!isActive}
                >
                  {results === null ? (
                    <div className="empty-state">
                      Analyze the deal to see the full engine output for these assumptions.
                    </div>
                  ) : (
                    <div className="underwrite-results-shell">
                      <SubNav
                        items={availableResultsViews}
                        active={resultsView}
                        onSelect={(id) => onResultsViewChange(id as ResultsViewId)}
                        label="Results views"
                        variant="inline"
                        idFor={(id) => tabId('results', id)}
                        controlsFor={(id) => panelId('results', id)}
                      />
                      {availableResultsViews.map((view) => (
                        <div
                          key={view.id}
                          id={panelId('results', view.id)}
                          role="tabpanel"
                          aria-labelledby={tabId('results', view.id)}
                          hidden={view.id !== resultsView}
                          className="underwrite-results"
                        >
                          {resultsViews[view.id]}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            }

            if (tab.id === 'operations' && hasOperationsSubNav) {
              return (
                <div
                  key={tab.id}
                  id={panelId('section', tab.id)}
                  role="tabpanel"
                  aria-labelledby={tabId('section', tab.id)}
                  hidden={!isActive}
                  className="underwrite-tab-panel"
                >
                  <SubNav
                    items={OPERATIONS_VIEWS}
                    active={operationsView}
                    onSelect={onOperationsViewChange}
                    label="Operations sections"
                    variant="inline"
                    idFor={(id) => tabId('operations', id)}
                    controlsFor={(id) => panelId('operations', id)}
                  />
                  {OPERATIONS_VIEWS.map((view) => (
                    <div
                      key={view.id}
                      id={panelId('operations', view.id)}
                      role="tabpanel"
                      aria-labelledby={tabId('operations', view.id)}
                      hidden={view.id !== operationsView}
                    >
                      <AssumptionFieldGrid
                        sections={sectionsForView(sections[tab.id], view.id)}
                        disabled={isSubmitting}
                      />
                    </div>
                  ))}
                </div>
              );
            }

            return (
              <div
                key={tab.id}
                id={panelId('section', tab.id)}
                role="tabpanel"
                aria-labelledby={tabId('section', tab.id)}
                hidden={!isActive}
                className="underwrite-tab-panel"
              >
                <AssumptionFieldGrid sections={sections[tab.id]} disabled={isSubmitting} />
              </div>
            );
          })}
        </div>

        <LiveCaseRail results={results} tab={activeTab} />
      </div>
    </div>
  );
}
