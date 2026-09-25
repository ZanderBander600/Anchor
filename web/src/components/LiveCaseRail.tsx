import { liveMetricsFor } from '../liveMetrics';
import type { LiveMetric } from '../liveMetrics';
import type { AcquisitionResults } from '../types';
import type { UnderwriteTabId } from '../underwrite';
import { isReference, referenceFigure, useAcquisitionReference } from '../useRefinancePresence';
import { ACQUISITION_REFERENCE_LABEL } from './AcquisitionReference';

/** Refinance V1 Stage 3: the rail's figures that hold the acquisition loan to
 * the sale -- the acquisition-financing reference when the Base Capital
 * Structure configures a refinance (R-P rules 3 to 5). */
const ACQUISITION_REFERENCE_METRICS: ReadonlySet<string> = new Set(['levered_irr', 'equity_multiple']);

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
  // Refinance V1 Stage 3 correction round: while it is not known whether a
  // refinance is configured, the levered IRR and equity multiple are withheld
  // rather than shown as if none were; once it is, they carry the reference
  // label. A settled "no refinance" shows them exactly as before.
  const presence = useAcquisitionReference();
  const reference = isReference(presence);
  const shown = (metric: LiveMetric): LiveMetric =>
    ACQUISITION_REFERENCE_METRICS.has(metric.id)
      ? {
          ...metric,
          value: referenceFigure(presence, metric.value),
          caption: reference ? ACQUISITION_REFERENCE_LABEL : metric.caption,
        }
      : metric;
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
          {liveMetricsFor(tab, results).map(shown).map((metric) => (
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
