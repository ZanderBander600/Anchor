/**
 * Phase 7 Gate P7.6 -- the New Investment builder.
 *
 * Name the Investment, state its Transaction Price, and choose saved Deals as
 * its Units, each with an optional label and a Unit Kind. Each Deal's own
 * stored purchase price and hold are shown beside it, read off its contract;
 * nothing is totalled and the Transaction Price is never proposed. The
 * backend's reconciliation decides, and its refusal is shown here, at the
 * price, in its own words with each Unit named.
 *
 * A Deal that already has Strategies or Scenarios is promoted: its hidden
 * decision set becomes this Investment -- the same Investment, kept exactly.
 * A Deal that is already a Unit of a visible Investment is shown as such; if
 * chosen anyway, the backend's refusal is shown.
 */

import { formatCurrency } from '../format';
import {
  storedHoldPeriod,
  storedPurchasePrice,
  TRANSACTION_PRICE_NOTE,
  UNIT_KIND_NOTE,
  UNIT_KIND_OPTIONS,
} from '../investmentCatalog';
import type { UnitKind, VisibleInvestment } from '../investmentTypes';
import { operatingModeLabel } from '../operatingMode';
import type { Deal } from '../types';
import { useNewInvestment } from '../useNewInvestment';
import type { DealDiscovery } from '../useNewInvestment';
import { InvestmentIssueList } from './InvestmentIssueList';
import { NumericInput } from './NumericInput';

export interface NewInvestmentPanelProps {
  deals: Deal[];
  investments: VisibleInvestment[];
  onCreated: (investment: VisibleInvestment) => void;
  onCancel: () => void;
}

function holdText(hold: number | null): string {
  return hold === null ? 'N/A' : `${hold} yrs`;
}

function counted(count: number, singular: string, plural: string): string {
  return count === 1 ? `1 ${singular}` : `${count} ${plural}`;
}

function discoveryText(found: DealDiscovery | undefined): string | null {
  if (found === undefined) {
    return null;
  }
  switch (found.status) {
    case 'checking':
      return 'Checking for existing strategies and scenarios…';
    case 'standalone':
      return 'Standalone';
    case 'hidden':
      return `Has ${counted(found.strategyCount, 'strategy', 'strategies')} and ${counted(found.scenarioCount, 'scenario', 'scenarios')}: they are kept, and this deal's decision set becomes the Investment.`;
    case 'unavailable':
      return found.message;
  }
}

