import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { DetailedAssumptionsForm } from './DetailedAssumptionsForm';
import { DETAILED_GOLDEN_FORM_VALUES } from '../convert';

afterEach(() => {
  cleanup();
});

describe('DetailedAssumptionsForm', () => {
  it('renders both section headings and all field-group titles', () => {
    render(
      <DetailedAssumptionsForm
        termsValues={DETAILED_GOLDEN_FORM_VALUES.terms}
        operatingValues={DETAILED_GOLDEN_FORM_VALUES.operating}
        onTermsFieldChange={vi.fn()}
        onOperatingFieldChange={vi.fn()}
        onSubmit={vi.fn()}
        isSubmitting={false}
      />,
    );

    expect(screen.getByText('Acquisition, Transaction & Debt')).toBeTruthy();
    expect(screen.getByText('Operating Model')).toBeTruthy();
    for (const title of ['Acquisition & Exit', 'Transaction Costs', 'Operations', 'Financing']) {
      expect(screen.getByText(title)).toBeTruthy();
    }
    for (const title of ['Revenue', 'Operating Expenses', 'Growth']) {
      expect(screen.getByText(title)).toBeTruthy();
    }
  });

  it('renders every terms field pre-filled with its supplied value', () => {
    render(
      <DetailedAssumptionsForm
        termsValues={DETAILED_GOLDEN_FORM_VALUES.terms}
        operatingValues={DETAILED_GOLDEN_FORM_VALUES.operating}
        onTermsFieldChange={vi.fn()}
        onOperatingFieldChange={vi.fn()}
        onSubmit={vi.fn()}
        isSubmitting={false}
      />,
    );

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('value', '10000000');
    expect(screen.getByLabelText(/^Hold Period/)).toHaveProperty('value', '5');
    expect(screen.getByLabelText(/^Exit Cap Rate/)).toHaveProperty('value', '6.5');
  });

  it('renders every operating field pre-filled with its supplied value', () => {
    render(
      <DetailedAssumptionsForm
        termsValues={DETAILED_GOLDEN_FORM_VALUES.terms}
        operatingValues={DETAILED_GOLDEN_FORM_VALUES.operating}
        onTermsFieldChange={vi.fn()}
        onOperatingFieldChange={vi.fn()}
        onSubmit={vi.fn()}
        isSubmitting={false}
      />,
    );

    expect(screen.getByLabelText(/^Gross Potential Rent/)).toHaveProperty('value', '800000');
    expect(screen.getByLabelText(/^Vacancy & Credit Loss/)).toHaveProperty('value', '5');
    expect(screen.getByLabelText(/^Management Fee/)).toHaveProperty('value', '5');
  });

  it('calls onTermsFieldChange when a terms field is edited', () => {
    const onTermsFieldChange = vi.fn();
    render(
      <DetailedAssumptionsForm
        termsValues={DETAILED_GOLDEN_FORM_VALUES.terms}
        operatingValues={DETAILED_GOLDEN_FORM_VALUES.operating}
        onTermsFieldChange={onTermsFieldChange}
        onOperatingFieldChange={vi.fn()}
        onSubmit={vi.fn()}
        isSubmitting={false}
      />,
    );

    fireEvent.change(screen.getByLabelText(/^Purchase Price/), {
      target: { value: '11000000' },
    });

    expect(onTermsFieldChange).toHaveBeenCalledWith('purchasePrice', '11000000');
  });

  it('calls onOperatingFieldChange when an operating field is edited', () => {
    const onOperatingFieldChange = vi.fn();
    render(
      <DetailedAssumptionsForm
        termsValues={DETAILED_GOLDEN_FORM_VALUES.terms}
        operatingValues={DETAILED_GOLDEN_FORM_VALUES.operating}
        onTermsFieldChange={vi.fn()}
        onOperatingFieldChange={onOperatingFieldChange}
        onSubmit={vi.fn()}
        isSubmitting={false}
      />,
    );

    fireEvent.change(screen.getByLabelText(/^Gross Potential Rent/), {
      target: { value: '850000' },
    });

    expect(onOperatingFieldChange).toHaveBeenCalledWith('grossPotentialRent', '850000');
  });

  it('calls onSubmit when the form is submitted', () => {
    const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
    render(
      <DetailedAssumptionsForm
        termsValues={DETAILED_GOLDEN_FORM_VALUES.terms}
        operatingValues={DETAILED_GOLDEN_FORM_VALUES.operating}
        onTermsFieldChange={vi.fn()}
        onOperatingFieldChange={vi.fn()}
        onSubmit={onSubmit}
        isSubmitting={false}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Analyze Deal/ }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('disables every input and shows "Analyzing…" while submitting', () => {
    render(
      <DetailedAssumptionsForm
        termsValues={DETAILED_GOLDEN_FORM_VALUES.terms}
        operatingValues={DETAILED_GOLDEN_FORM_VALUES.operating}
        onTermsFieldChange={vi.fn()}
        onOperatingFieldChange={vi.fn()}
        onSubmit={vi.fn()}
        isSubmitting={true}
      />,
    );

    expect(screen.getByLabelText(/^Purchase Price/)).toHaveProperty('disabled', true);
    expect(screen.getByLabelText(/^Gross Potential Rent/)).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: /Analyzing…/ })).toHaveProperty('disabled', true);
  });

  it('never renders a Current NOI, Occupancy, or NOI Growth field', () => {
    render(
      <DetailedAssumptionsForm
        termsValues={DETAILED_GOLDEN_FORM_VALUES.terms}
        operatingValues={DETAILED_GOLDEN_FORM_VALUES.operating}
        onTermsFieldChange={vi.fn()}
        onOperatingFieldChange={vi.fn()}
        onSubmit={vi.fn()}
        isSubmitting={false}
      />,
    );

    expect(screen.queryByLabelText(/^Current NOI/)).toBeNull();
    expect(screen.queryByLabelText(/^Occupancy/)).toBeNull();
    expect(screen.queryByLabelText(/^NOI Growth/)).toBeNull();
  });
});
