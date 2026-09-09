/**
 * D5.7 -- the Lease-Level Risk workspace.
 *
 * Replaces the honest placeholder D5.5/D5.6 left here. The analysis has
 * supported one-way and two-way Lease-Level sensitivity since D4.6B and the
 * endpoints since D5.3; this is the screen that asks the question.
 *
 * **Its own component, not Quick's.** Quick and Detailed show four matrices the
 * backend chose for them. Lease-Level has no such packages and will not get any
 * (D5.0): the analyst names the target, the metric and every candidate value.
 * Those are different products behind the same word, so Quick's and Detailed's
 * Risk surfaces are not touched, not migrated and not refactored.
 *
 * **No Break-Even.** Lease-Level break-even is unsupported, so this navigation
 * simply does not offer it. A tab that refuses is worse than a tab that is not
 * there.
 *
 * **State belongs to the deal (D5.8A).** It used to live here, in this
 * component, which is exactly why a completed sensitivity vanished the moment
 * the analyst opened another deal: the component unmounts and nothing outside
 * it remembered the run. The configuration and the results now live in
 * `useLeaseLevelDeal`, are hydrated per deal from the deal's own persisted
 * state, and are cleared per deal on open -- so a matrix survives navigation, a
 * refresh and a restart, and can never appear on a deal that did not produce
 * it. A sensitivity configuration is still an analytical question rather than
 * an underwriting assumption: changing it still marks nothing dirty, and it
 * still reaches no fingerprint.
 *
 * **It computes nothing.** Candidate values are converted by the shipped unit
 * convention and sent by the hook; results are formatted and shown. No metric
 * is derived, no cell interpolated, no baseline inferred, no scenario ranked,
 * and no run cached, batched or shortened. Nothing here re-runs a stored result
 * to display it.
 */

import { SubNav } from './SubNav';
import { LeaseLevelOneWaySensitivity } from './LeaseLevelOneWaySensitivity';
import { LeaseLevelTwoWaySensitivity } from './LeaseLevelTwoWaySensitivity';
import type { LeaseLevelSensitivityState } from '../useLeaseLevelDeal';
import type { SuiteRowFormValues } from '../leaseLevelTypes';

export type LeaseLevelSensitivityViewId = 'one-way' | 'two-way';

const SENSITIVITY_VIEWS: { id: LeaseLevelSensitivityViewId; label: string }[] = [
  { id: 'one-way', label: 'One-Way' },
  { id: 'two-way', label: 'Two-Way' },
];

export interface LeaseLevelSensitivityWorkspaceProps {
  /** The rent roll as it stands, for the shadowing aid only. Never a financial
   * input to anything on this screen. */
  rentRoll: SuiteRowFormValues[];
  /** The deal's own sensitivity state: the analyst's question, the runs, and
   * the two actions that submit them. */
  sensitivity: LeaseLevelSensitivityState;
}

/** Said above a table that came back from persistence rather than from a run in
 * this session.
 *
 * The table is identical either way -- it is the stored response, not a re-run
 * and not a recomputation -- so this is provenance, not a caveat. It earns its
 * place in one situation in particular: a new run that was refused leaves the
 * error beside the previous successful table, and without this line the two
 * would read as contradicting each other. */
const RESTORED_NOTE = 'Showing the last saved run for these assumptions.';

export function LeaseLevelSensitivityWorkspace({
  rentRoll,
  sensitivity,
}: LeaseLevelSensitivityWorkspaceProps) {
  const { view, setView } = sensitivity;

  return (
    <div className="risk-workspace lease-level-sensitivity">
      <p className="field-hint">
        Sensitivity runs against the assumptions currently on Underwrite. Candidate
        values are absolute — an Exit Cap Rate of 6.25 means a 6.25% exit cap, not a
        shift from the baseline. Each candidate is a complete re-underwrite.
      </p>

      <SubNav
        items={SENSITIVITY_VIEWS}
        active={view}
        onSelect={(id) => setView(id as LeaseLevelSensitivityViewId)}
        label="Lease-Level sensitivity views"
        idFor={(id) => `lease-level-sensitivity-tab-${id}`}
        controlsFor={(id) => `lease-level-sensitivity-panel-${id}`}
      />

      <div
        id="lease-level-sensitivity-panel-one-way"
        role="tabpanel"
        aria-labelledby="lease-level-sensitivity-tab-one-way"
        hidden={view !== 'one-way'}
      >
        <LeaseLevelOneWaySensitivity
          config={sensitivity.oneWayConfig}
          onConfigChange={sensitivity.setOneWayConfig}
          rentRoll={rentRoll}
          onRun={() => void sensitivity.runOneWay()}
          isRunning={sensitivity.isRunning}
          error={sensitivity.oneWayError}
          result={sensitivity.oneWayResult?.result ?? null}
          resultNote={sensitivity.isOneWayRestored ? RESTORED_NOTE : null}
        />
      </div>

      <div
        id="lease-level-sensitivity-panel-two-way"
        role="tabpanel"
        aria-labelledby="lease-level-sensitivity-tab-two-way"
        hidden={view !== 'two-way'}
      >
        <LeaseLevelTwoWaySensitivity
          config={sensitivity.twoWayConfig}
          onConfigChange={sensitivity.setTwoWayConfig}
          rentRoll={rentRoll}
          onRun={() => void sensitivity.runTwoWay()}
          isRunning={sensitivity.isRunning}
          error={sensitivity.twoWayError}
          result={sensitivity.twoWayResult?.result ?? null}
          resultNote={sensitivity.isTwoWayRestored ? RESTORED_NOTE : null}
        />
      </div>
    </div>
  );
}
