import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BreakEvenPanel } from './BreakEvenPanel';
import type { BreakEvenResult, ReturnHurdleMetric, StandardBreakEvenAnalysis } from '../types';

afterEach(() => {
  cleanup();
});

function makeResult(overrides: Partial<BreakEvenResult> = {}): BreakEvenResult {
  return {
    break_even_type: 'max_purchase_price',
    assumption: 'purchase_price',
    metric: 'levered_irr',
    target_metric_value: 0.10,
    baseline_assumption_value: 50_000_000,
    baseline_metric_value: 0.0791303,
    solved_assumption_value: 46_820_000,
    solved_metric_value: 0.10001,
    lower_search_bound: 25_000_000,
    upper_search_bound: 75_000_000,
    status: 'solved',
    ...overrides,
  };
}

function makeAnalysis(
  overrides: Partial<StandardBreakEvenAnalysis> = {},
): StandardBreakEvenAnalysis {
  return {
    max_purchase_price: makeResult(),
    max_exit_cap_rate: makeResult({
      break_even_type: 'max_exit_cap_rate',
      assumption: 'exit_cap_rate',
      baseline_assumption_value: 0.055,
      solved_assumption_value: 0.0612,
      lower_search_bound: 0.025,
      upper_search_bound: 0.105,
    }),
    min_noi_growth: makeResult({
      break_even_type: 'min_noi_growth',
      assumption: 'noi_growth',
      baseline_assumption_value: 0.03,
      solved_assumption_value: 0.0417,
      lower_search_bound: -0.07,
      upper_search_bound: 0.13,
    }),
    max_interest_rate: makeResult({
      break_even_type: 'max_interest_rate',
      assumption: 'interest_rate',
      metric: 'headline_dscr',
      target_metric_value: 1.20,
      baseline_assumption_value: 0.0525,
      baseline_metric_value: 1.1608,
      solved_assumption_value: 0.0461,
      solved_metric_value: 1.2001,
      lower_search_bound: 0.0,
      upper_search_bound: 0.2,
    }),
    min_current_noi: makeResult({
      break_even_type: 'min_current_noi',
      assumption: 'current_noi',
      metric: 'headline_dscr',
      target_metric_value: 1.20,
      baseline_assumption_value: 2_500_000,
      baseline_metric_value: 1.1608,
      solved_assumption_value: 2_585_000,
      solved_metric_value: 1.2001,
      lower_search_bound: 1_250_000,
      upper_search_bound: 3_750_000,
    }),
    ...overrides,
  };
}

/** An Equity Multiple-hurdle variant of the three return-driven results --
 * mirrors what the backend returns when ``return_hurdle_metric`` is
 * ``equity_multiple``: the DSCR results are untouched. */
function makeEquityMultipleAnalysis(
  overrides: Partial<StandardBreakEvenAnalysis> = {},
): StandardBreakEvenAnalysis {
  const base = makeAnalysis();
  return {
    ...base,
    max_purchase_price: makeResult({
      metric: 'equity_multiple',
      target_metric_value: 1.50,
      solved_assumption_value: 44_120_000,
      solved_metric_value: 1.5002,
    }),
    max_exit_cap_rate: makeResult({
      break_even_type: 'max_exit_cap_rate',
      assumption: 'exit_cap_rate',
      metric: 'equity_multiple',
      target_metric_value: 1.50,
      baseline_assumption_value: 0.055,
      solved_assumption_value: 0.0589,
      solved_metric_value: 1.5002,
      lower_search_bound: 0.025,
      upper_search_bound: 0.105,
    }),
    min_noi_growth: makeResult({
      break_even_type: 'min_noi_growth',
      assumption: 'noi_growth',
      metric: 'equity_multiple',
      target_metric_value: 1.50,
      baseline_assumption_value: 0.03,
      solved_assumption_value: 0.0398,
      solved_metric_value: 1.5002,
      lower_search_bound: -0.07,
      upper_search_bound: 0.13,
    }),
    ...overrides,
  };
}

const noop = () => {};

interface BuildPropsOverrides {
  analysis?: StandardBreakEvenAnalysis | null;
  isLoading?: boolean;
  error?: string | null;
  targetLeveredIrrPercent?: string;
  targetEquityMultiple?: string;
  targetHeadlineDscr?: string;
  returnHurdleMetric?: ReturnHurdleMetric;
  onTargetLeveredIrrChange?: (value: string) => void;
  onTargetEquityMultipleChange?: (value: string) => void;
  onTargetHeadlineDscrChange?: (value: string) => void;
  onReturnHurdleMetricChange?: (metric: ReturnHurdleMetric) => void;
}

