/**
 * Phase 7 Gate P7.5 -- the Decision Matrix, driven through
 * `RiskDecisionWorkspace` against a mocked `api.ts`.
 *
 * Every figure asserted here is a field of the backend decision package,
 * formatted. The fixtures are chosen so that any browser arithmetic would print
 * a different string: each Delta, Worst Case and Range the backend supplies is
 * deliberately *not* what subtracting, minimizing or spreading the cells would
 * give. If the UI computed its own, these tests would fail.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  analyzeDecisionMatrix,
  analyzePositionDecisionMatrix,
  ApiError,
  deleteInvestmentScenario,
  fetchScenarioTargetCatalog,
  fetchStrategyTargetCatalog,
  getDeal,
  listDealScenarios,
  listDealStrategies,
  listPositionPerspectives,
  readDealCapitalStructure,
  updateInvestmentStrategy,
} from './api';
import { RiskDecisionWorkspace } from './components/RiskDecisionWorkspace';
import type { RiskDecisionWorkspaceProps } from './components/RiskDecisionWorkspace';
import {
  DEAL_MATRIX_COPY,
  DIRTY_MATRIX_MESSAGE,
  EMPTY_MATRIX_MESSAGE,
  STALE_MATRIX_MESSAGE,
  UNSAVED_MATRIX_MESSAGE,
} from './decisionMatrix';
import type {
  DecisionCell,
  DecisionMatrixReport,
  DecisionMetricSpec,
  DecisionScenarioRange,
  DecisionStrategyFigures,
  DecisionWorstCase,
} from './decisionTypes';
import type { PositionDecisionMatrixReport } from './capitalTypes';
import type { InvestmentScenario } from './scenarioTypes';
import type { InvestmentStrategy, StrategyOverlay } from './strategyTypes';
import type { AcquisitionResults, IrrStatus } from './types';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    analyzeDecisionMatrix: vi.fn(),
    analyzePositionDecisionMatrix: vi.fn(),
    deleteInvestmentScenario: vi.fn(),
    fetchScenarioTargetCatalog: vi.fn(),
    fetchStrategyTargetCatalog: vi.fn(),
    getDeal: vi.fn(),
    listDealScenarios: vi.fn(),
    listDealStrategies: vi.fn(),
    listPositionPerspectives: vi.fn(),
    readDealCapitalStructure: vi.fn(),
    updateInvestmentStrategy: vi.fn(),
  };
});

const mockAnalyze = vi.mocked(analyzeDecisionMatrix);
const mockScenarios = vi.mocked(listDealScenarios);
const mockStrategies = vi.mocked(listDealStrategies);
const mockUpdateStrategy = vi.mocked(updateInvestmentStrategy);
const mockDeleteScenario = vi.mocked(deleteInvestmentScenario);
const mockPositionMatrix = vi.mocked(analyzePositionDecisionMatrix);
const mockPerspectives = vi.mocked(listPositionPerspectives);
const mockCapital = vi.mocked(readDealCapitalStructure);

// =============================================================================
// Saved Strategies and Scenarios
// =============================================================================

function strategy(id: string, name: string, overlays: StrategyOverlay[] = []): InvestmentStrategy {
  return {
    investment_id: 'inv-1',
    strategy: { strategy_id: id, name, description: null, overlays },
    created_at: '2026-09-14T00:00:00+00:00',
    updated_at: '2026-09-14T00:00:00+00:00',
  };
}

function scenario(id: string, name: string): InvestmentScenario {
  return {
    investment_id: 'inv-1',
    scenario: {
      scenario_id: id,
      name,
      description: null,
      overrides: [{ unit_id: 'deal-1', target: 'exit_cap_rate', operation: 'add', value: 0.005 }],
    },
    created_at: '2026-09-14T00:00:00+00:00',
    updated_at: '2026-09-14T00:00:00+00:00',
  };
}

const HOLD = strategy('st-hold', 'Hold / Lease-Up', [
  { unit_id: 'deal-1', domain: 'disposition', content: { hold_period: 5 } },
]);
const RENO = strategy('st-reno', 'Renovate', [
  { unit_id: 'deal-1', domain: 'acquisition', content: { purchase_price: 9_000_000, acquisition_cost_pct: 0.02 } },
]);
const DOWN = scenario('sc-down', 'Downside');
const UP = scenario('sc-up', 'Upside');

// =============================================================================
// The backend package, by hand
// =============================================================================

const SPECS: DecisionMetricSpec[] = [
  { metric: 'levered_irr', label: 'Levered IRR', unit: 'rate', direction: 'higher_is_better', horizon_dependent: false },
  { metric: 'unlevered_irr', label: 'Unlevered IRR', unit: 'rate', direction: 'higher_is_better', horizon_dependent: false },
  { metric: 'equity_multiple', label: 'Equity Multiple', unit: 'multiple', direction: 'higher_is_better', horizon_dependent: false },
  { metric: 'total_profit', label: 'Total Profit', unit: 'currency', direction: 'higher_is_better', horizon_dependent: false },
  { metric: 'total_equity_invested', label: 'Total Equity Invested', unit: 'currency', direction: 'lower_is_better', horizon_dependent: false },
  { metric: 'exit_value', label: 'Exit Value', unit: 'currency', direction: 'higher_is_better', horizon_dependent: true },
  { metric: 'min_dscr', label: 'Minimum DSCR', unit: 'multiple', direction: 'higher_is_better', horizon_dependent: true },
];

const DEFAULTS: Record<string, number> = {
  levered_irr: 0.12,
  unlevered_irr: 0.08,
  equity_multiple: 1.85,
  total_profit: 12_345_678,
  total_equity_invested: 10_000_000,
  exit_value: 98_765_432,
  min_dscr: 1.42,
};

interface CellSpec {
  strategy: string;
  scenario: string;
  values?: Record<string, number | null>;
  deltas?: Record<string, number | null>;
  irrStatus?: IrrStatus;
  invalid?: string[];
  specs?: DecisionMetricSpec[];
}

function cellOf(spec: CellSpec): DecisionCell {
  const specs = spec.specs ?? SPECS;
  const isBase = spec.scenario === 'base';
  if (spec.invalid !== undefined) {
    return {
      strategy_id: spec.strategy,
      scenario_id: spec.scenario,
      status: 'invalid',
      issues: spec.invalid.map((message) => ({ source: 'scenario', code: 'resolved_input_invalid', message, field: null })),
      source_fingerprint: null,
      cache_status: null,
      hold_period: null,
      results: null,
      metrics: specs.map((s) => ({ metric: s.metric, value: null, irr_status: null, reason: 'invalid_variant', message: 'invalid' })),
      deltas: specs.map((s) => ({ metric: s.metric, value: null, is_baseline: isBase, reason: 'invalid_variant', message: 'invalid', sources: [] })),
    };
  }
  return {
    strategy_id: spec.strategy,
    scenario_id: spec.scenario,
    status: 'valid',
    issues: [],
    source_fingerprint: `fp-${spec.strategy}-${spec.scenario}`,
    cache_status: 'miss',
    hold_period: 5,
    results: {} as AcquisitionResults,
    metrics: specs.map((s) => {
      const value = spec.values !== undefined && s.metric in spec.values ? spec.values[s.metric] : DEFAULTS[s.metric];
      const undefinedIrr = s.metric === 'levered_irr' && spec.irrStatus !== undefined;
      return {
        metric: s.metric,
        value: undefinedIrr ? null : value,
        irr_status: s.unit === 'rate' ? (undefinedIrr ? (spec.irrStatus ?? null) : 'defined') : null,
        reason: undefinedIrr ? 'irr_not_defined' : value === null ? 'not_reported' : null,
        message: undefinedIrr ? 'Levered IRR is not reported for this variant.' : value === null ? `${s.label} is not reported for this variant.` : null,
      };
    }),
    deltas: specs.map((s) => {
      const value = isBase ? 0 : (spec.deltas?.[s.metric] ?? null);
      return {
        metric: s.metric,
        value,
        is_baseline: isBase,
        reason: value === null ? 'base_scenario_not_reported' : null,
        message: value === null ? `No Delta vs Base: ${s.label} is not reported under this Strategy's Base Scenario.` : null,
        sources: [],
      };
    }),
  };
}

function worst(metric: string, value: number | null, scenarioId: string | null, message: string | null = null): DecisionWorstCase {
  return {
    metric,
    direction: metric === 'total_equity_invested' ? 'lower_is_better' : 'higher_is_better',
    value,
    scenario_id: scenarioId,
    scenario_name: null,
    reason: value === null ? 'scenario_invalid' : null,
    message,
    unavailable_scenario_ids: [],
    sources: [],
  };
}

function range(metric: string, spread: number | null, low: string | null, high: string | null, message: string | null = null): DecisionScenarioRange {
  return {
    metric,
    minimum: spread === null ? null : 0,
    minimum_scenario_id: low,
    maximum: spread === null ? null : 0,
    maximum_scenario_id: high,
    spread,
    reason: spread === null ? 'scenario_invalid' : null,
    message,
    unavailable_scenario_ids: [],
    sources: [],
  };
}

interface ReportSpec {
  strategies: { id: string; name: string; hold?: number }[];
  scenarios: { id: string; name: string }[];
  cells: CellSpec[];
  figures?: DecisionStrategyFigures[];
  specs?: DecisionMetricSpec[];
  omitted?: string;
}

function report(spec: ReportSpec): DecisionMatrixReport {
  const specs = spec.specs ?? SPECS;
  return {
    investment_id: 'inv-1',
    unit_id: 'deal-1',
    operating_mode: 'quick',
    matrix: {
      perspective: 'project',
      strategies: spec.strategies.map((s) => ({ strategy_id: s.id, name: s.name, is_base: s.id === 'base', hold_period: s.hold ?? 5 })),
      scenarios: spec.scenarios.map((c) => ({ scenario_id: c.id, name: c.name, is_base: c.id === 'base' })),
      metrics: specs,
      omitted_metrics:
        spec.omitted === undefined
          ? []
          : [
              { metric: 'exit_value', reason: 'different_hold_periods', message: spec.omitted },
              { metric: 'min_dscr', reason: 'different_hold_periods', message: spec.omitted },
            ],
      hold_periods: [5],
      cross_scenario_figures: spec.scenarios.length > 1,
      cells: spec.cells.map((c) => cellOf({ ...c, specs })),
      strategy_figures:
        spec.figures ?? spec.strategies.map((s) => ({ strategy_id: s.id, worst_cases: [], ranges: [] })),
      matrix_fingerprint: 'matrix-fp',
      matrix_fingerprint_reason: null,
    },
  };
}

const STRATEGY_AXIS = [
  { id: 'base', name: 'Base Strategy' },
  { id: 'st-hold', name: 'Hold / Lease-Up' },
  { id: 'st-reno', name: 'Renovate' },
];
const SCENARIO_AXIS = [
  { id: 'base', name: 'Base Scenario' },
  { id: 'sc-down', name: 'Downside' },
  { id: 'sc-up', name: 'Upside' },
];

/** The full 3 x 3. Hold / Lease-Up: IRR 12% / 9% / 15% -- but the backend's
 * Delta, Worst Case and Range are set to values no browser arithmetic over those
 * cells could produce. */
