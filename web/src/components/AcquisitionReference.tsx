/**
 * Refinance & Capital Events V1 Stage 3 -- the acquisition-financing reference,
 * named where an existing surface still shows it.
 *
 * With a refinance configured in the Base Capital Structure, the Project
 * levered IRR and equity multiple hold the acquisition loan to the sale. They
 * may appear only under the label "Acquisition financing — excludes later
 * capital events", never as the refinance-adjusted headline (R-P rules 3 to
 * 5). This notice says so once, above the figures it qualifies, and points to
 * where the refinance-adjusted return is.
 */

import { ACQUISITION_REFERENCE_LABEL } from '../refinanceCatalog';

// prettier-ignore
export const REFINANCE_REFERENCE_NOTICE =
  'This deal’s Capital Structure includes a refinance. The levered IRR and equity multiple here hold the acquisition loan to the sale, so they are the acquisition-financing reference and exclude later capital events. The refinance-adjusted return is Common Equity after Capital Structure, in Risk → Capital Structure.';

// prettier-ignore
export const INVESTMENT_REFINANCE_REFERENCE_NOTICE =
  'This Investment’s Capital Structure includes a refinance. The levered IRR and equity multiple here hold each acquisition loan to the sale, so they are the acquisition-financing reference and exclude later capital events. The refinance-adjusted return is Common Equity after Capital Structure, in Risk → Capital Structure.';

export { ACQUISITION_REFERENCE_LABEL };

/** The notice, naming the Deal or the Investment whose structure it is. */
export function RefinanceReferenceNotice({ subject = 'deal' }: { subject?: 'deal' | 'investment' }) {
  return (
    <p className="refinance-reference-notice" role="note">
      {subject === 'investment' ? INVESTMENT_REFINANCE_REFERENCE_NOTICE : REFINANCE_REFERENCE_NOTICE}
    </p>
  );
}
