/** The AM1 asset-deletion client request. */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { AssetManagementError, deleteManagedAsset } from './api';

const BASE = 'http://127.0.0.1:8000';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('deleteManagedAsset', () => {
  it('sends one encoded DELETE and does not try to read a 204 body', async () => {
    const json = vi.fn();
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 204, json } as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);

    await expect(deleteManagedAsset('asset / 1')).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/managed-assets/asset%20%2F%201`, {
      method: 'DELETE',
    });
    expect(json).not.toHaveBeenCalled();
  });

  it('preserves the backend explanation when deletion is refused', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ detail: 'Managed Asset missing was not found.' }),
      } as Response),
    );

    const failure = await deleteManagedAsset('missing').catch((caught: unknown) => caught);

    expect(failure).toBeInstanceOf(AssetManagementError);
    expect((failure as Error).message).toBe('Managed Asset missing was not found.');
  });
});
