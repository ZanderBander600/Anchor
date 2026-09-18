/**
 * Phase 7 Gate P7.9 Stage 3 -- the Partnership surfaces, driven directly.
 *
 * The editor, the result surface and the Risk view take their state as a prop,
 * so these tests hand them state and assert what an analyst sees. No `api.ts`
 * mock is needed: what is proved here is presentation, which is the whole of
 * what this layer is allowed to do.
 *
 * **The result fixture is deliberately not internally consistent.** Its
 * distribution difference is not its distributions less its benchmark
 * distributions, its advantage is not the positive part of that difference, its
 * Promote Earned is not its profit-distribution difference, and its MOIC is not
 * its distributions over its contributions. Every one of those is a figure the
 * browser could "obviously" re-derive, so a UI that derived any of them would
 * print a different string and fail here -- the `capitalStructureUi.test.tsx`
 * technique, applied to the gate where three similar-looking comparisons sit
 * side by side and the temptation to compute one from another is strongest
 * (P-3, P-5).
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  CHOOSE,
  NO_PARTNERS_MESSAGE as EDITOR_NO_PARTNERS_MESSAGE,
  PartnershipEditor,
  PROMOTE_CONFIRM_LABEL,
  UNSTATED_CHOICES_TITLE,
} from './components/PartnershipEditor';
import {
  BENCHMARK_MISMATCH_NOTICE,
  PartnershipResults,
} from './components/PartnershipResults';
import {
  ANALYSIS_ABSENT_MESSAGE,
  NO_PARTNERSHIP_MESSAGE,
  PartnershipWorkspace,
  STALE_PARTNERSHIP_MESSAGE,
} from './components/PartnershipWorkspace';
import { STALE_LABEL } from './components/StaleAnalysisNotice';
import { EMPTY_PARTNERSHIP_FORM, formFromPartnership } from './partnershipForm';
import type { PartnershipForm } from './partnershipForm';
import { investmentLeaveWarning } from './investmentCatalog';
import {
  blankStrategyDraft,
  buildStrategyRequest,
  draftFromStrategy,
  draftHasEconomicContent,
} from './strategyForm';
import type { StrategyEditorDraft } from './strategyForm';
import type {
  Partnership,
  PartnerResult,
  PartnershipResult,
  PartnershipVariantAnalysis,
} from './partnershipTypes';
import type { PartnershipState } from './usePartnership';

afterEach(cleanup);

// =============================================================================
// Fixtures
// =============================================================================

const PARTNERSHIP: Partnership = {
  partners: [
    {
      partner_id: 'lp',
      name: 'Harbor Capital LP',
      role: 'lp',
      investor_class: 'class_a',
      commitment_share: 0.9,
    },
    { partner_id: 'gp', name: 'Sponsor GP', role: 'gp', investor_class: null, commitment_share: 0.1 },
  ],
  contribution_rule: 'pro_rata_by_commitment',
  promote_benchmark: {
    shares: [
      { partner_id: 'lp', share: 0.8 },
      { partner_id: 'gp', share: 0.2 },
    ],
  },
  promote_participant_ids: ['gp'],
  tiers: [
    {
      tier_id: 'tier-1',
      name: 'Preferred Return',
      sequence: 1,
      kind: 'hurdle',
      split: {
        kind: 'explicit',
        shares: [
          { partner_id: 'lp', share: 1 },
          { partner_id: 'gp', share: 0 },
        ],
      },
      hurdle: {
        hurdle_subject: { kind: 'partner', partner_id: 'lp', investor_class: null, account: null },
        conditions: [
          {
            kind: 'irr',
            condition_id: 'cond-1',
            rate: 0.08,
            accrual_convention: 'simple',
            simple_distribution_order: 'accrued_return_first',
          },
        ],
        combinator: 'all',
      },
      catch_up: null,
    },
    {
      tier_id: 'tier-2',
      name: 'Residual',
      sequence: 2,
      kind: 'residual',
      split: { kind: 'pro_rata_by_contribution' },
      hurdle: null,
      catch_up: null,
    },
  ],
};

const PARTNER_NAMES = { lp: 'Harbor Capital LP', gp: 'Sponsor GP', promoter: 'Promote Vehicle' };
const TIER_NAMES = { 'tier-1': 'Preferred Return', 'tier-2': 'Residual' };

function partner(overrides: Partial<PartnerResult> & { partner_id: string }): PartnerResult {
  return {
    role: 'lp',
    investor_class: null,
    commitment_share: 0.9,
    benchmark_share: 0.9,
    benchmark_equals_commitment: true,
    is_promote_participant: false,
    contributions: [900000, 0],
    distributions: [0, 1300000],
    net_cash_flows: [-900000, 1300000],
    total_contributions: 900000,
    total_distributions: 1300000,
    profit: 400000,
    irr: 0.164,
    irr_status: 'defined',
    // Deliberately not total_distributions / total_contributions.
    moic: 1.33,
    moic_unavailable_reason: null,
    benchmark_distributions: [0, 1200000],
    total_benchmark_distributions: 1200000,
    capital_returned: 900000,
    profit_distributions: 400000,
    benchmark_capital_returned: 900000,
    benchmark_profit_distributions: 300000,
    // Deliberately not 1300000 - 1200000.
    distribution_difference: 77000,
    // Deliberately not max(distribution_difference, 0).
    distribution_advantage: 66000,
    distribution_disadvantage: 0,
    capital_return_difference: 0,
    // Deliberately not distribution_difference - capital_return_difference.
    profit_distribution_difference: 55000,
    promote_earned: null,
    promote_unavailable_reason: 'not_a_promote_participant',
    benchmark_capital_subordination: 0,
    distributions_by_tier: [{ tier_id: 'tier-1', sequence: 1, amount: 1300000 }],
    capital_return_difference_by_tier: [{ tier_id: 'tier-1', sequence: 1, amount: 0 }],
    profit_distribution_difference_by_tier: [{ tier_id: 'tier-1', sequence: 1, amount: 55000 }],
    promote_attribution_by_tier: null,
    ...overrides,
  };
}

/** The LP: not a promote participant, and its benchmark share differs from its
 * commitment -- the two disclosures the contract requires (R-A, R-E). */
