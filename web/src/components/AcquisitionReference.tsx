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
 *
 * **Fail closed** (Stage 3 correction round). While it is not yet known
 * whether a refinance is configured -- the read is in flight, or it failed --
 * those two figures are withheld rather than shown as if no refinance existed,
 * and a failure says so with a Retry. Only a settled answer shows them.
 */

import { ACQUISITION_REFERENCE_LABEL } from '../refinanceCatalog';
import type { RefinancePresence } from '../useRefinancePresence';

// prettier-ignore
export const REFINANCE_REFERENCE_NOTICE =
  'This deal’s Capital Structure includes a refinance. The levered IRR and equity multiple here hold the acquisition loan to the sale, so they are the acquisition-financing reference and exclude later capital events. The refinance-adjusted return is Common Equity after Capital Structure, in Risk → Capital Structure.';

// prettier-ignore
export const INVESTMENT_REFINANCE_REFERENCE_NOTICE =
  'This Investment’s Capital Structure includes a refinance. The levered IRR and equity multiple here hold each acquisition loan to the sale, so they are the acquisition-financing reference and exclude later capital events. The refinance-adjusted return is Common Equity after Capital Structure, in Risk → Capital Structure.';

// prettier-ignore
export const REFERENCE_CHECKING_NOTICE =
  'Checking the Capital Structure for a refinance. The levered IRR and equity multiple appear once that is known.';

// prettier-ignore
export const REFERENCE_ERROR_NOTICE =
  'Whether the Capital Structure includes a refinance could not be read, so the levered IRR and equity multiple are withheld: without that answer they could be mistaken for the refinance-adjusted return.';

export { ACQUISITION_REFERENCE_LABEL };
export { REFERENCE_CHECKING_VALUE, REFERENCE_WITHHELD_VALUE } from '../useRefinancePresence';

/** The notice for the current presence: the reference note when a refinance
 * is configured, a status while it is being read, an error with Retry when the
 * read failed, and nothing for a settled "no refinance". */
export function RefinanceReferenceNotice({
  presence,
  subject = 'deal',
}: {
  presence: RefinancePresence;
  subject?: 'deal' | 'investment';
}) {
  if (presence.status === 'loading') {
    return (
      <p className="refinance-reference-notice refinance-reference-checking" role="status">
        {REFERENCE_CHECKING_NOTICE}
      </p>
    );
  }
  if (presence.status === 'error') {
    return (
      <div className="refinance-reference-notice refinance-reference-error" role="alert">
        <span>{REFERENCE_ERROR_NOTICE}</span>
        <button type="button" className="btn btn-ghost btn-xs" onClick={presence.retry}>
          Retry
        </button>
      </div>
    );
  }
  if (!presence.configured) {
    return null;
  }
  return (
    <p className="refinance-reference-notice" role="note">
      {subject === 'investment' ? INVESTMENT_REFINANCE_REFERENCE_NOTICE : REFINANCE_REFERENCE_NOTICE}
    </p>
  );
}
