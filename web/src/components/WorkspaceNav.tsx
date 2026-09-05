import { WORKSPACES, workspacePanelId, workspaceTabId } from '../workspaces';
import type { WorkspaceId } from '../workspaces';

export interface WorkspaceNavProps {
  active: WorkspaceId;
  onSelect: (id: WorkspaceId) => void;
}

/**
 * Deal workspace navigation, following the ARIA tabs pattern. Purely
 * presentational: it owns no state, performs no calculation, and renders the
 * same five entries regardless of operating mode -- a workspace means the
 * same thing in Quick and Detailed.
 */
export function WorkspaceNav({ active, onSelect }: WorkspaceNavProps) {
  return (
    <div className="workspace-nav" role="tablist" aria-label="Deal workspace">
      {WORKSPACES.map((workspace) => {
        const isActive = workspace.id === active;
        return (
          <button
            key={workspace.id}
            id={workspaceTabId(workspace.id)}
            type="button"
            role="tab"
            aria-selected={isActive}
            aria-controls={workspacePanelId(workspace.id)}
            className={isActive ? 'workspace-tab workspace-tab-active' : 'workspace-tab'}
            onClick={() => onSelect(workspace.id)}
          >
            {workspace.label}
          </button>
        );
      })}
    </div>
  );
}
