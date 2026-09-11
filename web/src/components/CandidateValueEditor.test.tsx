/**
 * D5.8B -- the sensitivity ladder's numeric presentation.
 *
 * Human review found one field left out of the display convention every other
 * absolute numeric input in Anchor already follows: the ladder's **Step**.
 * Centre read `30,000,000` and Step read `1000000`, in the same row, for the
 * same assumption.
 *
 * The fix reuses the existing behaviour rather than adding a second one -- the
 * field asks `groupsThousands(target)` exactly as the candidate fields and
 * Centre do, so a currency step groups, a percentage step does not, and there
 * is no list of field names anywhere that could disagree.
 *
 * **Presentation only.** Every test below also checks the value that leaves the
 * component: form state never holds a separator, so the ladder generator and
 * the wire receive exactly what they received before. Formatting a field must
 * not be able to change a number.
 */

import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CandidateValueEditor } from './CandidateValueEditor';
import { sensitivityTarget } from '../leaseLevelSensitivity';
import { BLANK_LADDER_DRAFT } from '../leaseLevelSensitivityLadder';
import type { LadderDraft } from '../leaseLevelSensitivityLadder';
import type { LeaseLevelSensitivityTargetId } from '../leaseLevelSensitivityTypes';

afterEach(cleanup);

const LEGEND = 'Step formatting';

/**
 * Renders the editor as a controlled component, the way both sensitivity
 * panels do -- so what a test types is fed back in and the field shows what the
 * product would show, rather than what an uncontrolled input happens to hold.
 */
function renderEditor(
  targetId: LeaseLevelSensitivityTargetId,
  ladder: LadderDraft = BLANK_LADDER_DRAFT,
) {
  // Both halves are React state, so the component is driven exactly as the two
  // sensitivity panels drive it. What the assertions read is what the component
  // *emitted* -- the recorded calls -- rather than a mirror variable, so a test
  // can never pass on a value the component never actually handed out.
  const onChange = vi.fn<(values: string[]) => void>();
  const onLadderChange = vi.fn<(ladder: LadderDraft) => void>();

  function Harness() {
    const [currentLadder, setLadder] = useState(ladder);
    const [currentValues, setValues] = useState<string[]>([]);
    return (
      <CandidateValueEditor
        idPrefix="ladder-test"
        legend={LEGEND}
        target={sensitivityTarget(targetId)}
        values={currentValues}
        onChange={(next) => {
          setValues(next);
          onChange(next);
        }}
        ladder={currentLadder}
        onLadderChange={(next) => {
          setLadder(next);
          onLadderChange(next);
        }}
        disabled={false}
      />
    );
  }

  render(<Harness />);

  /** The draft as the component last emitted it -- form state, never display. */
  function emittedLadder(): LadderDraft {
    const calls = onLadderChange.mock.calls;
    return calls.length === 0 ? ladder : calls[calls.length - 1][0];
  }

  return { onChange, emittedLadder };
}

function stepField(): HTMLInputElement {
  return screen.getByLabelText(`${LEGEND} generator step`) as HTMLInputElement;
}

function centreField(): HTMLInputElement {
  return screen.getByLabelText(`${LEGEND} generator centre`) as HTMLInputElement;
}

function countField(): HTMLInputElement {
  return screen.getByLabelText(`${LEGEND} generator count`) as HTMLInputElement;
}

/** Types into a field and then moves focus away, which is when the grouped
 * form appears -- the same focus/blur convention `NumericInput` has applied to
 * every other absolute numeric field since D5.5E. */
async function typeAndBlur(
  user: ReturnType<typeof userEvent.setup>,
  field: HTMLInputElement,
  text: string,
): Promise<void> {
  await user.clear(field);
  await user.type(field, text);
  await user.tab();
}

// =============================================================================
// 29-33. An absolute numeric target
// =============================================================================