/** Fills in every required ``BreakEvenPanel`` prop with a sane default so
 * each test only has to spell out what it cares about. */
function baseProps(overrides: BuildPropsOverrides = {}) {
  return {
    analysis: null,
    isLoading: false,
    error: null,
    targetLeveredIrrPercent: '10.00',
    targetEquityMultiple: '1.50',
    targetHeadlineDscr: '1.20',
    returnHurdleMetric: 'levered_irr' as ReturnHurdleMetric,
    onTargetLeveredIrrChange: noop,
    onTargetEquityMultipleChange: noop,
    onTargetHeadlineDscrChange: noop,
    onReturnHurdleMetricChange: noop,
    ...overrides,
  };
}

describe('BreakEvenPanel', () => {
  it('renders nothing before a base analysis has run', () => {
    const { container } = render(<BreakEvenPanel {...baseProps()} />);

    expect(container.innerHTML).toBe('');
  });

  it('shows a loading state while break-even is calculating', () => {
    render(<BreakEvenPanel {...baseProps({ isLoading: true })} />);

    expect(screen.getByText(/Calculating break-even/)).toBeTruthy();
  });

  it('renders all five result cards with formatted values', () => {
    render(<BreakEvenPanel {...baseProps({ analysis: makeAnalysis() })} />);

    expect(screen.getByText('Maximum Purchase Price')).toBeTruthy();
    expect(screen.getByText('Maximum Exit Cap')).toBeTruthy();
    expect(screen.getByText('Minimum NOI Growth')).toBeTruthy();
    expect(screen.getByText('Maximum Interest Rate')).toBeTruthy();
    expect(screen.getByText('Minimum Current NOI')).toBeTruthy();

    expect(screen.getByText('$46,820,000')).toBeTruthy();
    expect(screen.getByText('6.12%')).toBeTruthy();
    expect(screen.getByText('4.17%')).toBeTruthy();
    expect(screen.getByText('4.61%')).toBeTruthy();
    expect(screen.getByText('$2,585,000')).toBeTruthy();
  });

  it('shows all three target hurdle controls with their current values', () => {
    render(
      <BreakEvenPanel
        {...baseProps({
          analysis: makeAnalysis(),
          targetLeveredIrrPercent: '9.50',
          targetEquityMultiple: '1.65',
          targetHeadlineDscr: '1.25',
        })}
      />,
    );

    expect(screen.getByLabelText(/^Target Levered IRR/)).toHaveProperty('value', '9.50');
    expect(screen.getByLabelText(/^Target Equity Multiple/)).toHaveProperty('value', '1.65');
    expect(screen.getByLabelText(/^Target Year 1 DSCR/)).toHaveProperty('value', '1.25');
  });

  it('calls the change handlers when a hurdle input changes', async () => {
    const user = userEvent.setup();
    const onIrrChange = vi.fn();
    const onEmChange = vi.fn();
    const onDscrChange = vi.fn();
    render(
      <BreakEvenPanel
        {...baseProps({
          analysis: makeAnalysis(),
          onTargetLeveredIrrChange: onIrrChange,
          onTargetEquityMultipleChange: onEmChange,
          onTargetHeadlineDscrChange: onDscrChange,
        })}
      />,
    );

    await user.type(screen.getByLabelText(/^Target Levered IRR/), '5');

    expect(onIrrChange).toHaveBeenCalled();
    expect(onEmChange).not.toHaveBeenCalled();
    expect(onDscrChange).not.toHaveBeenCalled();
  });

  it('shows "Not found in tested range" for a no-solution result', () => {
    const analysis = makeAnalysis({
      max_purchase_price: makeResult({
        status: 'no_solution_in_range',
        solved_assumption_value: null,
        solved_metric_value: null,
      }),
    });

    render(<BreakEvenPanel {...baseProps({ analysis })} />);

    expect(screen.getByText('Not found in tested range')).toBeTruthy();
    expect(screen.queryByText('Impossible')).toBeNull();
    expect(screen.queryByText(/no solution exists/i)).toBeNull();
  });

  it('shows a break-even error banner without requiring an analysis', () => {
    render(<BreakEvenPanel {...baseProps({ error: 'The break-even request failed.' })} />);

    expect(screen.getByText('The break-even request failed.')).toBeTruthy();
  });
});