const LP = partner({
  partner_id: 'lp',
  role: 'lp',
  investor_class: 'class_a',
  commitment_share: 0.9,
  benchmark_share: 0.8,
  benchmark_equals_commitment: false,
  is_promote_participant: false,
  promote_earned: null,
  promote_unavailable_reason: 'not_a_promote_participant',
  benchmark_capital_subordination: 85000,
  distribution_disadvantage: 0,
});

/** The GP: a stated promote participant with a Promote Earned that is
 * deliberately not its profit-distribution difference. */
const GP = partner({
  partner_id: 'gp',
  role: 'gp',
  commitment_share: 0.1,
  benchmark_share: 0.2,
  benchmark_equals_commitment: false,
  is_promote_participant: true,
  contributions: [100000, 0],
  distributions: [0, 260000],
  net_cash_flows: [-100000, 260000],
  total_contributions: 100000,
  total_distributions: 260000,
  profit: 160000,
  irr: 0.21,
  moic: 2.44,
  benchmark_distributions: [0, 200000],
  total_benchmark_distributions: 200000,
  capital_returned: 100000,
  profit_distributions: 160000,
  benchmark_capital_returned: 100000,
  benchmark_profit_distributions: 100000,
  distribution_difference: 61000,
  distribution_advantage: 61000,
  profit_distribution_difference: 62000,
  // Deliberately not profit_distribution_difference.
  promote_earned: 44000,
  promote_unavailable_reason: null,
  benchmark_capital_subordination: 0,
  promote_attribution_by_tier: [
    { tier_id: 'tier-1', sequence: 1, amount: -6000 },
    { tier_id: 'tier-2', sequence: 2, amount: 50000 },
  ],
});

/** A promote-only vehicle: it contributes nothing, so its MOIC and IRR are both
 * N/A with the engine's own reasons rather than zero or infinity. */
const PROMOTER = partner({
  partner_id: 'promoter',
  role: 'co_investor',
  commitment_share: 0,
  benchmark_share: 0,
  is_promote_participant: true,
  contributions: [0, 0],
  distributions: [0, 40000],
  net_cash_flows: [0, 40000],
  total_contributions: 0,
  total_distributions: 40000,
  profit: 40000,
  irr: null,
  irr_status: 'first_nonzero_not_negative',
  moic: null,
  moic_unavailable_reason: 'no_contributions',
  total_benchmark_distributions: 31000,
  benchmark_capital_returned: 0,
  benchmark_profit_distributions: 31000,
  capital_returned: 0,
  profit_distributions: 40000,
  distribution_difference: 9000,
  distribution_advantage: 9000,
  distribution_disadvantage: 0,
  capital_return_difference: 0,
  profit_distribution_difference: 9000,
  promote_earned: 0,
  promote_unavailable_reason: null,
  benchmark_capital_subordination: 0,
  promote_attribution_by_tier: [{ tier_id: 'tier-1', sequence: 1, amount: 0 }],
});

