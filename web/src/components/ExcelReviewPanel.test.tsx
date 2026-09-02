import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ExcelReviewPanel } from './ExcelReviewPanel';
import { BLANK_FORM_VALUES, DEFAULT_FORM_VALUES } from '../convert';
import type { AcquisitionFormValues } from '../types';

afterEach(() => {
  cleanup();
});

function makeValues(overrides: Partial<AcquisitionFormValues> = {}): AcquisitionFormValues {
  return { ...DEFAULT_FORM_VALUES, ...overrides };
}

describe('ExcelReviewPanel', () => {
  it('renders the workbook file name and all fourteen canonical fields, grouped', () => {
    render(
      <ExcelReviewPanel
        fileName="anchor_input.xlsx"
        values={makeValues()}
        requiredV2FieldIds={[]}
        error={null}
        onFieldChange={vi.fn()}
        onApprove={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('anchor_input.xlsx')).toBeTruthy();
    for (const title of ['Acquisition', 'Growth & Exit', 'Transaction Costs', 'Operations', 'Financing']) {
      expect(screen.getByText(title)).toBeTruthy();
    }
    expect(screen.getByLabelText('Excel Review Purchase Price')).toHaveProperty('value', '50000000');
    expect(screen.getByLabelText('Excel Review Interest-Only Period')).toHaveProperty('value', '0');
  });

  it('calls onFieldChange with the edited value, without mutating the values prop', () => {
    const onFieldChange = vi.fn();
    render(
      <ExcelReviewPanel
        fileName="anchor_input.xlsx"
        values={makeValues()}
        requiredV2FieldIds={[]}
        error={null}
        onFieldChange={onFieldChange}
        onApprove={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('Excel Review Purchase Price'), {
      target: { value: '52000000' },
    });

    expect(onFieldChange).toHaveBeenCalledWith('purchasePrice', '52000000');
  });

  it('marks a blank required V2 field as "Requires input"', () => {
    render(
      <ExcelReviewPanel
        fileName="anchor_input.xlsx"
        values={makeValues({ acquisitionCostPct: '' })}
        requiredV2FieldIds={['acquisition_cost_pct']}
        error={null}
        onFieldChange={vi.fn()}
        onApprove={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('Requires input')).toBeTruthy();
    expect(screen.getByText(/Additional underwriting assumptions/)).toBeTruthy();
  });

  it('does not mark a required V2 field once it has an explicit value, including 0', () => {
    render(
      <ExcelReviewPanel
        fileName="anchor_input.xlsx"
        values={makeValues({ acquisitionCostPct: '0' })}
        requiredV2FieldIds={['acquisition_cost_pct']}
        error={null}
        onFieldChange={vi.fn()}
        onApprove={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.queryByText('Requires input')).toBeNull();
    expect(screen.queryByText(/Additional underwriting assumptions/)).toBeNull();
  });

  it('shows no required-field messaging for a complete workbook (no defaulted V2 fields)', () => {
    render(
      <ExcelReviewPanel
        fileName="anchor_input.xlsx"
        values={makeValues()}
        requiredV2FieldIds={[]}
        error={null}
        onFieldChange={vi.fn()}
        onApprove={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.queryByText('Requires input')).toBeNull();
    expect(screen.queryByText(/Additional underwriting assumptions/)).toBeNull();
  });

  it('shows a validation error when given one, without blocking the rest of the panel', () => {
    render(
      <ExcelReviewPanel
        fileName="anchor_input.xlsx"
        values={makeValues({ acquisitionCostPct: '' })}
        requiredV2FieldIds={['acquisition_cost_pct']}
        error="Acquisition Costs is required."
        onFieldChange={vi.fn()}
        onApprove={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('Acquisition Costs is required.')).toBeTruthy();
  });

  it('calls onApprove when Approve & Load Assumptions is clicked', async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    render(
      <ExcelReviewPanel
        fileName="anchor_input.xlsx"
        values={makeValues()}
        requiredV2FieldIds={[]}
        error={null}
        onFieldChange={vi.fn()}
        onApprove={onApprove}
        onCancel={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Approve & Load Assumptions' }));

    expect(onApprove).toHaveBeenCalledTimes(1);
  });

  it('calls onCancel when Cancel Review is clicked', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <ExcelReviewPanel
        fileName="anchor_input.xlsx"
        values={makeValues()}
        requiredV2FieldIds={[]}
        error={null}
        onFieldChange={vi.fn()}
        onApprove={vi.fn()}
        onCancel={onCancel}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Cancel Review' }));

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('renders every field blank when the review values are all blank (new/blank proposal)', () => {
    render(
      <ExcelReviewPanel
        fileName="anchor_input.xlsx"
        values={BLANK_FORM_VALUES}
        requiredV2FieldIds={[]}
        error={null}
        onFieldChange={vi.fn()}
        onApprove={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('Excel Review Purchase Price')).toHaveProperty('value', '');
  });
});
