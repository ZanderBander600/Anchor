/**
 * Phase 7 Gate P7.6 -- the way back from a Unit to its Investment.
 *
 * Shown above the Deal workspace when the analyst opened the Deal from an
 * Investment's Units. A restrained breadcrumb: the Investment's name, then the
 * Unit's underwriting, and one action back. Returning re-reads the Investment,
 * so a Unit saved in the meantime is never assumed unchanged.
 */

export interface InvestmentReturnBarProps {
  investmentName: string;
  onBack: () => void;
}

export function InvestmentReturnBar({ investmentName, onBack }: InvestmentReturnBarProps) {
  return (
    <nav className="investment-return-bar" aria-label="Investment breadcrumb">
      <button type="button" className="investment-return-button" onClick={onBack}>
        <span aria-hidden="true">←</span> Back to Investment
      </button>
      <ol className="investment-return-trail">
        <li>{investmentName}</li>
        <li aria-current="page">Unit underwriting</li>
      </ol>
    </nav>
  );
}
