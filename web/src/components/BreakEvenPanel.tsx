import type { ChangeEvent } from 'react';
import type {
  BreakEvenResult,
  BreakEvenType,
  ReturnHurdleMetric,
  StandardBreakEvenAnalysis,
} from '../types';
import { formatCurrency, formatMultiple, formatPercent } from '../format';

/** Formats one break-even assumption value for display -- never recomputes it. */
function formatAssumptionValue(assumption: string, value: number): string {
  if (assumption === 'purchase_price' || assumption === 'current_noi') {
    return formatCurrency(value);
  }
  return formatPercent(value);
}

/** "for 10.00% Levered IRR" / "for 1.50x Equity Multiple" / "for 1.20x Year 1
 * DSCR" -- purely presentational. */
function hurdleSubtitle(result: BreakEvenResult): string {
  if (result.metric === 'levered_irr') {
    return `for ${formatPercent(result.target_metric_value)} Levered IRR`;
  }
  if (result.metric === 'equity_multiple') {
    return `for ${formatMultiple(result.target_metric_value)} Equity Multiple`;
  }
  return `for ${formatMultiple(result.target_metric_value)} Year 1 DSCR`;
}

interface CardConfig {
  key: BreakEvenType;
  title: string;
}

const RETURN_HURDLE_CARD_CONFIGS: CardConfig[] = [
  { key: 'max_purchase_price', title: 'Maximum Purchase Price' },
  { key: 'max_exit_cap_rate', title: 'Maximum Exit Cap' },
  { key: 'min_noi_growth', title: 'Minimum NOI Growth' },
];

const DSCR_CARD_CONFIGS: CardConfig[] = [
  { key: 'max_interest_rate', title: 'Maximum Interest Rate' },
  { key: 'min_current_noi', title: 'Minimum Current NOI' },
];

interface BreakEvenCardProps {
  title: string;
  result: BreakEvenResult;
}

function BreakEvenCard({ title, result }: BreakEvenCardProps) {
  const isSolved = result.status === 'solved' && result.solved_assumption_value !== null;

  return (
    <div className="break-even-card">
      <span className="break-even-title">{title}</span>
      <span className="break-even-subtitle">{hurdleSubtitle(result)}</span>
      <span className={isSolved ? 'break-even-value' : 'break-even-value break-even-no-solution'}>
        {isSolved
          ? formatAssumptionValue(result.assumption, result.solved_assumption_value as number)
          : 'Not found in tested range'}
      </span>
      <div className="break-even-meta">
        <span>Current: {formatAssumptionValue(result.assumption, result.baseline_assumption_value)}</span>
        <span>
          Search range: {formatAssumptionValue(result.assumption, result.lower_search_bound)} –{' '}
          {formatAssumptionValue(result.assumption, result.upper_search_bound)}
        </span>
      </div>
    </div>
  );
}

interface BreakEvenPanelProps {
  analysis: StandardBreakEvenAnalysis | null;
  isLoading: boolean;
  error: string | null;
  targetLeveredIrrPercent: string;
  targetEquityMultiple: string;
  targetHeadlineDscr: string;
  returnHurdleMetric: ReturnHurdleMetric;
  onTargetLeveredIrrChange: (value: string) => void;
  onTargetEquityMultipleChange: (value: string) => void;
  onTargetHeadlineDscrChange: (value: string) => void;
  onReturnHurdleMetricChange: (metric: ReturnHurdleMetric) => void;
}

export function BreakEvenPanel({
  analysis,
  isLoading,
  error,
  targetLeveredIrrPercent,
  targetEquityMultiple,
  targetHeadlineDscr,
  returnHurdleMetric,
  onTargetLeveredIrrChange,
  onTargetEquityMultipleChange,
  onTargetHeadlineDscrChange,
  onReturnHurdleMetricChange,
}: BreakEvenPanelProps) {
  if (!analysis && !isLoading && !error) {
    return null;
  }

  return (
    <section className="card break-even-panel">
      <h3 className="card-title">Break-Even Analysis</h3>

      <div className="break-even-hurdles">
        <label className="field break-even-hurdle-field">
          <span className="field-label">Target Levered IRR</span>
          <div className="field-input-wrap">
            <input
              className="field-input"
              type="number"
              inputMode="decimal"
              step="any"
              value={targetLeveredIrrPercent}
              onChange={(event: ChangeEvent<HTMLInputElement>) =>
                onTargetLeveredIrrChange(event.target.value)
              }
              style={{ paddingRight: '2.4rem' }}
            />
            <span className="field-affix field-affix-right">%</span>
          </div>
        </label>

        <label className="field break-even-hurdle-field">
          <span className="field-label">Target Equity Multiple</span>
          <div className="field-input-wrap">
            <input
              className="field-input"
              type="number"
              inputMode="decimal"
              step="any"
              value={targetEquityMultiple}
              onChange={(event: ChangeEvent<HTMLInputElement>) =>
                onTargetEquityMultipleChange(event.target.value)
              }
              style={{ paddingRight: '1.4rem' }}
            />
            <span className="field-affix field-affix-right">x</span>
          </div>
        </label>

        <label className="field break-even-hurdle-field">
          <span className="field-label">Target Year 1 DSCR</span>
          <div className="field-input-wrap">
            <input
              className="field-input"
              type="number"
              inputMode="decimal"
              step="any"
              value={targetHeadlineDscr}
              onChange={(event: ChangeEvent<HTMLInputElement>) =>
                onTargetHeadlineDscrChange(event.target.value)
              }
              style={{ paddingRight: '1.4rem' }}
            />
            <span className="field-affix field-affix-right">x</span>
          </div>
        </label>
      </div>

      {isLoading && <div className="sensitivity-status">Calculating break-even…</div>}
      {error && <div className="error-banner">{error}</div>}

      {analysis && !isLoading && (
        <>
          <div className="sensitivity-metric-toggle" role="group" aria-label="Return hurdle metric">
            <button
              type="button"
              className={
                returnHurdleMetric === 'levered_irr' ? 'metric-toggle-button active' : 'metric-toggle-button'
              }
              aria-pressed={returnHurdleMetric === 'levered_irr'}
              onClick={() => onReturnHurdleMetricChange('levered_irr')}
            >
              Levered IRR
            </button>
            <button
              type="button"
              className={
                returnHurdleMetric === 'equity_multiple'
                  ? 'metric-toggle-button active'
                  : 'metric-toggle-button'
              }
              aria-pressed={returnHurdleMetric === 'equity_multiple'}
              onClick={() => onReturnHurdleMetricChange('equity_multiple')}
            >
              Equity Multiple
            </button>
          </div>

          <div className="break-even-grid">
            {RETURN_HURDLE_CARD_CONFIGS.map((config) => (
              <BreakEvenCard key={config.key} title={config.title} result={analysis[config.key]} />
            ))}
          </div>

          <div className="break-even-grid">
            {DSCR_CARD_CONFIGS.map((config) => (
              <BreakEvenCard key={config.key} title={config.title} result={analysis[config.key]} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