export function NewInvestmentPanel({ deals, investments, onCreated, onCancel }: NewInvestmentPanelProps) {
  const builder = useNewInvestment({ onCreated });
  const feedback = builder.feedback;
  const names = Object.fromEntries(deals.map((deal) => [deal.id, deal.name]));
  const memberOf = (dealId: string) => investments.find((investment) => investment.units.some((unit) => unit.unit_id === dealId));

  return (
    <section className="card investment-builder" aria-labelledby="new-investment-title">
      <div className="card-title-row deal-library-header">
        <div>
          <h3 className="card-title" id="new-investment-title">
            New Investment
          </h3>
          <p className="card-subtitle">
            One transaction over one or more saved Deals. Each Deal becomes a Unit and keeps its own
            underwriting.
          </p>
        </div>
      </div>

      {feedback !== null && (
        <div className="error-banner investment-feedback" role="alert">
          <p className="scenario-editor-feedback-message">{feedback.message}</p>
          <InvestmentIssueList issues={feedback.general} names={names} />
        </div>
      )}

      <div className="investment-builder-fields">
        <div className="field">
          <label className="field-label" htmlFor="new-investment-name">
            Investment Name
          </label>
          <input
            id="new-investment-name"
            className="field-input"
            type="text"
            value={builder.name}
            onChange={(event) => builder.setName(event.target.value)}
            autoComplete="off"
            aria-invalid={(feedback?.name.length ?? 0) > 0 ? true : undefined}
            aria-describedby={(feedback?.name.length ?? 0) > 0 ? 'new-investment-name-issues' : undefined}
          />
          {feedback !== null && feedback.name.length > 0 && (
            <ul id="new-investment-name-issues" className="investment-issues" role="alert">
              {feedback.name.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          )}
        </div>
        <div className="field">
          <label className="field-label" htmlFor="new-investment-price">
            Transaction Price
          </label>
          <div className="field-input-wrap">
            <span className="field-affix field-affix-left">$</span>
            <NumericInput
              id="new-investment-price"
              className="field-input"
              value={builder.price}
              onChange={builder.setPrice}
              group
              style={{ paddingLeft: '1.4rem' }}
              aria-invalid={(feedback?.price.length ?? 0) > 0 ? true : undefined}
              aria-describedby="new-investment-price-note"
            />
          </div>
          <InvestmentIssueList issues={feedback?.price ?? []} names={names} id="new-investment-price-issues" />
        </div>
      </div>
      <p className="investment-note" id="new-investment-price-note">
        {TRANSACTION_PRICE_NOTE}
      </p>

      <fieldset className="investment-builder-units">
        <legend className="investment-section-label">Units</legend>
        <p className="investment-note">
          Choose saved Deals. Each Deal&apos;s own stored purchase price and hold are shown for reference.
        </p>
        {deals.length === 0 ? (
          <p className="scenario-muted">No saved deals yet. Save a deal first.</p>
        ) : (
          <div className="investment-table-scroll" role="region" aria-label="Deals to include" tabIndex={0}>
            <table className="investment-table investment-builder-table">
              <caption className="visually-hidden">Saved deals that can become units</caption>
              <thead>
                <tr>
                  <th scope="col">
                    <span className="visually-hidden">Include</span>
                  </th>
                  <th scope="col">Deal</th>
                  <th scope="col">Mode</th>
                  <th scope="col" className="investment-num">
                    Purchase Price
                  </th>
                  <th scope="col" className="investment-num">
                    Hold
                  </th>
                  <th scope="col">Label</th>
                  <th scope="col">Unit Kind</th>
                </tr>
              </thead>
              <tbody>
                {deals.map((deal) => {
                  const chosen = builder.selection.find((selection) => selection.dealId === deal.id);
                  const member = memberOf(deal.id);
                  const status =
                    member !== undefined ? `Unit of ${member.name}` : discoveryText(builder.discovery[deal.id]);
                  return (
                    <tr key={deal.id} className={chosen !== undefined ? 'investment-row-selected' : undefined}>
                      <td className="investment-check-cell">
                        <input
                          type="checkbox"
                          id={`new-investment-include-${deal.id}`}
                          checked={chosen !== undefined}
                          onChange={() => builder.toggle(deal)}
                          aria-label={`Include ${deal.name}`}
                        />
                      </td>
                      <th scope="row" className="investment-name-cell">
                        <label htmlFor={`new-investment-include-${deal.id}`}>{deal.name}</label>
                        {status !== null && <span className="investment-row-note">{status}</span>}
                      </th>
                      <td>{operatingModeLabel(deal.operating_mode)}</td>
                      <td className="investment-num">{formatCurrency(storedPurchasePrice(deal))}</td>
                      <td className="investment-num">{holdText(storedHoldPeriod(deal))}</td>
                      <td>
                        <input
                          className="field-input investment-compact-input"
                          type="text"
                          value={chosen?.label ?? ''}
                          onChange={(event) => builder.setLabel(deal.id, event.target.value)}
                          disabled={chosen === undefined}
                          aria-label={`Label for ${deal.name}`}
                          autoComplete="off"
                        />
                      </td>
                      <td>
                        <select
                          className="field-input investment-compact-input"
                          value={chosen?.kind ?? 'property'}
                          onChange={(event) => builder.setKind(deal.id, event.target.value as UnitKind)}
                          disabled={chosen === undefined}
                          aria-label={`Unit Kind for ${deal.name}`}
                        >
                          {UNIT_KIND_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="investment-note">{UNIT_KIND_NOTE}</p>
        <InvestmentIssueList issues={feedback?.units ?? []} names={names} id="new-investment-unit-issues" />
      </fieldset>

      <div className="scenario-editor-actions">
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel} disabled={builder.isCreating}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => void builder.create()}
          disabled={builder.isCreating || builder.isChecking}
        >
          {builder.isCreating ? 'Creating…' : 'Create Investment'}
        </button>
      </div>
    </section>
  );
}
