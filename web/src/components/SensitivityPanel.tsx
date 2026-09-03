import { useState } from 'react';
import type {
  SensitivityMetric,
  StandardDetailedSensitivityPresets,
  StandardSensitivityPresets,
  TwoWaySensitivityResult,
} from '../types';
import { formatCurrency, formatMultiple, formatPercent } from '../format';

const ASSUMPTION_LABELS: Record<string, string> = {
  purchase_price: 'Purchase Price',
  current_noi: 'Current NOI',
  noi_growth: 'NOI Growth',
  exit_cap_rate: 'Exit Cap',
  ltv: 'LTV',
  interest_rate: 'Interest Rate',
};

/** Formats one row/column assumption value for display -- never recomputes it. */
function formatAssumptionValue(assumption: string, value: number): string {
  if (assumption === 'purchase_price' || assumption === 'current_noi') {
    return formatCurrency(value);
  }
  return formatPercent(value, 2);
}

/** Formats one metric cell value for display -- never recomputes it. */
function formatMetricValue(metric: SensitivityMetric, value: number | null): string {
  if (value === null) {
    return 'N/A';
  }
  return metric === 'headline_dscr' ? formatMultiple(value) : formatPercent(value);
}

interface SensitivityMatrixProps {
  result: TwoWaySensitivityResult;
}

function SensitivityMatrix({ result }: SensitivityMatrixProps) {
  const rowLabel = ASSUMPTION_LABELS[result.row_assumption] ?? result.row_assumption;
  const columnLabel = ASSUMPTION_LABELS[result.column_assumption] ?? result.column_assumption;

  return (
    <div className="table-scroll">
      <table className="sensitivity-table">
        <thead>
          <tr>
            <th className="sensitivity-corner">
              <span className="sensitivity-row-axis">{rowLabel}</span>
              <span className="sensitivity-column-axis">{columnLabel}</span>
            </th>
            {result.column_values.map((columnValue, columnIndex) => (
              <th key={columnIndex}>
                {formatAssumptionValue(result.column_assumption, columnValue)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.row_values.map((rowValue, rowIndex) => (
            <tr key={rowIndex}>
              <th scope="row">{formatAssumptionValue(result.row_assumption, rowValue)}</th>
              {result.matrix[rowIndex].map((cell, columnIndex) => {
                const columnValue = result.column_values[columnIndex];
                const isBaseline =
                  rowValue === result.baseline_row_value &&
                  columnValue === result.baseline_column_value;
                return (
                  <td
                    key={columnIndex}
                    className={isBaseline ? 'sensitivity-cell sensitivity-baseline' : 'sensitivity-cell'}
                  >
                    {formatMetricValue(result.metric, cell)}
                    {isBaseline && <span className="sensitivity-baseline-tag"> (Base)</span>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type TabKey = 'exit_cap_noi_growth' | 'purchase_price_exit_cap' | 'interest_rate_ltv';

const ALL_TABS: { key: TabKey; label: string }[] = [
  { key: 'exit_cap_noi_growth', label: 'Exit Cap × NOI Growth' },
  { key: 'purchase_price_exit_cap', label: 'Purchase Price × Exit Cap' },
  { key: 'interest_rate_ltv', label: 'Interest Rate × LTV' },
];

interface SensitivityPanelProps {
  /** Detailed Operating Model V2.1 Gate 14: also accepts
   * ``StandardDetailedSensitivityPresets``, which has no
   * ``exit_cap_noi_growth`` member (``noi_growth`` has no
   * ``AcquisitionTerms`` counterpart) -- the tab list below is derived from
   * whichever shape is actually passed, never hardcoded to Quick's three
   * tabs. */
  presets: StandardSensitivityPresets | StandardDetailedSensitivityPresets | null;
  isLoading: boolean;
  error: string | null;
}

export function SensitivityPanel({ presets, isLoading, error }: SensitivityPanelProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('exit_cap_noi_growth');
  const [ltvMetric, setLtvMetric] = useState<SensitivityMetric>('levered_irr');

  if (!presets && !isLoading && !error) {
    return null;
  }

  const availableTabs = presets ? ALL_TABS.filter((tab) => tab.key in presets) : ALL_TABS;
  const effectiveActiveTab = availableTabs.some((tab) => tab.key === activeTab)
    ? activeTab
    : availableTabs[0]?.key;

  return (
    <section className="card sensitivity-panel">
      <h3 className="card-title">Sensitivity Analysis</h3>

      {isLoading && <div className="sensitivity-status">Calculating sensitivity…</div>}
      {error && <div className="error-banner">{error}</div>}

      {presets && (
        <>
          <div className="sensitivity-tabs" role="tablist">
            {availableTabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={effectiveActiveTab === tab.key}
                className={
                  effectiveActiveTab === tab.key ? 'sensitivity-tab active' : 'sensitivity-tab'
                }
                onClick={() => setActiveTab(tab.key)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {effectiveActiveTab === 'exit_cap_noi_growth' && 'exit_cap_noi_growth' in presets && (
            <SensitivityMatrix result={presets.exit_cap_noi_growth} />
          )}

          {effectiveActiveTab === 'purchase_price_exit_cap' && (
            <SensitivityMatrix result={presets.purchase_price_exit_cap} />
          )}

          {effectiveActiveTab === 'interest_rate_ltv' && (
            <>
              <div className="sensitivity-metric-toggle">
                <button
                  type="button"
                  className={
                    ltvMetric === 'levered_irr' ? 'metric-toggle-button active' : 'metric-toggle-button'
                  }
                  onClick={() => setLtvMetric('levered_irr')}
                >
                  Levered IRR
                </button>
                <button
                  type="button"
                  className={
                    ltvMetric === 'headline_dscr' ? 'metric-toggle-button active' : 'metric-toggle-button'
                  }
                  onClick={() => setLtvMetric('headline_dscr')}
                >
                  Year 1 DSCR
                </button>
              </div>
              <SensitivityMatrix
                result={
                  ltvMetric === 'levered_irr' ? presets.interest_rate_ltv : presets.interest_rate_ltv_dscr
                }
              />
            </>
          )}
        </>
      )}
    </section>
  );
}
