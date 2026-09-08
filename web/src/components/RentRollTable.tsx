/**
 * D5.5B -- the rent roll, one row per suite.
 *
 * **One primary grid, not two.** D4 acquisition supports at most one known lease
 * per suite, so a suite-centric row matches the capability exactly. Two
 * independent tables cross-referenced by hand on `suite_id` would make the
 * analyst maintain a join the model does not have, and would let a lease name a
 * suite that does not exist -- which this shape makes unreachable, because the
 * row owns the `suite_id` its lease is sent with.
 *
 * The transport is unchanged: `suites: [...]` and `leases: [...]` still travel
 * as two flat arrays. The single grid is UI composition only.
 *
 * **The grid holds what an analyst scans**; everything else lives in the
 * drawer. Nine columns fit a rent roll on screen at once, which is what makes a
 * rollover cluster or a rent outlier visible. Forcing all twenty-odd suite and
 * lease fields into the row would produce a table nobody can read and would
 * still not fit.
 *
 * **It computes no economics.** Area is added -- integers the analyst typed,
 * approved at D5.0 as an input aid -- and nothing else. No rent total, no
 * average, no WALT, no occupancy percentage.
 */

import type { ChangeEvent } from 'react';
import { LEASE_TYPE_OPTIONS, isRowOccupied } from '../leaseLevelConvert';
import type { SuiteRowFormValues } from '../leaseLevelTypes';
import type { RowIssues } from '../leaseLevelIssues';

export interface RentRollTableProps {
  rows: SuiteRowFormValues[];
  /** Backend issues already resolved to the row that produced them. */
  issuesByRow: Map<string, RowIssues>;
  disabled: boolean;
  onSuiteFieldChange: (rowId: string, key: 'suiteId' | 'suiteAreaSf' | 'marketRentPsf', value: string) => void;
  onLeaseFieldChange: (
    rowId: string,
    key: 'tenantName' | 'leaseExpirationDate' | 'baseRentPsf' | 'leaseType',
    value: string,
  ) => void;
  onToggleOccupancy: (rowId: string) => void;
  onOpenEditor: (rowId: string) => void;
  onDeleteRow: (rowId: string) => void;
  onAddRow: () => void;
}

/** The message for one field of one row, or undefined. */
function fieldError(issues: RowIssues | undefined, field: string): string | undefined {
  return issues?.fields.get(field)?.message;
}

interface CellInputProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  error?: string;
  type?: 'text' | 'number' | 'date';
  placeholder?: string;
}

/**
 * One editable cell.
 *
 * The visible column header names the field for a sighted analyst; `aria-label`
 * names it *and its row* for everyone else, because "Base Rent" repeated down a
 * column tells a screen-reader user nothing about which suite they are in.
 */
function CellInput({
  id,
  label,
  value,
  onChange,
  disabled,
  error,
  type = 'text',
  placeholder,
}: CellInputProps) {
  return (
    <>
      <input
        id={id}
        className="rent-roll-input"
        type={type}
        inputMode={type === 'number' ? 'decimal' : undefined}
        step={type === 'number' ? 'any' : undefined}
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        aria-label={label}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(event.target.value)}
      />
      {error && (
        <span className="field-error" id={`${id}-error`} role="alert">
          {error}
        </span>
      )}
    </>
  );
}

