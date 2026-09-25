/**
 * Refinance & Capital Events V1 Stage 3 -- the refinance surfaces, driven
 * directly.
 *
 * The editor keeps its draft in the caller's form, so a small stateful harness
 * stands in for the Capital Structure hook. The results surface takes the
 * backend's result as a prop.
 *
 * **The result fixture is deliberately not internally consistent**, as in
 * `capitalStructureUi.test.tsx`: its net event cash is not gross proceeds less
 * payoff and costs, and its Common Equity total row is not recurring plus event
 * cash. A surface that re-derived either would print a different string and
 * fail here (P-3, P-5; contract Section 12.5).
 */

import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  CapitalEventEditor,
  LTV_BASIS_NOTE,
  NO_REFINANCE_MESSAGE,
  NO_VALUATION_MESSAGE,
} from './components/CapitalEventEditor';
import { CapitalEventResults } from './components/CapitalEventResults';
import { ResultsSummaryPanel } from './components/ResultsSummaryPanel';
import { LiveCaseRail } from './components/LiveCaseRail';
import {
  REFERENCE_CHECKING_NOTICE,
  REFERENCE_CHECKING_VALUE,
  REFERENCE_ERROR_NOTICE,
  REFERENCE_WITHHELD_VALUE,
  REFINANCE_REFERENCE_NOTICE,
} from './components/AcquisitionReference';
import { AcquisitionReferenceContext } from './useRefinancePresence';
import {
  ACQUISITION_REFERENCE_LABEL,
  DIRECTION_HEADINGS,
  magnitudeText,
} from './refinanceCatalog';
import { EMPTY_FORM } from './capitalStructureForm';
import type { CapitalStructureForm } from './capitalStructureForm';
import {
  capitalEventsOf,
  eventMonthOfYear,
  formEvents,
  newCapitalEvent,
  withLtvEnabled,
} from './capitalEventForm';
import type {
  PrimaryReturnView,
  RefinanceResult,
  StructuredCapitalResult,
} from './capitalTypes';
import type { AcquisitionResults } from './types';

afterEach(cleanup);

const UNIT = 'deal-a';
const UNITS = [{ unitId: UNIT, name: 'Harbor Point' }];

// =============================================================================
// The editor
// =============================================================================

function Harness({ initial, onChange }: { initial: CapitalStructureForm; onChange: (form: CapitalStructureForm) => void }) {
  const [form, setForm] = useState(initial);
  return (
    <CapitalEventEditor
      prefix="t"
      form={form}
      onChange={(next) => {
        onChange(next);
        setForm(next);
      }}
      issues={[]}
      locked={false}
      units={UNITS}
      valuationOwnerId={null}
    />
  );
}

function editor(initial: CapitalStructureForm = EMPTY_FORM) {
  const onChange = vi.fn<(form: CapitalStructureForm) => void>();
  render(<Harness initial={initial} onChange={onChange} />);
  return () => onChange.mock.calls.at(-1)?.[0] as CapitalStructureForm;
}

