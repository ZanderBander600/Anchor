import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SensitivityPanel } from './SensitivityPanel';
import type { StandardSensitivityPresets, TwoWaySensitivityResult } from '../types';

afterEach(() => {
  cleanup();
});

function makeMatrix(
  overrides: Partial<TwoWaySensitivityResult> = {},
): TwoWaySensitivityResult {
  return {
    row_assumption: 'noi_growth',
    column_assumption: 'exit_cap_rate',
    metric: 'levered_irr',
    baseline_row_value: 0.03,
    baseline_column_value: 0.055,
    baseline_metric_value: 0.0791303,
    row_values: [0.01, 0.02, 0.03, 0.04, 0.05],
    column_values: [0.045, 0.05, 0.055, 0.06, 0.065],
    matrix: [
      [0.11, 0.12, 0.13, 0.14, 0.15],
      [0.16, 0.17, 0.18, 0.19, 0.2],
      [0.21, 0.22, 0.0791303, 0.23, 0.24],
      [0.25, 0.26, 0.27, 0.28, 0.29],
      [0.3, 0.31, 0.32, 0.33, 0.34],
    ],
    ...overrides,
  };
}

function makePresets(
  overrides: Partial<StandardSensitivityPresets> = {},
): StandardSensitivityPresets {
  return {
    exit_cap_noi_growth: makeMatrix(),
    purchase_price_exit_cap: makeMatrix({
      row_assumption: 'purchase_price',
      baseline_row_value: 50_000_000,
      row_values: [45_000_000, 47_500_000, 50_000_000, 52_500_000, 55_000_000],
    }),
    interest_rate_ltv: makeMatrix({
      row_assumption: 'interest_rate',
      column_assumption: 'ltv',
      baseline_row_value: 0.0525,
      baseline_column_value: 0.65,
      row_values: [0.0425, 0.0475, 0.0525, 0.0575, 0.0625],
      column_values: [0.55, 0.6, 0.65, 0.7, 0.75],
    }),
    interest_rate_ltv_dscr: makeMatrix({
      row_assumption: 'interest_rate',
      column_assumption: 'ltv',
      metric: 'headline_dscr',
      baseline_row_value: 0.0525,
      baseline_column_value: 0.65,
      baseline_metric_value: 1.1608,
      row_values: [0.0425, 0.0475, 0.0525, 0.0575, 0.0625],
      column_values: [0.55, 0.6, 0.65, 0.7, 0.75],
      matrix: [
        [1.4, 1.35, 1.3, 1.25, 1.2],
        [1.35, 1.3, 1.25, 1.2, 1.15],
        [1.3, 1.25, 1.1608, 1.15, 1.1],
        [1.25, 1.2, 1.15, 1.1, 1.05],
        [1.2, 1.15, 1.1, 1.05, 1.0],
      ],
    }),
    ...overrides,
  };
}

/** Column header labels, in order, excluding the axis-label corner cell. */
function columnHeaders(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('.sensitivity-table thead th'))
    .slice(1)
    .map((th) => th.textContent ?? '');
}

/** Row header labels (left-hand axis), in order. */
function rowHeaders(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('.sensitivity-table tbody th')).map(
    (th) => th.textContent ?? '',
  );
}

