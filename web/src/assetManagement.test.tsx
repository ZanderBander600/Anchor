/** Gate AM1 -- the Asset Management product surface.
 *
 * `docs/architecture/AM1_MANAGED_ASSETS_MONTHLY_PERFORMANCE.md` Section 7. The
 * claims that matter: the authorized figures reach the screen unchanged, the
 * frozen budget is visibly locked after creation, assessments are words and not
 * only colour, and no acquisition control is reachable from inside Asset
 * Management.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AssetManagementShell } from './components/AssetManagementShell';
import { CreateManagedAssetPanel } from './components/CreateManagedAssetPanel';
import { MonthlyPerformancePanel } from './components/MonthlyPerformancePanel';
import { MonthlyReportEditor } from './components/MonthlyReportEditor';
import { ManagedAssetWorkspace } from './components/ManagedAssetWorkspace';
import { NoiTrendChart } from './components/NoiTrendChart';
import {
  DEMO_ASSET,
  DEMO_BUDGET,
  DEMO_COMMENTARY,
  DEMO_PERFORMANCE,
  DEMO_REPORT,
} from './assetManagementFixture';
import {
  formatMoney,
  formatMonth,
  formatPoints,
  formatRate,
  formatVariancePct,
} from './assetManagementFormat';
import type { AssetPerformanceResponse } from './assetManagementTypes';
import type { AssetPerformanceState } from './useManagedAssets';

// The repository's convention: Testing Library does not auto-clean here, and a
// leaked render makes every later query ambiguous.
afterEach(cleanup);

function performanceState(overrides: Partial<AssetPerformanceState> = {}): AssetPerformanceState {
  return {
    reports: [DEMO_REPORT],
    reportsStatus: 'ready',
    performance: DEMO_PERFORMANCE,
    performanceStatus: 'ready',
    selectedMonth: '2027-03-01',
    error: null,
    selectMonth: vi.fn(),
    reload: vi.fn(),
    saveReport: vi.fn().mockResolvedValue(undefined),
    saveActuals: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

/** The cells of the statement row for `label`. */
function statementRow(label: string): string[] {
  const row = screen.getByRole('row', { name: new RegExp(`^${label}`) });
  return within(row)
    .getAllByRole('cell')
    .map((cell) => cell.textContent ?? '');
}

// ===========================================================================
// Formatting
// ===========================================================================

describe('Asset Management formatting', () => {
  it('renders an unavailable value as an em dash, never as zero', () => {
    expect(formatMoney(null)).toBe('—');
    expect(formatVariancePct(null)).toBe('—');
    expect(formatPoints(null)).toBe('—');
    expect(formatRate(null)).toBe('—');
  });

  it('uses accounting parentheses for negative figures', () => {
    expect(formatMoney(-5500)).toBe('($5,500)');
    expect(formatMoney(24500)).toBe('$24,500');
    expect(formatVariancePct(-0.08208955223880597)).toBe('(8.2%)');
    expect(formatPoints(-2.4999999999999911)).toBe('(2.5 pts)');
  });

  it('renders a month without applying the viewer timezone', () => {
    // `new Date("2027-03-01")` is UTC midnight, which is February 28th for
    // anyone west of UTC. The month label must not depend on where you are.
    expect(formatMonth('2027-03-01')).toBe('March 2027');
    expect(formatMonth('2027-01-01')).toBe('January 2027');
  });
});

// ===========================================================================
// The monthly statement
// ===========================================================================