describe('the refinance editor states what the analyst chose', () => {
  it('says there is no refinance until one is added', () => {
    editor();
    expect(screen.getByText(NO_REFINANCE_MESSAGE)).toBeTruthy();
  });

  it('adds a refinance with no timing, sizing or replacement invented', async () => {
    const user = userEvent.setup();
    const latest = editor();

    await user.click(screen.getByRole('button', { name: 'Add Refinance' }));

    const [event] = formEvents(latest());
    expect(event.year).toBe('');
    expect(event.replacementPositionId).toBe('');
    expect(event.fixedCapEnabled || event.ltvEnabled || event.dscrEnabled).toBe(false);
    expect(within(screen.getByLabelText('Timing')).getByText('Choose…')).toBeTruthy();
    // Every choice the backend would refuse is named before the round trip.
    expect(screen.getByText('State these before saving:')).toBeTruthy();
  });

  it('offers timing as the end of a hold year and stores the model month', async () => {
    const user = userEvent.setup();
    const latest = editor();
    await user.click(screen.getByRole('button', { name: 'Add Refinance' }));

    await user.selectOptions(screen.getByLabelText('Timing'), '2');

    expect(within(screen.getByLabelText('Timing')).getByText('End of Year 2')).toBeTruthy();
    expect(formEvents(latest())[0].year).toBe('2');
    expect(eventMonthOfYear(2)).toBe(24);
  });

  it('adds the replacement as an ordinary loan funded by this refinance', async () => {
    const user = userEvent.setup();
    const latest = editor();
    await user.click(screen.getByRole('button', { name: 'Add Refinance' }));

    await user.click(screen.getByRole('button', { name: 'Add Replacement Loan' }));

    const form = latest();
    const [event] = formEvents(form);
    const replacement = form.positions.find((position) => position.positionId === event.replacementPositionId);
    expect(replacement?.positionClass).toBe('senior_debt');
    expect(replacement?.fundingKind).toBe('capital_event');
  });

  it('shows the valuation choice only inside an enabled LTV constraint', async () => {
    const user = userEvent.setup();
    editor();
    await user.click(screen.getByRole('button', { name: 'Add Refinance' }));
    expect(screen.queryByLabelText('Valuation')).toBeNull();

    await user.click(screen.getByRole('checkbox', { name: 'Maximum LTV' }));

    // A Deal with no Investment has no valuation to reference: said, not
    // filled with the purchase price or any other value.
    const valuation = screen.getByLabelText('Valuation') as HTMLSelectElement;
    expect(valuation.value).toBe('');
    expect(valuation.disabled).toBe(true);
    expect(screen.getByText(NO_VALUATION_MESSAGE)).toBeTruthy();
    expect(screen.queryByText(LTV_BASIS_NOTE)).toBeNull();
  });

  it('forgets the valuation when LTV is switched off', () => {
    const event = { ...withLtvEnabled(newCapitalEvent([], { kind: 'unit', unitId: UNIT }), true), maxLtv: '65', timepointId: 'value-1' };

    const off = withLtvEnabled(event, false);

    expect(off.timepointId).toBe('');
    expect(off.maxLtv).toBe('');
  });

  it('confirms removal, removes the replacement with it, and returns focus to Add', async () => {
    const user = userEvent.setup();
    const latest = editor();
    await user.click(screen.getByRole('button', { name: 'Add Refinance' }));
    await user.click(screen.getByRole('button', { name: 'Add Replacement Loan' }));
    const name = formEvents(latest())[0].label;

    await user.click(screen.getByRole('button', { name: `Remove ${name}` }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Remove Refinance' }));

    expect(formEvents(latest())).toEqual([]);
    expect(latest().positions).toEqual([]);
    expect(capitalEventsOf(latest())).toBeUndefined();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Add Refinance' }));
  });

  it('keeps the refinance when removal is cancelled', async () => {
    const user = userEvent.setup();
    const latest = editor();
    await user.click(screen.getByRole('button', { name: 'Add Refinance' }));
    const name = formEvents(latest())[0].label;

    await user.click(screen.getByRole('button', { name: `Remove ${name}` }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));

    expect(formEvents(latest())).toHaveLength(1);
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

// =============================================================================
// The result surface
// =============================================================================

const SCOPE = { kind: 'unit' as const, unit_id: UNIT };

function executed(overrides: Partial<RefinanceResult['bridge'] & object> = {}): RefinanceResult {
  return {
    event_id: 'refi-year-2',
    kind: 'refinance',
    label: 'Year-2 refinance',
    scope: SCOPE,
    model_month: 24,
    hold_year: 2,
    status: 'executed',
    value_dependency: null,
    noi_dependency: { scope: SCOPE, model_month: 24, forward_year: 3, status: 'available', forward_noi: 800_000 },
    sizing: {
      capacities: [
        {
          kind: 'min_dscr',
          status: 'available',
          capacity: 8_000_000,
          operands: {
            min_dscr: 2,
            forward_noi: 800_000,
            continuing_senior_service: 0,
            service_capacity: 400_000,
            first_year_service_per_dollar: 0.05,
          },
          unavailable_reason: null,
          unavailable_message: null,
        },
      ],
      gross_proceeds: 8_000_000,
      binding: ['min_dscr'],
      tie: false,
    },
    payoffs: [
      {
        ref: { kind: 'legacy_acquisition_loan', unit_id: UNIT },
        position_id: `legacy-acquisition-loan:${UNIT}`,
        scheduled_payment_at_m: 20_000,
        payoff: 5_520_000,
        payoff_authority: 'acquisition_debt_balance_service',
        retiring_lender_fees: 0,
        provider_cash_flows: [-6_000_000, 240_000, 5_760_000, 0, 0, 0],
      },
    ],
    funding: {
      position_id: 'refi-loan',
      funding_month: 24,
      gross_proceeds: 8_000_000,
      replacement_lender_fees: 80_000,
      first_service_month: 25,
      first_year_service: 400_000,
      achieved_ltv: null,
      achieved_dscr: 2,
    },
    bridge: {
      gross_proceeds: 8_000_000,
      payoffs: 5_520_000,
      replacement_lender_fees: 80_000,
      retiring_lender_fees: 0,
      third_party_costs: 40_000,
      // Deliberately not 8,000,000 - 5,520,000 - 80,000 - 40,000.
      net_event_cash: 2_345_678,
      direction: 'distribution',
      ...overrides,
    },
    unavailable_reason: null,
    unavailable_message: null,
  } as RefinanceResult;
}

function unexecuted(): RefinanceResult {
  return {
    ...executed(),
    status: 'unavailable',
    sizing: null,
    payoffs: null,
    funding: null,
    bridge: null,
    unavailable_reason: 'timepoint_not_found',
    // The engine's own message carries its identity-shaped wording; the
    // surface must word the typed reason itself.
    unavailable_message: "'refi-year-2' timepoint year-2-value missing",
  };
}

function structured(events: RefinanceResult[], common: Partial<StructuredCapitalResult['common_equity']> = {}) {
  return {
    analysis_scope: SCOPE,
    unit_ids: [UNIT],
    hold_period: 5,
    status: 'complete',
    legacy_acquisition_loans: [],
    positions: [],
    funding_requirements: [],
    common_equity: {
      position_id: null,
      scope: SCOPE,
      status: 'complete',
      // Deliberately not recurring + event, year by year.
      cash_flows: [-4_000_000, 560_000, 2_999_999, 400_000, 400_000, 4_900_000],
      unavailable_reason: null,
      unavailable_message: null,
      irr: 0.2785,
      irr_status: 'defined',
      equity_multiple: 2.3,
      total_equity_invested: 4_000_000,
      total_cash_returned: 9_180_000,
      total_profit: 5_180_000,
      recurring_cash_flows: [-4_000_000, 560_000, 560_000, 400_000, 400_000, 4_900_000],
      event_cash_flows: [0, 0, 1_111_111, 0, 0, 0],
      ...common,
    },
    capital_events: events,
    unexecuted_positions: [],
  } as unknown as StructuredCapitalResult;
}

const PRIMARY: PrimaryReturnView = {
  primary_equity_namespace: 'common_equity_after_capital_structure',
  primary_investor_namespace: null,
  reference_namespace: 'acquisition_financing_reference',
  reference_excludes_capital_events: true,
  status: 'available',
  unavailable_reason: null,
  unavailable_message: null,
  capital_event_ids: ['refi-year-2'],
  executed_event_ids: ['refi-year-2'],
} as PrimaryReturnView;

function results(result: StructuredCapitalResult) {
  render(
    <CapitalEventResults
      result={result}
      primaryReturn={PRIMARY}
      unitNames={{ [UNIT]: 'Harbor Point' }}
      valuationLabels={{}}
    />,
  );
}

describe('the refinance result reports the engine’s figures and derives none', () => {
  it('prints the net event cash exactly, under a heading that says which way it moved', () => {
    results(structured([executed()]));

    expect(screen.getByTestId('refinance-net-cash').textContent).toBe('$2,345,678');
    expect(screen.getByText(DIRECTION_HEADINGS.distribution)).toBeTruthy();
  });

  it('prints a contribution as a magnitude under the contribution heading', () => {
    results(structured([executed({ net_event_cash: -640_000, direction: 'contribution' })]));

    expect(screen.getByTestId('refinance-net-cash').textContent).toBe('$640,000');
    expect(screen.getByText(DIRECTION_HEADINGS.contribution)).toBeTruthy();
    expect(magnitudeText(-640_000)).toBe('$640,000');
  });

  it('prints each Common Equity row as the engine reported it', () => {
    results(structured([executed()]));

    // The fixture's total is not recurring + event; the backend's total wins.
    expect(screen.getAllByText('$2,999,999').length).toBeGreaterThan(0);
    expect(screen.getAllByText('$1,111,111').length).toBeGreaterThan(0);
    expect(screen.queryByText('$1,671,111')).toBeNull();
  });

  it('shows an unexecuted refinance as N/A with its reason in the analyst’s words', () => {
    results(structured([unexecuted()], { cash_flows: null, recurring_cash_flows: null, event_cash_flows: null, irr: null, irr_status: null }));

    expect(screen.getByTestId('refinance-net-cash').textContent).toBe('N/A');
    const text = document.body.textContent ?? '';
    expect(text).toContain('no longer exists');
    for (const identity of ['refi-year-2', 'year-2-value', 'legacy_acquisition_loan', 'timepoint_not_found']) {
      expect(text).not.toContain(identity);
    }
    expect(text).not.toContain('$0');
  });
});

// =============================================================================
// The acquisition-financing reference on existing surfaces
// =============================================================================

function acquisitionResults(): AcquisitionResults {
  return {
    going_in_cap_rate: 0.08,
    loan_amount: 6_000_000,
    acquisition_costs: 0,
    financing_fee: 0,
    initial_equity: 4_000_000,
    monthly_debt_service: 20_000,
    annual_debt_service: [240_000, 240_000, 240_000, 240_000, 240_000],
    remaining_loan_balance: 4_800_000,
    noi_by_year: [800_000, 800_000, 800_000, 800_000, 800_000],
    capex_by_year: [0, 0, 0, 0, 0],
    exit_noi: 800_000,
    exit_value: 12_500_000,
    disposition_costs: 0,
    net_sale_proceeds: 7_700_000,
    unlevered_cash_flows: [-10_000_000, 800_000, 800_000, 800_000, 800_000, 13_300_000],
    levered_cash_flows: [-4_000_000, 560_000, 560_000, 560_000, 560_000, 8_260_000],
    unlevered_irr: 0.1194,
    levered_irr: 0.2522,
    equity_multiple: 2.62,
    dscr_by_year: [3.33, 3.33, 3.33, 3.33, 3.33],
    headline_dscr: 3.33,
    min_dscr: 3.33,
    levered_cash_on_cash_by_year: [0.14, 0.14, 0.14, 0.14, 0.14],
    unlevered_cash_yield_by_year: [0.08, 0.08, 0.08, 0.08, 0.08],
    cumulative_operating_distributions_by_year: [560_000, 1_120_000, 1_680_000, 2_240_000, 2_800_000],
    year_1_debt_yield: 0.1333,
    tenant_improvements_by_year: [0, 0, 0, 0, 0],
    leasing_commissions_by_year: [0, 0, 0, 0, 0],
    closing_project_capital: 0,
    project_capital_by_year: [0, 0, 0, 0, 0],
    post_hold_project_capital: 0,
    owner_expenses_by_year: [0, 0, 0, 0, 0],
    property_cash_flow_by_year: [800_000, 800_000, 800_000, 800_000, 800_000],
    unlevered_owner_cash_flow_by_year: [800_000, 800_000, 800_000, 800_000, 800_000],
    levered_owner_cash_flow_by_year: [560_000, 560_000, 560_000, 560_000, 560_000],
    total_closing_uses: 10_000_000,
    total_closing_sources: 10_000_000,
    net_additional_equity_requirement_by_year: [0, 0, 0, 0, 0],
    total_equity_invested: 4_000_000,
    total_cash_returned: 10_500_000,
    total_profit: 6_500_000,
    unlevered_irr_status: 'defined',
    levered_irr_status: 'defined',
  } as AcquisitionResults;
}

describe('an existing results surface names the acquisition-financing reference', () => {
  it('labels the levered figures only when a refinance is configured', () => {
    const { rerender } = render(
      <AcquisitionReferenceContext.Provider value={{ status: 'ready', configured: false }}>
        <ResultsSummaryPanel results={acquisitionResults()} />
      </AcquisitionReferenceContext.Provider>,
    );
    // A settled "no refinance" keeps the accepted presentation exactly.
    expect(screen.queryByText(ACQUISITION_REFERENCE_LABEL)).toBeNull();
    expect(screen.queryByText(REFINANCE_REFERENCE_NOTICE)).toBeNull();
    expect(screen.getByText('25.22%')).toBeTruthy();
    expect(screen.getByText('2.62x')).toBeTruthy();

    rerender(
      <AcquisitionReferenceContext.Provider value={{ status: 'ready', configured: true }}>
        <ResultsSummaryPanel results={acquisitionResults()} />
      </AcquisitionReferenceContext.Provider>,
    );
    expect(screen.getAllByText(ACQUISITION_REFERENCE_LABEL)).toHaveLength(2);
    expect(screen.getByText(REFINANCE_REFERENCE_NOTICE)).toBeTruthy();
    // The figure itself is unchanged: labeled, never recomputed.
    expect(screen.getByText('25.22%')).toBeTruthy();
  });

  it('withholds the levered figures while presence is being read', () => {
    render(
      <AcquisitionReferenceContext.Provider value={{ status: 'loading' }}>
        <ResultsSummaryPanel results={acquisitionResults()} />
      </AcquisitionReferenceContext.Provider>,
    );

    expect(screen.queryByText('25.22%')).toBeNull();
    expect(screen.queryByText('2.62x')).toBeNull();
    expect(screen.getAllByText(REFERENCE_CHECKING_VALUE)).toHaveLength(2);
    expect(screen.getByRole('status').textContent).toBe(REFERENCE_CHECKING_NOTICE);
    // Figures that no refinance changes are shown as always.
    expect(screen.getByText('8.00%')).toBeTruthy();
  });

  it('withholds them after a failed read, says so, and retries', async () => {
    const user = userEvent.setup();
    const retry = vi.fn();
    render(
      <AcquisitionReferenceContext.Provider value={{ status: 'error', retry }}>
        <ResultsSummaryPanel results={acquisitionResults()} />
      </AcquisitionReferenceContext.Provider>,
    );

    expect(screen.queryByText('25.22%')).toBeNull();
    expect(screen.queryByText('2.62x')).toBeNull();
    expect(screen.getAllByText(REFERENCE_WITHHELD_VALUE)).toHaveLength(2);
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain(REFERENCE_ERROR_NOTICE);
    await user.click(within(alert).getByRole('button', { name: 'Retry' }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
});

describe('the Underwrite Live Case rail names or withholds the reference (correction round)', () => {
  function rail(value: Parameters<typeof AcquisitionReferenceContext.Provider>[0]['value']) {
    render(
      <AcquisitionReferenceContext.Provider value={value}>
        <LiveCaseRail results={acquisitionResults()} tab="results" />
      </AcquisitionReferenceContext.Provider>,
    );
    return screen.getByRole('complementary', { name: 'Live case metrics' });
  }

  it('withholds the levered IRR and equity multiple while presence is being read', () => {
    const aside = rail({ status: 'loading' });

    expect(within(aside).queryByText('25.22%')).toBeNull();
    expect(within(aside).queryByText('2.62x')).toBeNull();
    expect(within(aside).getAllByText(REFERENCE_CHECKING_VALUE)).toHaveLength(2);
  });

  it('withholds them after a failed read', () => {
    const aside = rail({ status: 'error', retry: vi.fn() });

    expect(within(aside).queryByText('25.22%')).toBeNull();
    expect(within(aside).getAllByText(REFERENCE_WITHHELD_VALUE)).toHaveLength(2);
  });

  it('labels them when a refinance is configured', () => {
    const aside = rail({ status: 'ready', configured: true });

    expect(within(aside).getByText('25.22%')).toBeTruthy();
    expect(within(aside).getAllByText(ACQUISITION_REFERENCE_LABEL)).toHaveLength(2);
  });

  it('shows them exactly as before when no refinance is configured', () => {
    const aside = rail({ status: 'ready', configured: false });

    expect(within(aside).getByText('25.22%')).toBeTruthy();
    expect(within(aside).getByText('2.62x')).toBeTruthy();
    expect(within(aside).queryByText(ACQUISITION_REFERENCE_LABEL)).toBeNull();
  });
});
