/**
 * D5.6 -- the Lease-Level results surface.
 *
 * Three views, driven by `resultsViewsFor('lease_level')` so there is one
 * authority for what a mode's results contain. Until this gate that function
 * refused Lease-Level by name, which was correct while nothing could render it.
 *
 * The empty state matters as much as the populated one. Lease-Level persists no
 * analysis snapshot -- decision D5, deliberately -- so a reopened deal has
 * inputs and no results, and any edit clears the results that described the
 * previous inputs. Both cases say so plainly rather than showing a stale number
 * that looks current.
 */

import { LeaseLevelMetricSummary } from './LeaseLevelMetricSummary';
import { LeaseLevelOperatingStatement } from './LeaseLevelOperatingStatement';
import type { OperatingPeriodView } from './LeaseLevelOperatingStatement';
import { CashFlowTable } from './CashFlowTable';
import { SubNav } from './SubNav';
import { resultsViewsFor } from '../underwrite';
import type { ResultsViewId } from '../underwrite';
import type { LeaseLevelAcquisitionResults } from '../leaseLevelTypes';

export interface LeaseLevelResultsProps {
  /** The last successful analysis, or `null` when none describes the current
   * inputs -- a deal just reopened, or an assumption edited since. */
  analysis: LeaseLevelAcquisitionResults | null;
  /** True while an analysis is in flight, so the empty state can say so
   * instead of implying the analyst has not asked yet. */
  isAnalyzing: boolean;
  view: ResultsViewId;
  onViewChange: (view: ResultsViewId) => void;
  periodView: OperatingPeriodView;
  onPeriodViewChange: (view: OperatingPeriodView) => void;
}

export function LeaseLevelResults({
  analysis,
  isAnalyzing,
  view,
  onViewChange,
  periodView,
  onPeriodViewChange,
}: LeaseLevelResultsProps) {
  if (analysis === null) {
    return (
      <div className="empty-state" role="status">
        {isAnalyzing
          ? 'Running the analysis…'
          : 'Analyze to see results for these assumptions. Results are recalculated from the inputs rather than stored, so a reopened deal starts here.'}
      </div>
    );
  }

  const views = resultsViewsFor('lease_level');

  return (
    <div className="underwrite-results-shell">
      <SubNav
        items={views}
        active={view}
        onSelect={(id) => onViewChange(id as ResultsViewId)}
        label="Results views"
        variant="inline"
        idFor={(id) => `lease-level-results-tab-${id}`}
        controlsFor={(id) => `lease-level-results-panel-${id}`}
      />

      {/* Only the open view is mounted.
        *
        * The assumption tabs stay mounted-but-hidden because they hold an
        * analyst's in-progress typing, which a remount would discard. Results
        * hold nothing of the kind -- they are read-only renderings of one
        * response -- so keeping all three alive would buy nothing and cost a
        * great deal: a seven-year hold is 96 monthly columns across roughly
        * twenty-five rows, and there is no reason to build that while the
        * analyst is reading the summary. */}
      <div
        id={`lease-level-results-panel-${view}`}
        role="tabpanel"
        aria-labelledby={`lease-level-results-tab-${view}`}
        className="underwrite-results"
      >
        {view === 'summary' && <LeaseLevelMetricSummary analysis={analysis} />}
        {view === 'operating-statement' && (
          <LeaseLevelOperatingStatement
            analysis={analysis}
            view={periodView}
            onViewChange={onPeriodViewChange}
          />
        )}
        {/* The shared cash-flow table reads only `AcquisitionResults`, which
            every mode produces from the one returns engine -- so Lease-Level
            uses it unchanged rather than growing a second copy. */}
        {view === 'cash-flow' && <CashFlowTable results={analysis.results} />}
      </div>
    </div>
  );
}