describe('Monthly Performance', () => {
  const renderPanel = (view: 'monthly' | 'year_to_date' = 'monthly') =>
    render(
      <MonthlyPerformancePanel
        performance={DEMO_PERFORMANCE}
        view={view}
        onViewChange={vi.fn()}
        onEditActuals={vi.fn()}
      />,
    );

  it('shows the four authorized summary cards with their plan figures', () => {
    renderPanel();
    const noi = screen.getByRole('region', { name: 'Net Operating Income' });
    expect(within(noi).getByText('$61,500')).toBeTruthy();
    expect(within(noi).getByText('Budget $67,000')).toBeTruthy();

    const occupancy = screen.getByRole('region', { name: 'Occupancy' });
    expect(within(occupancy).getByText('92.5%')).toBeTruthy();
    expect(within(occupancy).getByText('Plan 95.0%')).toBeTruthy();

    const expenses = screen.getByRole('region', { name: 'Operating Expenses' });
    expect(within(expenses).getByText('$41,000')).toBeTruthy();
    expect(within(expenses).getByText('Budget $38,000')).toBeTruthy();

    const cashFlow = screen.getByRole('region', { name: 'Net Cash Flow' });
    expect(within(cashFlow).getByText('$19,000')).toBeTruthy();
    expect(within(cashFlow).getByText('Budget $24,500')).toBeTruthy();
  });

  it('renders the authorized NOI row exactly', () => {
    renderPanel();
    expect(statementRow('Net Operating Income')).toEqual([
      '$67,000',
      '$61,500',
      '($5,500)',
      '(8.2%)',
      'Unfavorable',
    ]);
  });

  it('renders the authorized revenue and expense totals', () => {
    renderPanel();
    expect(statementRow('Total Revenue')).toEqual([
      '$105,000',
      '$102,500',
      '($2,500)',
      '(2.4%)',
      'Unfavorable',
    ]);
    expect(statementRow('Total Operating Expenses')).toEqual([
      '$38,000',
      '$41,000',
      '$3,000',
      '7.9%',
      'Unfavorable',
    ]);
    expect(statementRow('Net Cash Flow')).toEqual([
      '$24,500',
      '$19,000',
      '($5,500)',
      '(22.4%)',
      'Unfavorable',
    ]);
  });

  it('reports occupancy in percentage points', () => {
    renderPanel();
    expect(statementRow('Occupancy')).toEqual([
      '95.0%',
      '92.5%',
      '(2.5 pts)',
      '(2.6%)',
      'Unfavorable',
    ]);
  });

  it('shows CapEx and debt service as neutral, never as favorable', () => {
    renderPanel();
    expect(statementRow('Capital Expenditures')[4]).toBe('Neutral');
    expect(statementRow('Debt Service')[4]).toBe('Neutral');
    expect(statementRow('Cash Flow After CapEx')[4]).toBe('Neutral');
  });

  it('states every assessment in words, not only in colour', () => {
    renderPanel();
    // Each assessment cell carries its word; the colour class is reinforcement.
    for (const word of ['Unfavorable', 'Favorable', 'On Plan', 'Neutral']) {
      expect(screen.getAllByText(word).length).toBeGreaterThan(0);
    }
  });

  it('says only "On plan" when occupancy lands exactly on plan', () => {
    // "0.0 pts below plan" asserts a direction that does not exist, and
    // contradicted the "On Plan" verdict printed beside it.
    const onPlan: AssetPerformanceResponse = {
      ...DEMO_PERFORMANCE,
      result: {
        ...DEMO_PERFORMANCE.result,
        monthly: {
          ...DEMO_PERFORMANCE.result.monthly,
          lines: DEMO_PERFORMANCE.result.monthly.lines.map((line) =>
            line.line === 'occupancy'
              ? {
                  ...line,
                  actual: line.budget,
                  variance: 0,
                  variance_pct: 0,
                  variance_points: 0,
                  assessment: 'on_plan' as const,
                }
              : line,
          ),
        },
      },
    };
    render(
      <MonthlyPerformancePanel
        performance={onPlan}
        view="monthly"
        onViewChange={vi.fn()}
        onEditActuals={vi.fn()}
      />,
    );
    const card = screen.getByRole('region', { name: 'Occupancy' });
    const delta = card.querySelector('.am-card-delta');
    expect(delta?.textContent?.trim()).toBe('On plan');
    expect(card.textContent).not.toMatch(/below plan|above plan|pts/i);
    // The direction marker is a claim about direction, and there is none.
    expect(card.querySelector('.am-direction')).toBeNull();
  });

  it('lists the deterministic attention items in words', () => {
    renderPanel();
    const attention = screen.getByRole('region', { name: 'Attention Required' });
    expect(within(attention).getByText('Occupancy is 2.5 pts below plan')).toBeTruthy();
    expect(
      within(attention).getByText('Repairs and Maintenance is $2,000 over budget'),
    ).toBeTruthy();
    expect(within(attention).getByText('Net Operating Income is 8.2% below plan')).toBeTruthy();
  });

  it('never lists a neutral or favorable line as needing attention', () => {
    renderPanel();
    const attention = screen.getByRole('region', { name: 'Attention Required' });
    expect(within(attention).queryByText(/Capital Expenditures/)).toBeNull();
    expect(within(attention).queryByText(/Debt Service/)).toBeNull();
    expect(within(attention).queryByText(/Other Income/)).toBeNull();
  });

  it('shows the management commentary', () => {
    renderPanel();
    const panel = screen.getByRole('region', { name: 'Management Commentary' });
    expect(within(panel).getByText(DEMO_COMMENTARY)).toBeTruthy();
  });

  it('reports no occupancy year to date, and says why', () => {
    renderPanel('year_to_date');
    const occupancy = screen.getByRole('region', { name: 'Occupancy' });
    expect(within(occupancy).getByText('—')).toBeTruthy();
    expect(
      within(occupancy).getByText(/sum of monthly occupancy rates is not a meaningful figure/i),
    ).toBeTruthy();
    expect(screen.queryByRole('row', { name: /^Occupancy/ })).toBeNull();
  });

  it('switches period when the toggle is used', async () => {
    const onViewChange = vi.fn();
    render(
      <MonthlyPerformancePanel
        performance={DEMO_PERFORMANCE}
        view="monthly"
        onViewChange={onViewChange}
        onEditActuals={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Year to Date' }));
    expect(onViewChange).toHaveBeenCalledWith('year_to_date');
  });
});

// ===========================================================================
// The NOI trend
// ===========================================================================

describe('NOI trend', () => {
  it('draws both series without a charting dependency', () => {
    const { container } = render(<NoiTrendChart points={DEMO_PERFORMANCE.result.noi_trend} />);
    expect(container.querySelectorAll('polyline').length).toBe(2);
    expect(screen.getByRole('img', { name: /budget noi compared with actual noi/i })).toBeTruthy();
  });

  it('states every plotted figure in an accessible table too', () => {
    render(<NoiTrendChart points={DEMO_PERFORMANCE.result.noi_trend} />);
    const table = screen.getByRole('table', {
      name: /budget and actual net operating income by month/i,
    });
    expect(within(table).getByText('$67,000')).toBeTruthy();
    expect(within(table).getByText('$61,500')).toBeTruthy();
  });

  it('anchors the first and last month labels inward so neither is clipped', () => {
    // Browser QA found "Mar 2027" rendered as "Mar 202": a centred label on an
    // edge point extends past the viewBox and is cut off.
    const { container } = render(
      <NoiTrendChart
        points={[
          {
            reporting_month: '2027-02-01',
            budget_net_operating_income: 67000,
            actual_net_operating_income: 66000,
          },
          {
            reporting_month: '2027-03-01',
            budget_net_operating_income: 67000,
            actual_net_operating_income: 61500,
          },
        ]}
      />,
    );
    const labels = [...container.querySelectorAll('text')].filter((node) =>
      /^[A-Z][a-z]{2} \d{4}$/.test(node.textContent ?? ''),
    );
    expect(labels.map((node) => node.textContent)).toEqual(['Feb 2027', 'Mar 2027']);
    expect(labels[0].getAttribute('text-anchor')).toBe('start');
    expect(labels[1].getAttribute('text-anchor')).toBe('end');
  });

  it('centres a lone month label', () => {
    const { container } = render(<NoiTrendChart points={DEMO_PERFORMANCE.result.noi_trend} />);
    const label = [...container.querySelectorAll('text')].find((node) =>
      /^[A-Z][a-z]{2} \d{4}$/.test(node.textContent ?? ''),
    );
    expect(label?.getAttribute('text-anchor')).toBe('middle');
  });

  it('says so plainly when nothing has been reported', () => {
    render(<NoiTrendChart points={[]} />);
    expect(screen.getByText(/no months have been reported yet/i)).toBeTruthy();
  });
});

// ===========================================================================
// The frozen budget
// ===========================================================================

describe('Monthly report editor', () => {
  it('lets both columns be entered when a month is first reported', () => {
    render(
      <MonthlyReportEditor
        report={null}
        month="2027-03-01"
        onMonthChange={vi.fn()}
        onCancel={vi.fn()}
        onCreate={vi.fn().mockResolvedValue(undefined)}
        onUpdate={vi.fn().mockResolvedValue(undefined)}
        error={null}
      />,
    );
    expect(screen.getByLabelText('Budget Rental Revenue')).toBeTruthy();
    expect(screen.getByLabelText('Actual Rental Revenue')).toBeTruthy();
  });

  it('locks every budget field once the report exists', () => {
    render(
      <MonthlyReportEditor
        report={DEMO_REPORT}
        month="2027-03-01"
        onMonthChange={vi.fn()}
        onCancel={vi.fn()}
        onCreate={vi.fn().mockResolvedValue(undefined)}
        onUpdate={vi.fn().mockResolvedValue(undefined)}
        error={null}
      />,
    );
    // No budget input exists at all -- not merely a disabled one.
    expect(screen.queryByLabelText('Budget Rental Revenue')).toBeNull();
    expect(screen.getByLabelText('Budget Rental Revenue, locked')).toBeTruthy();
    // The actuals remain editable.
    expect(screen.getByLabelText('Actual Rental Revenue')).toBeTruthy();
    expect(screen.getByText(/frozen when this report was created and cannot be changed/i))
      .toBeTruthy();
  });

  it('sends only actuals and commentary when editing an existing report', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(
      <MonthlyReportEditor
        report={DEMO_REPORT}
        month="2027-03-01"
        onMonthChange={vi.fn()}
        onCancel={vi.fn()}
        onCreate={vi.fn().mockResolvedValue(undefined)}
        onUpdate={onUpdate}
        error={null}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Save Actual Results' }));
    expect(onUpdate).toHaveBeenCalledTimes(1);
    const [request] = onUpdate.mock.calls[0];
    expect(Object.keys(request).sort()).toEqual(['actual', 'commentary']);
    expect(request.actual.rental_revenue).toBe(96000);
  });

  it('converts occupancy between percent on screen and a fraction on the wire', async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    render(
      <MonthlyReportEditor
        report={null}
        month="2027-03-01"
        onMonthChange={vi.fn()}
        onCancel={vi.fn()}
        onCreate={onCreate}
        onUpdate={vi.fn().mockResolvedValue(undefined)}
        error={null}
      />,
    );
    await userEvent.type(screen.getByLabelText('Budget Occupancy'), '95');
    await userEvent.type(screen.getByLabelText('Actual Occupancy'), '92.5');
    await userEvent.click(screen.getByRole('button', { name: 'Save Monthly Report' }));

    const [request] = onCreate.mock.calls[0];
    expect(request.budget.occupancy).toBeCloseTo(0.95, 10);
    expect(request.actual.occupancy).toBeCloseTo(0.925, 10);
  });

  it('shows the existing budget figures as read-only values', () => {
    render(
      <MonthlyReportEditor
        report={DEMO_REPORT}
        month="2027-03-01"
        onMonthChange={vi.fn()}
        onCancel={vi.fn()}
        onCreate={vi.fn().mockResolvedValue(undefined)}
        onUpdate={vi.fn().mockResolvedValue(undefined)}
        error={null}
      />,
    );
    // Grouped exactly as the editable column groups on blur, so the locked
    // figure reads as the same kind of number rather than as raw digits.
    const locked = screen.getByLabelText('Budget Payroll, locked');
    expect(DEMO_BUDGET.payroll).toBe(6000);
    expect(locked.textContent).toContain('6,000');

    const rental = screen.getByLabelText('Budget Rental Revenue, locked');
    expect(rental.textContent).toContain('100,000');

    // Occupancy is a percentage, not a grouped amount.
    const occupancy = screen.getByLabelText('Budget Occupancy, locked');
    expect(occupancy.textContent).toContain('95');
    expect(occupancy.textContent).not.toContain(',');
  });
});

// ===========================================================================
// The asset workspace
// ===========================================================================

describe('Managed asset workspace', () => {
  const renderWorkspace = (
    state = performanceState(),
    onView = vi.fn(),
    onDelete = vi.fn().mockResolvedValue(undefined),
  ) =>
    render(
      <ManagedAssetWorkspace
        asset={DEMO_ASSET}
        state={state}
        onViewAcquisitionBasis={onView}
        onDelete={onDelete}
      />,
    );

  it('identifies the building as an owned asset', () => {
    renderWorkspace();
    expect(screen.getByRole('heading', { name: 'Harbor Point Apartments' })).toBeTruthy();
    expect(screen.getByText('Owned Asset')).toBeTruthy();
    expect(screen.getByText(/Multifamily · Acquired Oct 2026 · Toronto, ON/)).toBeTruthy();
  });

  it('renders only the two functional tabs, with no dead future tabs', () => {
    renderWorkspace();
    const tabs = screen.getAllByRole('tab').map((tab) => tab.textContent);
    expect(tabs).toEqual(['Overview', 'Monthly Performance']);
    for (const absent of ['Business Plan', 'Debt & Covenants', 'Documents']) {
      expect(screen.queryByRole('tab', { name: absent })).toBeNull();
    }
  });

  it('exposes no acquisition control while inside Asset Management', () => {
    renderWorkspace();
    for (const forbidden of [
      /quick underwrite/i,
      /detailed underwrite/i,
      /^analyze/i,
      /analyze deal/i,
      /new deal/i,
      /deal library/i,
    ]) {
      expect(screen.queryByRole('button', { name: forbidden })).toBeNull();
    }
  });

  it('offers the acquisition only as quiet provenance', async () => {
    const onView = vi.fn();
    renderWorkspace(performanceState(), onView);
    await userEvent.click(screen.getAllByRole('button', { name: 'View Acquisition Basis' })[0]);
    expect(onView).toHaveBeenCalledWith(DEMO_ASSET.source_deal_id);
  });

  it('requires an inline confirmation that names what deletion preserves and removes', async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    renderWorkspace(performanceState(), vi.fn(), onDelete);

    await userEvent.click(screen.getByRole('button', { name: 'Delete Asset' }));

    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.getByText('Permanently delete Harbor Point Apartments?')).toBeTruthy();
    expect(screen.getByText(/deletes the managed asset and all of its monthly reports/i)).toBeTruthy();
    expect(screen.getByText(/source acquisition and its underwriting will remain/i)).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cancel' }));
  });

  it('cancels without deleting and returns focus to the opening control', async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    renderWorkspace(performanceState(), vi.fn(), onDelete);

    await userEvent.click(screen.getByRole('button', { name: 'Delete Asset' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.queryByText(/Permanently delete/)).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Delete Asset' }));
  });

  it('sends exactly one delete only after confirmation', async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    renderWorkspace(performanceState(), vi.fn(), onDelete);

    await userEvent.click(screen.getByRole('button', { name: 'Delete Asset' }));
    await userEvent.click(screen.getByRole('button', { name: 'Delete Asset' }));

    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it('keeps the confirmation open and explains a failed deletion', async () => {
    const onDelete = vi.fn().mockRejectedValue(new Error('The asset is still in use.'));
    renderWorkspace(performanceState(), vi.fn(), onDelete);

    await userEvent.click(screen.getByRole('button', { name: 'Delete Asset' }));
    await userEvent.click(screen.getByRole('button', { name: 'Delete Asset' }));

    expect((await screen.findByRole('alert')).textContent).toContain('The asset is still in use.');
    expect(screen.getByText('Permanently delete Harbor Point Apartments?')).toBeTruthy();
  });

  it('explains on Overview that later deal edits do not change the asset', async () => {
    renderWorkspace();
    await userEvent.click(screen.getByRole('tab', { name: 'Overview' }));
    expect(
      screen.getByText(/later edits to that deal do not change this asset/i),
    ).toBeTruthy();
  });

  it('never renders the raw acquisition fingerprint', async () => {
    // It stays on the contract and the wire, where it is what actually freezes
    // the basis -- but it is an internal digest, not something an asset manager
    // can act on. "View Acquisition Basis" is the human-facing provenance.
    renderWorkspace();
    await userEvent.click(screen.getByRole('tab', { name: 'Overview' }));
    expect(document.body.textContent).not.toContain(DEMO_ASSET.acquisition_fingerprint);
    expect(screen.queryByText(/Acquisition Fingerprint/i)).toBeNull();
    expect(screen.getAllByRole('button', { name: 'View Acquisition Basis' }).length)
      .toBeGreaterThan(0);
  });

  it('describes how budgets actually work, not a plan they are not derived from', () => {
    // The old note named an "Approved Acquisition Plan · captured <acquisition
    // date>", which was wrong twice over: that date is not when the basis was
    // captured, and a monthly budget is never derived from an acquisition plan.
    renderWorkspace();
    expect(
      screen.getByText('Monthly budgets are entered explicitly and lock after first save.'),
    ).toBeTruthy();
    expect(screen.queryByText(/Approved Acquisition Plan/i)).toBeNull();
    expect(document.body.textContent).not.toMatch(/captured Oct 2026/);
  });

  it('offers the reporting month picker over the months that have reports', () => {
    renderWorkspace();
    const picker = screen.getByLabelText('Reporting Month');
    expect(within(picker).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'March 2027',
    ]);
  });

  it('names every icon-only navigation button for the collapsed rail', () => {
    // Below 1024px the rail collapses and `.sidebar-nav-label` is hidden, which
    // removes it from the accessibility tree. Browser QA at 390px found these
    // five buttons with no accessible name at all.
    render(
      <AssetManagementShell
        state={{
          assets: [DEMO_ASSET],
          isLoading: false,
          error: null,
          reload: vi.fn(),
          create: vi.fn(),
          remove: vi.fn().mockResolvedValue(undefined),
        }}
        dealCount={1}
        onViewAcquisitionBasis={vi.fn()}
        onOpenAcquisitions={vi.fn()}
      />,
    );
    for (const name of [
      'Acquisitions',
      'Asset Management',
      'Portfolio Overview',
      'Managed Assets',
      'Monthly Reporting',
    ]) {
      expect(screen.getAllByRole('button', { name }).length).toBeGreaterThan(0);
    }
  });

  it('returns to the Managed Assets list with reachable focus after deletion', async () => {
    const remove = vi.fn().mockResolvedValue(undefined);
    render(
      <AssetManagementShell
        state={{
          assets: [DEMO_ASSET],
          isLoading: false,
          error: null,
          reload: vi.fn(),
          create: vi.fn(),
          remove,
        }}
        dealCount={1}
        onViewAcquisitionBasis={vi.fn()}
        onOpenAcquisitions={vi.fn()}
      />,
    );

    await userEvent.click(
      screen.getByRole('button', { name: /Harbor Point Apartments.*Multifamily/i }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Delete Asset' }));
    await userEvent.click(screen.getByRole('button', { name: 'Delete Asset' }));

    expect(remove).toHaveBeenCalledWith(DEMO_ASSET.id);
    const heading = screen.getByRole('heading', { name: 'Managed Assets' });
    expect(document.activeElement).toBe(heading);
  });

  it('shows an honest loading state instead of claiming no reporting yet', () => {
    renderWorkspace(
      performanceState({
        reports: [],
        reportsStatus: 'loading',
        performance: null,
        performanceStatus: 'idle',
        selectedMonth: null,
      }),
    );
    expect(screen.queryByText('No reporting yet')).toBeNull();
    expect(screen.getByText(/Loading this asset.s reporting history/i)).toBeTruthy();
  });

  it('guides the analyst when nothing has been reported yet', () => {
    renderWorkspace(
      performanceState({
        reports: [],
        reportsStatus: 'ready',
        performance: null,
        performanceStatus: 'idle',
        selectedMonth: null,
      }),
    );
    expect(screen.getByText(/budgets are entered explicitly/i)).toBeTruthy();
    // Offered both in the header and in the empty-state panel: an analyst
    // arriving at a blank asset should not have to hunt for the one way in.
    expect(screen.getAllByRole('button', { name: 'Add Monthly Report' })).toHaveLength(2);
  });
});

// ===========================================================================
// The Create Managed Asset form
// ===========================================================================

describe('Create Managed Asset form', () => {
  const renderPanel = (dealName: string, key: string, onCreate = vi.fn()) =>
    render(
      <CreateManagedAssetPanel
        key={key}
        dealName={dealName}
        isOpen
        onCancel={vi.fn()}
        onCreate={onCreate}
        error={null}
      />,
    );

  it('initializes its name from the deal it is opened on', () => {
    renderPanel('Harbor Point Apartments', 'deal-a');
    expect((screen.getByLabelText('Asset Name') as HTMLInputElement).value).toBe(
      'Harbor Point Apartments',
    );
  });

  it('does not let one deal inherit another deal’s draft', async () => {
    // App keys this panel by the active deal's identity, so moving to another
    // deal remounts it and every field re-initializes. Without that, Deal A's
    // authored name, dates and market stayed on screen and could be submitted
    // for Deal B.
    const view = renderPanel('Harbor Point Apartments', 'deal-a');

    await userEvent.clear(screen.getByLabelText('Asset Name'));
    await userEvent.type(screen.getByLabelText('Asset Name'), 'Renamed While On Deal A');
    await userEvent.type(screen.getByLabelText('Property Type (optional)'), 'Multifamily');
    await userEvent.type(screen.getByLabelText('Market (optional)'), 'Toronto, ON');

    view.rerender(
      <CreateManagedAssetPanel
        key="deal-b"
        dealName="Westlake Industrial"
        isOpen
        onCancel={vi.fn()}
        onCreate={vi.fn()}
        error={null}
      />,
    );

    expect((screen.getByLabelText('Asset Name') as HTMLInputElement).value).toBe(
      'Westlake Industrial',
    );
    expect((screen.getByLabelText('Property Type (optional)') as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('Market (optional)') as HTMLInputElement).value).toBe('');
  });

  it('submits the deal it is currently keyed to', async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    const view = renderPanel('Harbor Point Apartments', 'deal-a');
    await userEvent.clear(screen.getByLabelText('Asset Name'));
    await userEvent.type(screen.getByLabelText('Asset Name'), 'Draft For A');

    view.rerender(
      <CreateManagedAssetPanel
        key="deal-b"
        dealName="Westlake Industrial"
        isOpen
        onCancel={vi.fn()}
        onCreate={onCreate}
        error={null}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Create Managed Asset' }));

    expect(onCreate).toHaveBeenCalledTimes(1);
    expect(onCreate.mock.calls[0][0].name).toBe('Westlake Industrial');
  });
});
