import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ExcelUploadPanel } from './ExcelUploadPanel';

afterEach(() => {
  cleanup();
});

describe('ExcelUploadPanel', () => {
  it('always renders the upload control', () => {
    render(<ExcelUploadPanel isLoading={false} error={null} successMessage={null} onUpload={vi.fn()} />);

    expect(screen.getByLabelText('Upload Anchor Workbook (.xlsx)')).toBeTruthy();
  });

  it('shows an empty-state prompt before any upload', () => {
    render(<ExcelUploadPanel isLoading={false} error={null} successMessage={null} onUpload={vi.fn()} />);

    expect(screen.getByText(/Upload the canonical Anchor \.xlsx workbook/)).toBeTruthy();
  });

  it('calls onUpload with the selected file', async () => {
    const user = userEvent.setup();
    const onUpload = vi.fn();
    render(
      <ExcelUploadPanel isLoading={false} error={null} successMessage={null} onUpload={onUpload} />,
    );

    const file = new File(['PK'], 'anchor_input.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await user.upload(screen.getByLabelText('Upload Anchor Workbook (.xlsx)'), file);

    expect(onUpload).toHaveBeenCalledTimes(1);
    expect(onUpload).toHaveBeenCalledWith(file);
  });

  it('shows a loading state while the workbook is being parsed', () => {
    render(<ExcelUploadPanel isLoading={true} error={null} successMessage={null} onUpload={vi.fn()} />);

    expect(screen.getByText(/Parsing workbook/)).toBeTruthy();
  });

  it('disables the upload control while loading', () => {
    render(<ExcelUploadPanel isLoading={true} error={null} successMessage={null} onUpload={vi.fn()} />);

    expect(screen.getByLabelText('Upload Anchor Workbook (.xlsx)')).toHaveProperty('disabled', true);
  });

  it('shows an error state without also showing the empty-state prompt', () => {
    render(
      <ExcelUploadPanel
        isLoading={false}
        error="Workbook is missing the required exactly named 'Inputs' worksheet."
        successMessage={null}
        onUpload={vi.fn()}
      />,
    );

    expect(
      screen.getByText("Workbook is missing the required exactly named 'Inputs' worksheet."),
    ).toBeTruthy();
    expect(screen.queryByText(/Upload the canonical Anchor \.xlsx workbook/)).toBeNull();
  });

  it('shows a success message after a successful import, without the empty-state prompt', () => {
    render(
      <ExcelUploadPanel
        isLoading={false}
        error={null}
        successMessage={
          'Workbook loaded successfully. 9 assumptions imported from "anchor_input.xlsx". ' +
          'Review the values below, make any changes, then click Analyze Deal.'
        }
        onUpload={vi.fn()}
      />,
    );

    expect(
      screen.getByText(
        'Workbook loaded successfully. 9 assumptions imported from "anchor_input.xlsx". ' +
          'Review the values below, make any changes, then click Analyze Deal.',
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/Upload the canonical Anchor \.xlsx workbook/)).toBeNull();
  });

  it('prioritizes the error state over a stale success message', () => {
    render(
      <ExcelUploadPanel
        isLoading={false}
        error="Workbook is missing the required exactly named 'Inputs' worksheet."
        successMessage="Workbook loaded successfully. 9 assumptions imported."
        onUpload={vi.fn()}
      />,
    );

    expect(
      screen.getByText("Workbook is missing the required exactly named 'Inputs' worksheet."),
    ).toBeTruthy();
    expect(screen.queryByText(/Workbook loaded successfully/)).toBeNull();
  });

  it('does not show the success message while a new upload is loading', () => {
    render(
      <ExcelUploadPanel
        isLoading={true}
        error={null}
        successMessage="Workbook loaded successfully. 9 assumptions imported."
        onUpload={vi.fn()}
      />,
    );

    expect(screen.queryByText(/Workbook loaded successfully/)).toBeNull();
    expect(screen.getByText(/Parsing workbook/)).toBeTruthy();
  });
});
