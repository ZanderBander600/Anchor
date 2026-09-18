import { formatMoney, formatMonthShort } from '../assetManagementFormat';
import type { NoiTrendPoint } from '../assetManagementTypes';

/** Gate AM1 -- Budget NOI against Actual NOI, month by month.
 *
 * Inline SVG, deliberately: AM1 adds no charting dependency (Section 8). A
 * restrained two-series line is a handful of `<polyline>` points, and pulling in
 * a chart library to draw it would add a bundle, a theming surface and an
 * upgrade obligation for something the platform already renders natively.
 *
 * It performs no financial calculation. Both NOI series arrive already computed
 * by the Python engine; the only arithmetic here maps a dollar figure onto a
 * pixel coordinate, which is the same kind of scaling any axis performs.
 *
 * The chart is not the sole carrier of its information: every plotted figure is
 * also in the table above it, and the accessible table below (visually hidden)
 * states each month's two values for a screen reader.
 */

const VIEW_WIDTH = 720;
const VIEW_HEIGHT = 220;
const PADDING = { top: 16, right: 16, bottom: 30, left: 62 };

export interface NoiTrendChartProps {
  points: NoiTrendPoint[];
}

export function NoiTrendChart({ points }: NoiTrendChartProps) {
  if (points.length === 0) {
    return (
      <p className="am-empty">
        No months have been reported yet, so there is no trend to show.
      </p>
    );
  }

  const plotWidth = VIEW_WIDTH - PADDING.left - PADDING.right;
  const plotHeight = VIEW_HEIGHT - PADDING.top - PADDING.bottom;

  const values = points.flatMap((point) => [
    point.budget_net_operating_income,
    point.actual_net_operating_income,
  ]);
  // The axis always includes zero, so a reader never sees a truncated baseline
  // that visually exaggerates a small difference between budget and actual.
  const maximum = Math.max(0, ...values);
  const minimum = Math.min(0, ...values);
  const span = maximum - minimum || 1;

  const x = (index: number) =>
    points.length === 1
      ? PADDING.left + plotWidth / 2
      : PADDING.left + (index / (points.length - 1)) * plotWidth;
  const y = (value: number) =>
    PADDING.top + plotHeight - ((value - minimum) / span) * plotHeight;

  const line = (pick: (point: NoiTrendPoint) => number) =>
    points.map((point, index) => `${x(index)},${y(pick(point))}`).join(' ');

  const budgetLine = line((point) => point.budget_net_operating_income);
  const actualLine = line((point) => point.actual_net_operating_income);

  // Four gridlines, evenly spaced across the plotted range.
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => minimum + fraction * span);

  return (
    <div className="am-trend">
      <div className="am-trend-plot">
        <svg
          viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
          className="am-trend-svg"
          role="img"
          aria-label="Budget NOI compared with actual NOI, by month"
          preserveAspectRatio="xMidYMid meet"
        >
          {ticks.map((value) => (
            <g key={value}>
              <line
                className="am-trend-grid"
                x1={PADDING.left}
                x2={VIEW_WIDTH - PADDING.right}
                y1={y(value)}
                y2={y(value)}
              />
              <text className="am-trend-axis" x={PADDING.left - 8} y={y(value) + 4} textAnchor="end">
                {formatMoney(value)}
              </text>
            </g>
          ))}

          <polyline className="am-trend-line am-trend-line-budget" points={budgetLine} />
          <polyline className="am-trend-line am-trend-line-actual" points={actualLine} />

          {points.map((point, index) => (
            <g key={point.reporting_month}>
              <circle
                className="am-trend-dot am-trend-dot-budget"
                cx={x(index)}
                cy={y(point.budget_net_operating_income)}
                r={3.5}
              />
              <circle
                className="am-trend-dot am-trend-dot-actual"
                cx={x(index)}
                cy={y(point.actual_net_operating_income)}
                r={3.5}
              />
              {/* The first and last labels are anchored inward rather than
                * centred: a centred label on an edge point extends past the
                * viewBox and is clipped, which silently truncated "Mar 2027"
                * to "Mar 202". */}
              <text
                className="am-trend-axis"
                x={x(index)}
                y={VIEW_HEIGHT - 8}
                textAnchor={
                  points.length > 1 && index === 0
                    ? 'start'
                    : points.length > 1 && index === points.length - 1
                      ? 'end'
                      : 'middle'
                }
              >
                {formatMonthShort(point.reporting_month)}
              </text>
            </g>
          ))}
        </svg>
      </div>

      <ul className="am-trend-legend">
        <li>
          <span className="am-trend-key am-trend-key-budget" aria-hidden="true" />
          Budget NOI
        </li>
        <li>
          <span className="am-trend-key am-trend-key-actual" aria-hidden="true" />
          Actual NOI
        </li>
      </ul>

      {/* The same figures as a real table, for a reader who cannot see the
        * plot. Visually hidden rather than omitted: a chart must never be the
        * only place a number exists. */}
      <table className="am-visually-hidden">
        <caption>Budget and actual net operating income by month</caption>
        <thead>
          <tr>
            <th scope="col">Month</th>
            <th scope="col">Budget NOI</th>
            <th scope="col">Actual NOI</th>
          </tr>
        </thead>
        <tbody>
          {points.map((point) => (
            <tr key={point.reporting_month}>
              <th scope="row">{formatMonthShort(point.reporting_month)}</th>
              <td>{formatMoney(point.budget_net_operating_income)}</td>
              <td>{formatMoney(point.actual_net_operating_income)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
