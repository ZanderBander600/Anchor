import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import fixture from '../capitalEconomicsFixture.json';
import { irrNotReportedExplanation } from '../capitalEconomics';
import type { AcquisitionResults } from '../types';
import { ResultsSummaryPanel } from './ResultsSummaryPanel';

afterEach(cleanup);

function results(name: keyof typeof fixture.quick): AcquisitionResults {
  return fixture.quick[name].response as unknown as AcquisitionResults;
}

describe('ResultsSummaryPanel', () => {
  it('says why an IRR the engine does not report is N/A, in the Capital Economics words', () => {
    const unreported = results('v7_multiple_sign_changes');
    expect(unreported.levered_irr).toBeNull();
    render(<ResultsSummaryPanel results={unreported} />);

    const levered = irrNotReportedExplanation('Levered IRR', unreported.levered_irr_status);
    expect(levered).toBe(
      'Levered IRR is not reported because the modeled cash-flow pattern changes sign more than once.',
    );
    const card = screen.getByText('Levered IRR').closest('.stat-card') as HTMLElement;
    expect(card.textContent).toBe(`Levered IRRN/A${levered}`);

    const unlevered = irrNotReportedExplanation('Unlevered IRR', unreported.unlevered_irr_status);
    const row = screen.getByText('Unlevered IRR').closest('.info-row') as HTMLElement;
    expect(row.textContent).toBe(
      unlevered === null
        ? `Unlevered IRR${(unreported.unlevered_irr! * 100).toFixed(2)}%`
        : `Unlevered IRRN/A${unlevered}`,
    );
  });

  it('adds nothing beside an IRR the engine reports', () => {
    const reported = results('v1_empty');
    expect(reported.levered_irr_status).toBe('defined');
    render(<ResultsSummaryPanel results={reported} />);

    const card = screen.getByText('Levered IRR').closest('.stat-card') as HTMLElement;
    expect(card.querySelector('.stat-caption')).toBeNull();
    const row = screen.getByText('Unlevered IRR').closest('.info-row') as HTMLElement;
    expect(row.querySelector('.info-note')).toBeNull();
    expect(screen.queryByText(/is not reported because/)).toBeNull();
  });
});