function fullReport(overrides: Partial<ReportSpec> = {}): DecisionMatrixReport {
  const cells: CellSpec[] = [];
  for (const s of STRATEGY_AXIS) {
    for (const c of SCENARIO_AXIS) {
      const irr = c.id === 'base' ? 0.12 : c.id === 'sc-down' ? 0.09 : 0.15;
      cells.push({
        strategy: s.id,
        scenario: c.id,
        values: { levered_irr: irr },
        deltas: { levered_irr: c.id === 'sc-down' ? -0.0412 : 0.0333, total_profit: -450_000, equity_multiple: -0.21 },
      });
    }
  }
  const figures = STRATEGY_AXIS.map((s) => ({
    strategy_id: s.id,
    worst_cases: SPECS.map((spec) =>
      spec.metric === 'levered_irr' ? worst(spec.metric, 0.0777, 'sc-down') : worst(spec.metric, DEFAULTS[spec.metric], 'sc-up'),
    ),
    ranges: SPECS.map((spec) =>
      spec.metric === 'levered_irr' ? range(spec.metric, 0.0555, 'sc-down', 'sc-up') : range(spec.metric, 0, 'base', 'base'),
    ),
  }));
  return report({ strategies: STRATEGY_AXIS, scenarios: SCENARIO_AXIS, cells, figures, ...overrides });
}

