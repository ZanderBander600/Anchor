import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DealBar } from './DealBar';
import type { DealBarProps } from './DealBar';

afterEach(() => {
  cleanup();
});

function renderDealBar(overrides: Partial<DealBarProps> = {}) {
  const props: DealBarProps = {
    dealName: '',
    onDealNameChange: vi.fn(),
    isSavedDeal: false,
    isSaving: false,
    error: null,
    saveStatus: 'unsaved-deal',
    lastSavedAt: null,
    onSaveDeal: vi.fn(),
    onOpenLibrary: vi.fn(),
    onNewDeal: vi.fn(),
    ...overrides,
  };
  render(<DealBar {...props} />);
  return props;
}

describe('DealBar', () => {
  it('renders the deal name field and navigation actions', () => {
    renderDealBar();

    expect(screen.getByLabelText('Deal Name')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Deal Library' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'New Deal' })).toBeTruthy();
  });

  it('shows "Save Deal" for a new, unsaved deal', () => {
    renderDealBar({ isSavedDeal: false });

    expect(screen.getByRole('button', { name: 'Save Deal' })).toBeTruthy();
  });

  it('shows "Update Deal" once the deal has been saved/opened', () => {
    renderDealBar({ isSavedDeal: true });

    expect(screen.getByRole('button', { name: 'Update Deal' })).toBeTruthy();
  });

  it('calls onDealNameChange as the analyst types', async () => {
    const user = userEvent.setup();
    const onDealNameChange = vi.fn();
    renderDealBar({ onDealNameChange });

    await user.type(screen.getByLabelText('Deal Name'), 'X');

    expect(onDealNameChange).toHaveBeenCalledWith('X');
  });

  it('calls onSaveDeal when the save button is clicked', async () => {
    const user = userEvent.setup();
    const onSaveDeal = vi.fn();
    renderDealBar({ onSaveDeal });

    await user.click(screen.getByRole('button', { name: 'Save Deal' }));

    expect(onSaveDeal).toHaveBeenCalledTimes(1);
  });

  it('calls onOpenLibrary when Deal Library is clicked', async () => {
    const user = userEvent.setup();
    const onOpenLibrary = vi.fn();
    renderDealBar({ onOpenLibrary });

    await user.click(screen.getByRole('button', { name: 'Deal Library' }));

    expect(onOpenLibrary).toHaveBeenCalledTimes(1);
  });

  it('calls onNewDeal when New Deal is clicked', async () => {
    const user = userEvent.setup();
    const onNewDeal = vi.fn();
    renderDealBar({ onNewDeal });

    await user.click(screen.getByRole('button', { name: 'New Deal' }));

    expect(onNewDeal).toHaveBeenCalledTimes(1);
  });

  it('shows "Saving…" and disables the save button while saving', () => {
    renderDealBar({ isSaving: true });

    const button = screen.getByRole('button', { name: 'Saving…' });
    expect(button).toHaveProperty('disabled', true);
  });

  it('shows an error banner', () => {
    renderDealBar({ error: 'The deal could not be saved.' });

    expect(screen.getByText('The deal could not be saved.')).toBeTruthy();
  });

  describe('save status', () => {
    it('shows "Unsaved deal" for a never-saved deal', () => {
      renderDealBar({ saveStatus: 'unsaved-deal' });

      expect(screen.getByText('Unsaved deal')).toBeTruthy();
    });

    it('shows "Unsaved changes" when an opened/saved deal has since changed', () => {
      renderDealBar({ saveStatus: 'unsaved-changes' });

      expect(screen.getByText('Unsaved changes')).toBeTruthy();
    });

    it('shows "Saved" when the workspace matches its last-saved snapshot', () => {
      renderDealBar({ saveStatus: 'saved' });

      expect(screen.getByText(/^Saved/)).toBeTruthy();
    });

    it('appends the last-saved time when saved and available', () => {
      renderDealBar({ saveStatus: 'saved', lastSavedAt: '2026-09-01T12:00:00+00:00' });

      const status = screen.getByText(/^Saved/);
      expect(status.textContent).toContain('·');
    });

    it('does not append a timestamp when not saved', () => {
      renderDealBar({ saveStatus: 'unsaved-changes', lastSavedAt: '2026-09-01T12:00:00+00:00' });

      const status = screen.getByText('Unsaved changes');
      expect(status.textContent).toBe('Unsaved changes');
    });
  });
});
