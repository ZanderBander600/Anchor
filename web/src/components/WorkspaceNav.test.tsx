import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WorkspaceNav } from './WorkspaceNav';
import { WORKSPACES, workspacePanelId, workspaceTabId } from '../workspaces';

afterEach(cleanup);

describe('WorkspaceNav', () => {
  it('renders all five workspaces from the locked information architecture', () => {
    render(<WorkspaceNav active="overview" onSelect={vi.fn()} />);

    expect(WORKSPACES.map((workspace) => workspace.label)).toEqual([
      'Overview',
      'Underwrite',
      'Risk',
      'AI Analyst',
      'Documents',
    ]);
    for (const workspace of WORKSPACES) {
      expect(screen.getByRole('tab', { name: workspace.label })).toBeTruthy();
    }
  });

  it('marks only the active workspace selected', () => {
    render(<WorkspaceNav active="risk" onSelect={vi.fn()} />);

    expect(screen.getByRole('tab', { name: 'Risk' })).toHaveProperty('ariaSelected', 'true');
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveProperty('ariaSelected', 'false');
  });

  it('points each tab at the panel it controls', () => {
    render(<WorkspaceNav active="overview" onSelect={vi.fn()} />);

    const tab = screen.getByRole('tab', { name: 'Documents' });
    expect(tab.id).toBe(workspaceTabId('documents'));
    expect(tab.getAttribute('aria-controls')).toBe(workspacePanelId('documents'));
  });

  it('reports the selected workspace to the caller', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<WorkspaceNav active="overview" onSelect={onSelect} />);

    await user.click(screen.getByRole('tab', { name: 'AI Analyst' }));

    expect(onSelect).toHaveBeenCalledWith('ai');
  });

  it('exposes every tab as a real keyboard-operable button', () => {
    render(<WorkspaceNav active="overview" onSelect={vi.fn()} />);

    for (const workspace of WORKSPACES) {
      const tab = screen.getByRole('tab', { name: workspace.label });
      expect(tab.tagName).toBe('BUTTON');
      expect(tab).toHaveProperty('type', 'button');
    }
  });
});