// =============================================================================
// Driving the workspace
// =============================================================================

const DEFAULT_PROPS: RiskDecisionWorkspaceProps = {
  operatingMode: 'quick',
  dealId: 'deal-1',
  isDirty: false,
  savedAt: 'saved-1',
  isActive: true,
  view: 'matrix',
};

function renderMatrix(props: Partial<RiskDecisionWorkspaceProps> = {}) {
  let current = { ...DEFAULT_PROPS, ...props };
  const view = render(<RiskDecisionWorkspace {...current} />);
  return {
    user: userEvent.setup(),
    rerenderWith(next: Partial<RiskDecisionWorkspaceProps>) {
      current = { ...current, ...next };
      view.rerender(<RiskDecisionWorkspace {...current} />);
    },
  };
}

function saved(strategies: InvestmentStrategy[], scenarios: InvestmentScenario[]) {
  mockStrategies.mockResolvedValue({ deal_id: 'deal-1', investment_id: strategies.length + scenarios.length > 0 ? 'inv-1' : null, strategies });
  mockScenarios.mockResolvedValue({ deal_id: 'deal-1', investment_id: strategies.length + scenarios.length > 0 ? 'inv-1' : null, scenarios });
}

function button(name: string | RegExp): HTMLButtonElement {
  return screen.getByRole('button', { name }) as HTMLButtonElement;
}

