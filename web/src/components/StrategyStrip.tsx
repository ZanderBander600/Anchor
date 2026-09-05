import { useState } from 'react';
import { DealContextField } from './DealContextField';

export interface StrategyStripProps {
  value: string;
  onChange: (value: string) => void;
}

/**
 * Sprint C Gate C3 -- the compact Deal Context strip inside Underwrite.
 *
 * Deal Context's primary display home is Overview ("The Play"). Inside
 * Underwrite it collapses to one clamped line plus an Edit toggle, so it no
 * longer occupies a permanent multi-line textarea in a workspace whose job
 * is numbers.
 *
 * Editing reuses `DealContextField` unchanged, wired to the caller's
 * existing `onChange`, so every Sprint A behavior is preserved exactly:
 * editing marks a saved deal dirty, deterministic results survive, the AI
 * Deal Story invalidates, and nothing re-runs automatically. This component
 * holds only the open/closed flag.
 */
export function StrategyStrip({ value, onChange }: StrategyStripProps) {
  const [isEditing, setIsEditing] = useState(false);
  const trimmed = value.trim();

  return (
    <section className="strategy-strip">
      <div className="strategy-strip-row">
        <span className="strategy-strip-label">Strategy</span>
        {trimmed ? (
          <p className="strategy-strip-text">{trimmed}</p>
        ) : (
          <p className="strategy-strip-text strategy-strip-text-empty">
            No deal context yet. Add the business plan the AI Analyst should reason from.
          </p>
        )}
        <button
          type="button"
          className="btn btn-ghost btn-xs"
          aria-expanded={isEditing}
          onClick={() => setIsEditing((open) => !open)}
        >
          {isEditing ? 'Done' : 'Edit'}
        </button>
      </div>

      {/* Kept mounted and `hidden` while collapsed, matching the workspace
       * and Underwrite tab panels: an in-progress edit survives collapsing
       * the strip, and the disclosure never tears down the field. */}
      <div className="strategy-strip-editor" hidden={!isEditing}>
        <DealContextField value={value} onChange={onChange} />
      </div>
    </section>
  );
}
