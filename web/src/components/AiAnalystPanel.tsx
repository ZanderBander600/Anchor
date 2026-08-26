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

interface AiAnalystPanelProps {
  analysis: AIAnalysis | null;
  isLoading: boolean;
  error: string | null;
  onGenerate: () => void;
}

/**
 * Renders the "Anchor AI Analyst" section: a Generate button, loading/error
 * states, and (once generated) the structured interpretation returned by
 * the backend ``/ai/analysis`` endpoint. This component performs no
 * financial calculation and never sees or displays an API key -- it only
 * renders the ``AIAnalysis`` fields the backend already computed/generated.
 */
export function AiAnalystPanel({ analysis, isLoading, error, onGenerate }: AiAnalystPanelProps) {
  return (
    <section className="card ai-analyst-panel">
      <div className="ai-analyst-header">
        <h3 className="card-title">Anchor AI Analyst</h3>
        <button
          type="button"
          className="ai-generate-button"
          onClick={onGenerate}
          disabled={isLoading}
        >
          {isLoading ? 'Generating…' : 'Generate AI Analysis'}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {!analysis && !isLoading && !error && (
        <div className="ai-analyst-empty">
          Click <strong>Generate AI Analysis</strong> for an institutional-style
          interpretation of the deterministic results above.
        </div>
      )}

      {isLoading && <div className="sensitivity-status">Generating AI analysis…</div>}

      {analysis && !isLoading && (
        <div className="ai-analyst-sections">
          <AiAnalystProseSection title="Investment View" text={analysis.investment_view} />
          <AiAnalystProseSection title="Executive Summary" text={analysis.executive_summary} />

          <div className="ai-analyst-grid">
            <AiAnalystListSection title="Key Strengths" items={analysis.strengths} />
            <AiAnalystListSection title="Key Risks" items={analysis.risks} />
          </div>

          <AiAnalystListSection title="Return Drivers" items={analysis.return_drivers} />
          <AiAnalystProseSection title="Downside Analysis" text={analysis.downside_analysis} />
          <AiAnalystProseSection
            title="Capital Structure"
            text={analysis.capital_structure_analysis}
          />
          <AiAnalystProseSection
            title="Break-Even Interpretation"
            text={analysis.break_even_analysis}
          />
          <AiAnalystListSection
            title="Questions to Investigate"
            items={analysis.questions_to_investigate}
          />
          <AiAnalystListSection title="Confidence / Data Gaps" items={analysis.confidence_notes} />
        </div>
      )}
    </section>
  );
}