const COMPLETE: PartnershipResult = {
  status: 'complete',
  unavailable_reason: null,
  unavailable_message: null,
  upstream_reason: null,
  upstream_requirement_ids: [],
  cadence: 'annual',
  promote_participant_ids: ['gp', 'promoter'],
  common_equity_cash_flows: [-1000000, 1600000],
  common_equity_total_profit: 600000,
  partners: [LP, GP, PROMOTER],
  tiers: [
    {
      tier_id: 'tier-1',
      sequence: 1,
      kind: 'hurdle',
      split_rule: 'explicit',
      shares_by_period: [
        { period: 0, shares: [{ partner_id: 'lp', share: 1 }] },
        { period: 1, shares: [{ partner_id: 'lp', share: 1 }] },
      ],
      hurdle_subject: { kind: 'partner', partner_id: 'lp', investor_class: null, account: null },
      subject_partner_ids: ['lp'],
      combinator: 'all',
      catch_up_recipient: null,
      recipient_partner_ids: null,
      catch_up_rate: null,
      target_profit_share: null,
      amounts: [0, 1300000],
      partner_amounts: [{ partner_id: 'lp', amounts: [0, 1300000] }],
      conditions: [
        {
          condition_id: 'cond-1',
          period: 1,
          opening_balance: 900000,
          accrual: 72000,
          subject_contributions: 0,
          subject_distributions_before_tier: 0,
          subject_distributions_from_tier: 1300000,
          subject_distributions_after_tier: 0,
          closing_balance: 0,
          capacity_at_entry: 972000,
          satisfied_at_close: true,
          simple_distribution_order: 'accrued_return_first',
          outstanding_capital: 900000,
          accrued_return: 72000,
        },
      ],
      catch_up_records: [],
    },
    {
      tier_id: 'tier-2',
      sequence: 2,
      kind: 'residual',
      split_rule: 'pro_rata_by_contribution',
      shares_by_period: [{ period: 1, shares: [{ partner_id: 'gp', share: 1 }] }],
      hurdle_subject: null,
      subject_partner_ids: null,
      combinator: null,
      catch_up_recipient: null,
      recipient_partner_ids: null,
      catch_up_rate: null,
      target_profit_share: null,
      amounts: [300000],
      partner_amounts: [{ partner_id: 'gp', amounts: [300000] }],
      conditions: [],
      catch_up_records: [],
    },
  ],
  periods: [
    {
      period: 0,
      common_equity_cash_flow: -1000000,
      total_contributions: 1000000,
      total_distributions: 0,
      remaining_after_tier: [],
    },
    {
      period: 1,
      common_equity_cash_flow: 1600000,
      total_contributions: 0,
      total_distributions: 1600000,
      remaining_after_tier: [],
    },
  ],
};

const UNAVAILABLE: PartnershipResult = {
  status: 'unavailable',
  unavailable_reason: 'common_equity_unavailable',
  unavailable_message: 'The Common Equity Cash Flow could not be produced.',
  upstream_reason: 'unresolved_funding_requirement',
  upstream_requirement_ids: ['req-mezz-1'],
  cadence: 'annual',
  promote_participant_ids: ['gp'],
  common_equity_cash_flows: null,
  common_equity_total_profit: null,
  partners: null,
  tiers: null,
  periods: null,
};

function analysis(result: PartnershipResult | null): PartnershipVariantAnalysis {
  return {
    investment_id: 'inv-1',
    strategy_id: 'base',
    scenario_id: 'base',
    root_kind: 'hidden_unit',
    unit_ids: ['deal-1'],
    hold_period: 5,
    partnership: PARTNERSHIP,
    partnership_source: 'base',
    project_source_fingerprint: 'p',
    structured_source_fingerprint: 's',
    partnership_source_fingerprint: 'w',
    project_cache_status: 'hit',
    result,
  };
}

