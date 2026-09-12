/**
 * Phase 6 Gate D6.6 -- the shared Business Plan editor, as a component.
 *
 * Rendered through a small stateful harness so every interaction runs the real
 * add / edit / remove path and the real grouped numeric input.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { BusinessPlanEditor } from './BusinessPlanEditor';
import { blankBusinessPlanDraft, businessPlanDraftFromInput } from '../businessPlan';
import type { BusinessPlanDraft, BusinessPlanFieldIssue } from '../businessPlan';
import { referencePlan } from '../businessPlanFixture';

afterEach(cleanup);

interface HarnessProps {
  initial: BusinessPlanDraft;
  holdPeriod?: string;
  issues?: BusinessPlanFieldIssue[];
  disabled?: boolean;
  onPlan?: (plan: BusinessPlanDraft) => void;
}

function Harness({ initial, holdPeriod = '5', issues = [], disabled = false, onPlan }: HarnessProps) {
  const [plan, setPlan] = useState(initial);
  return (
    <BusinessPlanEditor
      plan={plan}
      onChange={(next) => {
        setPlan(next);
        onPlan?.(next);
      }}
      issues={issues}
      holdPeriod={holdPeriod}
      disabled={disabled}
    />
  );
}

function loaded(): BusinessPlanDraft {
  return businessPlanDraftFromInput(referencePlan());
}

function input(label: string): HTMLInputElement {
  return screen.getByLabelText(label) as HTMLInputElement;
}

describe('the empty state (U1)', () => {
  it('is a clean optional section with no rows, no inputs and no sample values', () => {
    const { container } = render(<Harness initial={blankBusinessPlanDraft()} />);
    expect(screen.getByRole('heading', { name: 'Business Plan' })).toBeTruthy();
    expect(screen.getByText('Optional')).toBeTruthy();
    expect(screen.getByText('Model project capital and owner-level expenses below NOI.')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Project Capital' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Owner Expenses' })).toBeTruthy();
    expect(screen.getByText('No project capital scheduled.')).toBeTruthy();
    expect(screen.getByText('No owner expenses scheduled.')).toBeTruthy();
    expect(container.querySelectorAll('input, select, table')).toHaveLength(0);
    expect(container.textContent).not.toMatch(/\d{2},\d{3}/);
    expect(screen.getByRole('button', { name: 'Add Project Capital' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Add Owner Expense' })).toBeTruthy();
  });

  it('separates Project Capital from the recurring reserve and TI / LC in its own words', () => {
    const { container } = render(<Harness initial={blankBusinessPlanDraft()} />);
    // Read as whole sentences: "TI / LC" sits in its own no-wrap span.
    const hints = [...container.querySelectorAll('.business-plan-hint')].map((hint) =>
      hint.textContent?.replace(/\s+/g, ' ').trim(),
    );
    expect(hints).toEqual([
      'One-time owner capital at closing, during the hold, or post-hold. Excludes recurring CapEx Reserve and TI / LC.',
      'Owner-level annual costs below NOI. Excludes property operating expenses and property management fees.',
    ]);
    expect(container.querySelector('.business-plan-nowrap')?.textContent).toBe('TI / LC');
  });

  it('teaches with one subordinate example line per empty part, and fabricates nothing', () => {
    const { container } = render(<Harness initial={blankBusinessPlanDraft()} />);
    const examples = [...container.querySelectorAll('.business-plan-empty-example')].map(
      (element) => element.textContent,
    );
    expect(examples).toEqual([
      'Examples: closing improvements, renovations, major building systems.',
      'Examples: asset management, partnership legal costs.',
    ]);
    // An empty part carries no item count and no row.
    expect(container.querySelectorAll('.business-plan-count')).toHaveLength(0);
    expect(container.querySelectorAll('tbody tr')).toHaveLength(0);
  });
});

describe('adding rows (PART AI)', () => {
  it('adds a blank Project Capital row and focuses its Description', async () => {
    const user = userEvent.setup();
    const seen: BusinessPlanDraft[] = [];
    render(<Harness initial={blankBusinessPlanDraft()} onPlan={(plan) => seen.push(plan)} />);
    await user.click(screen.getByRole('button', { name: 'Add Project Capital' }));

    const description = input('Description, new Project Capital item');
    expect(document.activeElement).toBe(description);
    expect(description.value).toBe('');
    expect((screen.getByLabelText('Category, new Project Capital item') as HTMLSelectElement).value).toBe('');
    expect(input('Model Month, new Project Capital item').value).toBe('');
    expect(input('Amount, new Project Capital item').value).toBe('');
    expect(screen.getByText('1 item')).toBeTruthy();
    expect(seen.at(-1)?.capitalItems).toHaveLength(1);
  });

  it('adds a blank Owner Expense row whose Last Year reads as through hold', async () => {
    const user = userEvent.setup();
    render(<Harness initial={blankBusinessPlanDraft()} />);
    await user.click(screen.getByRole('button', { name: 'Add Owner Expense' }));
    expect(document.activeElement).toBe(input('Description, new Owner Expense item'));
    const lastYear = input('Last Year, new Owner Expense item');
    expect(lastYear.value).toBe('');
    expect(lastYear.placeholder).toBe('Through Hold');
    expect(screen.getByText('Leave blank for Through Hold.')).toBeTruthy();
  });

  it('keeps an ID minted once, and never shows it, through typing', async () => {
    const user = userEvent.setup();
    const seen: BusinessPlanDraft[] = [];
    const { container } = render(
      <Harness initial={blankBusinessPlanDraft()} onPlan={(plan) => seen.push(plan)} />,
    );
    await user.click(screen.getByRole('button', { name: 'Add Project Capital' }));
    const minted = seen[0].capitalItems[0].itemId;
    await user.type(input('Description, new Project Capital item'), 'Roof');
    await user.type(input('Model Month, Roof'), '24');
    await user.type(input('Amount, Roof'), '500000');
    expect(new Set(seen.map((plan) => plan.capitalItems[0].itemId))).toEqual(new Set([minted]));
    expect(container.textContent).not.toContain(minted);
    for (const element of container.querySelectorAll('input')) {
      expect((element as HTMLInputElement).value).not.toBe(minted);
    }
  });
});

describe('a loaded plan (PART W, AJ-AM)', () => {
  it('renders every row in the stored order, with its values', () => {
    render(<Harness initial={loaded()} />);
    const descriptions = screen
      .getAllByLabelText(/^Description, /)
      .map((element) => (element as HTMLInputElement).value);
    expect(descriptions).toEqual([
      'Closing Improvements',
      'Unit Renovations',
      'Future Roof',
      'Asset Management',
      'Legal',
    ]);
    expect(screen.getByText('3 items')).toBeTruthy();
    expect(screen.getByText('2 items')).toBeTruthy();
  });

  it('labels each category and persists its enum token', () => {
    render(<Harness initial={loaded()} />);
    const category = screen.getByLabelText('Category, Future Roof') as HTMLSelectElement;
    expect(category.value).toBe('deferred_maintenance');
    expect(within(category).getAllByRole('option').map((option) => option.textContent)).toEqual([
      'Select…',
      'Value-Add Renovation',
      'Deferred Maintenance',
      'Building Systems',
      'Exterior / Common Area',
      'Other',
    ]);
    const owner = screen.getByLabelText('Category, Legal') as HTMLSelectElement;
    expect(within(owner).getAllByRole('option').map((option) => option.textContent)).toEqual([
      'Select…',
      'Asset Management',
      'Legal / Partnership',
      'Other',
    ]);
  });

  it('groups dollar amounts while not editing them', () => {
    render(<Harness initial={loaded()} />);
    expect(input('Amount, Closing Improvements').value).toBe('250,000');
    expect(input('Amount, Unit Renovations').value).toBe('1,000,000');
    expect(input('Annual Amount, Asset Management').value).toBe('50,000');
  });

  it('shows raw digits while editing and stores no separator', async () => {
    const user = userEvent.setup();
    const seen: BusinessPlanDraft[] = [];
    render(<Harness initial={loaded()} onPlan={(plan) => seen.push(plan)} />);
    const amount = input('Amount, Unit Renovations');
    await user.click(amount);
    expect(amount.value).toBe('1000000');
    await user.clear(amount);
    await user.type(amount, '30000000');
    await user.tab();
    expect(amount.value).toBe('30,000,000');
    expect(seen.at(-1)?.capitalItems[1].amount).toBe('30000000');
  });

  it('tags month 0 as Closing, 18 as Year 2 and 61 as Post-Hold on a five-year hold', () => {
    render(<Harness initial={loaded()} />);
    expect(screen.getByText('Closing')).toBeTruthy();
    expect(screen.getByText('Year 2')).toBeTruthy();
    expect(screen.getByText('Post-Hold')).toBeTruthy();
    expect(input('Model Month, Closing Improvements').value).toBe('0');
    expect(screen.getByText('0 = Closing')).toBeTruthy();
  });

  it('reclassifies the tag, and only the tag, when the hold changes', () => {
    const { rerender } = render(<Harness initial={loaded()} holdPeriod="5" />);
    expect(screen.getByText('Post-Hold')).toBeTruthy();
    rerender(<Harness initial={loaded()} holdPeriod="6" />);
    expect(screen.queryByText('Post-Hold')).toBeNull();
    expect(screen.getByText('Year 6')).toBeTruthy();
    expect(input('Model Month, Future Roof').value).toBe('61');
  });

  it('shows a through-hold Last Year as blank, and zero as zero', () => {
    const plan = loaded();
    plan.capitalItems[0] = { ...plan.capitalItems[0], amount: '0' };
    render(<Harness initial={plan} />);
    expect(input('Last Year, Asset Management').value).toBe('');
    expect(input('Last Year, Legal').value).toBe('3');
    expect(input('Amount, Closing Improvements').value).toBe('0');
  });
});

describe('removing rows (PART M)', () => {
  it('removes one row by its accessible name and returns focus to the section', async () => {
    const user = userEvent.setup();
    const seen: BusinessPlanDraft[] = [];
    render(<Harness initial={loaded()} onPlan={(plan) => seen.push(plan)} />);
    await user.click(screen.getByRole('button', { name: 'Remove Unit Renovations' }));
    expect(screen.queryByDisplayValue('Unit Renovations')).toBeNull();
    expect(seen.at(-1)?.capitalItems.map((item) => item.itemId)).toEqual(['cap-closing', 'cap-roof']);
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Add Project Capital' }));
  });

  it('can clear every row, leaving the empty state', async () => {
    const user = userEvent.setup();
    render(<Harness initial={loaded()} />);
    for (const button of screen.getAllByRole('button', { name: /^Remove / })) {
      await user.click(button);
    }
    expect(screen.getByText('No project capital scheduled.')).toBeTruthy();
    expect(screen.getByText('No owner expenses scheduled.')).toBeTruthy();
  });
});

describe('keyboard (U12)', () => {
  it('tabs through a capital row in reading order, then on to the next row', async () => {
    const user = userEvent.setup();
    render(<Harness initial={loaded()} />);
    input('Description, Closing Improvements').focus();
    const order = [
      'Category, Closing Improvements',
      'Model Month, Closing Improvements',
      'Amount, Closing Improvements',
      'Remove Closing Improvements',
      'Description, Unit Renovations',
    ];
    for (const name of order) {
      await user.tab();
      expect(
        document.activeElement?.getAttribute('aria-label'),
        `expected focus on ${name}`,
      ).toBe(name);
    }
  });

  it('tabs through an owner-expense row, Last Year included, to Remove', async () => {
    const user = userEvent.setup();
    render(<Harness initial={loaded()} />);
    input('Description, Legal').focus();
    for (const name of [
      'Category, Legal',
      'Annual Amount, Legal',
      'First Year, Legal',
      'Last Year, Legal',
      'Remove Legal',
    ]) {
      await user.tab();
      expect(document.activeElement?.getAttribute('aria-label')).toBe(name);
    }
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Add Owner Expense' }));
  });

  it('removes a row from the keyboard', async () => {
    const user = userEvent.setup();
    render(<Harness initial={loaded()} />);
    screen.getByRole('button', { name: 'Remove Legal' }).focus();
    await user.keyboard('{Enter}');
    expect(screen.queryByDisplayValue('Legal')).toBeNull();
  });
});

describe('issues (U10, PART P)', () => {
  it('marks the field, associates the message and keeps the value', () => {
    render(
      <Harness
        initial={loaded()}
        issues={[
          { collection: 'capital', itemId: 'cap-renovation', field: 'amount', message: 'Amount must be 0 or greater.' },
          { collection: 'owner_expense', itemId: 'oe-legal', field: null, message: 'Duplicate item.' },
          { collection: null, itemId: null, field: null, message: 'business_plan must be an object.' },
        ]}
      />,
    );
    const amount = input('Amount, Unit Renovations');
    expect(amount.getAttribute('aria-invalid')).toBe('true');
    const describedBy = amount.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy!)?.textContent).toBe('Amount must be 0 or greater.');
    expect(amount.value).toBe('1,000,000');
    expect(screen.getByText('Duplicate item.')).toBeTruthy();
    expect(screen.getByText('business_plan must be an object.')).toBeTruthy();
    // Unaffected fields stay unmarked.
    expect(input('Amount, Closing Improvements').getAttribute('aria-invalid')).toBeNull();
  });

  it('keeps the timing tag described alongside a month error', () => {
    render(
      <Harness
        initial={loaded()}
        issues={[{ collection: 'capital', itemId: 'cap-roof', field: 'month', message: 'Bad month.' }]}
      />,
    );
    const month = input('Model Month, Future Roof');
    const ids = (month.getAttribute('aria-describedby') ?? '').split(' ');
    expect(ids.map((id) => document.getElementById(id)?.textContent)).toEqual([
      'Bad month.',
      'Post-Hold',
    ]);
  });
});

describe('presentation (D6.6 polish)', () => {
  it('shows each timing state as a tag beside its month, never as a control', () => {
    const { container } = render(<Harness initial={loaded()} />);
    const tags = [...container.querySelectorAll('.business-plan-timing')];
    expect(tags.map((tag) => [tag.textContent, tag.className])).toEqual([
      ['Closing', 'business-plan-timing business-plan-timing-closing'],
      ['Year 2', 'business-plan-timing business-plan-timing-hold'],
      ['Post-Hold', 'business-plan-timing business-plan-timing-post-hold'],
    ]);
    for (const tag of tags) {
      // Text beside the authoritative input: same cell, not focusable, not a field.
      expect(tag.closest('.business-plan-month')?.querySelector('input')).toBeTruthy();
      expect(tag.tagName).toBe('SPAN');
      expect(tag.getAttribute('tabindex')).toBeNull();
    }
    expect(input('Model Month, Future Roof').value).toBe('61');
  });

  it('presents a blank Last Year as the Through Hold state while keeping the value blank', async () => {
    const user = userEvent.setup();
    const seen: BusinessPlanDraft[] = [];
    const { container } = render(<Harness initial={loaded()} onPlan={(plan) => seen.push(plan)} />);
    const states = () =>
      [...container.querySelectorAll('.business-plan-empty-state')].map((state) => [
        state.textContent,
        state.getAttribute('aria-hidden'),
      ]);
    // Asset Management runs through the hold; Legal ends in Year 3.
    expect(states()).toEqual([['Through Hold', 'true']]);
    expect(input('Last Year, Asset Management').value).toBe('');
    expect(input('Last Year, Asset Management').placeholder).toBe('Through Hold');

    // Typing a year replaces the state; clearing it brings the state back.
    await user.type(input('Last Year, Asset Management'), '4');
    expect(states()).toEqual([]);
    await user.clear(input('Last Year, Asset Management'));
    expect(states()).toEqual([['Through Hold', 'true']]);
    expect(seen.at(-1)?.ownerExpenseItems[0].lastYear).toBe('');
  });

  it('renders item counts as metadata beside the subsection title', () => {
    const { container } = render(<Harness initial={loaded()} />);
    const counts = [...container.querySelectorAll('.business-plan-group-head .business-plan-count')];
    expect(counts.map((count) => count.textContent)).toEqual(['3 items', '2 items']);
  });

  it('keeps Remove a quiet text action and Add a secondary action', () => {
    render(<Harness initial={loaded()} />);
    for (const remove of screen.getAllByRole('button', { name: /^Remove / })) {
      expect(remove.className).toBe('business-plan-remove');
      expect(remove.textContent).toBe('Remove');
    }
    for (const name of ['Add Project Capital', 'Add Owner Expense']) {
      const add = screen.getByRole('button', { name });
      expect(add.className).toContain('btn-secondary');
      expect(add.className).not.toContain('btn-primary');
    }
  });

  it('shows the model-month key and the Last Year key only beside rows that use them', () => {
    render(<Harness initial={loaded()} />);
    expect(screen.getByText('0 = Closing · 1–12 = Year 1 · 13–24 = Year 2 · etc.')).toBeTruthy();
    expect(screen.getByText('Leave blank for Through Hold.')).toBeTruthy();
    cleanup();
    render(<Harness initial={blankBusinessPlanDraft()} />);
    expect(screen.queryByText('0 = Closing · 1–12 = Year 1 · 13–24 = Year 2 · etc.')).toBeNull();
    expect(screen.queryByText('Leave blank for Through Hold.')).toBeNull();
  });
});

describe('rendering hygiene', () => {
  it('disables every control while a request is in flight', () => {
    const { container } = render(<Harness initial={loaded()} disabled />);
    for (const control of container.querySelectorAll('input, select, button')) {
      expect((control as HTMLInputElement).disabled).toBe(true);
    }
  });

  it('renders a populated plan without React warnings', () => {
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<Harness initial={loaded()} />);
    expect(errors).not.toHaveBeenCalled();
    errors.mockRestore();
  });
});
