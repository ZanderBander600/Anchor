import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AiAnalystPanel } from './AiAnalystPanel';
import type { AIAnalysis } from '../types';

afterEach(() => {
  cleanup();
});

function makeAnalysis(overrides: Partial<AIAnalysis> = {}): AIAnalysis {
  return {
    executive_summary: 'This is a five-year value-add acquisition with moderate leverage.',
    investment_view: 'Return profile is reasonable given the supplied sensitivity evidence.',
    strengths: ['Levered IRR clears the target hurdle at baseline.', 'DSCR cushion in Year 1.'],
    risks: ['Exit cap rate expansion compresses returns per the sensitivity matrix.'],
    return_drivers: ['NOI growth', 'Exit cap rate assumption'],
    downside_analysis: 'Levered IRR remains positive across the tested exit cap range.',
    capital_structure_analysis: '65% LTV produces a Year 1 DSCR above 1.15x.',
    break_even_analysis: 'Maximum purchase price break-even was found within the tested range.',
    questions_to_investigate: ['What is the in-place rent roll composition?'],
    confidence_notes: ['No tenant credit data was supplied.'],
    ...overrides,
  };
}

describe('AiAnalystPanel', () => {
  it('always renders the section title and Generate button', () => {
    render(<AiAnalystPanel analysis={null} isLoading={false} error={null} onGenerate={vi.fn()} />);

    expect(screen.getByText('Anchor AI Analyst')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Generate AI Analysis' })).toBeTruthy();
  });

  it('shows an empty-state prompt before any analysis has been generated', () => {
    render(<AiAnalystPanel analysis={null} isLoading={false} error={null} onGenerate={vi.fn()} />);

    expect(screen.getByText(/Click/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Generate AI Analysis' })).toBeTruthy();
  });

  it('calls onGenerate when the button is clicked', async () => {
    const user = userEvent.setup();
    const onGenerate = vi.fn();
    render(<AiAnalystPanel analysis={null} isLoading={false} error={null} onGenerate={onGenerate} />);

    await user.click(screen.getByRole('button', { name: 'Generate AI Analysis' }));

    expect(onGenerate).toHaveBeenCalledTimes(1);
  });

  it('shows a loading state and disables the button while pending', () => {
    render(<AiAnalystPanel analysis={null} isLoading={true} error={null} onGenerate={vi.fn()} />);

    expect(screen.getByText(/Generating AI analysis/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Generating…' })).toHaveProperty('disabled', true);
  });

  it('renders every structured section of a generated analysis', () => {
    render(
      <AiAnalystPanel analysis={makeAnalysis()} isLoading={false} error={null} onGenerate={vi.fn()} />,
    );

    expect(screen.getByText('Investment View')).toBeTruthy();
    expect(screen.getByText('Executive Summary')).toBeTruthy();
    expect(screen.getByText('Key Strengths')).toBeTruthy();
    expect(screen.getByText('Key Risks')).toBeTruthy();
    expect(screen.getByText('Return Drivers')).toBeTruthy();
    expect(screen.getByText('Downside Analysis')).toBeTruthy();
    expect(screen.getByText('Capital Structure')).toBeTruthy();
    expect(screen.getByText('Break-Even Interpretation')).toBeTruthy();
    expect(screen.getByText('Questions to Investigate')).toBeTruthy();
    expect(screen.getByText('Confidence / Data Gaps')).toBeTruthy();

    expect(
      screen.getByText('Levered IRR clears the target hurdle at baseline.'),
    ).toBeTruthy();
    expect(
      screen.getByText('Exit cap rate expansion compresses returns per the sensitivity matrix.'),
    ).toBeTruthy();
    expect(screen.getByText('What is the in-place rent roll composition?')).toBeTruthy();
  });

  it('renders strengths and risks as separate list items', () => {
    render(
      <AiAnalystPanel
        analysis={makeAnalysis({ strengths: ['A', 'B'], risks: ['C'] })}
        isLoading={false}
        error={null}
        onGenerate={vi.fn()}
      />,
    );

    expect(screen.getByText('A')).toBeTruthy();
    expect(screen.getByText('B')).toBeTruthy();
    expect(screen.getByText('C')).toBeTruthy();
  });

  it('shows an AI-specific error without hiding the Generate button', () => {
    render(
      <AiAnalystPanel
        analysis={null}
        isLoading={false}
        error="The AI Analyst is not configured."
        onGenerate={vi.fn()}
      />,
    );

    expect(screen.getByText('The AI Analyst is not configured.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Generate AI Analysis' })).toBeTruthy();
  });

  it('never renders anything resembling a raw API key', () => {
    const { container } = render(
      <AiAnalystPanel analysis={makeAnalysis()} isLoading={false} error={null} onGenerate={vi.fn()} />,
    );

    expect(container.innerHTML).not.toMatch(/sk-[A-Za-z0-9]/);
    expect(container.innerHTML.toLowerCase()).not.toContain('openai_api_key');
  });
});
