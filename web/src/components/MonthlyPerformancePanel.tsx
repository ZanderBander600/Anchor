import {
  ASSESSMENT_LABELS,
  EMPHASIZED_LINES,
  LINE_LABELS,
  UNAVAILABLE,
  assessmentClass,
  formatFigure,
  formatMoney,
  formatMonth,
  formatPoints,
  formatRate,
  formatVariance,
  formatVariancePct,
} from '../assetManagementFormat';
import type {
  AssetPerformanceResponse,
  LineVariance,
  PerformanceView,
} from '../assetManagementTypes';
import { NoiTrendChart } from './NoiTrendChart';

/** Gate AM1 -- the Monthly Performance view: summary cards, the actual-versus-
 * budget statement, attention items, commentary and the NOI trend.
 *
 * Displays only. Every figure on this screen -- each total, variance,
 * percentage, assessment and attention message -- arrives already computed by
 * `anchor.asset_management.performance`. This component performs no financial
 * arithmetic of any kind; it formats and lays out what the engine returned.
 *
 * Colour is never the sole carrier of meaning: every assessment is also a word,
 * and every attention item states its direction in prose.
 */

/** The arrow shown beside an assessment. Decorative: it repeats a direction the
 * adjacent words already state. */
function DirectionMark({ line }: { line: LineVariance }) {
  if (line.assessment === 'neutral' || line.assessment === 'on_plan') {
    return null;
  }
  const rising = line.variance > 0;
  return (
    <svg className="am-direction" viewBox="0 0 12 12" aria-hidden="true" focusable="false">
      <path
        d={rising ? 'M6 2.5 L10 8 L2 8 Z' : 'M6 9.5 L2 4 L10 4 Z'}
        fill="currentColor"
      />
    </svg>
  );
}

interface SummaryCardProps {
  label: string;
  value: string;
  planLabel: string;
  line: LineVariance | undefined;
}

function SummaryCard({ label, value, planLabel, line }: SummaryCardProps) {
  return (
    <section className="am-card" aria-label={label}>
      <h3 className="am-card-label">{label}</h3>
      <p className="am-card-value">{value}</p>
      <p className="am-card-plan">{planLabel}</p>
      {line !== undefined && (
        <p className={`am-card-delta ${assessmentClass(line.assessment)}`}>
          <DirectionMark line={line} />
          <span>
            {line.unit === 'percent'
              ? `${formatPoints(line.variance_points)} ${line.variance > 0 ? 'above' : 'below'} plan`
              : summaryDelta(line)}
            {' · '}
            {ASSESSMENT_LABELS[line.assessment]}
          </span>
        </p>
      )}
    </section>
  );
}

/** A summary card's one-line delta, in words. Reads "over plan" for a line
 * where more is worse and "above plan" where more is better, so the phrasing
 * never implies a verdict opposite to the assessment beside it. */
function summaryDelta(line: LineVariance): string {
  if (line.assessment === 'on_plan') {
    return 'On plan';
  }
  const magnitude = formatMoney(Math.abs(line.variance));
  if (line.variance === 0) {
    return `${magnitude} against plan`;
  }
  if (line.direction === 'lower_is_favorable') {
    return line.variance > 0 ? `${magnitude} over plan` : `${magnitude} under plan`;
  }
  return line.variance > 0 ? `${magnitude} above plan` : `${magnitude} below plan`;
}

export interface MonthlyPerformancePanelProps {
  performance: AssetPerformanceResponse;
  view: PerformanceView;
  onViewChange: (view: PerformanceView) => void;
  onEditActuals: () => void;
}

