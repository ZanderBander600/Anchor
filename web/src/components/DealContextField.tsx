import type { ChangeEvent } from 'react';

export interface DealContextFieldProps {
  value: string;
  onChange: (value: string) => void;
}

/**
 * Owner Return Metrics V3 Gate A4 -- the compact Deal Context textarea,
 * shared unmodified by Quick and Detailed (mirrors `ResultsPanel`/
 * `OwnerReturnSchedule`'s "one component, both modes" convention). Purely
 * qualitative, user-authored strategy/business-plan text -- never a
 * numerical underwriting input, never validated as one, and never read by
 * the deterministic engine. The caller owns all state, persistence, and
 * dirty-tracking; this component only renders the field and forwards edits.
 */
export function DealContextField({ value, onChange }: DealContextFieldProps) {
  return (
    <section className="card deal-context-field">
      <label className="field">
        <span className="field-label">Deal Context</span>
        <textarea
          className="field-input deal-context-textarea"
          placeholder="Describe the investment strategy, business plan, return priorities, key risks, or intended hold / refinance / sale approach..."
          value={value}
          rows={3}
          onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onChange(event.target.value)}
        />
      </label>
    </section>
  );
}
