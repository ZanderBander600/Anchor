/**
 * Phase 7 Gate P7.10 Stage 4 -- the one loading abstraction.
 *
 * Ratified at the Stage 4 independent review (Correction 3). Six loading flows
 * were folded into `useAsyncResource`, so the behaviour they each had
 * separately -- a loading state, a typed error, a retry, and above all the
 * refusal to let a superseded response overwrite a newer one -- is proved here
 * once, on the abstraction itself, rather than six times by inference.
 *
 * The stale-response test is the one that matters: it is the bug this kind of
 * hook exists to prevent, it is invisible in a screenshot, and it produces a
 * screen showing one memo's numbers under another memo's name.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { messageOf, useAsyncResource } from './useAsyncResource';

afterEach(cleanup);

/** A promise whose settlement this test controls. */
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (cause: unknown) => void } {
  let resolve!: (value: T) => void;
  let reject!: (cause: unknown) => void;
  const promise = new Promise<T>((settle, fail) => {
    resolve = settle;
    reject = fail;
  });
  return { promise, resolve, reject };
}

interface ProbeProps {
  initialKey: string | null;
  load: (key: string) => Promise<string>;
}

/** A component that does nothing but show the resource, so the assertions read
 * as what an analyst would see. */
function Probe({ initialKey, load }: ProbeProps) {
  const [key, setKey] = useState(initialKey);
  const resource = useAsyncResource(key, () => load(key ?? ''), 'Could not load.');
  return (
    <div>
      <p data-testid="status">{resource.status}</p>
      <p data-testid="loading">{String(resource.isLoading)}</p>
      <p data-testid="data">{resource.data ?? ''}</p>
      <p data-testid="error">{resource.error ?? ''}</p>
      <button type="button" onClick={resource.reload}>
        Retry
      </button>
      <button type="button" onClick={() => setKey('second')}>
        Switch
      </button>
      <button type="button" onClick={() => setKey(null)}>
        Clear
      </button>
    </div>
  );
}

function shown(id: string): string {
  return screen.getByTestId(id).textContent ?? '';
}

describe('P7.10 Stage 4 -- useAsyncResource', () => {
  it('is loading before the read lands, and ready with its value after', async () => {
    const first = deferred<string>();
    render(<Probe initialKey="first" load={() => first.promise} />);

    expect(shown('status')).toBe('loading');
    expect(shown('loading')).toBe('true');
    // Nothing is shown while loading: not a zero, not a stale value.
    expect(shown('data')).toBe('');

    await act(async () => {
      first.resolve('first answer');
    });

    expect(shown('status')).toBe('ready');
    expect(shown('loading')).toBe('false');
    expect(shown('data')).toBe('first answer');
    expect(shown('error')).toBe('');
  });

  it('a null key is idle rather than a permanent spinner', () => {
    const load = vi.fn();
    render(<Probe initialKey={null} load={load} />);

    expect(shown('status')).toBe('idle');
    expect(shown('loading')).toBe('false');
    expect(load).not.toHaveBeenCalled();
  });

  it('keeps the thrown message, and falls back only when there is none', async () => {
    const failing = deferred<string>();
    render(<Probe initialKey="first" load={() => failing.promise} />);

    await act(async () => {
      failing.reject(new Error('The valuation is unavailable at this month.'));
    });

    expect(shown('status')).toBe('error');
    expect(shown('error')).toBe('The valuation is unavailable at this month.');
    expect(shown('data')).toBe('');

    expect(messageOf(new Error(''), 'Could not load.')).toBe('Could not load.');
    expect(messageOf('a thrown string', 'Could not load.')).toBe('Could not load.');
  });

  it('a superseded response never overwrites the newer one', async () => {
    // The whole point of the hook. The first read is slow; the analyst moves
    // on; the slow answer arrives last and must be thrown away, because it
    // describes a key nobody is looking at any more.
    const first = deferred<string>();
    const second = deferred<string>();
    const load = vi.fn((key: string) => (key === 'first' ? first.promise : second.promise));

    render(<Probe initialKey="first" load={load} />);
    await userEvent.click(screen.getByRole('button', { name: 'Switch' }));

    await act(async () => {
      second.resolve('second answer');
    });
    expect(shown('data')).toBe('second answer');

    // The first read lands afterwards, for the key that is gone.
    await act(async () => {
      first.resolve('FIRST ANSWER, LATE');
    });

    expect(shown('data')).toBe('second answer');
    expect(shown('status')).toBe('ready');
  });

  it('switching keys shows loading rather than the previous key`s value', async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const load = (key: string) => (key === 'first' ? first.promise : second.promise);

    render(<Probe initialKey="first" load={load} />);
    await act(async () => {
      first.resolve('first answer');
    });
    expect(shown('data')).toBe('first answer');

    await userEvent.click(screen.getByRole('button', { name: 'Switch' }));

    // Not the old value under the new name.
    expect(shown('status')).toBe('loading');
    expect(shown('data')).toBe('');
  });

  it('a retry re-reads the same key, and says so while it is in flight', async () => {
    const attempts: Array<ReturnType<typeof deferred<string>>> = [];
    const load = () => {
      const next = deferred<string>();
      attempts.push(next);
      return next.promise;
    };

    render(<Probe initialKey="first" load={load} />);
    await act(async () => {
      attempts[0].reject(new Error('Network unavailable.'));
    });
    expect(shown('status')).toBe('error');

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    // The retry is visibly in flight: the button is not inert.
    expect(shown('status')).toBe('loading');
    expect(shown('error')).toBe('');
    expect(attempts).toHaveLength(2);

    await act(async () => {
      attempts[1].resolve('recovered');
    });
    expect(shown('data')).toBe('recovered');
  });

  it('does not re-read because the caller rebuilt its closure', async () => {
    // Every caller passes an inline arrow, so a hook keyed on the function
    // would read forever. This is the request loop QA found in Phase 1, and it
    // is held here rather than left to be rediscovered.
    const load = vi.fn(() => Promise.resolve('answer'));
    const { rerender } = render(<Probe initialKey="first" load={load} />);
    await waitFor(() => expect(shown('data')).toBe('answer'));

    for (let index = 0; index < 5; index += 1) {
      rerender(<Probe initialKey="first" load={load} />);
    }
    await waitFor(() => expect(shown('data')).toBe('answer'));

    expect(load).toHaveBeenCalledTimes(1);
  });

  it('a response arriving after unmount writes nothing', async () => {
    const late = deferred<string>();
    const { unmount } = render(<Probe initialKey="first" load={() => late.promise} />);
    unmount();

    const warn = vi.spyOn(console, 'error');
    await act(async () => {
      late.resolve('too late');
    });

    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });
});
