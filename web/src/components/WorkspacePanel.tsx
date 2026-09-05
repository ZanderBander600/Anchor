import type { ReactNode } from 'react';
import { workspacePanelId, workspaceTabId } from '../workspaces';
import type { WorkspaceId } from '../workspaces';

export interface WorkspacePanelProps {
  id: WorkspaceId;
  active: WorkspaceId;
  /** Workspace heading, shown at the top of the panel. */
  title: string;
  /** One supporting line describing what the workspace owns. */
  subtitle: string;
  /** Extra class for the panel root. Used by Underwrite to opt into the
   * fill-available-height treatment its Results tables need. */
  className?: string;
  children: ReactNode;
}

/**
 * One deal workspace region, paired with its tab in `WorkspaceNav`.
 *
 * Sprint C Gate C2: every workspace panel stays **mounted**; the inactive
 * ones carry the `hidden` attribute, which removes them from layout and from
 * the accessibility tree. This is the standard ARIA tab-panel pattern, and it
 * is what makes C2.7's state-preservation guarantee structural rather than
 * something each panel has to remember to support: deal-level state already
 * lives in `App.tsx`, but `OmReviewPanel`/`DetailedOmReviewPanel` hold
 * per-field analyst approval state internally, so unmounting Documents
 * mid-review would silently discard an in-progress review. Hidden panels
 * occupy no layout, so this costs nothing in scroll length.
 */
export function WorkspacePanel({
  id,
  active,
  title,
  subtitle,
  className,
  children,
}: WorkspacePanelProps) {
  return (
    <section
      id={workspacePanelId(id)}
      role="tabpanel"
      aria-labelledby={workspaceTabId(id)}
      hidden={id !== active}
      className={className ? `workspace-panel ${className}` : 'workspace-panel'}
    >
      <div className="workspace-panel-head">
        <h2 className="workspace-title">{title}</h2>
        <p className="workspace-subtitle">{subtitle}</p>
      </div>
      <div className="workspace-body">{children}</div>
    </section>
  );
}
