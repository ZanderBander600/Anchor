import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DealHeader } from './DealHeader';
import type { DealHeaderProps } from './DealHeader';

afterEach(cleanup);

function renderHeader(overrides: Partial<DealHeaderProps> = {}) {
  const props: DealHeaderProps = {
    dealName: '',
    onDealNameChange: vi.fn(),
    operatingMode: 'quick',
    onOperatingModeChange: vi.fn(),
    isSavedDeal: false,
    isSaving: false,
    saveStatus: 'unsaved-deal',
    lastSavedAt: null,
    error: null,
    onSaveDeal: vi.fn(),
    onAnalyze: vi.fn(),
    isAnalyzing: false,
    onDuplicateDeal: vi.fn(),
    onDeleteDeal: vi.fn(),
    ...overrides,
  };
  render(<DealHeader {...props} />);
  return props;
}

describe('DealHeader', () => {
  it('renders the deal name field and both primary actions', () => {
    renderHeader({ dealName: '111 Main St' });

    expect(screen.getByLabelText('Deal Name')).toHaveProperty('value', '111 Main St');
    expect(screen.getByRole('button', { name: 'Save Deal' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Analyze' })).toBeTruthy();
  });

  it('reports deal name edits to the caller', async () => {
    const user = userEvent.setup();
    const props = renderHeader();

    await user.type(screen.getByLabelText('Deal Name'), 'A');

    expect(props.onDealNameChange).toHaveBeenCalledWith('A');
  });

  it('shows "Save Deal" for a new deal and "Update Deal" once it is saved', () => {
    renderHeader({ isSavedDeal: false });
    expect(screen.getByRole('button', { name: 'Save Deal' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Update Deal' })).toBeNull();

    cleanup();
    renderHeader({ isSavedDeal: true });
    expect(screen.getByRole('button', { name: 'Update Deal' })).toBeTruthy();
  });

  it('shows "Saving…" and disables save while a save is in flight', () => {
    renderHeader({ isSaving: true });

    expect(screen.getByRole('button', { name: 'Saving…' })).toHaveProperty('disabled', true);
  });

  it('calls the caller-supplied handlers for save and analyze', async () => {
    const user = userEvent.setup();
    const props = renderHeader();

    await user.click(screen.getByRole('button', { name: 'Save Deal' }));
    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(props.onSaveDeal).toHaveBeenCalledTimes(1);
    expect(props.onAnalyze).toHaveBeenCalledTimes(1);
  });

  it('disables Analyze while an analysis is running', () => {
    renderHeader({ isAnalyzing: true });

    const analyze = screen.getByRole('button', { name: 'Analyze' });
    expect(analyze).toHaveProperty('disabled', true);
    expect(analyze.getAttribute('aria-busy')).toBe('true');
  });

  it('renders the operating mode as a tablist and reports a change', async () => {
    const user = userEvent.setup();
    const props = renderHeader({ operatingMode: 'quick' });

    expect(screen.getByRole('tab', { name: 'Quick Underwrite' })).toHaveProperty(
      'ariaSelected',
      'true',
    );
    expect(screen.getByRole('tab', { name: 'Detailed Underwrite' })).toHaveProperty(
      'ariaSelected',
      'false',
    );

    await user.click(screen.getByRole('tab', { name: 'Detailed Underwrite' }));

    expect(props.onOperatingModeChange).toHaveBeenCalledWith('detailed');
  });

  describe('save status', () => {
    it('shows "Unsaved deal" for a never-saved deal', () => {
      renderHeader({ saveStatus: 'unsaved-deal' });
      expect(screen.getByText('Unsaved deal')).toBeTruthy();
    });

    it('shows "Unsaved changes" when a saved deal has since changed', () => {
      renderHeader({ saveStatus: 'unsaved-changes', isSavedDeal: true });
      expect(screen.getByText('Unsaved changes')).toBeTruthy();
    });

    it('appends the last-saved time when saved and available', () => {
      renderHeader({
        saveStatus: 'saved',
        isSavedDeal: true,
        lastSavedAt: '2026-09-01T12:00:00+00:00',
      });
      expect(screen.getByText(/^Saved · /)).toBeTruthy();
    });

    it('omits the timestamp when the deal is not saved', () => {
      renderHeader({ saveStatus: 'unsaved-changes', lastSavedAt: '2026-09-01T12:00:00+00:00' });
      expect(screen.getByText('Unsaved changes')).toBeTruthy();
      expect(screen.queryByText(/·/)).toBeNull();
    });

    it('never relies on color alone -- the status text is always present', () => {
      renderHeader({ saveStatus: 'saved', isSavedDeal: true });
      expect(screen.getByText(/^Saved/).textContent).toContain('Saved');
    });
  });

  describe('overflow menu', () => {
    it('is closed until the icon button is activated', async () => {
      const user = userEvent.setup();
      renderHeader({ isSavedDeal: true });

      expect(screen.queryByRole('menuitem', { name: 'Duplicate Deal' })).toBeNull();

      await user.click(screen.getByRole('button', { name: 'More deal actions' }));

      expect(screen.getByRole('menuitem', { name: 'Duplicate Deal' })).toBeTruthy();
      expect(screen.getByRole('menuitem', { name: 'Delete Deal' })).toBeTruthy();
    });

    it('calls duplicate and delete for a saved deal', async () => {
      const user = userEvent.setup();
      const props = renderHeader({ isSavedDeal: true });

      await user.click(screen.getByRole('button', { name: 'More deal actions' }));
      await user.click(screen.getByRole('menuitem', { name: 'Duplicate Deal' }));
      expect(props.onDuplicateDeal).toHaveBeenCalledTimes(1);

      await user.click(screen.getByRole('button', { name: 'More deal actions' }));
      await user.click(screen.getByRole('menuitem', { name: 'Delete Deal' }));
      expect(props.onDeleteDeal).toHaveBeenCalledTimes(1);
    });

    it('disables duplicate and delete for a deal that was never saved', async () => {
      const user = userEvent.setup();
      renderHeader({ isSavedDeal: false });

      await user.click(screen.getByRole('button', { name: 'More deal actions' }));

      expect(screen.getByRole('menuitem', { name: 'Duplicate Deal' })).toHaveProperty(
        'disabled',
        true,
      );
      expect(screen.getByRole('menuitem', { name: 'Delete Deal' })).toHaveProperty(
        'disabled',
        true,
      );
    });

    it('closes on Escape', async () => {
      const user = userEvent.setup();
      renderHeader({ isSavedDeal: true });

      await user.click(screen.getByRole('button', { name: 'More deal actions' }));
      await user.keyboard('{Escape}');

      expect(screen.queryByRole('menuitem', { name: 'Duplicate Deal' })).toBeNull();
    });
  });

  it('shows a save error banner', () => {
    renderHeader({ error: 'Deal name is required.' });
    expect(screen.getByText('Deal name is required.')).toBeTruthy();
  });

  it('displays no deal metadata Anchor does not actually store', () => {
    // Sprint C explicitly excludes the concept image's property photo,
    // address, asset type and building size -- no production contract
    // supports them.
    renderHeader({ dealName: '111 Main St', isSavedDeal: true });

    expect(document.querySelector('.deal-header img')).toBeNull();
    for (const invented of [/Industrial/, /\bSF\b/, /Dallas/, /Asset Type/]) {
      expect(screen.queryByText(invented)).toBeNull();
    }
  });
});
