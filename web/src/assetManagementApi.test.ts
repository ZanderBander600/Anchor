/** The AM1 asset-deletion and commentary-only client requests. */

import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  AssetManagementError,
  deleteManagedAsset,
  updateMonthlyReportCommentary,
} from './api';

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

describe('updateMonthlyReportCommentary', () => {
  it('PUTs exactly { commentary } to the commentary-only route -- no figures', async () => {
    const saved = { managed_asset_id: 'asset / 1', reporting_month: '2027-03-01', commentary: 'Note.' };
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => saved } as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);

    await expect(updateMonthlyReportCommentary('asset / 1', '2027-03-01', 'Note.')).resolves.toEqual(
      saved,
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BASE}/managed-assets/asset%20%2F%201/reports/2027-03-01/commentary`);
    expect(init.method).toBe('PUT');
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body).toEqual({ commentary: 'Note.' });
    expect(Object.keys(body)).toEqual(['commentary']);
    expect('actual' in body || 'budget' in body).toBe(false);
  });

  it('sends none written as null', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => ({}) } as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);
    await updateMonthlyReportCommentary('asset-1', '2027-03-01', null);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ commentary: null });
  });

  it('reports the structured commentary refusal in the analyst’s words', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({
          detail: [
            {
              code: 'invalid_commentary',
              message: 'Management commentary cannot be blank. Leave it out instead.',
              scope: null,
              field: 'commentary',
            },
          ],
        }),
      } as Response),
    );
    const failure = await updateMonthlyReportCommentary('asset-1', '2027-03-01', ' ').catch(
      (caught: unknown) => caught,
    );
    expect(failure).toBeInstanceOf(AssetManagementError);
    expect((failure as Error).message).toBe(
      'Management commentary cannot be blank. Leave it out instead.',
    );
  });
});
