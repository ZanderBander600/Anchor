import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DetailedOmReviewPanel } from './DetailedOmReviewPanel';
import type { DetailedExtractionResult } from '../types';
import type { FieldCandidates } from '../types';

afterEach(() => {
  cleanup();
});

function missing(field_id: string): FieldCandidates {
  return { field_id, candidates: [] };
}

function makeDetailedExtraction(
  overrides: Partial<DetailedExtractionResult> = {},
): DetailedExtractionResult {
  const base: DetailedExtractionResult = {
    purchase_price: {
      field_id: 'purchase_price',
      candidates: [
        {
          value: '10000000',
          status: 'stated',
          provenance: { page: 1, anchor: 'paragraph:0', snippet: 'Purchase Price: $10,000,000' },
        },
      ],
    },
    hold_period: missing('hold_period'),
    exit_cap_rate: missing('exit_cap_rate'),
    ltv: missing('ltv'),
    interest_rate: missing('interest_rate'),
    amortization: missing('amortization'),
    acquisition_cost_pct: missing('acquisition_cost_pct'),
    financing_fee_pct: missing('financing_fee_pct'),
    disposition_cost_pct: missing('disposition_cost_pct'),
    annual_capex_reserve: missing('annual_capex_reserve'),
    io_period: missing('io_period'),
    gross_potential_rent: {
      field_id: 'gross_potential_rent',
      candidates: [
        {
          value: '800000',
          status: 'stated',
          provenance: { page: 31, anchor: 'paragraph:1', snippet: 'Potential Base Rent: $800,000' },
        },
        {
          value: '820000',
          status: 'conflicting',
          provenance: { page: 32, anchor: 'paragraph:2', snippet: 'GPR: $820,000' },
        },
      ],
    },
    other_income: missing('other_income'),
    vacancy_credit_loss_pct: missing('vacancy_credit_loss_pct'),
    property_taxes: {
      field_id: 'property_taxes',
      candidates: [
        {
          value: '60000',
          status: 'interpreted',
          provenance: { page: 32, anchor: 'paragraph:3', snippet: 'Real Estate Taxes: $60,000' },
        },
      ],
    },
    insurance: missing('insurance'),
    utilities: missing('utilities'),
    repairs_maintenance: missing('repairs_maintenance'),
    other_operating_expenses: missing('other_operating_expenses'),
    management_fee_pct: missing('management_fee_pct'),
    revenue_growth: missing('revenue_growth'),
    expense_growth: missing('expense_growth'),
    ...overrides,
  };
  return base;
}

function fieldCard(label: string): HTMLElement {
  const heading = screen.getByText(label);
  const card = heading.closest('.om-field-card');
  if (!card) {
    throw new Error(`No .om-field-card ancestor found for label ${label}`);
  }
  return card as HTMLElement;
}

describe('DetailedOmReviewPanel', () => {
  it('always renders the upload control', () => {
    render(
      <DetailedOmReviewPanel
        extraction={null}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('Upload OM (PDF)')).toBeTruthy();
  });

  it('shows an empty-state prompt before any upload', () => {
    render(
      <DetailedOmReviewPanel
        extraction={null}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText(/Upload an Offering Memorandum PDF/)).toBeTruthy();
  });

  it('calls onUpload with the selected file', async () => {
    const user = userEvent.setup();
    const onUpload = vi.fn();
    render(
      <DetailedOmReviewPanel
        extraction={null}
        isLoading={false}
        error={null}
        onUpload={onUpload}
        onFinishReview={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);

    expect(onUpload).toHaveBeenCalledTimes(1);
    expect(onUpload).toHaveBeenCalledWith(file);
  });

  it('shows a loading state while extraction is in flight', () => {
    render(
      <DetailedOmReviewPanel
        extraction={null}
        isLoading={true}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText(/Extracting proposed assumptions/)).toBeTruthy();
  });

  it('shows an explicit failure state', () => {
    render(
      <DetailedOmReviewPanel
        extraction={null}
        isLoading={false}
        error="The Azure Document Intelligence request failed."
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('The Azure Document Intelligence request failed.')).toBeTruthy();
  });

  it('renders a stated candidate with its source snippet, provenance, and evidence badge', () => {
    render(
      <DetailedOmReviewPanel
        extraction={makeDetailedExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    const card = fieldCard('Gross Potential Rent');
    expect(within(card).getAllByText(/Page (31|32)/).length).toBeGreaterThan(0);
    expect(within(card).getByText(/Potential Base Rent: \$800,000/)).toBeTruthy();
  });

  it('shows missing fields as visibly unresolved, with no fabricated value', () => {
    render(
      <DetailedOmReviewPanel
        extraction={makeDetailedExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    const missingCard = fieldCard('Insurance');
    expect(within(missingCard).getByText('Missing')).toBeTruthy();
    expect(within(missingCard).getByText('Not found in OM.')).toBeTruthy();
    expect(missingCard.classList.contains('om-field-card-missing')).toBe(true);
  });

  it('marks a genuinely conflicting field with both candidates visible', () => {
    render(
      <DetailedOmReviewPanel
        extraction={makeDetailedExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    const card = fieldCard('Gross Potential Rent');
    expect(within(card).getByText('800000')).toBeTruthy();
    expect(within(card).getByText('820000')).toBeTruthy();
  });

  it('extracted candidate values are editable before approval', async () => {
    const user = userEvent.setup();
    render(
      <DetailedOmReviewPanel
        extraction={makeDetailedExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    const card = fieldCard('Property Taxes');
    await user.click(within(card).getByRole('button', { name: 'Edit' }));
    const input = within(card).getByLabelText('Edit Property Taxes');
    await user.clear(input);
    await user.type(input, '65000');
    await user.click(within(card).getByRole('button', { name: 'Save' }));

    expect(within(card).getByText('Approved')).toBeTruthy();
  });

  it('only hands off explicitly approved fields on "Use approved values"', async () => {
    const user = userEvent.setup();
    const onFinishReview = vi.fn();
    render(
      <DetailedOmReviewPanel
        extraction={makeDetailedExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={onFinishReview}
        onCancel={vi.fn()}
      />,
    );

    const purchasePriceCard = fieldCard('Purchase Price');
    await user.click(within(purchasePriceCard).getByRole('button', { name: 'Approve' }));
    await user.click(screen.getByRole('button', { name: 'Use approved values' }));

    expect(onFinishReview).toHaveBeenCalledWith({ purchase_price: '10000000' });
  });

  it('calls onCancel when Cancel Review is clicked', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <DetailedOmReviewPanel
        extraction={makeDetailedExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
        onCancel={onCancel}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Cancel Review' }));

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('groups fields under the Detailed Acquisition/Terms and Operating Model headings', () => {
    render(
      <DetailedOmReviewPanel
        extraction={makeDetailedExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    for (const title of ['Acquisition & Exit', 'Transaction Costs', 'Financing']) {
      expect(screen.getByText(title)).toBeTruthy();
    }
    for (const title of ['Revenue', 'Operating Expenses', 'Growth']) {
      expect(screen.getByText(title)).toBeTruthy();
    }
  });
});
