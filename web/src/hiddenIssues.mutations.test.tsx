/**
 * D5.5D -- mutation kills for hidden-field issue surfacing.
 *
 * The behavioural mutants are driven through the real app; the structural ones
 * are audited against the real source, because "the frontend does not restate a
 * backend rule" is a property of the code rather than of one render.
 *
 * The central design claim under test: the drawer decides what to banner by
 * **recording what it asked about**, not by consulting a list of conditionally
 * hidden fields. A list would need maintaining alongside the JSX and would
 * silently rot; the recording cannot, because it is the JSX doing the asking.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { LeaseLevelApiError, analyzeLeaseLevelAcquisition, getDeal, listDeals } from './api';
import { resolveRowIssues } from './leaseLevelIssues';
import type { SubmittedRentRoll } from './leaseLevelIssues';
import type { LeaseLevelIssue } from './leaseLevelTypes';

import editorSource from './components/SuiteLeaseEditor.tsx?raw';
import tableSource from './components/RentRollTable.tsx?raw';
import issuesSource from './leaseLevelIssues.ts?raw';
import workspaceSource from './components/LeaseLevelWorkspace.tsx?raw';

import { HIDDEN_RECOVERY_ISSUE, savedDeal } from './hiddenIssuesFixture';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    analyzeLeaseLevelAcquisition: vi.fn(),
    getDeal: vi.fn(),
    listDeals: vi.fn(),
  };
});

const mockAnalyze = vi.mocked(analyzeLeaseLevelAcquisition);
const mockGetDeal = vi.mocked(getDeal);
const mockListDeals = vi.mocked(listDeals);

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function rows(): HTMLElement[] {
  const panel = document.getElementById('lease-level-panel-rent-roll') as HTMLElement;
  return within(panel).getAllByRole('row').slice(1) as HTMLElement[];
}

/** The drawer's row-level banner, or null.
 *
 * Queried by class rather than by `role="alert"`: an inline field error is also
 * an alert, so asking for "an alert" would conflate the two surfaces this gate
 * exists to keep separate. */
function banner(): HTMLElement | null {
  return drawer().querySelector('.suite-editor-banner');
}

function drawer(): HTMLElement {
  const element = document.querySelector('.suite-editor');
  if (element === null) {
    throw new Error('No suite editor is open');
  }
  return element as HTMLElement;
}

async function hiddenRecoveryState(issues: LeaseLevelIssue[] = [HIDDEN_RECOVERY_ISSUE]) {
  mockListDeals.mockResolvedValue([savedDeal()]);
  mockGetDeal.mockResolvedValue(savedDeal());
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('Fulton Exchange');
  await user.click(screen.getByText('Fulton Exchange'));
  await waitFor(() => {
    expect(screen.getByRole('tablist', { name: 'Lease-Level sections' })).toBeTruthy();
  });
  await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
  await user.click(
    within(rows()[0]).getByRole('button', { name: /Edit details for suite 100/ }),
  );
  await user.selectOptions(within(drawer()).getByLabelText('Lease Type'), 'nnn');

  mockAnalyze.mockRejectedValue(new LeaseLevelApiError('refused', [], issues));
  await user.click(screen.getByRole('button', { name: /^Analyz/i }));
  await waitFor(() => {
    expect(mockAnalyze).toHaveBeenCalled();
  });
  return user;
}

// =============================================================================
// M1-M2: the message survives the field going away
// =============================================================================

describe('M1: the row flag and the drawer message agree', () => {
  it('a flagged row explains itself when opened', async () => {
    await hiddenRecoveryState();

    // The flag that promises an explanation...
    const details = within(rows()[0]).getByRole('button', {
      name: /Edit details for suite 100/,
    });
    expect(details.textContent).toContain('!');

    // ...and the explanation it promises.
    expect(banner()?.textContent).toMatch(/carries a recovery basis or expense stop/);
  });
});

describe('M2: the hidden issue is not dropped', () => {
  it('appears somewhere legible rather than nowhere', async () => {
    await hiddenRecoveryState();
    const text = drawer().textContent ?? '';
    expect(text).toMatch(/carries a recovery basis or expense stop/);
  });

  it('survives even when no other issue exists to carry it', async () => {
    // The failure mode a naive fix has: bannering only alongside a row-level
    // issue, so a lone hidden-field issue still vanishes.
    await hiddenRecoveryState([HIDDEN_RECOVERY_ISSUE]);
    expect(banner()).not.toBeNull();
    expect(banner()!.textContent).toMatch(/carries a recovery basis or expense stop/);
  });
});

// =============================================================================
// M3: never on the wrong suite
// =============================================================================