describe('BreakEvenPanel -- Equity Multiple return hurdle', () => {
  it('renders the Target Equity Multiple control', () => {
    render(<BreakEvenPanel {...baseProps({ analysis: makeAnalysis() })} />);

    expect(screen.getByText('Target Equity Multiple')).toBeTruthy();
  });

  it('treats "1.50" as 1.50x, not a percentage', () => {
    render(
      <BreakEvenPanel
        {...baseProps({ analysis: makeAnalysis(), targetEquityMultiple: '1.50' })}
      />,
    );

    const input = screen.getByLabelText(/^Target Equity Multiple/) as HTMLInputElement;
    expect(input.value).toBe('1.50');
    // The DSCR-style "x" affix, not a "%" affix -- 1.50 is displayed as-is.
    expect(screen.queryByText('150.00%')).toBeNull();
  });

  it('renders the Levered IRR / Equity Multiple toggle', () => {
    render(<BreakEvenPanel {...baseProps({ analysis: makeAnalysis() })} />);

    expect(screen.getByRole('button', { name: 'Levered IRR' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Equity Multiple' })).toBeTruthy();
  });

  it('calls onReturnHurdleMetricChange when the toggle is clicked', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <BreakEvenPanel
        {...baseProps({ analysis: makeAnalysis(), onReturnHurdleMetricChange: onChange })}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Equity Multiple' }));

    expect(onChange).toHaveBeenCalledWith('equity_multiple');
  });

  it('renders Equity Multiple hurdle subtitles formatted as X.XXx', () => {
    render(
      <BreakEvenPanel
        {...baseProps({
          analysis: makeEquityMultipleAnalysis(),
          returnHurdleMetric: 'equity_multiple',
        })}
      />,
    );

    expect(screen.getAllByText('for 1.50x Equity Multiple').length).toBe(3);
  });

  it('switching from IRR to Equity Multiple updates only the three return-hurdle cards', () => {
    const { rerender } = render(
      <BreakEvenPanel {...baseProps({ analysis: makeAnalysis(), returnHurdleMetric: 'levered_irr' })} />,
    );

    expect(screen.getAllByText('for 10.00% Levered IRR').length).toBe(3);
    expect(screen.getByText('$46,820,000')).toBeTruthy();
    const dscrSubtitlesBefore = screen.getAllByText('for 1.20x Year 1 DSCR');
    expect(dscrSubtitlesBefore.length).toBe(2);

    rerender(
      <BreakEvenPanel
        {...baseProps({
          analysis: makeEquityMultipleAnalysis(),
          returnHurdleMetric: 'equity_multiple',
        })}
      />,
    );

    // The three return-hurdle cards now show the Equity Multiple hurdle and
    // their newly solved values.
    expect(screen.getAllByText('for 1.50x Equity Multiple').length).toBe(3);
    expect(screen.getByText('$44,120,000')).toBeTruthy();
    expect(screen.queryByText('for 10.00% Levered IRR')).toBeNull();

    // The DSCR cards are untouched -- same subtitle, same values, still two
    // of them.
    const dscrSubtitlesAfter = screen.getAllByText('for 1.20x Year 1 DSCR');
    expect(dscrSubtitlesAfter.length).toBe(2);
    expect(screen.getByText('Maximum Interest Rate')).toBeTruthy();
    expect(screen.getByText('Minimum Current NOI')).toBeTruthy();
  });

  it('leaves the DSCR cards unchanged under the Equity Multiple hurdle', () => {
    render(
      <BreakEvenPanel
        {...baseProps({
          analysis: makeEquityMultipleAnalysis(),
          returnHurdleMetric: 'equity_multiple',
        })}
      />,
    );

    expect(screen.getByText('Maximum Interest Rate')).toBeTruthy();
    expect(screen.getByText('Minimum Current NOI')).toBeTruthy();
    expect(screen.getAllByText('for 1.20x Year 1 DSCR').length).toBe(2);
    expect(screen.getByText('4.61%')).toBeTruthy();
    expect(screen.getByText('$2,585,000')).toBeTruthy();
  });

  it('shows "Not found in tested range" for an Equity Multiple no-solution result', () => {
    const analysis = makeEquityMultipleAnalysis({
      max_purchase_price: makeResult({
        metric: 'equity_multiple',
        target_metric_value: 1.50,
        status: 'no_solution_in_range',
        solved_assumption_value: null,
        solved_metric_value: null,
      }),
    });

    render(
      <BreakEvenPanel {...baseProps({ analysis, returnHurdleMetric: 'equity_multiple' })} />,
    );

    expect(screen.getByText('Not found in tested range')).toBeTruthy();
    expect(screen.queryByText(/impossible/i)).toBeNull();
    expect(screen.queryByText(/no solution exists/i)).toBeNull();
  });
});
