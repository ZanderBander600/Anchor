import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { WorkspacePanel } from './WorkspacePanel';
import { workspacePanelId, workspaceTabId } from '../workspaces';

afterEach(cleanup);

describe('WorkspacePanel', () => {
  it('renders its heading, subtitle and children when active', () => {
    render(
      <WorkspacePanel id="risk" active="risk" title="Risk" subtitle="Sensitivity and break-evens.">
        <p>Panel content</p>
      </WorkspacePanel>,
    );

    expect(screen.getByRole('heading', { name: 'Risk' })).toBeTruthy();
    expect(screen.getByText('Sensitivity and break-evens.')).toBeTruthy();
    expect(screen.getByText('Panel content')).toBeTruthy();
  });

  it('stays mounted but hidden when it is not the active workspace', () => {
    // Sprint C Gate C2: inactive panels are `hidden`, not unmounted -- that is
    // what preserves in-progress state (notably the OM review panels' own
    // per-field approval state) across workspace navigation.
    render(
      <WorkspacePanel id="risk" active="overview" title="Risk" subtitle="Sensitivity.">
        <p>Panel content</p>
      </WorkspacePanel>,
    );

    const panel = document.getElementById(workspacePanelId('risk')) as HTMLElement;
    expect(panel.hasAttribute('hidden')).toBe(true);
    // Still in the DOM -- its children were never torn down.
    expect(panel.textContent).toContain('Panel content');
    // ...but out of the accessibility tree.
    expect(screen.queryByRole('heading', { name: 'Risk' })).toBeNull();
  });

  it('is a tabpanel labelled by its own tab', () => {
    render(
      <WorkspacePanel id="documents" active="documents" title="Documents" subtitle="Ingestion.">
        <p>Panel content</p>
      </WorkspacePanel>,
    );

    const panel = document.getElementById(workspacePanelId('documents')) as HTMLElement;
    expect(panel.getAttribute('role')).toBe('tabpanel');
    expect(panel.getAttribute('aria-labelledby')).toBe(workspaceTabId('documents'));
  });
});