describe('SensitivityPanel', () => {
  it('renders nothing before a base analysis has run', () => {
    const { container } = render(
      <SensitivityPanel presets={null} isLoading={false} error={null} />,
    );

    expect(container.innerHTML).toBe('');
  });

  it('shows a loading state while sensitivity is calculating', () => {
    render(<SensitivityPanel presets={null} isLoading={true} error={null} />);

    expect(screen.getByText(/Calculating sensitivity/)).toBeTruthy();
  });

  it('renders the standard tabs', () => {
    render(<SensitivityPanel presets={makePresets()} isLoading={false} error={null} />);

    expect(screen.getByRole('tab', { name: 'Exit Cap × NOI Growth' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Purchase Price × Exit Cap' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Interest Rate × LTV' })).toBeTruthy();
  });

  it('formats row and column labels as percentages for the Exit Cap x NOI Growth matrix', () => {
    const { container } = render(
      <SensitivityPanel presets={makePresets()} isLoading={false} error={null} />,
    );

    expect(rowHeaders(container)).toEqual(['1.00%', '2.00%', '3.00%', '4.00%', '5.00%']);
    expect(columnHeaders(container)).toEqual([
      '4.50%',
      '5.00%',
      '5.50%',
      '6.00%',
      '6.50%',
    ]);
  });

  it('formats currency row labels for the Purchase Price x Exit Cap tab', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <SensitivityPanel presets={makePresets()} isLoading={false} error={null} />,
    );

    await user.click(screen.getByRole('tab', { name: 'Purchase Price × Exit Cap' }));

    expect(rowHeaders(container)).toEqual([
      '$45,000,000',
      '$47,500,000',
      '$50,000,000',
      '$52,500,000',
      '$55,000,000',
    ]);
  });

  it('formats IRR metric cells as percentages with two decimal places', () => {
    const { container } = render(
      <SensitivityPanel presets={makePresets()} isLoading={false} error={null} />,
    );

    const baselineCell = container.querySelector('.sensitivity-baseline');
    expect(baselineCell?.textContent).toContain('7.91%');
  });

  it('identifies exactly one baseline cell, matching the base assumption values', () => {
    const { container } = render(
      <SensitivityPanel presets={makePresets()} isLoading={false} error={null} />,
    );

    const baselineCells = container.querySelectorAll('.sensitivity-baseline');
    expect(baselineCells.length).toBe(1);
    expect(baselineCells[0].textContent).toContain('(Base)');

    // Baseline is row index 2 (noi_growth 0.03), column index 2 (exit_cap_rate 0.055).
    const rows = container.querySelectorAll('.sensitivity-table tbody tr');
    const baselineRowCells = rows[2].querySelectorAll('td');
    expect(baselineRowCells[2]).toBe(baselineCells[0]);
  });

  it('renders N/A for a null metric cell without corrupting other cells', () => {
    const presets = makePresets({
      exit_cap_noi_growth: makeMatrix({
        baseline_metric_value: null,
        matrix: [
          [null, 0.12, 0.13, 0.14, 0.15],
          [0.16, 0.17, 0.18, 0.19, 0.2],
          [0.21, 0.22, null, 0.23, 0.24],
          [0.25, 0.26, 0.27, 0.28, 0.29],
          [0.3, 0.31, 0.32, 0.33, 0.34],
        ],
      }),
    });
    const { container } = render(
      <SensitivityPanel presets={presets} isLoading={false} error={null} />,
    );

    const cells = Array.from(container.querySelectorAll('.sensitivity-cell')).map(
      (cell) => cell.textContent ?? '',
    );
    // One of the two null cells is also the baseline cell, so its text is
    // "N/A (Base)" rather than a bare "N/A".
    const naCount = cells.filter((text) => text.startsWith('N/A')).length;
    expect(naCount).toBe(2);
  });

  it('switches to the Interest Rate x LTV matrix and toggles between IRR and DSCR', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <SensitivityPanel presets={makePresets()} isLoading={false} error={null} />,
    );

    await user.click(screen.getByRole('tab', { name: 'Interest Rate × LTV' }));
    let baselineCell = container.querySelector('.sensitivity-baseline');
    expect(baselineCell?.textContent).toContain('7.91%');

    await user.click(screen.getByRole('button', { name: 'Year 1 DSCR' }));
    baselineCell = container.querySelector('.sensitivity-baseline');
    expect(baselineCell?.textContent).toContain('1.16x');
    expect(baselineCell?.textContent).not.toContain('7.91%');
  });

  it('shows a sensitivity error banner without requiring presets', () => {
    render(
      <SensitivityPanel presets={null} isLoading={false} error="Sensitivity request failed." />,
    );

    expect(screen.getByText('Sensitivity request failed.')).toBeTruthy();
  });
});