describe('an absolute numeric target (Purchase Price)', () => {
  it('29: Centre displays grouped thousands, as it already did', async () => {
    const user = userEvent.setup({ delay: null });
    renderEditor('purchase_price');

    await typeAndBlur(user, centreField(), '30000000');

    expect(centreField().value).toBe('30,000,000');
  });

  it('30, M11: Step displays grouped thousands too', async () => {
    // The reported defect, in one assertion. Before this gate the same row read
    // `Centre 30,000,000` beside `Step 1000000`.
    const user = userEvent.setup({ delay: null });
    renderEditor('purchase_price');

    await typeAndBlur(user, stepField(), '1000000');

    expect(stepField().value).toBe('1,000,000');
  });

  it('31, 32, M12: the value the ladder receives is still unformatted', async () => {
    // The claim that makes the formatting safe. `NumericInput` strips
    // separators on the way in, so form state -- and therefore the generator,
    // and therefore the wire -- never sees a comma. A `Number('1,000,000')` is
    // `NaN`, and a ladder built from `NaN` produces nothing, so a regression
    // here would be silent and total.
    const user = userEvent.setup({ delay: null });
    const { emittedLadder, onChange } = renderEditor('purchase_price');

    await typeAndBlur(user, centreField(), '30000000');
    await typeAndBlur(user, stepField(), '1000000');
    await typeAndBlur(user, countField(), '3');

    expect(emittedLadder()).toEqual({ center: '30000000', step: '1000000', count: '3' });
    expect(Number(emittedLadder().step)).toBe(1_000_000);

    // And the values it generates are the absolute values D5.7 always produced.
    await user.click(screen.getByRole('button', { name: 'Fill Values' }));
    expect(onChange).toHaveBeenCalledWith(['29000000', '30000000', '31000000']);
  });

  it('33: the field shows the raw digits again while it is being edited', async () => {
    // The existing convention, unchanged: grouped while you read it, plain
    // while you edit it, so the caret never jumps over an inserted separator.
    const user = userEvent.setup({ delay: null });
    renderEditor('purchase_price');

    await typeAndBlur(user, stepField(), '1000000');
    expect(stepField().value).toBe('1,000,000');

    await user.click(stepField());
    expect(stepField().value).toBe('1000000');
  });

  it('37: Count is never grouped, whatever the target is', async () => {
    // It is how many values to produce, never a quantity of money or area.
    const user = userEvent.setup({ delay: null });
    renderEditor('purchase_price');

    await typeAndBlur(user, countField(), '5');

    expect(countField().value).toBe('5');
  });
});

// =============================================================================
// 34, 35. Percentage targets are untouched
// =============================================================================

describe('a percentage target (Exit Cap Rate)', () => {
  it('34, M13: Centre and Step keep their percentage-scale display', async () => {
    const user = userEvent.setup({ delay: null });
    renderEditor('exit_cap_rate');

    await typeAndBlur(user, centreField(), '6.25');
    await typeAndBlur(user, stepField(), '0.25');

    expect(centreField().value).toBe('6.25');
    expect(stepField().value).toBe('0.25');
  });

  it('35, M13: the generated ladder is still exact percentage-scale values', async () => {
    // `6.25` centre, `0.25` step, five values means 6.00 / 6.25 / 6.50 and so
    // on -- the D5.7 semantics, byte-for-byte. A thousands separator applied
    // here would not merely look wrong; `0.25` has no thousands to group, and a
    // rule that grouped it anyway would be a rule operating on the wrong scale.
    const user = userEvent.setup({ delay: null });
    const { onChange } = renderEditor('exit_cap_rate');

    await typeAndBlur(user, centreField(), '6.25');
    await typeAndBlur(user, stepField(), '0.25');
    await typeAndBlur(user, countField(), '5');
    await user.click(screen.getByRole('button', { name: 'Fill Values' }));

    expect(onChange).toHaveBeenCalledWith(['5.75', '6', '6.25', '6.5', '6.75']);
  });

  it('M13: a percentage step is never grouped even when it is large', async () => {
    // The mutant this kills is "group everything": a step of `1000` on a
    // percentage target must still read `1000`, because the field is on the
    // percentage scale and a separator there would imply a magnitude it does
    // not have.
    const user = userEvent.setup({ delay: null });
    renderEditor('renewal_probability');

    await typeAndBlur(user, stepField(), '1000');

    expect(stepField().value).toBe('1000');
  });
});

