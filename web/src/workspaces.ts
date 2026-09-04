/** The five deal workspaces. Locked by the Sprint C Gate C1 information
 * architecture (`docs/workspace_ux_visual_system_v3_spec.md` section 3).
 *
 * Kept out of `WorkspaceNav.tsx` so that file exports only its component --
 * this is navigation vocabulary, shared by the nav, the panels, and `App`. */
export type WorkspaceId = 'overview' | 'underwrite' | 'risk' | 'ai' | 'documents';

export const WORKSPACES: { id: WorkspaceId; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'underwrite', label: 'Underwrite' },
  { id: 'risk', label: 'Risk' },
  { id: 'ai', label: 'AI Analyst' },
  { id: 'documents', label: 'Documents' },
];

/** Stable ids so each tab and its panel can point at one another
 * (`aria-controls` / `aria-labelledby`). */
export function workspaceTabId(id: WorkspaceId): string {
  return `workspace-tab-${id}`;
}

export function workspacePanelId(id: WorkspaceId): string {
  return `workspace-panel-${id}`;
}