describe('M3: the hidden issue stays on its own row', () => {
  it('does not leak into another suite’s drawer', async () => {
    const user = await hiddenRecoveryState();

    await user.click(
      within(rows()[1]).getByRole('button', { name: /Edit details for suite 200/ }),
    );
    expect(within(drawer()).queryByText(/carries a recovery basis/)).toBeNull();
    expect(banner()).toBeNull();
  });

  it('resolves against the submitted array, both path conventions', () => {
    // D5.5B's resolver is unchanged; this pins that D5.5D did not regress it,
    // since bannering the wrong row is worse than bannering nothing.
    const submitted: SubmittedRentRoll = {
      suiteRowIds: ['r0', 'r1', 'r2'],
      suiteIds: ['100', '200', '300'],
      leaseRowIds: ['r0', 'r1'],
    };
    const byIndex = resolveRowIssues(
      [{ code: 'X', path: 'leases[1].recovery_basis', message: 'm', severity: 'error' }],
      submitted,
    );
    expect([...byIndex.byRow.keys()]).toEqual(['r1']);

    const bySuiteId = resolveRowIssues(
      [
        {
          code: 'Y',
          path: 'suites[300].initial_vacancy',
          message: 'm',
          severity: 'error',
        },
      ],
      submitted,
    );
    expect([...bySuiteId.byRow.keys()]).toEqual(['r2']);
  });
});

// =============================================================================
// M4: shown once, in one place
// =============================================================================

describe('M4: no duplication between inline and banner', () => {
  it('a rendered field shows its message inline only', async () => {
    mockListDeals.mockResolvedValue([savedDeal()]);
    mockGetDeal.mockResolvedValue(savedDeal());
    mockAnalyze.mockRejectedValue(
      new LeaseLevelApiError(
        'refused',
        [],
        [
          {
            code: 'SUITE_AREA_OUT_OF_DOMAIN',
            path: 'suites[0].suite_area_sf',
            message: 'must be greater than zero',
            severity: 'error',
          },
        ],
      ),
    );
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText('Fulton Exchange');
    await user.click(screen.getByText('Fulton Exchange'));
    await waitFor(() => {
      expect(screen.getByRole('tablist', { name: 'Lease-Level sections' })).toBeTruthy();
    });
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    await user.click(screen.getByRole('button', { name: /^Analyz/i }));
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    await user.click(
      within(rows()[0]).getByRole('button', { name: /Edit details for suite 100/ }),
    );

    // Inline once, and the banner never appears -- the field was rendered, so
    // the drawer asked about it and consumed it.
    expect(within(drawer()).getAllByText('must be greater than zero')).toHaveLength(1);
    expect(banner()).toBeNull();
  });

  it('a hidden field shows its message in the banner only', async () => {
    await hiddenRecoveryState();
    expect(
      within(drawer()).getAllByText(/carries a recovery basis or expense stop/),
    ).toHaveLength(1);
  });
});

// =============================================================================
// M5: no client-side rule
// =============================================================================

describe('M5: the frontend renders issues, it does not derive them', () => {
  it('states no recovery rule anywhere in the rent-roll UI', () => {
    for (const [name, source] of [
      ['SuiteLeaseEditor.tsx', editorSource],
      ['RentRollTable.tsx', tableSource],
      ['leaseLevelIssues.ts', issuesSource],
      ['LeaseLevelWorkspace.tsx', workspaceSource],
    ] as const) {
      for (const forbidden of [
        'MISSING_MODIFIED_GROSS_RECOVERY_BASIS',
        'RECOVERY_BASIS_ON_NON_MODIFIED_GROSS',
        'UNSUPPORTED_RECOVERY_BASIS',
        'EXPENSE_STOP_OUT_OF_DOMAIN',
      ]) {
        expect(source, `${name} names the backend code ${forbidden}`).not.toContain(
          forbidden,
        );
      }
    }
  });

  it('the banner is built from returned issues, not from row state', () => {
    // The mutant: `if (leaseType !== 'modified_gross' && expenseStopPsf) show(...)`.
    // The banner may only read the issue list.
    const start = editorSource.indexOf('const unrendered =');
    const end = editorSource.indexOf('const banner =');
    expect(start).toBeGreaterThan(-1);
    const body = editorSource.slice(start, end);
    expect(body).toContain('issues.fields');
    for (const forbidden of ['leaseType', 'expenseStopPsf', 'recoveryBasis', 'row.lease']) {
      expect(body, `the banner inspects ${forbidden} instead of the issue list`).not.toContain(
        forbidden,
      );
    }
  });

  it('invents nothing before a response', async () => {
    mockListDeals.mockResolvedValue([savedDeal()]);
    mockGetDeal.mockResolvedValue(savedDeal());
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText('Fulton Exchange');
    await user.click(screen.getByText('Fulton Exchange'));
    await waitFor(() => {
      expect(screen.getByRole('tablist', { name: 'Lease-Level sections' })).toBeTruthy();
    });
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    await user.click(
      within(rows()[0]).getByRole('button', { name: /Edit details for suite 100/ }),
    );
    await user.selectOptions(within(drawer()).getByLabelText('Lease Type'), 'nnn');

    // The invalid state exists locally, and the UI says nothing about it.
    expect(banner()).toBeNull();
  });

  it('decides what to banner by what it asked, not by a hidden-field list', () => {
    // The design claim. A list would be a second thing to maintain; the
    // recording set cannot drift from the JSX because it is the JSX.
    expect(editorSource).toContain('const consumed = new Set<string>()');
    expect(editorSource).toContain('consumed.add(field)');
    expect(editorSource).toContain('!consumed.has(field)');
    // And no enumeration of conditionally hidden fields exists to rot.
    expect(editorSource).not.toMatch(/HIDDEN_FIELDS|CONDITIONAL_FIELDS|hiddenFields/);
  });
});