function partnershipState(overrides: Partial<PartnershipState> = {}): PartnershipState {
  return {
    saved: null,
    draft: null,
    investmentId: null,
    listStatus: 'ready',
    loadError: null,
    isSaving: false,
    saveError: null,
    saveIssues: [],
    hasDraft: false,
    isDirtyDraft: false,
    analysis: null,
    analysisError: null,
    analysisIssues: [],
    isAnalyzing: false,
    isAnalysisCurrent: true,
    canSave: true,
    canAnalyze: true,
    edit: vi.fn(),
    add: vi.fn(),
    change: vi.fn(),
    cancel: vi.fn(),
    save: vi.fn(async () => {}),
    remove: vi.fn(async () => {}),
    analyze: vi.fn(async () => {}),
    retryLoad: vi.fn(),
    ...overrides,
  };
}

// =============================================================================
// The editor
// =============================================================================

describe('the Partnership editor states nothing the analyst has not', () => {
  function renderEditor(form: PartnershipForm, onChange = vi.fn()) {
    render(
      <PartnershipEditor
        id="editor"
        prefix="deal"
        form={form}
        onChange={onChange}
        issues={[]}
        locked={false}
        lockedReason={null}
      />,
    );
    return onChange;
  }

  it('offers “Choose…” for every required selection, selected by default', () => {
    renderEditor(formFromPartnership({ ...PARTNERSHIP, contribution_rule: 'pro_rata_by_commitment' }));
    // The contribution rule has exactly one member in v1 and is still a choice.
    const rule = screen.getByLabelText('Contribution Rule') as HTMLSelectElement;
    expect(within(rule).getByText(CHOOSE)).toBeTruthy();
  });

  it('starts a brand-new Partnership with every choice unstated', () => {
    renderEditor(EMPTY_PARTNERSHIP_FORM);
    const rule = screen.getByLabelText('Contribution Rule') as HTMLSelectElement;
    expect(rule.value).toBe('');
    expect(screen.getByText(UNSTATED_CHOICES_TITLE)).toBeTruthy();
    expect(screen.getAllByText(EDITOR_NO_PARTNERS_MESSAGE).length).toBeGreaterThan(0);
  });

  it('lists what is still unstated, in the analyst’s words', () => {
    renderEditor(EMPTY_PARTNERSHIP_FORM);
    expect(screen.getByText('Select a contribution rule.')).toBeTruthy();
    expect(
      screen.getByText(
        'Confirm which partners earn a promote. Select none if no partner is measured for one.',
      ),
    ).toBeTruthy();
  });

  it('requires the promote-participant confirmation as its own control', async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(formFromPartnership(PARTNERSHIP));
    const confirm = screen.getByLabelText(PROMOTE_CONFIRM_LABEL) as HTMLInputElement;
    expect(confirm.checked).toBe(true);
    await user.click(confirm);
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ promoteParticipantsConfirmed: false }),
    );
  });

  it('un-confirms the set when a participant is toggled', async () => {
    const user = userEvent.setup();
    const onChange = renderEditor(formFromPartnership(PARTNERSHIP));
    const participants = screen
      .getByRole('heading', { name: 'Promote Participants' })
      .closest('section') as HTMLElement;
    await user.click(within(participants).getByLabelText('Harbor Capital LP'));
    // The confirmation is of a specific answer, not a box that stays ticked
    // while the answer moves underneath it.
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        promoteParticipantIds: ['gp', 'lp'],
        promoteParticipantsConfirmed: false,
      }),
    );
  });

  it('offers a SIMPLE distribution order only while SIMPLE is chosen', async () => {
    const form = formFromPartnership(PARTNERSHIP);
    const { unmount } = render(
      <PartnershipEditor
        id="editor"
        prefix="deal"
        form={form}
        onChange={vi.fn()}
        issues={[]}
        locked={false}
        lockedReason={null}
      />,
    );
    expect(screen.getByLabelText('Distribution Order')).toBeTruthy();
    unmount();

    const compounding: PartnershipForm = {
      ...form,
      tiers: form.tiers.map((tier) =>
        tier.tierId === 'tier-1'
          ? {
              ...tier,
              conditions: tier.conditions.map((condition) => ({
                ...condition,
                accrualConvention: 'annual_compound' as const,
              })),
            }
          : tier,
      ),
    };
    render(
      <PartnershipEditor
        id="editor"
        prefix="deal"
        form={compounding}
        onChange={vi.fn()}
        issues={[]}
        locked={false}
        lockedReason={null}
      />,
    );
    // Forbidden on `annual_compound`, so it is not offered at all.
    expect(screen.queryByLabelText('Distribution Order')).toBeNull();
  });

  it('never offers an economic-account catch-up recipient', () => {
    const form = formFromPartnership(PARTNERSHIP);
    const catchUp: PartnershipForm = {
      ...form,
      tiers: form.tiers.map((tier) =>
        tier.tierId === 'tier-2'
          ? { ...tier, kind: 'catch_up' as const, splitRule: 'explicit' as const }
          : tier,
      ),
    };
    renderEditor(catchUp);
    const recipient = screen.getByLabelText('Catch-Up Recipient') as HTMLSelectElement;
    const options = within(recipient)
      .getAllByRole('option')
      .map((option) => (option as HTMLOptionElement).value);
    expect(options).toEqual(['', 'partner', 'investor_class']);
  });

  it('never offers a pro-rata split on a catch-up tier (R-D)', () => {
    const form = formFromPartnership(PARTNERSHIP);
    const catchUp: PartnershipForm = {
      ...form,
      tiers: form.tiers.map((tier) =>
        tier.tierId === 'tier-2' ? { ...tier, kind: 'catch_up' as const } : tier,
      ),
    };
    renderEditor(catchUp);
    const splits = screen.getAllByLabelText('Split Rule') as HTMLSelectElement[];
    const catchUpSplit = splits[splits.length - 1];
    const options = within(catchUpSplit)
      .getAllByRole('option')
      .map((option) => (option as HTMLOptionElement).value);
    expect(options).toEqual(['', 'explicit']);
  });

  it('shows a refusal against the partner or tier it names', () => {
    render(
      <PartnershipEditor
        id="editor"
        prefix="deal"
        form={formFromPartnership(PARTNERSHIP)}
        onChange={vi.fn()}
        issues={[
          {
            code: 'invalid_share',
            message: 'Commitment share must be between 0 and 1.',
            partner_id: 'lp',
            tier_id: null,
            field: 'commitment_share',
            period: null,
          },
        ]}
        locked={false}
        lockedReason={null}
      />,
    );
    expect(screen.getByText('Commitment share must be between 0 and 1.')).toBeTruthy();
  });
});

