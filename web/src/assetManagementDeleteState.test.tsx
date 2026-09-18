/** AM1 deletion state: a successful server delete disappears locally at once. */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { DEMO_ASSET } from './assetManagementFixture';
import { useManagedAssets } from './useManagedAssets';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    listManagedAssets: vi.fn(),
    deleteManagedAsset: vi.fn(),
  };
});

const api = await import('./api');
const listManagedAssets = vi.mocked(api.listManagedAssets);
const deleteManagedAsset = vi.mocked(api.deleteManagedAsset);

function Harness() {
  const state = useManagedAssets();
  return (
    <div>
      <ul>
        {state.assets.map((asset) => (
          <li key={asset.id}>{asset.name}</li>
        ))}
      </ul>
      <button type="button" onClick={() => void state.remove(DEMO_ASSET.id)}>
        Remove loaded asset
      </button>
    </div>
  );
}

beforeEach(() => {
  listManagedAssets.mockResolvedValue([DEMO_ASSET]);
  deleteManagedAsset.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('useManagedAssets deletion', () => {
  it('removes the deleted asset from the loaded portfolio after the request succeeds', async () => {
    render(<Harness />);
    await screen.findByText(DEMO_ASSET.name);

    await userEvent.click(screen.getByRole('button', { name: 'Remove loaded asset' }));

    expect(deleteManagedAsset).toHaveBeenCalledWith(DEMO_ASSET.id);
    expect(screen.queryByText(DEMO_ASSET.name)).toBeNull();
  });
});