// =============================================================================
// M6: the stored value survives
// =============================================================================

describe('M6: switching lease type does not delete the hidden value', () => {
  it('keeps the stop and submits it', async () => {
    await hiddenRecoveryState();
    const [, inputs] = mockAnalyze.mock.calls[0];
    expect(inputs.leases[0].lease_type).toBe('nnn');
    expect(inputs.leases[0].expense_stop_psf).toBe(9.5);
    expect(inputs.leases[0].recovery_basis).toBe('expense_stop_psf');
  });

  it('restores it on the way back', async () => {
    const user = await hiddenRecoveryState();
    await user.selectOptions(
      within(drawer()).getByLabelText('Lease Type'),
      'modified_gross',
    );
    expect((within(drawer()).getByLabelText('Expense Stop') as HTMLInputElement).value).toBe(
      '9.5',
    );
  });
});

// =============================================================================
// M7-M8: the workspace fallback keeps its job, and only its job
// =============================================================================

describe('M7: the workspace fallback still catches what no row owns', () => {
  it('shows an unresolvable issue', async () => {
    mockListDeals.mockResolvedValue([savedDeal()]);
    mockGetDeal.mockResolvedValue(savedDeal());
    mockAnalyze.mockRejectedValue(
      new LeaseLevelApiError(
        'refused',
        [],
        [
          {
            code: 'RENTABLE_AREA_NOT_RECONCILED',
            path: 'property.rentable_area_sf',
            message: 'suite areas do not sum to rentable area',
            severity: 'error',
          },
          {
            code: 'SOMETHING_NEW',
            path: 'suites[99].invented_field',
            message: 'a path this build cannot place',
            severity: 'error',
          },
        ],
      ),
    );
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText('Fulton Exchange');
    await user.click(screen.getByText('Fulton Exchange'));
    await waitFor(() => {
      expect(screen.getByRole('tablist', { name: 'Lease-Level sections' })).toBeTruthy();
    });
    await user.click(screen.getByRole('tab', { name: 'Rent Roll' }));
    await user.click(screen.getByRole('button', { name: /^Analyz/i }));
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });

    expect(screen.getByText(/do not sum to rentable area/)).toBeTruthy();
    expect(screen.getByText(/a path this build cannot place/)).toBeTruthy();
  });
});

describe('M8: the drawer banner shows only this row’s issues', () => {
  it('does not repeat workspace-level errors', async () => {
    const user = await hiddenRecoveryState([
      HIDDEN_RECOVERY_ISSUE,
      {
        code: 'RENTABLE_AREA_NOT_RECONCILED',
        path: 'property.rentable_area_sf',
        message: 'suite areas do not sum to rentable area',
        severity: 'error',
      },
    ]);

    const rowBanner = banner();
    expect(rowBanner).not.toBeNull();
    expect(rowBanner!.textContent).toMatch(/carries a recovery basis/);
    expect(rowBanner!.textContent).not.toMatch(/do not sum to rentable area/);
    // It is still shown at the workspace level, where it belongs.
    expect(screen.getByText(/do not sum to rentable area/)).toBeTruthy();

    // And another row's issue never appears here either.
    await user.click(
      within(rows()[1]).getByRole('button', { name: /Edit details for suite 200/ }),
    );
    expect(banner()).toBeNull();
  });
});
