import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { DealContextField } from './DealContextField';

afterEach(() => {
  cleanup();
});

describe('DealContextField', () => {
  it('renders the current value and placeholder', () => {
    render(<DealContextField value="Value-add strategy." onChange={vi.fn()} />);

    const textarea = screen.getByLabelText('Deal Context');
    expect(textarea).toHaveProperty('value', 'Value-add strategy.');
    expect(textarea).toHaveProperty(
      'placeholder',
      'Describe the investment strategy, business plan, return priorities, key risks, or intended hold / refinance / sale approach...',
    );
  });

  it('forwards every edit to onChange -- no formula, no transformation', () => {
    const onChange = vi.fn();
    render(<DealContextField value="" onChange={onChange} />);

    fireEvent.change(screen.getByLabelText('Deal Context'), {
      target: { value: 'Refinance in Year 5.' },
    });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('Refinance in Year 5.');
  });

  it('renders as a textarea, not a single-line input', () => {
    render(<DealContextField value="" onChange={vi.fn()} />);

    expect(screen.getByLabelText('Deal Context').tagName).toBe('TEXTAREA');
  });
});
