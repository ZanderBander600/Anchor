/**
 * D5.5D -- a backend issue stays legible when its control is conditionally hidden.
 *
 * **The gap.** D5.5C made the backend answer correctly: an NNN lease carrying a
 * recovery basis is refused with `RECOVERY_BASIS_ON_NON_MODIFIED_GROSS` at
 * `leases[n].recovery_basis`. D5.5B anchors that path to the right row and flags
 * its Details button. But the drawer renders the recovery controls only for a
 * Modified Gross lease -- and for *this* error the lease is NNN by definition.
 * So the analyst was told a row had a problem, opened it, and found nothing.
 *
 * The state is genuinely reachable: D5.5B deliberately keeps a stored expense
 * stop when the field is hidden rather than deleting the analyst's data, so
 * Modified Gross -> enter a stop -> switch to NNN -> Analyze produces exactly it.
 *
 * **The rule.** An issue the row owns is shown inline when the drawer renders a
 * control for it, and in the drawer's banner when it does not. Never in both,
 * and never nowhere. The frontend still invents nothing: it renders issues the
 * backend returned, and no client-side recovery rule exists.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import {
  LeaseLevelApiError,
  analyzeLeaseLevelAcquisition,
  getDeal,
  listDeals,
} from './api';
import type { LeaseLevelIssue } from './leaseLevelTypes';
import { HIDDEN_RECOVERY_ISSUE, results, savedDeal } from './hiddenIssuesFixture';

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

let confirmSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.clearAllMocks();
  confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  confirmSpy.mockRestore();
});

// =============================================================================
// Fixture: three suites -- one Modified Gross, one NNN, one vacant
// =============================================================================

async function openRentRoll() {
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
  return user;
}

function rows(): HTMLElement[] {
  const panel = document.getElementById('lease-level-panel-rent-roll') as HTMLElement;
  return within(panel).getAllByRole('row').slice(1) as HTMLElement[];
}

function drawer(): HTMLElement {
  const element = document.querySelector('.suite-editor');
  if (element === null) {
    throw new Error('No suite editor is open');
  }
  return element as HTMLElement;
}

function analyzeButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: /^Analyz/i }) as HTMLButtonElement;
}

async function refuseWith(issues: LeaseLevelIssue[]) {
  mockAnalyze.mockRejectedValue(new LeaseLevelApiError('refused', [], issues));
  const user = await openRentRoll();
  await user.click(analyzeButton());
  await waitFor(() => {
    expect(mockAnalyze).toHaveBeenCalled();
  });
  return user;
}

/**
 * Reach the state the defect lives in, then submit -- in that order.
 *
 * Editing the lease type invalidates the analysis those issues belonged to, so
 * switching *after* a refusal correctly clears them. The reproduction is the
 * other way round: the analyst hides the control first, and the refusal then
 * arrives describing a field the drawer is no longer showing.
 */
async function refuseWithLeaseSwitchedTo(
  leaseType: string,
  issues: LeaseLevelIssue[],
) {
  const user = await openRentRoll();
  await user.click(
    within(rows()[0]).getByRole('button', { name: /Edit details for suite 100/ }),
  );
  await user.selectOptions(within(drawer()).getByLabelText('Lease Type'), leaseType);

  mockAnalyze.mockRejectedValue(new LeaseLevelApiError('refused', [], issues));
  await user.click(analyzeButton());
  await waitFor(() => {
    expect(mockAnalyze).toHaveBeenCalled();
  });
  return user;
}

// =============================================================================
// 1. The reproduction
// =============================================================================