// =============================================================================
// The result surface
// =============================================================================

describe('the Partnership result surface shows only backend figures', () => {
  function renderResults(result: PartnershipResult) {
    render(
      <PartnershipResults result={result} partnerNames={PARTNER_NAMES} tierNames={TIER_NAMES} />,
    );
  }

  /** One partner's row inside the section a heading names. */
  function row(heading: string, partnerName: RegExp): HTMLElement {
    const section = screen
      .getByRole('heading', { name: heading })
      .closest('section') as HTMLElement;
    return within(section).getByRole('row', { name: partnerName });
  }

  it('prints the engine’s distribution difference, not one it derived', () => {
    renderResults(COMPLETE);
    // 1,300,000 - 1,200,000 would be 100,000. The engine said 77,000.
    const lp = row('Distribution Difference vs Benchmark', /Harbor Capital LP/);
    expect(within(lp).getByText('$77,000')).toBeTruthy();
    expect(within(lp).queryByText('$100,000')).toBeNull();
  });

  it('prints the engine’s advantage, not the positive part of the difference', () => {
    renderResults(COMPLETE);
    // max(77,000, 0) would be 77,000. The engine said 66,000 for the LP, so the
    // advantage column cannot be the difference column's positive part.
    const lp = row('Distribution Difference vs Benchmark', /Harbor Capital LP/);
    const advantage = lp.querySelector('[data-field="distribution_advantage"]') as HTMLElement;
    expect(advantage.textContent).toBe('$66,000');
  });

  it('prints the engine’s Promote Earned, not the profit difference', () => {
    renderResults(COMPLETE);
    // The GP's profit-distribution difference is 62,000; its Promote Earned is
    // 44,000. A surface that equated them would print the wrong one.
    const gp = row('Promote Earned', /Sponsor GP/);
    const promote = gp.querySelector('[data-field="promote_earned"]') as HTMLElement;
    expect(promote.textContent).toBe('$44,000');
    expect(promote.textContent).not.toBe('$62,000');
  });

  it('keeps advantage, Promote Earned and subordination under separate headings', () => {
    renderResults(COMPLETE);
    expect(screen.getByRole('heading', { name: 'Distribution Difference vs Benchmark' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Promote Earned' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Benchmark Capital Subordination' })).toBeTruthy();
    // The subordination figure is the engine's own, and is not a promote.
    expect(screen.getByText('$85,000')).toBeTruthy();
  });

  it("reports a non-participant's Promote Earned as N/A with the reason (R-E)", () => {
    renderResults(COMPLETE);
    const promoteTable = screen
      .getByRole('heading', { name: 'Promote Earned' })
      .closest('section') as HTMLElement;
    const lpRow = within(promoteTable).getByRole('row', { name: /Harbor Capital LP/ });
    expect(within(lpRow).getByText('N/A')).toBeTruthy();
    expect(
      within(lpRow).getByText(
        'Not applicable: this partner is not one of the stated promote participants.',
      ),
    ).toBeTruthy();
    // Never a zero.
    expect(within(lpRow).queryByText('$0')).toBeNull();
  });

  it('discloses a benchmark share that differs from the commitment (R-A)', () => {
    renderResults(COMPLETE);
    expect(screen.getAllByText(BENCHMARK_MISMATCH_NOTICE).length).toBeGreaterThan(0);
  });

  it('says nothing about a mismatch when the two agree', () => {
    const agreeing: PartnershipResult = {
      ...COMPLETE,
      partners: [partner({ partner_id: 'lp', benchmark_equals_commitment: true })],
    };
    renderResults(agreeing);
    expect(screen.queryByText(BENCHMARK_MISMATCH_NOTICE)).toBeNull();
  });

  it('reports an N/A MOIC and IRR with the engine’s reasons, never zero', () => {
    renderResults(COMPLETE);
    const returns = screen
      .getByRole('heading', { name: 'Partner Returns' })
      .closest('section') as HTMLElement;
    const row = within(returns).getByRole('row', { name: /Promote Vehicle/ });
    expect(
      within(row).getByText('MOIC is not reported because this partner contributed no capital.'),
    ).toBeTruthy();
    expect(
      within(row).getByText(
        'Partner IRR is not reported because the modeled cash flows do not begin with an investment.',
      ),
    ).toBeTruthy();
  });

  it('shows a signed per-tier promote attribution, negative tiers included', () => {
    renderResults(COMPLETE);
    const attribution = screen
      .getByRole('heading', { name: 'Promote Attribution by Tier' })
      .closest('section') as HTMLElement;
    // Only the partner total is floored at zero; a tier may be negative.
    expect(within(attribution).getByText('-$6,000')).toBeTruthy();
    expect(within(attribution).getByText('$50,000')).toBeTruthy();
  });

  it('shows the tier audit: applied shares, accounts and the Common Equity context', () => {
    renderResults(COMPLETE);
    expect(screen.getByRole('heading', { name: 'Tier Audit' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Common Equity Cash Flow' })).toBeTruthy();
    // The engine's derived Common Equity Total Profit, echoed.
    expect(screen.getByText('$600,000')).toBeTruthy();
    // A hurdle account row, by its own condition id.
    expect(screen.getByText('cond-1')).toBeTruthy();
    expect(screen.getByText('Accrued Return First')).toBeTruthy();
  });

  it('reports an unavailable Partnership honestly, with no partner figures', () => {
    renderResults(UNAVAILABLE);
    expect(screen.getByText('Partnership unavailable')).toBeTruthy();
    expect(screen.getByText('The Common Equity Cash Flow could not be produced.')).toBeTruthy();
    expect(
      screen.getByText(
        'The Common Equity Cash Flow is unavailable because a Funding Requirement is unresolved.',
      ),
    ).toBeTruthy();
    expect(screen.getByText('req-mezz-1')).toBeTruthy();
    // No zero-filled partner table.
    expect(screen.queryByRole('heading', { name: 'Partner Returns' })).toBeNull();
    expect(screen.queryByText('$0')).toBeNull();
  });
});

// =============================================================================
// The Risk view
// =============================================================================

describe('the Partnership Risk view is opt-in and honest about staleness', () => {
  it('shows an empty state and Add Partnership before one exists', () => {
    render(
      <PartnershipWorkspace
        state={partnershipState()}
        prefix=""
        blockedReason={null}
        isInvestment={false}
      />,
    );
    expect(screen.getByText(NO_PARTNERSHIP_MESSAGE)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Add Partnership' })).toBeTruthy();
    // No waterfall controls nobody asked for.
    expect(screen.queryByLabelText('Contribution Rule')).toBeNull();
  });

  it('opens a blank editor from Add, and the saved one from Edit', async () => {
    const user = userEvent.setup();
    const add = vi.fn();
    render(
      <PartnershipWorkspace
        state={partnershipState({ add })}
        prefix=""
        blockedReason={null}
        isInvestment={false}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Add Partnership' }));
    expect(add).toHaveBeenCalled();

    cleanup();
    const edit = vi.fn();
    render(
      <PartnershipWorkspace
        state={partnershipState({ saved: PARTNERSHIP, edit })}
        prefix=""
        blockedReason={null}
        isInvestment={false}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Edit Partnership' }));
    expect(edit).toHaveBeenCalled();
  });

  it('lists the saved partners and tiers, and who earns a promote', () => {
    render(
      <PartnershipWorkspace
        state={partnershipState({ saved: PARTNERSHIP })}
        prefix=""
        blockedReason={null}
        isInvestment={false}
      />,
    );
    const partners = screen.getByLabelText('Saved partners');
    expect(within(partners).getByText('Harbor Capital LP')).toBeTruthy();
    expect(within(partners).getByText('Promote participant')).toBeTruthy();
    expect(within(partners).getByText('No promote')).toBeTruthy();
    const tiers = screen.getByLabelText('Saved waterfall tiers');
    expect(within(tiers).getByText('Preferred Return')).toBeTruthy();
  });

  it('will not analyse before a Partnership is saved (FP-2)', () => {
    render(
      <PartnershipWorkspace
        state={partnershipState({ canAnalyze: false })}
        prefix=""
        blockedReason={null}
        isInvestment={false}
      />,
    );
    expect(screen.getByText(ANALYSIS_ABSENT_MESSAGE)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Run Analysis' }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it('keeps a stale analysis on screen and labels it out of date', () => {
    render(
      <PartnershipWorkspace
        state={partnershipState({
          saved: PARTNERSHIP,
          analysis: analysis(COMPLETE),
          isAnalysisCurrent: false,
        })}
        prefix=""
        blockedReason={null}
        isInvestment={false}
      />,
    );
    expect(screen.getByText(STALE_LABEL)).toBeTruthy();
    expect(screen.getByText(STALE_PARTNERSHIP_MESSAGE)).toBeTruthy();
    // Real work against real saved inputs: it is kept, not discarded.
    expect(screen.getByRole('heading', { name: 'Partner Returns' })).toBeTruthy();
  });

  it('says nothing about staleness while the analysis is current', () => {
    render(
      <PartnershipWorkspace
        state={partnershipState({
          saved: PARTNERSHIP,
          analysis: analysis(COMPLETE),
          isAnalysisCurrent: true,
        })}
        prefix=""
        blockedReason={null}
        isInvestment={false}
      />,
    );
    expect(screen.queryByText(STALE_LABEL)).toBeNull();
  });

  it('blocks editing while the base underwriting has unsaved changes', () => {
    render(
      <PartnershipWorkspace
        state={partnershipState({ saved: PARTNERSHIP })}
        prefix=""
        blockedReason="Save the deal first."
        isInvestment={false}
      />,
    );
    expect(screen.getByText('Save the deal first.')).toBeTruthy();
    expect(
      (screen.getByRole('button', { name: 'Edit Partnership' }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it('namespaces its element ids so a Deal and an Investment never collide', () => {
    const { container: dealRoot } = render(
      <PartnershipWorkspace
        state={partnershipState({ saved: PARTNERSHIP, hasDraft: true, draft: formFromPartnership(PARTNERSHIP) })}
        prefix=""
        blockedReason={null}
        isInvestment={false}
      />,
    );
    const { container: investmentRoot } = render(
      <PartnershipWorkspace
        state={partnershipState({ saved: PARTNERSHIP, hasDraft: true, draft: formFromPartnership(PARTNERSHIP) })}
        prefix="investment-"
        blockedReason={null}
        isInvestment
      />,
    );
    const ids = (root: HTMLElement) =>
      [...root.querySelectorAll('[id]')].map((node) => node.id).filter((id) => id !== '');
    const dealIds = ids(dealRoot);
    const investmentIds = ids(investmentRoot);
    expect(dealIds.length).toBeGreaterThan(0);
    // Both workspaces stay mounted together, so not one id may be shared.
    expect(dealIds.filter((id) => investmentIds.includes(id))).toEqual([]);
    expect(investmentIds.every((id) => id.startsWith('investment-'))).toBe(true);
  });
});

// =============================================================================
// The Strategy domain: inherit, replace, explicitly none
// =============================================================================

describe('a Strategy states the Partnership domain in three distinct ways', () => {
  function draftWith(partnership: StrategyEditorDraft['partnership']): StrategyEditorDraft {
    return { ...blankStrategyDraft(['deal-1']), name: 'Alternative', partnership };
  }

  function builtDraft(editor: StrategyEditorDraft) {
    const built = buildStrategyRequest(editor);
    if ('feedback' in built) {
      throw new Error(`refused: ${JSON.stringify(built.feedback)}`);
    }
    return built.draft;
  }

  it('sends no overlay to inherit the Base Partnership', () => {
    const draft = builtDraft(
      draftWith({ choice: 'inherit', form: EMPTY_PARTNERSHIP_FORM }),
    );
    expect(draft.root_overlays).toBeUndefined();
  });

  it('sends a null content for the explicit “no Partnership”', () => {
    const draft = builtDraft(draftWith({ choice: 'none', form: EMPTY_PARTNERSHIP_FORM }));
    expect(draft.root_overlays).toEqual([{ domain: 'partnership', content: null }]);
  });

  it('sends the whole authored Partnership for a replacement', () => {
    const draft = builtDraft(
      draftWith({ choice: 'specific', form: formFromPartnership(PARTNERSHIP) }),
    );
    expect(draft.root_overlays).toEqual([{ domain: 'partnership', content: PARTNERSHIP }]);
  });

  it('reads all three states back from a saved Strategy', () => {
    const record = (overlays: unknown) => ({
      investment_id: 'inv-1',
      strategy: {
        strategy_id: 's1',
        name: 'Alternative',
        description: null,
        overlays: [],
        ...(overlays === undefined ? {} : { root_overlays: overlays }),
      },
      created_at: '',
      updated_at: '',
    });

    const inherit = draftFromStrategy(
      record(undefined) as never,
      ['deal-1'],
      () => 'k',
    );
    expect(inherit.partnership.choice).toBe('inherit');

    const none = draftFromStrategy(
      record([{ domain: 'partnership', content: null }]) as never,
      ['deal-1'],
      () => 'k',
    );
    expect(none.partnership.choice).toBe('none');

    const specific = draftFromStrategy(
      record([{ domain: 'partnership', content: PARTNERSHIP }]) as never,
      ['deal-1'],
      () => 'k',
    );
    expect(specific.partnership.choice).toBe('specific');
    // Reopened with every stable id kept, so the Partner matrix still compares
    // the same partner (P-8).
    expect(specific.partnership.form.partners.map((p) => p.partnerId)).toEqual(['lp', 'gp']);
  });

  it('counts a stated Partnership domain as economic content', () => {
    expect(
      draftHasEconomicContent(draftWith({ choice: 'inherit', form: EMPTY_PARTNERSHIP_FORM })),
    ).toBe(false);
    // Deliberately having no partnership is a real decision that resolves
    // differently from Base.
    expect(
      draftHasEconomicContent(draftWith({ choice: 'none', form: EMPTY_PARTNERSHIP_FORM })),
    ).toBe(true);
  });
});

// =============================================================================
// Unsaved drafts
// =============================================================================

describe('an open Partnership editor is an unsaved draft', () => {
  it('warns before leaving, beside the other decision drafts', () => {
    expect(
      investmentLeaveWarning({
        details: false,
        strategyDraft: false,
        scenarioDraft: false,
        partnershipDraft: true,
      }),
    ).toBe('You have an unsaved Partnership draft. Leaving will discard it.');

    expect(
      investmentLeaveWarning({
        details: false,
        strategyDraft: true,
        scenarioDraft: false,
        capitalStructureDraft: true,
        partnershipDraft: true,
      }),
    ).toBe(
      'You have an unsaved Strategy draft, an unsaved Capital Structure draft and an unsaved Partnership draft. Leaving will discard them.',
    );
  });

  it('says nothing when no draft is open', () => {
    expect(
      investmentLeaveWarning({
        details: false,
        strategyDraft: false,
        scenarioDraft: false,
        partnershipDraft: false,
      }),
    ).toBeNull();
  });
});
