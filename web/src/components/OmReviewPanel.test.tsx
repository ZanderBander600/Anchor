import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { OmReviewPanel } from './OmReviewPanel';
import type { ExtractionResult, FieldCandidates } from '../types';

afterEach(() => {
  cleanup();
});

function missing(field_id: string): FieldCandidates {
  return { field_id, candidates: [] };
}

function makeExtraction(overrides: Partial<ExtractionResult> = {}): ExtractionResult {
  const base: ExtractionResult = {
    purchase_price: {
      field_id: 'purchase_price',
      candidates: [
        {
          value: '1000000',
          status: 'stated',
          provenance: { page: 1, anchor: 'paragraph:0', snippet: 'Purchase Price: $1,000,000' },
        },
      ],
    },
    current_noi: {
      field_id: 'current_noi',
      candidates: [
        {
          value: '75000',
          status: 'conflicting',
          provenance: { page: 1, anchor: 'paragraph:1', snippet: 'NOI: $75,000' },
        },
        {
          value: '80000',
          status: 'conflicting',
          provenance: { page: 2, anchor: 'paragraph:2', snippet: 'NOI: $80,000' },
        },
      ],
    },
    occupancy: missing('occupancy'),
    noi_growth: {
      field_id: 'noi_growth',
      candidates: [
        {
          value: '0.03',
          status: 'unverifiable',
          provenance: { page: 3, anchor: 'paragraph:3', snippet: 'Growth assumption varies.' },
        },
      ],
    },
    hold_period: missing('hold_period'),
    exit_cap_rate: {
      field_id: 'exit_cap_rate',
      candidates: [
        {
          value: '0.055',
          status: 'interpreted',
          provenance: { page: 1, anchor: 'paragraph:4', snippet: 'Exit cap rate: 5.50%' },
        },
      ],
    },
    ltv: missing('ltv'),
    interest_rate: missing('interest_rate'),
    amortization: missing('amortization'),
    deal_context: {
      property_name: {
        field_id: 'property_name',
        candidates: [{ value: 'Sunset Gardens', status: 'stated', provenance: null }],
      },
      address: missing('address'),
      property_type: missing('property_type'),
      unit_count_or_building_area: missing('unit_count_or_building_area'),
      year_built: missing('year_built'),
    },
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

describe('OmReviewPanel', () => {
  it('always renders the upload control', () => {
    render(
      <OmReviewPanel extraction={null} isLoading={false} error={null} onUpload={vi.fn()} onFinishReview={vi.fn()} />,
    );

    expect(screen.getByLabelText('Upload OM (PDF)')).toBeTruthy();
  });

  it('shows an empty-state prompt before any upload', () => {
    render(
      <OmReviewPanel extraction={null} isLoading={false} error={null} onUpload={vi.fn()} onFinishReview={vi.fn()} />,
    );

    expect(screen.getByText(/Upload an Offering Memorandum PDF/)).toBeTruthy();
  });

  it('calls onUpload with the selected file', async () => {
    const user = userEvent.setup();
    const onUpload = vi.fn();
    render(
      <OmReviewPanel extraction={null} isLoading={false} error={null} onUpload={onUpload} onFinishReview={vi.fn()} />,
    );

    const file = new File(['%PDF-1.4'], 'om.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('Upload OM (PDF)'), file);

    expect(onUpload).toHaveBeenCalledTimes(1);
    expect(onUpload).toHaveBeenCalledWith(file);
  });

  it('shows a loading state while extraction is in flight', () => {
    render(
      <OmReviewPanel extraction={null} isLoading={true} error={null} onUpload={vi.fn()} onFinishReview={vi.fn()} />,
    );

    expect(screen.getByText(/Extracting proposed assumptions/)).toBeTruthy();
  });

  it('shows an explicit failure state distinct from an all-fields-missing screen', () => {
    render(
      <OmReviewPanel
        extraction={null}
        isLoading={false}
        error="The Azure Document Intelligence request failed."
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
      />,
    );

    expect(screen.getByText('The Azure Document Intelligence request failed.')).toBeTruthy();
    expect(screen.queryByText('Purchase Price')).toBeNull();
    expect(screen.queryByText('Missing')).toBeNull();
  });

  it('renders a stated candidate with its source snippet, provenance, and evidence badge', () => {
    render(
      <OmReviewPanel
        extraction={makeExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
      />,
    );

    const card = fieldCard('Purchase Price');
    expect(within(card).getByText('1000000')).toBeTruthy();
    expect(within(card).getByText('Stated')).toBeTruthy();
    expect(within(card).getByText(/Purchase Price: \$1,000,000/)).toBeTruthy();
    expect(within(card).getByText(/Page 1/)).toBeTruthy();
  });

  it('gives missing, unverifiable, and conflicting fields visually distinct treatments', () => {
    render(
      <OmReviewPanel
        extraction={makeExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
      />,
    );

    const missingCard = fieldCard('Hold Period');
    expect(within(missingCard).getByText('Missing')).toBeTruthy();
    expect(missingCard.classList.contains('om-field-card-missing')).toBe(true);

    const unverifiableCard = fieldCard('NOI Growth');
    expect(within(unverifiableCard).getByText('Unverifiable')).toBeTruthy();
    expect(unverifiableCard.querySelector('.om-candidate-unverifiable')).toBeTruthy();

    const conflictingCard = fieldCard('Current NOI');
    expect(conflictingCard.querySelectorAll('.om-candidate-conflicting').length).toBe(2);

    // Distinct classes, not merely distinct text.
    expect(missingCard.querySelector('.om-candidate-unverifiable')).toBeNull();
    expect(unverifiableCard.classList.contains('om-field-card-missing')).toBe(false);
  });

  it('renders a missing field as read-only "Not found in OM" with no value-entry, edit, or approval control', () => {
    render(
      <OmReviewPanel
        extraction={makeExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
      />,
    );

    const card = fieldCard('Hold Period');
    expect(within(card).getByText('Not found in OM.')).toBeTruthy();
    expect(within(card).getByText('Missing')).toBeTruthy();
    expect(card.querySelector('input')).toBeNull();
    expect(card.querySelector('button')).toBeNull();
    expect(within(card).queryByText('Pending review')).toBeNull();
  });

  it('shows every candidate of a conflicting field simultaneously, each with its own approve control', () => {
    render(
      <OmReviewPanel
        extraction={makeExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
      />,
    );

    const card = fieldCard('Current NOI');
    expect(within(card).getByText('75000')).toBeTruthy();
    expect(within(card).getByText('80000')).toBeTruthy();
    expect(within(card).getAllByRole('button', { name: 'Approve' })).toHaveLength(2);
  });

  it('approving one candidate in a conflicting field marks the others as not-approved', async () => {
    const user = userEvent.setup();
    render(
      <OmReviewPanel
        extraction={makeExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
      />,
    );

    const card = fieldCard('Current NOI');
    const approveButtons = within(card).getAllByRole('button', { name: 'Approve' });
    await user.click(approveButtons[0]);

    expect(within(card).getByRole('button', { name: 'Approved' })).toBeTruthy();
    expect(within(card).getAllByRole('button', { name: 'Approve' })).toHaveLength(1);
  });

  it('committing an edit on a stated field sets its review-state to approved with the edited value', async () => {
    const user = userEvent.setup();
    render(
      <OmReviewPanel
        extraction={makeExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
      />,
    );

    const card = fieldCard('Purchase Price');
    expect(within(card).getByText('Pending review')).toBeTruthy();

    await user.click(within(card).getByRole('button', { name: 'Edit' }));
    const input = within(card).getByLabelText('Edit Purchase Price');
    await user.clear(input);
    await user.type(input, '1100000');
    await user.click(within(card).getByRole('button', { name: 'Save' }));

    expect(within(card).getByText('Approved', { selector: '.om-review-state-badge' })).toBeTruthy();
  });

  it('committing an edit on a conflicting candidate sets its review-state to approved with the edited value', async () => {
    const user = userEvent.setup();
    render(
      <OmReviewPanel
        extraction={makeExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
      />,
    );

    const card = fieldCard('Current NOI');
    await user.click(within(card).getByRole('button', { name: 'Edit' }));
    const input = within(card).getByLabelText('Edit Current NOI');
    await user.clear(input);
    await user.type(input, '78000');
    await user.click(within(card).getByRole('button', { name: 'Save' }));

    expect(within(card).getByText('Approved', { selector: '.om-review-state-badge' })).toBeTruthy();
  });

  it('rejecting a field sets its review-state to rejected independently of other fields', async () => {
    const user = userEvent.setup();
    render(
      <OmReviewPanel
        extraction={makeExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
      />,
    );

    const purchasePriceCard = fieldCard('Purchase Price');
    await user.click(within(purchasePriceCard).getByRole('button', { name: 'Reject' }));

    expect(within(purchasePriceCard).getByText('Rejected')).toBeTruthy();

    const holdPeriodCard = fieldCard('Hold Period');
    expect(within(holdPeriodCard).getByText('Not found in OM.')).toBeTruthy();
  });

  it('keeps review-state independent of the evidence-status badge', async () => {
    const user = userEvent.setup();
    render(
      <OmReviewPanel
        extraction={makeExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
      />,
    );

    const card = fieldCard('Purchase Price');
    expect(within(card).getByText('Pending review')).toBeTruthy();
    expect(within(card).getByText('Stated')).toBeTruthy();

    await user.click(within(card).getByRole('button', { name: 'Approve' }));

    expect(within(card).getByText('Approved', { selector: '.om-review-state-badge' })).toBeTruthy();
    expect(within(card).getByText('Stated')).toBeTruthy();
  });

  it('renders deal-context fields as read-only text with no approve/edit/reject controls', () => {
    render(
      <OmReviewPanel
        extraction={makeExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
      />,
    );

    expect(screen.getByText('Sunset Gardens')).toBeTruthy();
    expect(screen.getAllByText('Not found in document').length).toBeGreaterThan(0);
    const dealContextSection = screen.getByText('Deal Context (reference only)').closest('.om-deal-context');
    expect(dealContextSection?.querySelector('button')).toBeNull();
  });

  it('assembles only approved values and calls onFinishReview with them', async () => {
    const user = userEvent.setup();
    const onFinishReview = vi.fn();
    render(
      <OmReviewPanel
        extraction={makeExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={onFinishReview}
      />,
    );

    await user.click(within(fieldCard('Purchase Price')).getByRole('button', { name: 'Approve' }));
    await user.click(within(fieldCard('Exit Cap Rate')).getByRole('button', { name: 'Approve' }));

    await user.click(screen.getByRole('button', { name: 'Use approved values' }));

    expect(onFinishReview).toHaveBeenCalledWith({
      purchase_price: '1000000',
      exit_cap_rate: '0.055',
    });
  });

  it('shows an excluded-fields summary naming every field not yet approved', () => {
    render(
      <OmReviewPanel
        extraction={makeExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
      />,
    );

    const summary = screen.getByText(/Not carried to the form/);
    expect(summary.textContent).toContain('Purchase Price');
    expect(summary.textContent).toContain('Hold Period');
  });

  it('resets review state when a new extraction result is uploaded', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <OmReviewPanel
        extraction={makeExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
      />,
    );

    await user.click(within(fieldCard('Purchase Price')).getByRole('button', { name: 'Approve' }));
    expect(
      within(fieldCard('Purchase Price')).getByText('Approved', { selector: '.om-review-state-badge' }),
    ).toBeTruthy();

    rerender(
      <OmReviewPanel
        extraction={makeExtraction()}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onFinishReview={vi.fn()}
      />,
    );

    expect(within(fieldCard('Purchase Price')).getByText('Pending review')).toBeTruthy();
  });
});