async function run(user: ReturnType<typeof userEvent.setup>) {
  const runButton = await screen.findByRole('button', { name: /Run Decision Matrix|Refresh Matrix/ });
  await waitFor(() => expect((runButton as HTMLButtonElement).disabled).toBe(false));
  await user.click(runButton);
  await screen.findByRole('table');
}

/** The matrix the view ran by itself when it first came on screen: exactly one
 * request, and no click. */
async function autoRun() {
  await screen.findByRole('table');
  expect(mockAnalyze).toHaveBeenCalledTimes(1);
}

function table(): HTMLElement {
  return screen.getByRole('table');
}

/** The cell of one metric row inside one Strategy's row group, in one column. */
function cell(strategyName: string, metric: string, column: string): HTMLElement {
  const group = within(table()).getByRole('rowheader', { name: new RegExp(`^${strategyName}`) }).closest('tbody') as HTMLElement;
  const row = within(group).getByRole('rowheader', { name: `${metric}, ${strategyName}` }).closest('tr') as HTMLElement;
  const found = row.querySelector(`[data-column="${column}"]`);
  if (found === null) {
    throw new Error(`No ${column} cell for ${strategyName} / ${metric}`);
  }
  return found as HTMLElement;
}

beforeEach(() => {
  vi.resetAllMocks();
  saved([], []);
  vi.mocked(fetchScenarioTargetCatalog).mockResolvedValue({ quick: [], detailed: [], lease_level: [] });
  vi.mocked(fetchStrategyTargetCatalog).mockResolvedValue({ quick: [], detailed: [], lease_level: [] });
  vi.mocked(getDeal).mockRejectedValue(new ApiError('not used'));
  // The Risk workspace reads the Base Capital Structure; this Deal has none.
  mockCapital.mockResolvedValue({
    deal_id: 'deal-1',
    investment_id: null,
    capital_structure: { positions: [] },
  });
});

afterEach(() => {
  cleanup();
});

// =============================================================================
// Opt-in
// =============================================================================

