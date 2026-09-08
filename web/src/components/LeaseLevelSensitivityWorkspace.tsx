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
 * **State is transient, and deliberately local.** A sensitivity configuration is
 * an analytical question, not an underwriting assumption: it is not persisted,
 * it is not fingerprinted, and changing it does not make the deal dirty. Keeping
 * it here rather than in `useLeaseLevelDeal` is what makes that structural --
 * there is no path from a control on this screen to the saved-snapshot
 * comparison. The workspace panels stay mounted (the ARIA tab pattern), so the
 * configuration survives a trip to Underwrite and back without being stored
 * anywhere.
 *
 * **It computes nothing.** Candidate values are converted by the shipped unit
 * convention and sent; results are formatted and shown. No metric is derived,
 * no cell interpolated, no baseline inferred, no scenario ranked, and no run
 * cached, batched or shortened.
 */

import { useState } from 'react';
import { SubNav } from './SubNav';
import { BLANK_LADDER_DRAFT } from '../leaseLevelSensitivityLadder';
import { LeaseLevelOneWaySensitivity } from './LeaseLevelOneWaySensitivity';
import { LeaseLevelTwoWaySensitivity } from './LeaseLevelTwoWaySensitivity';
import type { OneWaySensitivityConfig } from './LeaseLevelOneWaySensitivity';
import type { TwoWaySensitivityConfig } from './LeaseLevelTwoWaySensitivity';
import {
  ApiError,
  runLeaseLevelOneWaySensitivity,
  runLeaseLevelTwoWaySensitivity,
} from '../api';
import { FormValidationError } from '../convert';
import { candidateToWireValue, sensitivityTarget } from '../leaseLevelSensitivity';
import type { LeaseLevelSensitivityTargetId } from '../leaseLevelSensitivityTypes';
import type {
  LeaseLevelOneWaySensitivityResult,
  LeaseLevelTwoWaySensitivityResult,
} from '../leaseLevelSensitivityTypes';
import type {
  LeaseLevelInputsRequest,
  SuiteRowFormValues,
} from '../leaseLevelTypes';
import type { AcquisitionTermsRequest } from '../types';

export type LeaseLevelSensitivityViewId = 'one-way' | 'two-way';

const SENSITIVITY_VIEWS: { id: LeaseLevelSensitivityViewId; label: string }[] = [
  { id: 'one-way', label: 'One-Way' },
  { id: 'two-way', label: 'Two-Way' },
];

export interface LeaseLevelSensitivityWorkspaceProps {
  /** The rent roll as it stands, for the shadowing aid only. Never a financial
   * input to anything on this screen. */
  rentRoll: SuiteRowFormValues[];
  /** The one authoritative Lease-Level request mapper -- literally the function
   * Analyze calls. Returns `null` when a field is blank, having marked it. */
  buildRequest: () => { terms: AcquisitionTermsRequest; inputs: LeaseLevelInputsRequest } | null;
  /** What to say when `buildRequest` reported blanks. */
  blanksMessage: string;
}

/** No candidate values yet is a question that has not been asked, not a run
 * with an empty answer. Stated rather than silently submitted. */
const NO_VALUES_MESSAGE =
  'Enter at least one candidate value before running the sensitivity.';

const INITIAL_ONE_WAY: OneWaySensitivityConfig = {
  metric: 'levered_irr',
  assumption: 'exit_cap_rate',
  values: [],
  ladder: BLANK_LADDER_DRAFT,
};

const INITIAL_TWO_WAY: TwoWaySensitivityConfig = {
  metric: 'levered_irr',
  rowAssumption: 'exit_cap_rate',
  rowValues: [],
  rowLadder: BLANK_LADDER_DRAFT,
  columnAssumption: 'purchase_price',
  columnValues: [],
  columnLadder: BLANK_LADDER_DRAFT,
};

/** Every candidate value for one target, converted by the shipped unit
 * convention, in the analyst's order. Throws `FormValidationError` for a blank
 * or unparseable entry so the workspace can report it by name. */
function wireValues(assumption: LeaseLevelSensitivityTargetId, values: string[]): number[] {
  const target = sensitivityTarget(assumption);
  return values.map((value) => candidateToWireValue(target, value));
}

