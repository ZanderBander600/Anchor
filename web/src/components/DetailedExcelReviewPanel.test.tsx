import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DetailedExcelReviewPanel } from './DetailedExcelReviewPanel';
import { BLANK_DETAILED_FORM_VALUES, DETAILED_GOLDEN_FORM_VALUES } from '../convert';

afterEach(() => {
  cleanup();
});

describe('DetailedExcelReviewPanel', () => {
  it('renders the workbook file name and both field groups (Terms + Operating Model)', () => {
    render(
      <DetailedExcelReviewPanel
        fileName="anchor_detailed_input_v2_1.xlsx"
        termsValues={DETAILED_GOLDEN_FORM_VALUES.terms}
        operatingValues={DETAILED_GOLDEN_FORM_VALUES.operating}
        error={null}
        onTermsFieldChange={vi.fn()}
        onOperatingFieldChange={vi.fn()}
        onApprove={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('anchor_detailed_input_v2_1.xlsx')).toBeTruthy();
    for (const title of ['Acquisition & Exit', 'Transaction Costs', 'Operations', 'Financing']) {
      expect(screen.getByText(title)).toBeTruthy();
    }
    for (const title of ['Revenue', 'Operating Expenses', 'Growth']) {
      expect(screen.getByText(title)).toBeTruthy();
    }
    expect(screen.getByLabelText('Detailed Excel Review Purchase Price')).toHaveProperty(
      'value',
      '10000000',
    );
    expect(screen.getByLabelText('Detailed Excel Review Gross Potential Rent')).toHaveProperty(
      'value',
      '800000',
    );
  });

  it('calls onTermsFieldChange with the edited value for an AcquisitionTerms field', () => {
    const onTermsFieldChange = vi.fn();
    render(
      <DetailedExcelReviewPanel
        fileName="anchor_detailed_input_v2_1.xlsx"
        termsValues={DETAILED_GOLDEN_FORM_VALUES.terms}
        operatingValues={DETAILED_GOLDEN_FORM_VALUES.operating}
        error={null}
        onTermsFieldChange={onTermsFieldChange}
        onOperatingFieldChange={vi.fn()}
        onApprove={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('Detailed Excel Review Purchase Price'), {
      target: { value: '11000000' },
    });

    expect(onTermsFieldChange).toHaveBeenCalledWith('purchasePrice', '11000000');
  });

  it('calls onOperatingFieldChange with the edited value for a DetailedOperatingInputs field', () => {
    const onOperatingFieldChange = vi.fn();
    render(
      <DetailedExcelReviewPanel
        fileName="anchor_detailed_input_v2_1.xlsx"
        termsValues={DETAILED_GOLDEN_FORM_VALUES.terms}
        operatingValues={DETAILED_GOLDEN_FORM_VALUES.operating}
        error={null}
        onTermsFieldChange={vi.fn()}
        onOperatingFieldChange={onOperatingFieldChange}
        onApprove={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('Detailed Excel Review Gross Potential Rent'), {
      target: { value: '850000' },
    });

    expect(onOperatingFieldChange).toHaveBeenCalledWith('grossPotentialRent', '850000');
  });

  it('shows a validation error when given one', () => {
    render(
      <DetailedExcelReviewPanel
        fileName="anchor_detailed_input_v2_1.xlsx"
        termsValues={BLANK_DETAILED_FORM_VALUES.terms}
        operatingValues={BLANK_DETAILED_FORM_VALUES.operating}
        error="Purchase Price is required."
        onTermsFieldChange={vi.fn()}
        onOperatingFieldChange={vi.fn()}
        onApprove={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('Purchase Price is required.')).toBeTruthy();
  });

  it('calls onApprove when Approve & Load Assumptions is clicked', async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    render(
      <DetailedExcelReviewPanel
        fileName="anchor_detailed_input_v2_1.xlsx"
        termsValues={DETAILED_GOLDEN_FORM_VALUES.terms}
        operatingValues={DETAILED_GOLDEN_FORM_VALUES.operating}
        error={null}
        onTermsFieldChange={vi.fn()}
        onOperatingFieldChange={vi.fn()}
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
      <DetailedExcelReviewPanel
        fileName="anchor_detailed_input_v2_1.xlsx"
        termsValues={DETAILED_GOLDEN_FORM_VALUES.terms}
        operatingValues={DETAILED_GOLDEN_FORM_VALUES.operating}
        error={null}
        onTermsFieldChange={vi.fn()}
        onOperatingFieldChange={vi.fn()}
        onApprove={vi.fn()}
        onCancel={onCancel}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Cancel Review' }));

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('renders every field blank when the review values are all blank', () => {
    render(
      <DetailedExcelReviewPanel
        fileName="anchor_detailed_input_v2_1.xlsx"
        termsValues={BLANK_DETAILED_FORM_VALUES.terms}
        operatingValues={BLANK_DETAILED_FORM_VALUES.operating}
        error={null}
        onTermsFieldChange={vi.fn()}
        onOperatingFieldChange={vi.fn()}
        onApprove={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('Detailed Excel Review Purchase Price')).toHaveProperty(
      'value',
      '',
    );
  });
});