describe('the reported reproduction', () => {
  it('shows the recovery issue in the drawer once the control is hidden', async () => {
    await refuseWithLeaseSwitchedTo('nnn', [HIDDEN_RECOVERY_ISSUE]);

    // The drawer is still open on suite 100, and now explains the flag rather
    // than showing nothing where the recovery controls used to be.
    expect(within(drawer()).queryByLabelText('Recovery Basis')).toBeNull();
    expect(within(drawer()).getByText(/carries a recovery basis or expense stop/)).toBeTruthy();
  });

  it('does not force the hidden control into view to say so', async () => {
    // Showing the recovery controls to carry the message would suggest the
    // analyst should fill them in -- the opposite of what the backend said.
    await refuseWithLeaseSwitchedTo('nnn', [HIDDEN_RECOVERY_ISSUE]);

    expect(within(drawer()).queryByLabelText('Recovery Basis')).toBeNull();
    expect(within(drawer()).queryByLabelText('Expense Stop')).toBeNull();
    expect(within(drawer()).getByText(/carries a recovery basis or expense stop/)).toBeTruthy();
  });

  it('walks the whole reproduction: hide the field, analyze, read the reason', async () => {
    mockAnalyze.mockRejectedValue(
      new LeaseLevelApiError('refused', [], [HIDDEN_RECOVERY_ISSUE]),
    );
    const user = await openRentRoll();

    // 1-2. The lease is Modified Gross and carries a stop.
    await user.click(
      within(rows()[0]).getByRole('button', { name: /Edit details for suite 100/ }),
    );
    expect((within(drawer()).getByLabelText('Expense Stop') as HTMLInputElement).value).toBe(
      '9.5',
    );

    // 3. Switch it to NNN. The value is kept, the control goes away.
    await user.selectOptions(within(drawer()).getByLabelText('Lease Type'), 'nnn');
    expect(within(drawer()).queryByLabelText('Expense Stop')).toBeNull();

    // 4. Analyze -- the backend refuses, exactly as D5.5C makes it.
    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    // The stop really was still submitted; nothing was cleaned up client-side.
    expect(inputs.leases[0].expense_stop_psf).toBe(9.5);
    expect(inputs.leases[0].lease_type).toBe('nnn');

    // 5-6. The reason is readable.
    await user.click(
      within(rows()[0]).getByRole('button', { name: /Edit details for suite 100/ }),
    );
    expect(within(drawer()).getByText(/carries a recovery basis or expense stop/)).toBeTruthy();
  });

  it('restores the stored value when the analyst switches back', async () => {
    const user = await openRentRoll();
    await user.click(
      within(rows()[0]).getByRole('button', { name: /Edit details for suite 100/ }),
    );

    await user.selectOptions(within(drawer()).getByLabelText('Lease Type'), 'nnn');
    expect(within(drawer()).queryByLabelText('Expense Stop')).toBeNull();

    await user.selectOptions(
      within(drawer()).getByLabelText('Lease Type'),
      'modified_gross',
    );
    expect((within(drawer()).getByLabelText('Expense Stop') as HTMLInputElement).value).toBe(
      '9.5',
    );
    expect(
      (within(drawer()).getByLabelText('Recovery Basis') as HTMLSelectElement).value,
    ).toBe('expense_stop_psf');
  });
});

// =============================================================================
// 2. Classification: inline, drawer banner, or workspace fallback
// =============================================================================