export function MonthlyPerformancePanel({
  performance,
  view,
  onViewChange,
  onEditActuals,
}: MonthlyPerformancePanelProps) {
  const { result } = performance;
  const period = view === 'monthly' ? result.monthly : result.year_to_date;
  const byLine = new Map(period.lines.map((line) => [line.line, line]));

  const heading =
    view === 'monthly'
      ? `${formatMonth(result.reporting_month)} Operating Statement`
      : `Year to Date through ${formatMonth(result.reporting_month)}`;

  return (
    <div className="am-performance">
      <div className="am-performance-controls">
        <div
          className="am-view-toggle"
          role="group"
          aria-label="Reporting period"
        >
          {(['monthly', 'year_to_date'] as const).map((candidate) => (
            <button
              key={candidate}
              type="button"
              className={
                view === candidate ? 'am-view-button am-view-button-active' : 'am-view-button'
              }
              aria-pressed={view === candidate}
              onClick={() => onViewChange(candidate)}
            >
              {candidate === 'monthly' ? 'Monthly' : 'Year to Date'}
            </button>
          ))}
        </div>
        {view === 'year_to_date' && (
          <p className="am-ytd-note">
            {result.year_to_date_months === 1
              ? '1 reported month, January through the selected month.'
              : `${result.year_to_date_months} reported months, January through the selected month.`}{' '}
            Occupancy is a rate and is not summed.
          </p>
        )}
      </div>

      <div className="am-cards">
        <SummaryCard
          label="Net Operating Income"
          value={formatMoney(period.actual.net_operating_income)}
          planLabel={`Budget ${formatMoney(period.budget.net_operating_income)}`}
          line={byLine.get('net_operating_income')}
        />
        {view === 'monthly' ? (
          <SummaryCard
            label="Occupancy"
            value={formatRate(result.monthly.lines.find((l) => l.line === 'occupancy')?.actual ?? null)}
            planLabel={`Plan ${formatRate(
              result.monthly.lines.find((l) => l.line === 'occupancy')?.budget ?? null,
            )}`}
            line={byLine.get('occupancy')}
          />
        ) : (
          <section className="am-card" aria-label="Occupancy">
            <h3 className="am-card-label">Occupancy</h3>
            <p className="am-card-value">{UNAVAILABLE}</p>
            <p className="am-card-plan">Not reported year to date</p>
            <p className="am-card-delta am-card-note">
              A sum of monthly occupancy rates is not a meaningful figure.
            </p>
          </section>
        )}
        <SummaryCard
          label="Operating Expenses"
          value={formatMoney(period.actual.total_operating_expenses)}
          planLabel={`Budget ${formatMoney(period.budget.total_operating_expenses)}`}
          line={byLine.get('total_operating_expenses')}
        />
        <SummaryCard
          label="Net Cash Flow"
          value={formatMoney(period.actual.net_cash_flow)}
          planLabel={`Budget ${formatMoney(period.budget.net_cash_flow)}`}
          line={byLine.get('net_cash_flow')}
        />
      </div>

      <div className="am-columns">
        <section className="am-panel am-statement" aria-labelledby="am-statement-heading">
          <div className="am-panel-head">
            <h3 id="am-statement-heading" className="am-panel-title">
              {heading}
            </h3>
            <button type="button" className="am-secondary-button" onClick={onEditActuals}>
              Edit Actuals
            </button>
          </div>

          {/* The scroll container keeps the table readable at 390px without the
            * page itself scrolling sideways. */}
          <div className="am-table-scroll">
            <table className="am-table">
              <thead>
                <tr>
                  <th scope="col" className="am-col-line">
                    Financial Line
                  </th>
                  <th scope="col" className="am-col-figure">
                    Approved Budget
                  </th>
                  <th scope="col" className="am-col-figure">
                    Actual
                  </th>
                  <th scope="col" className="am-col-figure">
                    Variance
                  </th>
                  <th scope="col" className="am-col-figure">
                    Variance %
                  </th>
                  <th scope="col" className="am-col-assessment">
                    Assessment
                  </th>
                </tr>
              </thead>
              <tbody>
                {period.lines.map((line) => (
                  <tr
                    key={line.line}
                    className={EMPHASIZED_LINES.has(line.line) ? 'am-row-total' : undefined}
                  >
                    <th scope="row" className="am-col-line">
                      {LINE_LABELS[line.line]}
                    </th>
                    <td className="am-col-figure">{formatFigure(line, line.budget)}</td>
                    <td className="am-col-figure">{formatFigure(line, line.actual)}</td>
                    <td className="am-col-figure">{formatVariance(line)}</td>
                    <td className="am-col-figure">{formatVariancePct(line.variance_pct)}</td>
                    <td className={`am-col-assessment ${assessmentClass(line.assessment)}`}>
                      {ASSESSMENT_LABELS[line.assessment]}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <div className="am-side">
          <section className="am-panel" aria-labelledby="am-attention-heading">
            <h3 id="am-attention-heading" className="am-panel-title">
              Attention Required
            </h3>
            {period.attention.length === 0 ? (
              <p className="am-empty">
                Nothing is unfavorable against plan this period.
              </p>
            ) : (
              <ul className="am-attention-list">
                {period.attention.map((item) => (
                  <li key={item.line} className="am-attention-item">
                    <span className={assessmentClass(item.assessment)}>
                      <svg
                        className="am-direction"
                        viewBox="0 0 12 12"
                        aria-hidden="true"
                        focusable="false"
                      >
                        <path d="M6 9.5 L2 4 L10 4 Z" fill="currentColor" />
                      </svg>
                    </span>
                    <span className="am-attention-text">{item.message}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="am-panel" aria-labelledby="am-commentary-heading">
            <h3 id="am-commentary-heading" className="am-panel-title">
              Management Commentary
            </h3>
            {result.commentary === null ? (
              <p className="am-empty">No commentary has been written for this month.</p>
            ) : (
              <p className="am-commentary">{result.commentary}</p>
            )}
            <button type="button" className="am-secondary-button" onClick={onEditActuals}>
              Update Commentary
            </button>
          </section>
        </div>
      </div>

      <section className="am-panel" aria-labelledby="am-trend-heading">
        <h3 id="am-trend-heading" className="am-panel-title">
          Budget NOI versus Actual NOI
        </h3>
        <NoiTrendChart points={result.noi_trend} />
      </section>
    </div>
  );
}