describe('the matrix stays simple until there is something to compare', () => {
  it('shows one restrained sentence and no Run when nothing is saved', async () => {
    renderMatrix();
    expect(await screen.findByText(EMPTY_MATRIX_MESSAGE)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Run Decision Matrix' })).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
    expect(mockAnalyze).not.toHaveBeenCalled();
  });

  it('asks for a save first on an unsaved deal, and requests nothing', async () => {
    renderMatrix({ dealId: null, savedAt: null });
    expect(screen.getByText(UNSAVED_MATRIX_MESSAGE)).toBeTruthy();
    await Promise.resolve();
    expect(mockScenarios).not.toHaveBeenCalled();
    expect(mockStrategies).not.toHaveBeenCalled();
  });

  it('runs itself once when the view opens, as one request for the whole package', async () => {
    saved([HOLD], [DOWN]);
    mockAnalyze.mockResolvedValue(fullReport());
    renderMatrix();
    await autoRun();
    expect(mockAnalyze).toHaveBeenCalledWith('inv-1');
    expect(button('Refresh Matrix')).toBeTruthy();
  });

  it('waits until the matrix view is on screen, and never re-runs on a view switch', async () => {
    saved([HOLD], [DOWN]);
    mockAnalyze.mockResolvedValue(fullReport());
    const { rerenderWith } = renderMatrix({ view: 'strategies' });
    expect(await screen.findByText('Hold / Lease-Up')).toBeTruthy();
    // Everything a run needs is ready -- the hidden Run button is enabled --
    // and still nothing ran, because the matrix is not on screen.
    await waitFor(() =>
      expect(
        (screen.getByText('Run Decision Matrix').closest('button') as HTMLButtonElement).disabled,
      ).toBe(false),
    );
    expect(mockAnalyze).not.toHaveBeenCalled();

    rerenderWith({ view: 'matrix' });
    await autoRun();
    rerenderWith({ view: 'scenarios' });
    rerenderWith({ view: 'matrix' });
    rerenderWith({ isActive: false });
    rerenderWith({ isActive: true });
    expect(screen.getByRole('table')).toBeTruthy();
    expect(mockAnalyze).toHaveBeenCalledTimes(1);
  });

  it('never runs itself while the base has unsaved edits, and keeps the prompt', async () => {
    saved([HOLD], [DOWN]);
    mockAnalyze.mockResolvedValue(fullReport());
    renderMatrix({ isDirty: true });
    expect(await screen.findByText(DEAL_MATRIX_COPY.blocked)).toBeTruthy();
    await waitFor(() => expect(button('Run Decision Matrix').disabled).toBe(true));
    expect(screen.queryByRole('table')).toBeNull();
    expect(mockAnalyze).not.toHaveBeenCalled();
  });
});

// =============================================================================
// The shapes
// =============================================================================

describe('the axes', () => {
  it('with only Scenarios: the Base Strategy under Base and each Scenario, with Worst and Range', async () => {
    saved([], [DOWN, UP]);
    mockAnalyze.mockResolvedValue(
      report({
        strategies: [STRATEGY_AXIS[0]],
        scenarios: SCENARIO_AXIS,
        cells: SCENARIO_AXIS.map((c) => ({ strategy: 'base', scenario: c.id })),
        figures: [{ strategy_id: 'base', worst_cases: SPECS.map((s) => worst(s.metric, 1, 'sc-down')), ranges: SPECS.map((s) => range(s.metric, 0, 'base', 'base')) }],
      }),
    );
    renderMatrix();
    await autoRun();

    expect(within(table()).getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Metric', 'Base', 'Downside', 'Upside', 'Worst Case', 'Range',
    ]);
    expect(within(table()).getAllByRole('rowheader').filter((h) => h.getAttribute('scope') === 'rowgroup').map((h) => h.textContent)).toEqual([
      'Base Strategy5-year hold',
    ]);
  });

  it('with only Strategies: each Strategy under the Base Scenario, and no Worst or Range', async () => {
    saved([HOLD, RENO], []);
    mockAnalyze.mockResolvedValue(
      report({
        strategies: STRATEGY_AXIS,
        scenarios: [SCENARIO_AXIS[0]],
        cells: STRATEGY_AXIS.map((s) => ({ strategy: s.id, scenario: 'base' })),
      }),
    );
    renderMatrix();
    await autoRun();

    expect(within(table()).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Metric', 'Base']);
    expect(screen.queryByText('Worst Case')).toBeNull();
    const groups = within(table()).getAllByRole('rowheader').filter((h) => h.getAttribute('scope') === 'rowgroup');
    expect(groups.map((h) => h.textContent)).toEqual([
      'Base Strategy5-year hold',
      'Hold / Lease-Up5-year hold',
      'Renovate5-year hold',
    ]);
    // Base Strategy first, Base Scenario first.
    expect(within(table()).getAllByRole('rowheader', { name: /^Levered IRR, / }).map((h) => h.textContent)).toEqual([
      'Levered IRR, Base Strategy',
      'Levered IRR, Hold / Lease-Up',
      'Levered IRR, Renovate',
    ]);
  });
});

describe('every figure is a backend field', () => {
  it('shows the full 3 x 3 with each cell, the backend Delta, Worst Case and Range', async () => {
    saved([HOLD, RENO], [DOWN, UP]);
    mockAnalyze.mockResolvedValue(fullReport());
    renderMatrix();
    await autoRun();

    expect(cell('Hold / Lease-Up', 'Levered IRR', 'base').textContent).toBe('12.00%');
    // The backend's Delta, never 9% - 12% = -3.00 pts.
    expect(cell('Hold / Lease-Up', 'Levered IRR', 'sc-down').textContent).toBe('9.00%-4.12 pts vs Base');
    expect(cell('Hold / Lease-Up', 'Levered IRR', 'sc-up').textContent).toBe('15.00%+3.33 pts vs Base');
    expect(cell('Hold / Lease-Up', 'Total Profit', 'sc-down').textContent).toBe('$12,345,678-$450,000 vs Base');
    expect(cell('Hold / Lease-Up', 'Equity Multiple', 'sc-up').textContent).toBe('1.85x-0.21x vs Base');
    // The Base Scenario column carries no noisy "+0.00".
    expect(cell('Renovate', 'Levered IRR', 'base').textContent).toBe('12.00%');
    // The backend's Worst Case and Range, never min() = 9% or max - min = 6 pts.
    expect(cell('Hold / Lease-Up', 'Levered IRR', 'worst').textContent).toBe('7.77%Downside');
    expect(cell('Hold / Lease-Up', 'Levered IRR', 'range').textContent).toBe('5.55 ptsLow: Downside · High: Upside');
    expect(cell('Hold / Lease-Up', 'Total Equity Invested', 'worst').textContent).toBe('$10,000,000Upside');
    // No winner, score or ranking is shown anywhere.
    expect(document.body.textContent).not.toMatch(/best|winner|rank|score|recommend|expected/i);
  });

  it('keeps the cache status off screen but available to diagnostics', async () => {
    saved([HOLD], [DOWN]);
    mockAnalyze.mockResolvedValue(fullReport());
    renderMatrix();
    await autoRun();
    expect(cell('Hold / Lease-Up', 'Levered IRR', 'sc-down').getAttribute('data-cache-status')).toBe('miss');
    expect(screen.queryByText(/\b(miss|hit|bypassed|cache)\b/i)).toBeNull();
  });

  it('is a table inside its own keyboard-reachable scrolling region', async () => {
    saved([HOLD], [DOWN]);
    mockAnalyze.mockResolvedValue(fullReport());
    renderMatrix();
    await autoRun();
    const region = screen.getByRole('region', { name: 'Decision matrix table' });
    expect(region.getAttribute('tabindex')).toBe('0');
    expect(within(region).getByRole('table')).toBe(table());
  });
});

describe('honest cells', () => {
  it('keeps an invalid variant in its own cell with the validators’ reasons', async () => {
    saved([HOLD, RENO], [DOWN, UP]);
    const base = fullReport();
    const cells = base.matrix.cells.map((c) =>
      c.strategy_id === 'st-reno' && c.scenario_id === 'sc-down'
        ? cellOf({ strategy: 'st-reno', scenario: 'sc-down', invalid: ['exit_cap_rate must be greater than 0.'] })
        : c,
    );
    const message = 'Not available: every scenario must be a valid variant, and Downside is not.';
    const figures = base.matrix.strategy_figures.map((f) =>
      f.strategy_id === 'st-reno'
        ? {
            strategy_id: f.strategy_id,
            worst_cases: SPECS.map((s) => worst(s.metric, null, null, message)),
            ranges: SPECS.map((s) => range(s.metric, null, null, null, message)),
          }
        : f,
    );
    mockAnalyze.mockResolvedValue({ ...base, matrix: { ...base.matrix, cells, strategy_figures: figures, matrix_fingerprint: null } });
    renderMatrix();
    await autoRun();

    const invalid = cell('Renovate', 'Levered IRR', 'sc-down');
    expect(invalid.textContent).toContain('Invalid variant');
    expect(invalid.textContent).toContain('exit_cap_rate must be greater than 0.');
    expect(invalid.getAttribute('rowspan')).toBe('7');
    // The rest of the row and every other row still stand.
    expect(cell('Renovate', 'Levered IRR', 'sc-up').textContent).toBe('15.00%+3.33 pts vs Base');
    expect(cell('Hold / Lease-Up', 'Levered IRR', 'sc-down').textContent).toBe('9.00%-4.12 pts vs Base');
    // Worst and Range are N/A with the backend's reason, in one shared note.
    expect(cell('Renovate', 'Levered IRR', 'worst').textContent).toBe('N/A');
    expect(cell('Renovate', 'Levered IRR', 'range').textContent).toBe('N/A');
    const notes = screen.getByRole('list', { name: 'Figures not available' });
    expect(within(notes).getAllByText(new RegExp(message))).toHaveLength(1);
    expect(within(cell('Renovate', 'Levered IRR', 'worst')).getByText('N/A').getAttribute('title')).toBe(message);
  });

  it('shows the numbers a validator quotes as an analyst reads them, never as float noise', async () => {
    saved([HOLD, RENO], [DOWN, UP]);
    const base = fullReport();
    const raw = 'exit_cap_rate: value -0.0049999999999999975 must be greater than 0.';
    const cells = base.matrix.cells.map((c) =>
      c.strategy_id === 'st-reno' && c.scenario_id === 'sc-down'
        ? cellOf({ strategy: 'st-reno', scenario: 'sc-down', invalid: [raw] })
        : c,
    );
    mockAnalyze.mockResolvedValue({ ...base, matrix: { ...base.matrix, cells, matrix_fingerprint: null } });
    renderMatrix();
    await autoRun();

    const surface = document.getElementById('decision-matrix') ?? document.body;
    expect(surface.textContent).toContain('exit_cap_rate: value -0.50% must be greater than 0%.');
    expect(document.body.textContent).not.toContain('0.0049999999999999975');
  });

  it('shows an undefined IRR as N/A with the engine’s reason, and its Delta as N/A', async () => {
    saved([HOLD], [DOWN]);
    const base = fullReport();
    const cells = base.matrix.cells.map((c) =>
      c.strategy_id === 'st-hold' && c.scenario_id === 'sc-down'
        ? cellOf({ strategy: 'st-hold', scenario: 'sc-down', irrStatus: 'multiple_sign_changes', deltas: { total_profit: -450_000 } })
        : c,
    );
    mockAnalyze.mockResolvedValue({ ...base, matrix: { ...base.matrix, cells } });
    renderMatrix();
    await autoRun();

    const na = cell('Hold / Lease-Up', 'Levered IRR', 'sc-down');
    expect(na.textContent).toBe('N/A');
    expect(na.textContent).not.toMatch(/0\.00%|-∞|failed/);
    const notes = screen.getByRole('list', { name: 'Figures not available' });
    expect(within(notes).getByText(/Levered IRR is not reported because/)).toBeTruthy();
  });

  it('states once, above the table, why Exit Value and Minimum DSCR are not compared', async () => {
    saved([HOLD, RENO], [DOWN]);
    const independent = SPECS.filter((s) => !s.horizon_dependent);
    const omitted = 'Strategies use different hold periods (5 and 7 years). Exit Value and Minimum DSCR are not compared across different horizons.';
    mockAnalyze.mockResolvedValue(
      report({
        strategies: [STRATEGY_AXIS[0], { id: 'st-hold', name: 'Hold / Lease-Up', hold: 7 }],
        scenarios: SCENARIO_AXIS.slice(0, 2),
        cells: [STRATEGY_AXIS[0], STRATEGY_AXIS[1]].flatMap((s) => SCENARIO_AXIS.slice(0, 2).map((c) => ({ strategy: s.id, scenario: c.id }))),
        specs: independent,
        omitted,
      }),
    );
    renderMatrix();
    await autoRun();

    expect(screen.getAllByText(omitted)).toHaveLength(1);
    expect(screen.getByRole('note').textContent).toBe(omitted);
    expect(within(table()).queryByRole('rowheader', { name: /^Exit Value/ })).toBeNull();
    expect(within(table()).queryByRole('rowheader', { name: /^Minimum DSCR/ })).toBeNull();
    expect(within(table()).getByText('7-year hold')).toBeTruthy();
  });
});

// =============================================================================
// Current or out of date
// =============================================================================

describe('an old matrix is never shown as current', () => {
  async function ran() {
    saved([HOLD], [DOWN]);
    mockAnalyze.mockResolvedValue(fullReport());
    const rendered = renderMatrix();
    await autoRun();
    return rendered;
  }

  it('marks the matrix out of date after a new save of the deal, until it is refreshed', async () => {
    const { user, rerenderWith } = await ran();
    rerenderWith({ savedAt: 'saved-2' });
    expect(screen.getByText(STALE_MATRIX_MESSAGE)).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
    // A stale matrix waits for Refresh; it never re-runs itself.
    expect(mockAnalyze).toHaveBeenCalledTimes(1);
    await run(user);
    expect(mockAnalyze).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(STALE_MATRIX_MESSAGE)).toBeNull();
  });

  it('hides the matrix and disables Refresh while the base is dirty, then allows it once saved', async () => {
    const { rerenderWith } = await ran();
    rerenderWith({ isDirty: true });
    expect(screen.getByText(DIRTY_MATRIX_MESSAGE)).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
    expect(button('Refresh Matrix').disabled).toBe(true);
    expect(button('Refresh Matrix').getAttribute('aria-describedby')).toBe('decision-matrix-blocked-reason');

    rerenderWith({ isDirty: false, savedAt: 'saved-2' });
    expect(button('Refresh Matrix').disabled).toBe(false);
    expect(screen.getByText(STALE_MATRIX_MESSAGE)).toBeTruthy();
  });

  it('marks the matrix out of date when a Scenario is deleted', async () => {
    mockDeleteScenario.mockResolvedValue(undefined);
    const { user, rerenderWith } = await ran();
    rerenderWith({ view: 'scenarios' });
    await user.click(button('Delete Downside'));
    await user.click(button('Delete Scenario'));
    await waitFor(() => expect(mockDeleteScenario).toHaveBeenCalledWith('inv-1', 'sc-down'));
    rerenderWith({ view: 'matrix' });
    await waitFor(() => expect(screen.queryByRole('table')).toBeNull());
  });

  it('relabels a renamed Strategy at once, without a re-run', async () => {
    mockUpdateStrategy.mockResolvedValue({ ...HOLD, strategy: { ...HOLD.strategy, name: 'Hold Longer' } });
    const { user, rerenderWith } = await ran();
    rerenderWith({ view: 'strategies' });
    await user.click(button('Edit Hold / Lease-Up'));
    const name = screen.getByLabelText('Strategy Name');
    await user.clear(name);
    await user.type(name, 'Hold Longer');
    await user.click(button('Save Strategy'));
    await waitFor(() => expect(mockUpdateStrategy).toHaveBeenCalledTimes(1));

    rerenderWith({ view: 'matrix' });
    expect(within(table()).getByRole('rowheader', { name: /^Hold Longer/ })).toBeTruthy();
    expect(mockAnalyze).toHaveBeenCalledTimes(1);
  });
});