describe('issue classification', () => {
  it('A: an issue whose control is rendered stays inline, not in the banner', async () => {
    const user = await refuseWith([
      {
        code: 'LEASE_AREA_MISMATCH',
        path: 'leases[0].leased_area_sf',
        message: 'does not match the suite area',
        severity: 'error',
      },
    ]);
    await user.click(
      within(rows()[0]).getByRole('button', { name: /Edit details for suite 100/ }),
    );

    const field = within(drawer()).getByLabelText('Leased Area');
    expect(field.getAttribute('aria-invalid')).toBe('true');
    const describedBy = field.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy!.split(' ').pop()!)?.textContent).toBe(
      'does not match the suite area',
    );

    // Shown once. Not repeated in the banner.
    expect(
      within(drawer()).getAllByText('does not match the suite area'),
    ).toHaveLength(1);
    expect(within(drawer()).queryByText(/not showing a control for/)).toBeNull();
  });

  it('B: an issue the drawer owns but cannot anchor goes to the banner', async () => {
    await refuseWithLeaseSwitchedTo('nnn', [HIDDEN_RECOVERY_ISSUE]);

    const banner = within(drawer()).getByRole('alert');
    expect(within(banner).getByText(/carries a recovery basis or expense stop/)).toBeTruthy();
    expect(within(banner).getByText(/not showing a control for/)).toBeTruthy();
  });

  it('C: an issue no row owns stays in the workspace fallback', async () => {
    await refuseWith([
      {
        code: 'RENTABLE_AREA_NOT_RECONCILED',
        path: 'property.rentable_area_sf',
        message: 'suite areas do not sum to rentable area',
        severity: 'error',
      },
    ]);
    expect(screen.getByText(/do not sum to rentable area/)).toBeTruthy();
    expect(document.querySelector('.suite-editor')).toBeNull();
  });

  it('a hidden vacancy issue on an occupied suite reaches the banner', async () => {
    // Representable from loaded or externally-written data: the suite has a
    // tenant, so the drawer shows no vacancy section at all, yet the backend
    // reports a treatment it should not be carrying.
    const user = await refuseWith([
      {
        code: 'INITIAL_VACANCY_ON_OCCUPIED_SUITE',
        path: 'suites[100].initial_vacancy',
        message: 'has a lease but carries an initial-vacancy treatment',
        severity: 'error',
      },
    ]);
    await user.click(
      within(rows()[0]).getByRole('button', { name: /Edit details for suite 100/ }),
    );

    expect(within(drawer()).queryByLabelText('Initial Vacancy Strategy')).toBeNull();
    expect(
      within(drawer()).getByText(/carries an initial-vacancy treatment/),
    ).toBeTruthy();
  });

  it('a lease issue on a vacant suite reaches the banner', async () => {
    const user = await refuseWith([
      {
        code: 'LEASE_AREA_MISMATCH',
        path: 'suites[300].suite_area_sf',
        message: 'suite three has a problem',
        severity: 'error',
      },
      {
        code: 'MULTIPLE_KNOWN_LEASES_IN_SUITE',
        path: 'suites[300]',
        message: 'has more than one known lease',
        severity: 'error',
      },
    ]);
    await user.click(
      within(rows()[2]).getByRole('button', { name: /Edit details for suite 300/ }),
    );

    // Row-level issues were already bannered before D5.5D; they still are.
    expect(within(drawer()).getByText(/has more than one known lease/)).toBeTruthy();
    // And the field issue is inline, because suite area is rendered for any row.
    expect(
      within(drawer()).getByLabelText('Suite Area').getAttribute('aria-invalid'),
    ).toBe('true');
  });

  it('a vacancy issue on a vacant suite stays inline, not in the banner', async () => {
    const user = await refuseWith([
      {
        code: 'MISSING_INITIAL_LEASE_UP_MONTHS',
        path: 'suites[300].initial_vacancy',
        message: 'states no initial-vacancy treatment',
        severity: 'error',
      },
    ]);
    await user.click(
      within(rows()[2]).getByRole('button', { name: /Edit details for suite 300/ }),
    );

    expect(
      within(drawer())
        .getByLabelText('Initial Vacancy Strategy')
        .getAttribute('aria-invalid'),
    ).toBe('true');
    expect(within(drawer()).queryByText(/not showing a control for/)).toBeNull();
  });
});

// =============================================================================
// 3. Row ownership is not regressed
// =============================================================================

describe('row ownership', () => {
  it('does not show one suite’s hidden issue on another suite', async () => {
    const user = await refuseWithLeaseSwitchedTo('nnn', [HIDDEN_RECOVERY_ISSUE]);

    // Suite 200's drawer must stay clean.
    await user.click(
      within(rows()[1]).getByRole('button', { name: /Edit details for suite 200/ }),
    );
    expect(within(drawer()).queryByText(/carries a recovery basis/)).toBeNull();
    expect(within(drawer()).queryByRole('alert')).toBeNull();

    // Suite 300's too.
    await user.click(
      within(rows()[2]).getByRole('button', { name: /Edit details for suite 300/ }),
    );
    expect(within(drawer()).queryByText(/carries a recovery basis/)).toBeNull();
  });

  it('keeps the suite-ID-keyed convention working', async () => {
    const user = await refuseWith([
      {
        code: 'INITIAL_VACANCY_ON_OCCUPIED_SUITE',
        path: 'suites[200].initial_vacancy',
        message: 'suite two hundred carries a treatment',
        severity: 'error',
      },
    ]);
    // "200" is the suite id, not index 200 and not index 2.
    await user.click(
      within(rows()[1]).getByRole('button', { name: /Edit details for suite 200/ }),
    );
    expect(within(drawer()).getByText(/suite two hundred carries a treatment/)).toBeTruthy();

    await user.click(
      within(rows()[2]).getByRole('button', { name: /Edit details for suite 300/ }),
    );
    expect(within(drawer()).queryByText(/suite two hundred/)).toBeNull();
  });

  it('does not announce unrelated workspace errors in the drawer', async () => {
    const user = await refuseWith([
      {
        code: 'RENTABLE_AREA_NOT_RECONCILED',
        path: 'property.rentable_area_sf',
        message: 'suite areas do not sum to rentable area',
        severity: 'error',
      },
    ]);
    await user.click(
      within(rows()[0]).getByRole('button', { name: /Edit details for suite 100/ }),
    );
    expect(within(drawer()).queryByText(/do not sum to rentable area/)).toBeNull();
    expect(within(drawer()).queryByRole('alert')).toBeNull();
  });
});