// =============================================================================
// 36. Market Rent / SF follows the same metadata as its candidates
// =============================================================================

describe('a currency-per-square-foot target (Market Rent / SF)', () => {
  it('36: Step follows the same convention the candidate fields use', async () => {
    // No new format is invented for this target: the field asks the same
    // `groupsThousands(target)` the candidate inputs beside it ask, so a step
    // and a candidate on the same assumption can never disagree about how a
    // number looks.
    const user = userEvent.setup({ delay: null });
    renderEditor('market_rent_psf');

    await user.click(screen.getByRole('button', { name: 'Add Value' }));
    await typeAndBlur(
      user,
      screen.getByLabelText(`${LEGEND} 1`) as HTMLInputElement,
      '1500',
    );
    await typeAndBlur(user, stepField(), '1500');

    expect((screen.getByLabelText(`${LEGEND} 1`) as HTMLInputElement).value).toBe('1,500');
    expect(stepField().value).toBe('1,500');
  });
});

// =============================================================================
// D5.9 -- keyboard replacement reaches every grouped sensitivity field
// =============================================================================

/** Keyboard focus in Chromium's order: whole display selected, then focus.
 * `NumericInput.test.tsx` holds the measured reasoning. */
function focusAsTheBrowserDoes(field: HTMLInputElement): void {
  act(() => {
    field.setSelectionRange(0, field.value.length);
    field.focus();
  });
}

describe('D5.9: Tab-and-type replaces in the sensitivity editor', () => {
  it('10: a Purchase Price candidate is replaced, not appended to', async () => {
    const user = userEvent.setup({ delay: null });
    const { onChange } = renderEditor('purchase_price');

    await user.click(screen.getByRole('button', { name: 'Add Value' }));
    const candidate = () => screen.getByLabelText(`${LEGEND} 1`) as HTMLInputElement;
    await typeAndBlur(user, candidate(), '50000000');
    expect(candidate().value).toBe('50,000,000');

    focusAsTheBrowserDoes(candidate());
    await user.keyboard('48000000');
    await user.tab();

    expect(candidate().value).toBe('48,000,000');
    expect(onChange).toHaveBeenLastCalledWith(['48000000']);
  });

  it('10: Centre is replaced, not appended to', async () => {
    const user = userEvent.setup({ delay: null });
    const { emittedLadder } = renderEditor('purchase_price');

    await typeAndBlur(user, centreField(), '30000000');
    focusAsTheBrowserDoes(centreField());
    await user.keyboard('32000000');
    await user.tab();

    expect(centreField().value).toBe('32,000,000');
    expect(emittedLadder().center).toBe('32000000');
  });

  it('11: Step is replaced and keeps its D5.8B grouped display', async () => {
    const user = userEvent.setup({ delay: null });
    const { emittedLadder } = renderEditor('purchase_price');

    await typeAndBlur(user, stepField(), '1000000');
    expect(stepField().value).toBe('1,000,000');

    focusAsTheBrowserDoes(stepField());
    await user.keyboard('2000000');
    await user.tab();

    expect(stepField().value).toBe('2,000,000');
    expect(emittedLadder().step).toBe('2000000');
  });

  it('11: a percentage Step is still ungrouped and still replaced', async () => {
    const user = userEvent.setup({ delay: null });
    const { emittedLadder } = renderEditor('exit_cap_rate');

    await typeAndBlur(user, stepField(), '0.25');
    await user.click(stepField());
    await user.keyboard('{Control>}a{/Control}0.5');
    await user.tab();

    expect(stepField().value).toBe('0.5');
    expect(emittedLadder().step).toBe('0.5');
  });
});
