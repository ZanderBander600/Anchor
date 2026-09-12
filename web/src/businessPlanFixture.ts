/**
 * Phase 6 Gate D6.6 -- the reference Business Plan the D6.6 suites share.
 *
 * Test-only data, named without `.test.` because several test files import it
 * (the same reason `hiddenIssuesFixture.ts` and `leaseLevelDealFixture.ts` exist).
 * No production module imports it.
 *
 * The gate's API-created plan (PART AO): three Project Capital items -- closing,
 * in the hold, and after a five-year hold -- and two Owner Expenses, one of them
 * through the hold. Deliberately in neither category nor ID order, so a sort
 * anywhere on the way through would show.
 */

import type { BusinessPlanInput } from './businessPlan';

export function referencePlan(): BusinessPlanInput {
  return {
    capital_items: [
      {
        item_id: 'cap-closing',
        description: 'Closing Improvements',
        category: 'building_systems',
        month: 0,
        amount: 250000,
      },
      {
        item_id: 'cap-renovation',
        description: 'Unit Renovations',
        category: 'value_add_renovation',
        month: 18,
        amount: 1000000,
      },
      {
        item_id: 'cap-roof',
        description: 'Future Roof',
        category: 'deferred_maintenance',
        month: 61,
        amount: 500000,
      },
    ],
    owner_expense_items: [
      {
        item_id: 'oe-asset-management',
        description: 'Asset Management',
        category: 'asset_management',
        annual_amount: 50000,
        first_year: 1,
        last_year: null,
      },
      {
        item_id: 'oe-legal',
        description: 'Legal',
        category: 'legal_partnership',
        annual_amount: 15000,
        first_year: 2,
        last_year: 3,
      },
    ],
  };
}