// =============================================================================
// 4. The frontend still invents nothing
// =============================================================================

describe('no client-side rule', () => {
  it('shows nothing before the backend has been asked', async () => {
    const user = await openRentRoll();
    await user.click(
      within(rows()[0]).getByRole('button', { name: /Edit details for suite 100/ }),
    );

    // A lease that is Modified Gross with a stop, then switched to NNN -- the
    // exact invalid state -- and the drawer says nothing, because nothing has
    // been submitted. Only the backend decides.
    await user.selectOptions(within(drawer()).getByLabelText('Lease Type'), 'nnn');
    expect(within(drawer()).queryByRole('alert')).toBeNull();
    expect(within(drawer()).queryByText(/MODIFIED_GROSS/)).toBeNull();
  });

  it('clears the banner once the analyst edits, rather than re-deriving it', async () => {
    const user = await refuseWithLeaseSwitchedTo('nnn', [HIDDEN_RECOVERY_ISSUE]);
    expect(within(drawer()).getByRole('alert')).toBeTruthy();

    // Any edit invalidates the analysis those issues belonged to.
    const tenant = within(drawer()).getByLabelText('Tenant');
    await user.type(tenant, '!');

    expect(within(drawer()).queryByRole('alert')).toBeNull();
  });

  it('does not delete the hidden value when the type changes', async () => {
    mockAnalyze.mockResolvedValue(results());
    const user = await openRentRoll();
    await user.click(
      within(rows()[0]).getByRole('button', { name: /Edit details for suite 100/ }),
    );
    await user.selectOptions(within(drawer()).getByLabelText('Lease Type'), 'gross');

    await user.click(analyzeButton());
    await waitFor(() => {
      expect(mockAnalyze).toHaveBeenCalled();
    });
    const [, inputs] = mockAnalyze.mock.calls[0];
    expect(inputs.leases[0].lease_type).toBe('gross');
    expect(inputs.leases[0].expense_stop_psf).toBe(9.5);
    expect(inputs.leases[0].recovery_basis).toBe('expense_stop_psf');
  });
});

// =============================================================================
// 5. Accessibility
// =============================================================================

describe('accessibility', () => {
  it('announces the banner as an alert, in text', async () => {
    await refuseWithLeaseSwitchedTo('nnn', [HIDDEN_RECOVERY_ISSUE]);

    const banner = within(drawer()).getByRole('alert');
    // Carried by words, not by colour or an icon.
    expect(banner.textContent).toMatch(/carries a recovery basis or expense stop/);
    expect(banner.textContent).toMatch(/not showing a control for/);
  });

  it('keeps field-level aria associations for exact-field issues', async () => {
    const user = await refuseWith([
      {
        code: 'SUITE_AREA_OUT_OF_DOMAIN',
        path: 'suites[0].suite_area_sf',
        message: 'must be greater than zero',
        severity: 'error',
      },
    ]);
    await user.click(
      within(rows()[0]).getByRole('button', { name: /Edit details for suite 100/ }),
    );

    const field = within(drawer()).getByLabelText('Suite Area');
    expect(field.getAttribute('aria-invalid')).toBe('true');
    const ids = (field.getAttribute('aria-describedby') ?? '').split(' ');
    expect(
      ids.map((id) => document.getElementById(id)?.textContent).join(' '),
    ).toContain('must be greater than zero');
    // Its accessible name is still just the label.
    expect(within(drawer()).getByLabelText('Suite Area')).toBe(field);
  });
});