export function RentRollTable({
  rows,
  issuesByRow,
  disabled,
  onSuiteFieldChange,
  onLeaseFieldChange,
  onToggleOccupancy,
  onOpenEditor,
  onDeleteRow,
  onAddRow,
}: RentRollTableProps) {
  return (
    <div className="rent-roll">
      <div className="table-scroll">
        <table className="rent-roll-table">
          <caption className="visually-hidden">
            Rent roll: one row per suite, with the suite&rsquo;s current lease where
            it has one.
          </caption>
          <thead>
            <tr>
              <th scope="col">Suite</th>
              <th scope="col">Area SF</th>
              <th scope="col">Status</th>
              <th scope="col">Tenant</th>
              <th scope="col">Lease Expiration</th>
              <th scope="col">Base Rent /SF</th>
              <th scope="col">Lease Type</th>
              <th scope="col">Suite Market Rent</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const issues = issuesByRow.get(row.rowId);
              const occupied = isRowOccupied(row);
              // A row whose suite is not named yet is "new suite". Deliberately
              // not a computed row number: the table already conveys position
              // to assistive technology, and restating it here would duplicate
              // what the row semantics say -- and would be arithmetic in a
              // module that is audited for having none.
              const name = row.suiteId.trim() === '' ? 'new suite' : `suite ${row.suiteId}`;
              return (
                <tr key={row.rowId} className={issues?.hasError ? 'rent-roll-row-error' : undefined}>
                  <th scope="row">
                    <CellInput
                      id={`suite-id-${row.rowId}`}
                      label={`Suite, ${name}`}
                      value={row.suiteId}
                      onChange={(next) => onSuiteFieldChange(row.rowId, 'suiteId', next)}
                      disabled={disabled}
                      error={fieldError(issues, 'suite_id')}
                    />
                  </th>
                  <td>
                    <CellInput
                      id={`suite-area-${row.rowId}`}
                      label={`Area SF, ${name}`}
                      value={row.suiteAreaSf}
                      onChange={(next) => onSuiteFieldChange(row.rowId, 'suiteAreaSf', next)}
                      disabled={disabled}
                      type="number"
                      error={fieldError(issues, 'suite_area_sf')}
                    />
                  </td>
                  <td>
                    {/* The control edits the lease itself -- there is no status
                        field. A suite is occupied exactly when it has a lease,
                        which is the engine's own rule. The word is rendered
                        beside the control so status is never carried by colour
                        alone. */}
                    <button
                      type="button"
                      className={occupied ? 'status-pill status-occupied' : 'status-pill status-vacant'}
                      disabled={disabled}
                      aria-pressed={occupied}
                      aria-label={`${name} is ${occupied ? 'occupied' : 'vacant'}. Mark ${
                        occupied ? 'vacant' : 'occupied'
                      }.`}
                      onClick={() => onToggleOccupancy(row.rowId)}
                    >
                      {occupied ? 'Occupied' : 'Vacant'}
                    </button>
                    {issues?.vacancyMessage && (
                      <span className="field-error" role="alert">
                        {issues.vacancyMessage}
                      </span>
                    )}
                  </td>
                  <td>
                    {row.lease === null ? (
                      <span className="rent-roll-empty" aria-hidden="true">
                        &mdash;
                      </span>
                    ) : (
                      <CellInput
                        id={`lease-tenant-${row.rowId}`}
                        label={`Tenant, ${name}`}
                        value={row.lease.tenantName}
                        onChange={(next) => onLeaseFieldChange(row.rowId, 'tenantName', next)}
                        disabled={disabled}
                        error={fieldError(issues, 'tenant_name')}
                      />
                    )}
                  </td>
                  <td>
                    {row.lease === null ? (
                      <span className="rent-roll-empty" aria-hidden="true">
                        &mdash;
                      </span>
                    ) : (
                      <CellInput
                        id={`lease-expiration-${row.rowId}`}
                        label={`Lease Expiration, ${name}`}
                        value={row.lease.leaseExpirationDate}
                        onChange={(next) =>
                          onLeaseFieldChange(row.rowId, 'leaseExpirationDate', next)
                        }
                        disabled={disabled}
                        type="date"
                        error={fieldError(issues, 'lease_expiration_date')}
                      />
                    )}
                  </td>
                  <td>
                    {row.lease === null ? (
                      <span className="rent-roll-empty" aria-hidden="true">
                        &mdash;
                      </span>
                    ) : (
                      <CellInput
                        id={`lease-rent-${row.rowId}`}
                        label={`Base Rent per SF, ${name}`}
                        value={row.lease.baseRentPsf}
                        onChange={(next) => onLeaseFieldChange(row.rowId, 'baseRentPsf', next)}
                        disabled={disabled}
                        type="number"
                        error={fieldError(issues, 'base_rent_psf')}
                      />
                    )}
                  </td>
                  <td>
                    {row.lease === null ? (
                      <span className="rent-roll-empty" aria-hidden="true">
                        &mdash;
                      </span>
                    ) : (
                      <select
                        id={`lease-type-${row.rowId}`}
                        className="rent-roll-input"
                        value={row.lease.leaseType}
                        disabled={disabled}
                        aria-label={`Lease Type, ${name}`}
                        onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                          onLeaseFieldChange(row.rowId, 'leaseType', event.target.value)
                        }
                      >
                        <option value="">Select&hellip;</option>
                        {LEASE_TYPE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                  <td>
                    <CellInput
                      id={`suite-market-rent-${row.rowId}`}
                      label={`Suite Market Rent, ${name}`}
                      value={row.marketRentPsf}
                      onChange={(next) => onSuiteFieldChange(row.rowId, 'marketRentPsf', next)}
                      disabled={disabled}
                      type="number"
                      placeholder="Property default"
                      error={fieldError(issues, 'market_rent_psf')}
                    />
                  </td>
                  <td className="rent-roll-actions">
                    <button
                      type="button"
                      className="btn btn-ghost btn-xs"
                      disabled={disabled}
                      aria-label={`Edit details for ${name}`}
                      onClick={() => onOpenEditor(row.rowId)}
                    >
                      Details
                      {issues?.hasDrawerError && (
                        <span className="rent-roll-flag" aria-hidden="true">
                          !
                        </span>
                      )}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-xs"
                      disabled={disabled}
                      aria-label={`Delete ${name}`}
                      onClick={() => onDeleteRow(row.rowId)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {rows.length === 0 && (
        <p className="field-hint">
          No suites yet. Add one row per leasable space &mdash; including vacant
          space, which carries area and is underwritten explicitly rather than
          left out of the roll.
        </p>
      )}

      <div className="rent-roll-toolbar">
        <button type="button" className="btn btn-secondary" disabled={disabled} onClick={onAddRow}>
          Add Suite
        </button>
        <p className="field-hint rent-roll-note">
          {/* Stated once, here, rather than repeated on every row. */}
          Anchor currently supports one known in-place lease per suite. Future
          rollover is modeled from the market leasing assumptions.
        </p>
      </div>
    </div>
  );
}