describe('the Position perspective', () => {
  function withPosition() {
    mockCapital.mockResolvedValue({
      deal_id: 'deal-1',
      investment_id: 'inv-1',
      capital_structure: { positions: [] },
    });
    mockPerspectives.mockResolvedValue({
      investment_id: 'inv-1',
      positions: [
        {
          position_id: 'mezz-1',
          name: 'Mezzanine Loan',
          position_class: 'mezzanine_debt',
          scope: { kind: 'investment', unit_id: null },
          is_common_equity_marker: false,
          present_in_base: true,
          strategy_ids: [],
        },
        {
          position_id: 'pref-1',
          name: 'Preferred Equity',
          position_class: 'preferred_equity',
          scope: { kind: 'investment', unit_id: null },
          is_common_equity_marker: false,
          present_in_base: true,
          strategy_ids: [],
        },
      ],
    });
    // Held in flight: what is proved is when the request is made.
    mockPositionMatrix.mockReturnValue(new Promise<PositionDecisionMatrixReport>(() => {}));
  }

  async function choosePosition(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole('radio', { name: 'Position' }));
  }

  it('runs itself once for the first addressable position, and never on a switch back', async () => {
    withPosition();
    saved([], []);
    const { user } = renderMatrix();
    expect(await screen.findByText(EMPTY_MATRIX_MESSAGE)).toBeTruthy();
    await choosePosition(user);

    await waitFor(() => expect(mockPositionMatrix).toHaveBeenCalledTimes(1));
    expect(mockPositionMatrix).toHaveBeenCalledWith('inv-1', 'mezz-1');
    await user.click(screen.getByRole('radio', { name: 'Project' }));
    await choosePosition(user);
    expect(mockPositionMatrix).toHaveBeenCalledTimes(1);
    // Choosing another position is the analyst's own comparison: it waits for Run.
    await user.selectOptions(screen.getByRole('combobox'), 'pref-1');
    expect(mockPositionMatrix).toHaveBeenCalledTimes(1);
    // With nothing to compare, the Project matrix never asked for anything.
    expect(mockAnalyze).not.toHaveBeenCalled();
  });

  it('never runs itself while the base has unsaved edits', async () => {
    withPosition();
    saved([], []);
    const { user } = renderMatrix({ isDirty: true });
    expect(await screen.findByText(EMPTY_MATRIX_MESSAGE)).toBeTruthy();
    await choosePosition(user);
    await waitFor(() => expect(mockPerspectives).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole('combobox')).toBeTruthy();
    expect(mockPositionMatrix).not.toHaveBeenCalled();
  });

  it('asks for nothing when the Deal has no Investment yet', async () => {
    saved([], []);
    const { user } = renderMatrix();
    expect(await screen.findByText(EMPTY_MATRIX_MESSAGE)).toBeTruthy();
    await waitFor(() => expect(mockCapital).toHaveBeenCalledTimes(1));
    await choosePosition(user);
    expect(mockPerspectives).not.toHaveBeenCalled();
    expect(mockPositionMatrix).not.toHaveBeenCalled();
    expect(mockAnalyze).not.toHaveBeenCalled();
  });
});

describe('a failed request', () => {
  it('reports the failure for the whole package and retries', async () => {
    saved([HOLD], [DOWN]);
    mockAnalyze.mockRejectedValueOnce(new ApiError('The decision matrix could not be completed (HTTP 500).'));
    const { user } = renderMatrix();

    // The automatic run fails and says so, exactly as a clicked one would.
    const alert = await screen.findByRole('alert');
    expect(mockAnalyze).toHaveBeenCalledTimes(1);
    expect(alert.textContent).toContain('The decision matrix could not be completed (HTTP 500).');
    mockAnalyze.mockResolvedValue(fullReport());
    await user.click(within(alert).getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('table')).toBeTruthy();
    expect(mockAnalyze).toHaveBeenCalledTimes(2);
  });
});
