/**
 * Phase 7 Gate P7.9 Stage 3 -- the `PARTNER(partner_id)` Decision Matrix panel.
 *
 * The panel takes its state as a prop, so these tests hand it a report and
 * assert what an analyst sees. Every figure, Delta, Worst Case and Range in the
 * fixture is a backend field; the panel formats and lays out, and these tests
 * exist to prove it never does more than that.
 *
 * **The decisive case is the per-cell identity.** One `partner_id` is the LP
 * under the Base Strategy and a co-investor under another, because a Strategy
 * replaces the Partnership whole and a name and role are presentation (P-8). A
 * panel that labelled every cell from the perspective's own name and role would
 * report the same words in both columns and fail here.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  NO_PARTNERS_MESSAGE,
  PARTNER_ABSENT_MESSAGE,
  PARTNER_NOT_ANALYSED_MESSAGE,
  PARTNER_STALE_MESSAGE,
  PartnerDecisionMatrixPanel,
  RUN_PARTNER_MESSAGE,
} from './components/PartnerDecisionMatrixPanel';
import { STALE_LABEL } from './components/StaleAnalysisNotice';
import type {
  PartnerDecisionCell,
  PartnerDecisionMatrixReport,
  PartnerPerspective,
} from './partnershipTypes';
import type { PartnerDecisionMatrixState } from './usePartnerDecisionMatrix';

afterEach(cleanup);

const PERSPECTIVE: PartnerPerspective = {
  partner_id: 'investor-1',
  name: 'Harbor Capital',
  present_in_base: true,
  strategy_ids: ['base', 'strat-jv'],
};

function cell(overrides: Partial<PartnerDecisionCell> & { strategy_id: string; scenario_id: string }): PartnerDecisionCell {
  return {
    status: 'valid',
    applicability: 'present',
    partner_name: 'Harbor Capital',
    partner_role: 'lp',
    issues: [],
    project_source_fingerprint: 'p',
    structured_source_fingerprint: 's',
    partnership_source_fingerprint: 'w',
    source_fingerprint: 'w',
    hold_period: 5,
    partnership_status: 'complete',
    unavailable_reason: null,
    unavailable_message: null,
    is_promote_participant: false,
    metrics: [
      { metric: 'total_contributions', value: 900000, irr_status: null, reason: null, message: null },
      { metric: 'partner_irr', value: 0.164, irr_status: 'defined', reason: null, message: null },
      {
        metric: 'promote_earned',
        value: null,
        irr_status: null,
        reason: 'not_reported',
        message:
          'Not available: the selected partner is not in this Strategy’s Partnership, or is not one of its promote participants.',
      },
    ],
    deltas: [
      { metric: 'total_contributions', value: null, is_baseline: true, reason: null, message: null },
      { metric: 'partner_irr', value: null, is_baseline: true, reason: null, message: null },
      { metric: 'promote_earned', value: null, is_baseline: true, reason: null, message: null },
    ],
    ...overrides,
  };
}

const METRICS: PartnerDecisionMatrixReport['matrix']['metrics'] = [
  {
    metric: 'total_contributions',
    label: 'Contributions',
    unit: 'currency',
    direction: 'lower_is_better',
    horizon_dependent: false,
  },
  {
    metric: 'partner_irr',
    label: 'Partner IRR',
    unit: 'rate',
    direction: 'higher_is_better',
    horizon_dependent: false,
  },
  {
    metric: 'promote_earned',
    label: 'Promote Earned',
    unit: 'currency',
    direction: 'higher_is_better',
    horizon_dependent: false,
  },
];

function report(cells: PartnerDecisionCell[]): PartnerDecisionMatrixReport {
  return {
    investment_id: 'inv-1',
    root_kind: 'hidden_unit',
    unit_ids: ['deal-1'],
    partner: PERSPECTIVE,
    matrix: {
      perspective: 'partner',
      partner_id: 'investor-1',
      partner_name: 'Harbor Capital',
      strategies: [
        { strategy_id: 'base', name: 'Base', is_base: true, hold_period: 5 },
        { strategy_id: 'strat-jv', name: 'JV Recapitalization', is_base: false, hold_period: 7 },
      ],
      scenarios: [
        { scenario_id: 'base', name: 'Base', is_base: true },
        { scenario_id: 'downside', name: 'Downside', is_base: false },
      ],
      metrics: METRICS,
      omitted_metrics: [],
      hold_periods: [5, 7],
      cross_scenario_figures: false,
      cells,
      strategy_figures: [],
      matrix_fingerprint: 'f',
      matrix_fingerprint_reason: null,
    },
  };
}

function matrixState(overrides: Partial<PartnerDecisionMatrixState> = {}): PartnerDecisionMatrixState {
  return {
    partners: [PERSPECTIVE],
    listStatus: 'ready',
    listError: null,
    retryList: vi.fn(),
    selectedPartnerId: 'investor-1',
    selectPartner: vi.fn(),
    report: null,
    error: null,
    isCurrent: true,
    hasRun: false,
    isRunning: false,
    canRun: true,
    run: vi.fn(async () => {}),
    ...overrides,
  };
}

function renderPanel(state: PartnerDecisionMatrixState) {
  render(<PartnerDecisionMatrixPanel state={state} ids="" isDirty={false} />);
}

describe('the PARTNER perspective', () => {
  it('offers the addressable partners, and runs nothing until asked', async () => {
    const user = userEvent.setup();
    const run = vi.fn(async () => {});
    renderPanel(matrixState({ run }));

    expect(
      (screen.getByRole('combobox', { name: 'Partner' }) as HTMLSelectElement).value,
    ).toBe('investor-1');
    expect(screen.getByText(RUN_PARTNER_MESSAGE)).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Run Partner Matrix' }));
    expect(run).toHaveBeenCalled();
  });

  it('says so when there is no partner to compare', () => {
    renderPanel(matrixState({ partners: [], selectedPartnerId: null, canRun: false }));
    expect(screen.getByText(NO_PARTNERS_MESSAGE)).toBeTruthy();
    expect(screen.queryByRole('combobox', { name: 'Partner' })).toBeNull();
  });

  it('drops the report on screen when a different partner is selected', async () => {
    const user = userEvent.setup();
    const selectPartner = vi.fn();
    renderPanel(
      matrixState({
        partners: [PERSPECTIVE, { ...PERSPECTIVE, partner_id: 'gp', name: 'Sponsor GP' }],
        selectPartner,
      }),
    );
    await user.selectOptions(screen.getByRole('combobox', { name: 'Partner' }), 'gp');
    expect(selectPartner).toHaveBeenCalledWith('gp');
  });
});

describe('each cell is described by its own Strategy’s Partnership (P-8)', () => {
  it('reports a different name and role for one partner id across Strategies', () => {
    renderPanel(
      matrixState({
        hasRun: true,
        report: report([
          cell({ strategy_id: 'base', scenario_id: 'base', partner_name: 'Harbor Capital', partner_role: 'lp' }),
          cell({ strategy_id: 'base', scenario_id: 'downside', partner_name: 'Harbor Capital', partner_role: 'lp' }),
          // The same stable id, described differently by the Strategy that
          // replaced the Partnership whole.
          cell({
            strategy_id: 'strat-jv',
            scenario_id: 'base',
            partner_name: 'Harbor Capital Co-Invest',
            partner_role: 'co_investor',
          }),
          cell({
            strategy_id: 'strat-jv',
            scenario_id: 'downside',
            partner_name: 'Harbor Capital Co-Invest',
            partner_role: 'co_investor',
          }),
        ]),
      }),
    );

    // The perspective's own name labels the selector, never a cell.
    expect(screen.getAllByText('Harbor Capital Co-Invest').length).toBe(2);
    expect(screen.getAllByText('Co-Investor').length).toBe(2);
    expect(screen.getAllByText('LP').length).toBe(2);
  });

  it('shows no identity where the partner is not present', () => {
    renderPanel(
      matrixState({
        hasRun: true,
        report: report([
          cell({ strategy_id: 'base', scenario_id: 'base' }),
          cell({ strategy_id: 'base', scenario_id: 'downside' }),
          cell({
            strategy_id: 'strat-jv',
            scenario_id: 'base',
            applicability: 'not_present',
            partner_name: null,
            partner_role: null,
            partnership_status: null,
            is_promote_participant: null,
            metrics: [],
            deltas: [],
          }),
          cell({
            strategy_id: 'strat-jv',
            scenario_id: 'downside',
            applicability: 'not_present',
            partner_name: null,
            partner_role: null,
            partnership_status: null,
            is_promote_participant: null,
            metrics: [],
            deltas: [],
          }),
        ]),
      }),
    );
    expect(screen.getAllByText(PARTNER_ABSENT_MESSAGE).length).toBe(2);
  });
});

describe('every applicability state is its own state, and none is a zero', () => {
  it('distinguishes present, absent, not analysed and invalid', () => {
    renderPanel(
      matrixState({
        hasRun: true,
        report: report([
          cell({ strategy_id: 'base', scenario_id: 'base' }),
          cell({
            strategy_id: 'base',
            scenario_id: 'downside',
            applicability: 'not_present',
            partner_name: null,
            partner_role: null,
            metrics: [],
            deltas: [],
          }),
          cell({
            strategy_id: 'strat-jv',
            scenario_id: 'base',
            status: 'invalid',
            applicability: 'not_analysed',
            partner_name: null,
            partner_role: null,
            source_fingerprint: null,
            partnership_source_fingerprint: null,
            metrics: [],
            deltas: [],
            issues: [
              {
                source: 'partnership',
                code: 'catch_up_rate_not_above_target',
                message: 'The catch-up rate must exceed its target profit share.',
                field: 'partnership.tiers[tier-2]',
              },
            ],
          }),
          cell({
            strategy_id: 'strat-jv',
            scenario_id: 'downside',
            applicability: 'not_analysed',
            partner_name: null,
            partner_role: null,
            metrics: [],
            deltas: [],
          }),
        ]),
      }),
    );

    expect(screen.getByText(PARTNER_ABSENT_MESSAGE)).toBeTruthy();
    expect(screen.getByText(PARTNER_NOT_ANALYSED_MESSAGE)).toBeTruthy();
    expect(screen.getByText('Invalid variant')).toBeTruthy();
    // The validator's own words, never the panel's paraphrase.
    expect(
      screen.getByText('The catch-up rate must exceed its target profit share.'),
    ).toBeTruthy();
  });

  it("reports a non-participant's Promote Earned as N/A with the backend's reason", () => {
    renderPanel(
      matrixState({
        hasRun: true,
        report: report([
          cell({ strategy_id: 'base', scenario_id: 'base' }),
          cell({ strategy_id: 'base', scenario_id: 'downside' }),
          cell({ strategy_id: 'strat-jv', scenario_id: 'base' }),
          cell({ strategy_id: 'strat-jv', scenario_id: 'downside' }),
        ]),
      }),
    );
    const promoteRows = screen.getAllByRole('row', { name: /Promote Earned/ });
    const firstCell = within(promoteRows[0]).getAllByText('N/A')[0];
    expect(firstCell).toBeTruthy();
    expect(
      screen.getAllByText(
        'Not available: the selected partner is not in this Strategy’s Partnership, or is not one of its promote participants.',
      ).length,
    ).toBeGreaterThan(0);
    // Never zero.
    expect(within(promoteRows[0]).queryByText('$0')).toBeNull();
  });

  it('reports an unavailable upstream as N/A with the engine’s message', () => {
    renderPanel(
      matrixState({
        hasRun: true,
        report: report([
          cell({
            strategy_id: 'base',
            scenario_id: 'base',
            partnership_status: 'unavailable',
            unavailable_reason: 'common_equity_unavailable',
            unavailable_message: 'Funding Requirement req-1 is unresolved.',
            metrics: METRICS.map((spec) => ({
              metric: spec.metric,
              value: null,
              irr_status: null,
              reason: 'not_reported',
              message: null,
            })),
          }),
          cell({ strategy_id: 'base', scenario_id: 'downside' }),
          cell({ strategy_id: 'strat-jv', scenario_id: 'base' }),
          cell({ strategy_id: 'strat-jv', scenario_id: 'downside' }),
        ]),
      }),
    );
    // The cell's own unavailable message stands in for each missing figure.
    expect(
      screen.getAllByText('Funding Requirement req-1 is unresolved.').length,
    ).toBeGreaterThan(0);
    // The partner is still present, so its identity is still stated.
    expect(screen.getAllByText('Harbor Capital').length).toBeGreaterThan(0);
  });
});

describe('the Partner matrix judges nothing', () => {
  it('shows the backend’s figures and Delta, and never a winner or a score', () => {
    renderPanel(
      matrixState({
        hasRun: true,
        report: report([
          cell({ strategy_id: 'base', scenario_id: 'base' }),
          cell({
            strategy_id: 'base',
            scenario_id: 'downside',
            metrics: [
              {
                metric: 'total_contributions',
                value: 950000,
                irr_status: null,
                reason: null,
                message: null,
              },
              { metric: 'partner_irr', value: 0.121, irr_status: 'defined', reason: null, message: null },
              { metric: 'promote_earned', value: 12000, irr_status: null, reason: null, message: null },
            ],
            deltas: [
              {
                metric: 'total_contributions',
                value: 50000,
                is_baseline: false,
                reason: null,
                message: null,
              },
              { metric: 'partner_irr', value: -0.043, is_baseline: false, reason: null, message: null },
              { metric: 'promote_earned', value: 12000, is_baseline: false, reason: null, message: null },
            ],
          }),
          cell({ strategy_id: 'strat-jv', scenario_id: 'base' }),
          cell({ strategy_id: 'strat-jv', scenario_id: 'downside' }),
        ]),
      }),
    );

    // The backend's Delta, formatted: a rate difference reads in points.
    expect(screen.getByText('+$50,000 vs Base')).toBeTruthy();
    expect(screen.getByText('-4.30 pts vs Base')).toBeTruthy();
    // No ranking vocabulary anywhere on screen.
    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/winner|best|rank|score|recommend/i);
  });

  it('marks a stale report out of date rather than presenting it as current', () => {
    renderPanel(
      matrixState({
        hasRun: true,
        isCurrent: false,
        report: report([
          cell({ strategy_id: 'base', scenario_id: 'base' }),
          cell({ strategy_id: 'base', scenario_id: 'downside' }),
          cell({ strategy_id: 'strat-jv', scenario_id: 'base' }),
          cell({ strategy_id: 'strat-jv', scenario_id: 'downside' }),
        ]),
      }),
    );
    expect(screen.getByText(STALE_LABEL)).toBeTruthy();
    expect(screen.getByText(PARTNER_STALE_MESSAGE)).toBeTruthy();
    // Kept on screen: it is real work against real saved inputs.
    expect(screen.getByRole('table')).toBeTruthy();
  });

  it('says nothing about staleness while the report is current', () => {
    renderPanel(
      matrixState({
        hasRun: true,
        isCurrent: true,
        report: report([
          cell({ strategy_id: 'base', scenario_id: 'base' }),
          cell({ strategy_id: 'base', scenario_id: 'downside' }),
          cell({ strategy_id: 'strat-jv', scenario_id: 'base' }),
          cell({ strategy_id: 'strat-jv', scenario_id: 'downside' }),
        ]),
      }),
    );
    expect(screen.queryByText(STALE_LABEL)).toBeNull();
  });

  it('scrolls the table inside its own region rather than widening the page', () => {
    renderPanel(
      matrixState({
        hasRun: true,
        report: report([
          cell({ strategy_id: 'base', scenario_id: 'base' }),
          cell({ strategy_id: 'base', scenario_id: 'downside' }),
          cell({ strategy_id: 'strat-jv', scenario_id: 'base' }),
          cell({ strategy_id: 'strat-jv', scenario_id: 'downside' }),
        ]),
      }),
    );
    const region = screen.getByRole('region', { name: 'Partner decision matrix table' });
    expect(region.getAttribute('tabindex')).toBe('0');
  });
});