export function LeaseLevelSensitivityWorkspace({
  rentRoll,
  buildRequest,
  blanksMessage,
}: LeaseLevelSensitivityWorkspaceProps) {
  const [view, setView] = useState<LeaseLevelSensitivityViewId>('one-way');
  const [oneWay, setOneWay] = useState<OneWaySensitivityConfig>(INITIAL_ONE_WAY);
  const [twoWay, setTwoWay] = useState<TwoWaySensitivityConfig>(INITIAL_TWO_WAY);
  const [oneWayResult, setOneWayResult] = useState<LeaseLevelOneWaySensitivityResult | null>(null);
  const [twoWayResult, setTwoWayResult] = useState<LeaseLevelTwoWaySensitivityResult | null>(null);
  const [oneWayError, setOneWayError] = useState<string | null>(null);
  const [twoWayError, setTwoWayError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  /** The message for a failed run.
   *
   * A backend refusal is surfaced as the backend worded it --
   * `SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE`,
   * `NON_POSITIVE_FORWARD_EXIT_NOI`, an unsupported target, a repeated axis
   * target. None of them is converted into `N/A`, a zero, a skipped cell or a
   * partial table. */
  function messageFor(caught: unknown): string {
    if (caught instanceof ApiError || caught instanceof FormValidationError) {
      return caught.message;
    }
    return 'An unexpected error occurred while running the sensitivity.';
  }

  async function runOneWay(): Promise<void> {
    setOneWayError(null);
    if (oneWay.values.length === 0) {
      setOneWayError(NO_VALUES_MESSAGE);
      return;
    }
    setIsRunning(true);
    try {
      const request = buildRequest();
      if (request === null) {
        setOneWayError(blanksMessage);
        return;
      }
      const values = wireValues(oneWay.assumption, oneWay.values);
      const result = await runLeaseLevelOneWaySensitivity(request.terms, request.inputs, {
        assumption: oneWay.assumption,
        values,
        metric: oneWay.metric,
      });
      setOneWayResult(result);
    } catch (caught) {
      // A refused run has no partial answer, so the previous table is cleared
      // rather than left on screen beside an error that contradicts it.
      setOneWayResult(null);
      setOneWayError(messageFor(caught));
    } finally {
      setIsRunning(false);
    }
  }

  async function runTwoWay(): Promise<void> {
    setTwoWayError(null);
    if (twoWay.rowValues.length === 0 || twoWay.columnValues.length === 0) {
      setTwoWayError(NO_VALUES_MESSAGE);
      return;
    }
    setIsRunning(true);
    try {
      const request = buildRequest();
      if (request === null) {
        setTwoWayError(blanksMessage);
        return;
      }
      const result = await runLeaseLevelTwoWaySensitivity(request.terms, request.inputs, {
        row_assumption: twoWay.rowAssumption,
        row_values: wireValues(twoWay.rowAssumption, twoWay.rowValues),
        column_assumption: twoWay.columnAssumption,
        column_values: wireValues(twoWay.columnAssumption, twoWay.columnValues),
        metric: twoWay.metric,
      });
      setTwoWayResult(result);
    } catch (caught) {
      setTwoWayResult(null);
      setTwoWayError(messageFor(caught));
    } finally {
      setIsRunning(false);
    }
  }

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
          config={oneWay}
          onConfigChange={setOneWay}
          rentRoll={rentRoll}
          onRun={() => void runOneWay()}
          isRunning={isRunning}
          error={oneWayError}
          result={oneWayResult}
        />
      </div>

      <div
        id="lease-level-sensitivity-panel-two-way"
        role="tabpanel"
        aria-labelledby="lease-level-sensitivity-tab-two-way"
        hidden={view !== 'two-way'}
      >
        <LeaseLevelTwoWaySensitivity
          config={twoWay}
          onConfigChange={setTwoWay}
          rentRoll={rentRoll}
          onRun={() => void runTwoWay()}
          isRunning={isRunning}
          error={twoWayError}
          result={twoWayResult}
        />
      </div>
    </div>
  );
}
