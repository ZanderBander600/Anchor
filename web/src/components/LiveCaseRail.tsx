import { liveMetricsFor } from '../liveMetrics';
import type { AcquisitionResults } from '../types';
import type { UnderwriteTabId } from '../underwrite';

export interface LiveCaseRailProps {
  /** The current authoritative analysis, or null when none has been run. */
  results: AcquisitionResults | null;
  /** Which Underwrite tab is active -- selects which already-computed
   * figures the rail emphasises. */
  tab: UnderwriteTabId;
}

/**
 * Sprint C Gate C3 -- the persistent Live Case rail inside Underwrite.
 *
 * Shows already-computed figures from the current deterministic analysis
 * next to the assumptions that move them. It performs NO calculation: every
 * value is a direct read of an `AcquisitionResults` field, formatted by the
 * existing helpers (see `liveMetrics.ts`). It never triggers an analysis and
 * never writes state -- it only reflects what the engine last returned, so
 * it can go stale exactly as the rest of the app's analysis state does.
 *
 * With no valid analysis it says so plainly rather than rendering zeros.
 */
export function LiveCaseRail({ results, tab }: LiveCaseRailProps) {
  return (
    <aside className="live-case" aria-label="Live case metrics">
      <div className="live-case-head">
        <h3 className="live-case-title">Live Case</h3>
        {results && <span className="live-case-badge">Last analysis</span>}
      </div>

      {results === null ? (
        <p className="live-case-empty">Analyze the deal to populate live metrics.</p>
      ) : (
        <dl className="live-case-metrics">
          {liveMetricsFor(tab, results).map((metric) => (
            <div className="live-case-metric" key={metric.id}>
              <dt className="live-case-metric-label">{metric.label}</dt>
              <dd
                className={
                  metric.value === 'N/A'
                    ? 'live-case-metric-value live-case-metric-value-unavailable'
                    : 'live-case-metric-value'
                }
              >
                {metric.value}
              </dd>
              {metric.caption && <dd className="live-case-metric-caption">{metric.caption}</dd>}
            </div>
          ))}
        </dl>
      )}
    </aside>
  );
}
