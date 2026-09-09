import { useState } from 'react';
import type { AIAnalysis } from '../types';

interface AiAnalystListSectionProps {
  title: string;
  items: string[];
}

function AiAnalystListSection({ title, items }: AiAnalystListSectionProps) {
  return (
    <div className="ai-analyst-section">
      <h4 className="ai-analyst-section-title">{title}</h4>
      <ul className="ai-analyst-list">
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

interface AiAnalystProseSectionProps {
  title: string;
  text: string;
}

function AiAnalystProseSection({ title, text }: AiAnalystProseSectionProps) {
  return (
    <div className="ai-analyst-section">
      <h4 className="ai-analyst-section-title">{title}</h4>
      <p className="ai-analyst-prose">{text}</p>
    </div>
  );
}

/**
 * Sprint C Gate C4 -- the report's section list.
 *
 * Every entry maps to a field the `AIAnalysis` contract already carries; no
 * section is invented, renamed, reordered relative to the report's own
 * reading order, or synthesised from other fields. The titles are exactly
 * the ones the panel rendered before this gate.
 */
const AI_SECTIONS = [
  { id: 'investment-view', label: 'Investment View' },
  { id: 'executive-summary', label: 'Executive Summary' },
  { id: 'strengths', label: 'Strengths' },
  { id: 'risks', label: 'Risks' },
  { id: 'return-drivers', label: 'Return Drivers' },
  { id: 'downside', label: 'Downside Analysis' },
  { id: 'capital-structure', label: 'Capital Structure' },
  { id: 'break-even', label: 'Break-Even Interpretation' },
  { id: 'questions', label: 'Questions to Investigate' },
  { id: 'confidence', label: 'Confidence / Data Gaps' },
] as const;

type AiSectionId = (typeof AI_SECTIONS)[number]['id'];

interface AiAnalystPanelProps {
  analysis: AIAnalysis | null;
  isLoading: boolean;
  error: string | null;
  onGenerate: () => void;
  /**
   * D5.8A: whether this deal has a break-even analysis to interpret.
   *
   * Quick and Detailed do -- the deterministic break-even layer answers five
   * questions for both -- so the section stays exactly as it shipped. A
   * Lease-Level deal has none: break-even is unsupported for that mode, so
   * `break_even_analysis` can only ever say that none was supplied, and a
   * navigation item whose whole content is "this was not provided" is worth
   * less than no item at all. The panel is told the fact rather than the mode:
   * this component has no business knowing which underwriting mode it is
   * rendering, and the reason the section is absent is the absence of the
   * analysis, not the name of the mode.
   */
  hasBreakEvenAnalysis?: boolean;
  /**
   * D5.8A: where the report on screen came from, when that is worth saying.
   *
   * `null` for a report generated in this session -- it came from the button
   * the analyst just pressed and needs no explaining. It is supplied for a
   * report restored from the deal, which arrives without anyone asking for it:
   * reopening a saved deal shows a report the analyst did not generate in this
   * session, and this says so rather than leaving them to wonder how current it
   * is. (It is exactly as current as the assumptions on screen: a restored
   * report is only ever handed back while its stored fingerprint still matches
   * them.)
   */
  analysisNote?: string | null;
}

/**
 * Renders the "Anchor AI Analyst" section: a Generate button, loading/error
 * states, and (once generated) the structured interpretation returned by
 * the backend ``/ai/analysis`` endpoint. This component performs no
 * financial calculation and never sees or displays an API key -- it only
 * renders the ``AIAnalysis`` fields the backend already computed/generated.
 *
 * Sprint C Gate C4: the report is no longer one long scrolling document. A
 * section list on the left selects which part of the report the reading area
 * shows, so Risks or Questions are one click away rather than several
 * screens down. Every section stays mounted with the inactive ones `hidden`
 * -- the same pattern the workspaces and Underwrite tabs use -- so nothing
 * is lost or re-fetched by navigating, and no AI request is ever triggered
 * by reading. The Deal Story stays on Overview; it is deliberately not
 * duplicated here.
 */
export function AiAnalystPanel({
  analysis,
  isLoading,
  error,
  onGenerate,
  hasBreakEvenAnalysis = true,
  analysisNote = null,
}: AiAnalystPanelProps) {
  const [activeSection, setActiveSection] = useState<AiSectionId>('investment-view');

  const sections = hasBreakEvenAnalysis
    ? AI_SECTIONS
    : AI_SECTIONS.filter((section) => section.id !== 'break-even');

  // D5.8A: the button says which of the two things pressing it will do.
  //
  // A report on screen -- generated in this session, or restored from the deal
  // because its stored fingerprint still matches these assumptions -- means the
  // next press replaces it. No report means there is nothing yet, which is also
  // exactly what an assumption edit leaves behind: the stale report is dropped,
  // and the button honestly reads Generate again.
  const generateLabel = analysis === null ? 'Generate AI Analysis' : 'Regenerate Analysis';

  return (
    <section className="card ai-analyst-panel">
      <div className="ai-analyst-header">
        <h3 className="card-title">Anchor AI Analyst</h3>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={onGenerate}
          disabled={isLoading}
        >
          {isLoading ? 'Generating…' : generateLabel}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {!analysis && !isLoading && !error && (
        <div className="ai-analyst-empty">
          Click <strong>Generate AI Analysis</strong> for an institutional-style
          interpretation of the deterministic results.
        </div>
      )}

      {isLoading && <div className="sensitivity-status">Generating AI analysis…</div>}

      {analysis && !isLoading && analysisNote !== null && (
        <p className="field-hint ai-analyst-restored-note">{analysisNote}</p>
      )}

      {analysis && !isLoading && (
        <div className="ai-analyst-body">
          <nav className="ai-analyst-nav" role="tablist" aria-label="AI report sections">
            {sections.map((section) => {
              const isActive = section.id === activeSection;
              return (
                <button
                  key={section.id}
                  id={`ai-section-tab-${section.id}`}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  aria-controls={`ai-section-panel-${section.id}`}
                  className={
                    isActive ? 'ai-analyst-nav-item ai-analyst-nav-item-active' : 'ai-analyst-nav-item'
                  }
                  onClick={() => setActiveSection(section.id)}
                >
                  {section.label}
                </button>
              );
            })}
          </nav>

          <div className="ai-analyst-reader">
            {sections.map((section) => (
              <div
                key={section.id}
                id={`ai-section-panel-${section.id}`}
                role="tabpanel"
                aria-labelledby={`ai-section-tab-${section.id}`}
                hidden={section.id !== activeSection}
                className="ai-analyst-sections"
              >
                {section.id === 'investment-view' && (
                  <AiAnalystProseSection title="Investment View" text={analysis.investment_view} />
                )}
                {section.id === 'executive-summary' && (
                  <AiAnalystProseSection
                    title="Executive Summary"
                    text={analysis.executive_summary}
                  />
                )}
                {section.id === 'strengths' && (
                  <AiAnalystListSection title="Key Strengths" items={analysis.strengths} />
                )}
                {section.id === 'risks' && (
                  <AiAnalystListSection title="Key Risks" items={analysis.risks} />
                )}
                {section.id === 'return-drivers' && (
                  <AiAnalystListSection title="Return Drivers" items={analysis.return_drivers} />
                )}
                {section.id === 'downside' && (
                  <AiAnalystProseSection
                    title="Downside Analysis"
                    text={analysis.downside_analysis}
                  />
                )}
                {section.id === 'capital-structure' && (
                  <AiAnalystProseSection
                    title="Capital Structure"
                    text={analysis.capital_structure_analysis}
                  />
                )}
                {section.id === 'break-even' && (
                  <AiAnalystProseSection
                    title="Break-Even Interpretation"
                    text={analysis.break_even_analysis}
                  />
                )}
                {section.id === 'questions' && (
                  <AiAnalystListSection
                    title="Questions to Investigate"
                    items={analysis.questions_to_investigate}
                  />
                )}
                {section.id === 'confidence' && (
                  <AiAnalystListSection
                    title="Confidence / Data Gaps"
                    items={analysis.confidence_notes}
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
