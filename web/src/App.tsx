import { useState } from 'react';
import type { FormEvent } from 'react';
import {
  analyzeAcquisition,
  analyzeDetailedAcquisition,
  ApiError,
  createDeal,
  createDetailedDeal,
  deleteDeal,
  duplicateDeal,
  fetchAIAnalysis,
  fetchBreakEvenAnalysis,
  fetchDealFingerprint,
  fetchDetailedAIAnalysis,
  fetchDetailedBreakEvenAnalysis,
  fetchDetailedDealFingerprint,
  fetchDetailedSensitivityPresets,
  fetchSensitivityPresets,
  getDeal,
  listDeals,
  updateDeal,
  updateDealAiSnapshot,
  updateDealAnalysisSnapshot,
  updateDetailedDeal,
  uploadDetailedExcel,
  uploadDetailedOm,
  uploadExcel,
  uploadOm,
} from './api';
import { AiAnalystPanel } from './components/AiAnalystPanel';
import { AssumptionsForm } from './components/AssumptionsForm';
import { BreakEvenPanel } from './components/BreakEvenPanel';
import { DealBar } from './components/DealBar';
import { DealContextField } from './components/DealContextField';
import type { SaveStatus } from './components/DealBar';
import { DealLibraryPanel } from './components/DealLibraryPanel';
import { DetailedAssumptionsForm } from './components/DetailedAssumptionsForm';
import { DetailedExcelReviewPanel } from './components/DetailedExcelReviewPanel';
import { DetailedOmReviewPanel } from './components/DetailedOmReviewPanel';
import { ExcelReviewPanel } from './components/ExcelReviewPanel';
import { ExcelUploadPanel } from './components/ExcelUploadPanel';
import { OmReviewPanel } from './components/OmReviewPanel';
import { OperatingStatementTable } from './components/OperatingStatementTable';
import { OwnerSummaryPanel } from './components/OwnerSummaryPanel';
import { ResultsPanel } from './components/ResultsPanel';
import { SensitivityPanel } from './components/SensitivityPanel';
import { buildOwnerSummaryData } from './ownerSummary';
import {
  BLANK_DETAILED_FORM_VALUES,
  BLANK_FORM_VALUES,
  buildAcquisitionRequest,
  buildAcquisitionTermsRequest,
  buildApprovedDetailedOperatingFormValues,
  buildApprovedDetailedTermsFormValues,
  buildApprovedFormValues,
  buildDetailedFormValuesFromExcelIntakeReport,
  buildDetailedOperatingFormValuesFromRequest,
  buildDetailedOperatingInputsRequest,
  buildDetailedTermsFormValuesFromRequest,
  buildFormValuesFromAcquisitionInputs,
  buildFormValuesFromExcelIntakeReport,
  DEFAULT_TARGET_EQUITY_MULTIPLE,
  DEFAULT_TARGET_HEADLINE_DSCR,
  DEFAULT_TARGET_LEVERED_IRR_PERCENT,
  FormValidationError,
  parseNumber,
  parsePercent,
} from './convert';
import type {
  AcquisitionFieldId,
  AcquisitionFormValues,
  AcquisitionRequest,
  AcquisitionResults,
  AcquisitionTermsFormValues,
  AcquisitionTermsRequest,
  AIAnalysis,
  Deal,
  DetailedAcquisitionResults,
  DetailedExtractionResult,
  DetailedFormValues,
  DetailedOperatingFieldId,
  DetailedOperatingFormValues,
  DetailedOperatingInputsRequest,
  DetailedTermsFieldId,
  ExtractionResult,
  OperatingMode,
  ReturnHurdleMetric,
  StandardBreakEvenAnalysis,
  StandardDetailedBreakEvenAnalysis,
  StandardDetailedSensitivityPresets,
  StandardSensitivityPresets,
  V2FieldId,
} from './types';

/** Owner Return Metrics V3 Gate A6: `Deal.analysis_snapshot`'s type is
 * `AcquisitionResults | DetailedAcquisitionResults | null` at the shared
 * `Deal` shape level (mirroring `inputs` vs. `terms`/
 * `detailed_operating_inputs`), but `Deal` is not a discriminated union
 * TypeScript can narrow purely from `operating_mode` -- this checks the one
 * field only `DetailedAcquisitionResults` has (`operating_projection`,
 * absent from `AcquisitionResults`) to narrow it for real, rather than an
 * unchecked type assertion. */
function isDetailedAnalysisSnapshot(
  snapshot: AcquisitionResults | DetailedAcquisitionResults,
): snapshot is DetailedAcquisitionResults {
  return 'operating_projection' in snapshot;
}

export default function App() {
  // Detailed Operating Model V2.1 Gate 6: Quick/Detailed mode toggle.
  // Detailed mode is a self-contained workspace with its own form and
  // result state below -- it never reads or writes any Quick-mode state
  // (`values`, `results`, `sensitivity`, `breakEven`, `aiAnalysis`, the
  // deal library, etc.), so switching modes can never regress or corrupt
  // Quick's existing behavior. Persistence (Gate 11), sensitivity/break-even
  // UI (Gate 14, reusing `SensitivityPanel`/`BreakEvenPanel`, generalized to
  // accept either mode's contract shape), and the AI Analyst (Gate 9,
  // reusing `AiAnalystPanel`) are all wired below, over Detailed's own
  // independent state -- driven by the deterministic Detailed context/
  // analysis the backend already builds. Detailed's "Generate AI Analysis"
  // request intentionally keeps using the same fixed default hurdle targets
  // Quick mode starts with (`DEFAULT_TARGET_LEVERED_IRR_PERCENT` etc.)
  // rather than the break-even panel's own edited targets -- Gate 14 is a
  // wiring-only gate that explicitly excludes AI changes.
  const [operatingMode, setOperatingMode] = useState<OperatingMode>('quick');

  const [detailedValues, setDetailedValues] = useState<DetailedFormValues>(
    BLANK_DETAILED_FORM_VALUES,
  );
  const [detailedResults, setDetailedResults] = useState<DetailedAcquisitionResults | null>(
    null,
  );
  const [isDetailedSubmitting, setIsDetailedSubmitting] = useState(false);
  const [detailedError, setDetailedError] = useState<string | null>(null);

  // Detailed Operating Model V2.1 Gate 14: Detailed sensitivity/break-even,
  // mirroring Quick's `sensitivity`/`breakEven` state shape exactly, over
  // Detailed's own independent state (never Quick's). `lastDetailedRequest`
  // stores the `terms`/`detailedOperatingInputs` pair just analyzed --
  // the Detailed counterpart of Quick's `lastRequest` -- so a break-even
  // target edit can re-run the search without re-deriving the request.
  const [detailedSensitivity, setDetailedSensitivity] =
    useState<StandardDetailedSensitivityPresets | null>(null);
  const [isDetailedSensitivityLoading, setIsDetailedSensitivityLoading] = useState(false);
  const [detailedSensitivityError, setDetailedSensitivityError] = useState<string | null>(null);
  const [lastDetailedRequest, setLastDetailedRequest] = useState<{
    terms: AcquisitionTermsRequest;
    detailedOperatingInputs: DetailedOperatingInputsRequest;
  } | null>(null);
  const [detailedTargetLeveredIrrPercent, setDetailedTargetLeveredIrrPercent] = useState(
    DEFAULT_TARGET_LEVERED_IRR_PERCENT,
  );
  const [detailedTargetEquityMultiple, setDetailedTargetEquityMultiple] = useState(
    DEFAULT_TARGET_EQUITY_MULTIPLE,
  );
  const [detailedTargetHeadlineDscr, setDetailedTargetHeadlineDscr] = useState(
    DEFAULT_TARGET_HEADLINE_DSCR,
  );
  const [detailedReturnHurdleMetric, setDetailedReturnHurdleMetric] =
    useState<ReturnHurdleMetric>('levered_irr');
  const [detailedBreakEven, setDetailedBreakEven] =
    useState<StandardDetailedBreakEvenAnalysis | null>(null);
  const [isDetailedBreakEvenLoading, setIsDetailedBreakEvenLoading] = useState(false);
  const [detailedBreakEvenError, setDetailedBreakEvenError] = useState<string | null>(null);

  const [detailedAiAnalysis, setDetailedAiAnalysis] = useState<AIAnalysis | null>(null);
  const [isDetailedAiAnalysisLoading, setIsDetailedAiAnalysisLoading] = useState(false);
  const [detailedAiAnalysisError, setDetailedAiAnalysisError] = useState<string | null>(null);

  function clearDetailedAiAnalysis() {
    setDetailedAiAnalysis(null);
    setDetailedAiAnalysisError(null);
  }

  /** Detailed counterpart of `resetDownstreamAnalysisState`: clears
   * everything derived from a Detailed analyze call (results, sensitivity,
   * break-even, AI output) without touching `detailedValues` itself. Never
   * touches any Quick-mode state. */
  function resetDetailedDownstreamAnalysisState() {
    setDetailedResults(null);
    setDetailedError(null);
    setDetailedSensitivity(null);
    setDetailedSensitivityError(null);
    setLastDetailedRequest(null);
    setDetailedBreakEven(null);
    setDetailedBreakEvenError(null);
    clearDetailedAiAnalysis();
  }

  // Detailed Operating Model V2.1 Gate 10: Detailed Excel ingestion.
  // Mirrors Quick's `excelReview` state/handlers exactly (same
  // upload -> temporary review -> explicit approve/cancel control
  // philosophy), over `DetailedFormValues` instead of
  // `AcquisitionFormValues`. A successful upload never touches
  // `detailedValues` -- only `handleApproveDetailedExcelReview` does. A
  // second upload replaces `detailedExcelReview` wholesale, never merges.
  const [isUploadingDetailedExcel, setIsUploadingDetailedExcel] = useState(false);
  const [detailedExcelUploadError, setDetailedExcelUploadError] = useState<string | null>(
    null,
  );
  const [detailedExcelUploadSuccessMessage, setDetailedExcelUploadSuccessMessage] = useState<
    string | null
  >(null);

  interface DetailedExcelReviewState {
    fileName: string;
    values: DetailedFormValues;
  }
  const [detailedExcelReview, setDetailedExcelReview] =
    useState<DetailedExcelReviewState | null>(null);
  const [detailedExcelReviewError, setDetailedExcelReviewError] = useState<string | null>(
    null,
  );

  async function handleUploadDetailedExcel(file: File) {
    setIsUploadingDetailedExcel(true);
    setDetailedExcelUploadError(null);
    setDetailedExcelUploadSuccessMessage(null);
    setDetailedExcelReviewError(null);
    try {
      const report = await uploadDetailedExcel(file);
      setDetailedExcelReview({
        fileName: file.name,
        values: buildDetailedFormValuesFromExcelIntakeReport(report),
      });
      setDetailedExcelUploadSuccessMessage(
        'Workbook parsed successfully. Review the imported assumptions below before loading ' +
          'them into the deal.',
      );
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setDetailedExcelUploadError(apiError.message);
      } else {
        setDetailedExcelUploadError('An unexpected error occurred while parsing the workbook.');
      }
    } finally {
      setIsUploadingDetailedExcel(false);
    }
  }

  function handleDetailedExcelReviewTermsFieldChange(
    key: keyof AcquisitionTermsFormValues,
    value: string,
  ) {
    setDetailedExcelReview((previous) =>
      previous
        ? { ...previous, values: { ...previous.values, terms: { ...previous.values.terms, [key]: value } } }
        : previous,
    );
    setDetailedExcelReviewError(null);
  }

  function handleDetailedExcelReviewOperatingFieldChange(
    key: keyof DetailedOperatingFormValues,
    value: string,
  ) {
    setDetailedExcelReview((previous) =>
      previous
        ? {
            ...previous,
            values: { ...previous.values, operating: { ...previous.values.operating, [key]: value } },
          }
        : previous,
    );
    setDetailedExcelReviewError(null);
  }

  /** Validates and converts the review state using the exact same
   * `buildAcquisitionTermsRequest`/`buildDetailedOperatingInputsRequest`
   * conversion `handleDetailedSubmit` already uses -- no duplicate
   * financial validation lives here. Only on success does this touch
   * `detailedValues`; upload and editing never do. Never auto-runs
   * Analyze. */
  function handleApproveDetailedExcelReview() {
    if (!detailedExcelReview) {
      return;
    }
    let termsRequest;
    let operatingRequest;
    try {
      termsRequest = buildAcquisitionTermsRequest(detailedExcelReview.values.terms);
      operatingRequest = buildDetailedOperatingInputsRequest(
        detailedExcelReview.values.operating,
      );
    } catch (validationError) {
      if (validationError instanceof FormValidationError) {
        setDetailedExcelReviewError(validationError.message);
        return;
      }
      throw validationError;
    }
    setDetailedValues({
      terms: buildDetailedTermsFormValuesFromRequest(termsRequest),
      operating: buildDetailedOperatingFormValuesFromRequest(operatingRequest),
    });
    setDetailedResults(null);
    setDetailedError(null);
    clearDetailedAiAnalysis();
    setDetailedExcelReview(null);
    setDetailedExcelReviewError(null);
    setDetailedExcelUploadSuccessMessage(
      'Detailed assumptions approved and loaded. Review the deal assumptions, then click ' +
        'Analyze Deal.',
    );
  }

  /** Discards the pending Detailed Excel review without touching
   * `detailedValues`, leaving it exactly as it was before the upload. */
  function handleCancelDetailedExcelReview() {
    setDetailedExcelReview(null);
    setDetailedExcelReviewError(null);
    setDetailedExcelUploadSuccessMessage(null);
  }

  // Detailed Operating Model V2.1 Gate 12: Detailed OM ingestion. Mirrors
  // Quick's ocrExtraction/handleUploadOm/handleFinishOmReview exactly (same
  // upload -> per-field review -> explicit approve/reject/finish control
  // philosophy), over DetailedExtractionResult/DetailedFormValues instead.
  // A successful upload never touches `detailedValues` -- only
  // `handleFinishDetailedOmReview` does, and only for the fields the
  // analyst explicitly approved. Unlike Quick's OM panel, Detailed's also
  // gets an explicit Cancel (`handleCancelDetailedOmReview`) -- Gate 12
  // requires a saved Detailed deal to survive an OM upload untouched until
  // an explicit approve/cancel decision, the same guarantee Gate 10's
  // Excel review already gives Detailed mode.
  const [detailedOcrExtraction, setDetailedOcrExtraction] =
    useState<DetailedExtractionResult | null>(null);
  const [isDetailedExtracting, setIsDetailedExtracting] = useState(false);
  const [detailedExtractionError, setDetailedExtractionError] = useState<string | null>(null);

  async function handleUploadDetailedOm(file: File) {
    setIsDetailedExtracting(true);
    setDetailedExtractionError(null);
    setDetailedOcrExtraction(null);
    try {
      const extraction = await uploadDetailedOm(file);
      setDetailedOcrExtraction(extraction);
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setDetailedExtractionError(apiError.message);
      } else {
        setDetailedExtractionError('An unexpected error occurred while extracting the OM.');
      }
    } finally {
      setIsDetailedExtracting(false);
    }
  }

  /** Merges only the explicitly analyst-approved Detailed OM fields into
   * `detailedValues` -- an unapproved/rejected/missing field is left
   * exactly as it was, never defaulted to zero or blanked. Never calls
   * `/analyze`. */
  function handleFinishDetailedOmReview(
    approvedValues: Partial<Record<DetailedTermsFieldId | DetailedOperatingFieldId, string>>,
  ) {
    const termsValues = buildApprovedDetailedTermsFormValues(approvedValues);
    const operatingValues = buildApprovedDetailedOperatingFormValues(approvedValues);
    if (Object.keys(termsValues).length === 0 && Object.keys(operatingValues).length === 0) {
      return;
    }
    setDetailedValues((previous) => ({
      terms: { ...previous.terms, ...termsValues },
      operating: { ...previous.operating, ...operatingValues },
    }));
    setDetailedResults(null);
    setDetailedError(null);
    clearDetailedAiAnalysis();
    clearSaveDetailedDealError();
  }

  /** Discards the pending Detailed OM extraction without touching
   * `detailedValues`, leaving it exactly as it was before the upload. */
  function handleCancelDetailedOmReview() {
    setDetailedOcrExtraction(null);
    setDetailedExtractionError(null);
  }

  // ===========================================================================
  // Detailed Operating Model V2.1 Gate 11 -- Detailed deal persistence.
  //
  // Mirrors Quick's Deal Bar / dirty-tracking state below exactly (same
  // shapes, same single-snapshot-comparison philosophy), over
  // `DetailedFormValues` instead of `AcquisitionFormValues` and the
  // dedicated `createDetailedDeal`/`updateDetailedDeal` endpoints -- never a
  // fabricated `AcquisitionInputs` for a Detailed deal. `view` and
  // `savedDeals`/`isDealsLoading`/`dealsError` (declared with Quick's
  // persistence state further below) are shared across both modes: there is
  // one Deal Library listing both Quick and Detailed deals together, not
  // two independent libraries. `handleOpenDeal`/`handleDeleteDeal` (also
  // below) dispatch by `deal.operating_mode` and are the only functions
  // that touch both this state and Quick's.
  // ===========================================================================

  const [detailedDealName, setDetailedDealName] = useState('');
  const [currentDetailedDealId, setCurrentDetailedDealId] = useState<string | null>(null);
  const [isSavingDetailedDeal, setIsSavingDetailedDeal] = useState(false);
  const [saveDetailedDealError, setSaveDetailedDealError] = useState<string | null>(null);
  const [lastDetailedSavedAt, setLastDetailedSavedAt] = useState<string | null>(null);
  // Owner Return Metrics V3 Gate A4: optional, user-authored deal metadata,
  // included in the dirty-tracking snapshot below exactly like `dealName`
  // and `values` -- editing it marks the deal dirty and Save persists it,
  // with zero separate plumbing.
  const [detailedDealContext, setDetailedDealContext] = useState('');

  interface DetailedDealSnapshot {
    dealName: string;
    values: DetailedFormValues;
    dealContext: string;
  }
  const BLANK_DETAILED_SNAPSHOT: DetailedDealSnapshot = {
    dealName: '',
    values: BLANK_DETAILED_FORM_VALUES,
    dealContext: '',
  };
  const [detailedSavedSnapshot, setDetailedSavedSnapshot] =
    useState<DetailedDealSnapshot>(BLANK_DETAILED_SNAPSHOT);

  function isSameDetailedSnapshot(a: DetailedDealSnapshot, b: DetailedDealSnapshot): boolean {
    if (a.dealName !== b.dealName || a.dealContext !== b.dealContext) {
      return false;
    }
    const termsKeys = Object.keys(a.values.terms) as (keyof AcquisitionTermsFormValues)[];
    if (!termsKeys.every((key) => a.values.terms[key] === b.values.terms[key])) {
      return false;
    }
    const operatingKeys = Object.keys(a.values.operating) as (keyof DetailedOperatingFormValues)[];
    return operatingKeys.every((key) => a.values.operating[key] === b.values.operating[key]);
  }

  const isDetailedDirty = !isSameDetailedSnapshot(
    { dealName: detailedDealName, values: detailedValues, dealContext: detailedDealContext },
    detailedSavedSnapshot,
  );
  const detailedSaveStatus: SaveStatus =
    currentDetailedDealId === null
      ? 'unsaved-deal'
      : isDetailedDirty
        ? 'unsaved-changes'
        : 'saved';

  /** Prompts before a Detailed New Deal / Open Deal action would discard
   * unsaved Detailed work; mirrors `confirmDiscardIfDirty` exactly, over
   * `isDetailedDirty`. */
  function confirmDiscardIfDetailedDirty(): boolean {
    if (!isDetailedDirty) {
      return true;
    }
    return window.confirm('You have unsaved changes that will be lost. Continue?');
  }

  function clearSaveDetailedDealError() {
    setSaveDetailedDealError(null);
  }

  function clearDetailedIntakeFeedback() {
    setDetailedExcelUploadSuccessMessage(null);
    setDetailedExcelUploadError(null);
    setDetailedExcelReview(null);
    setDetailedExcelReviewError(null);
    setDetailedOcrExtraction(null);
    setDetailedExtractionError(null);
  }

  function handleDetailedDealNameChange(value: string) {
    setDetailedDealName(value);
  }

  /** Owner Return Metrics V3 Gate A4: editing Deal Context marks the deal
   * dirty (via the snapshot comparison above) exactly like editing any
   * assumption, but deliberately does NOT call
   * `resetDetailedDownstreamAnalysisState()` -- deterministic
   * `detailedResults`/`detailedSensitivity`/`detailedBreakEven` remain
   * valid, since Deal Context is not a financial input. Only the AI
   * Analyst output is cleared: it interpreted the *previous* Deal Context
   * (or none), so it is now stale. AI is never automatically re-run. */
  function handleDetailedDealContextChange(value: string) {
    setDetailedDealContext(value);
    clearDetailedAiAnalysis();
  }

  /** Shared by Detailed New Deal and by deleting the currently-open
   * Detailed deal: both end in the same blank, never-saved Detailed
   * workspace state. Never touches any Quick-mode state. */
  function resetToBlankDetailedDeal() {
    setDetailedValues(BLANK_DETAILED_FORM_VALUES);
    setDetailedDealName('');
    setDetailedDealContext('');
    setCurrentDetailedDealId(null);
    setLastDetailedSavedAt(null);
    setDetailedSavedSnapshot(BLANK_DETAILED_SNAPSHOT);
    resetDetailedDownstreamAnalysisState();
    clearSaveDetailedDealError();
    clearDetailedIntakeFeedback();
  }

  /** Persists exactly the 22 assumptions already converged onto
   * `detailedValues` via `buildAcquisitionTermsRequest`/
   * `buildDetailedOperatingInputsRequest` -- the same conversion
   * `handleDetailedSubmit` already uses. Never persists `detailedResults`,
   * AI output, or any other calculated value; never calls `/analyze`. */
  async function handleSaveDetailedDeal() {
    let terms;
    let detailedOperatingInputs;
    try {
      terms = buildAcquisitionTermsRequest(detailedValues.terms);
      detailedOperatingInputs = buildDetailedOperatingInputsRequest(detailedValues.operating);
    } catch (validationError) {
      if (validationError instanceof FormValidationError) {
        setSaveDetailedDealError(validationError.message);
        return;
      }
      throw validationError;
    }

    const name = detailedDealName.trim() || 'Untitled Deal';

    const dealContext = detailedDealContext.trim() || null;

    setIsSavingDetailedDeal(true);
    setSaveDetailedDealError(null);
    try {
      // Owner Return Metrics V3 Gate A7: mirrors handleSaveDeal's
      // provenance-validated snapshot-attachment flow exactly -- see its
      // comment.
      const deal = currentDetailedDealId
        ? await updateDetailedDeal(currentDetailedDealId, name, terms, detailedOperatingInputs, dealContext)
        : await createDetailedDeal(name, terms, detailedOperatingInputs, dealContext);
      setCurrentDetailedDealId(deal.id);
      setDetailedDealName(deal.name);
      setDetailedDealContext(deal.deal_context ?? '');
      setLastDetailedSavedAt(deal.updated_at);
      setDetailedSavedSnapshot({
        dealName: deal.name,
        values: detailedValues,
        dealContext: deal.deal_context ?? '',
      });

      if (detailedResults !== null) {
        const fingerprint = await fetchDetailedDealFingerprint(
          terms,
          detailedOperatingInputs,
          dealContext,
        );
        await updateDealAnalysisSnapshot(
          deal.id,
          detailedResults,
          fingerprint.financial_input_fingerprint,
        );
        if (detailedAiAnalysis !== null) {
          await updateDealAiSnapshot(deal.id, detailedAiAnalysis, fingerprint.ai_context_fingerprint);
        }
      }
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setSaveDetailedDealError(apiError.message);
      } else {
        setSaveDetailedDealError('An unexpected error occurred while saving the deal.');
      }
    } finally {
      setIsSavingDetailedDeal(false);
    }
  }

  /** Smallest consistent interaction with the existing single-toggle UI:
   * New Deal in Detailed mode preserves the currently selected mode (it is
   * the Detailed workspace's own New Deal button, rendered only while
   * Detailed mode is active) rather than offering a separate mode choice --
   * no navigation redesign. Preserves Quick's own `handleNewDeal` exactly. */
  function handleNewDetailedDeal() {
    if (!confirmDiscardIfDetailedDirty()) {
      return;
    }
    resetToBlankDetailedDeal();
    setView('workspace');
  }

  function handleDetailedTermsFieldChange(
    key: keyof AcquisitionTermsFormValues,
    value: string,
  ) {
    setDetailedValues((previous) => ({
      ...previous,
      terms: { ...previous.terms, [key]: value },
    }));
    resetDetailedDownstreamAnalysisState();
  }

  function handleDetailedOperatingFieldChange(
    key: keyof DetailedOperatingFormValues,
    value: string,
  ) {
    setDetailedValues((previous) => ({
      ...previous,
      operating: { ...previous.operating, [key]: value },
    }));
    resetDetailedDownstreamAnalysisState();
  }

  /** Detailed Operating Model V2.1 Gate 14: the Detailed counterpart of
   * `runBreakEven`, over `terms`/`detailedOperatingInputs` instead of a
   * single `AcquisitionRequest`, delegating to
   * `fetchDetailedBreakEvenAnalysis` -- no threshold search of its own. */
  async function runDetailedBreakEven(
    terms: AcquisitionTermsRequest,
    detailedOperatingInputs: DetailedOperatingInputsRequest,
    leveredIrrPercentInput: string,
    equityMultipleInput: string,
    headlineDscrInput: string,
    metric: ReturnHurdleMetric,
  ) {
    let targetLeveredIrr: number;
    let targetEquityMultipleValue: number;
    let targetHeadlineDscrValue: number;
    try {
      targetLeveredIrr = parsePercent('Target Levered IRR', leveredIrrPercentInput);
      targetEquityMultipleValue = parseNumber('Target Equity Multiple', equityMultipleInput);
      targetHeadlineDscrValue = parseNumber('Target Year 1 DSCR', headlineDscrInput);
    } catch (validationError) {
      if (validationError instanceof FormValidationError) {
        setDetailedBreakEven(null);
        setDetailedBreakEvenError(validationError.message);
        return;
      }
      throw validationError;
    }

    setIsDetailedBreakEvenLoading(true);
    setDetailedBreakEvenError(null);
    try {
      const analysis = await fetchDetailedBreakEvenAnalysis(
        terms,
        detailedOperatingInputs,
        targetLeveredIrr,
        targetEquityMultipleValue,
        targetHeadlineDscrValue,
        metric,
      );
      setDetailedBreakEven(analysis);
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setDetailedBreakEvenError(apiError.message);
      } else {
        setDetailedBreakEvenError(
          'An unexpected error occurred while calculating break-even results.',
        );
      }
    } finally {
      setIsDetailedBreakEvenLoading(false);
    }
  }

  function handleDetailedTargetLeveredIrrChange(value: string) {
    setDetailedTargetLeveredIrrPercent(value);
    if (lastDetailedRequest) {
      void runDetailedBreakEven(
        lastDetailedRequest.terms,
        lastDetailedRequest.detailedOperatingInputs,
        value,
        detailedTargetEquityMultiple,
        detailedTargetHeadlineDscr,
        detailedReturnHurdleMetric,
      );
    }
  }

  function handleDetailedTargetEquityMultipleChange(value: string) {
    setDetailedTargetEquityMultiple(value);
    if (lastDetailedRequest) {
      void runDetailedBreakEven(
        lastDetailedRequest.terms,
        lastDetailedRequest.detailedOperatingInputs,
        detailedTargetLeveredIrrPercent,
        value,
        detailedTargetHeadlineDscr,
        detailedReturnHurdleMetric,
      );
    }
  }

  function handleDetailedTargetHeadlineDscrChange(value: string) {
    setDetailedTargetHeadlineDscr(value);
    if (lastDetailedRequest) {
      void runDetailedBreakEven(
        lastDetailedRequest.terms,
        lastDetailedRequest.detailedOperatingInputs,
        detailedTargetLeveredIrrPercent,
        detailedTargetEquityMultiple,
        value,
        detailedReturnHurdleMetric,
      );
    }
  }

  function handleDetailedReturnHurdleMetricChange(metric: ReturnHurdleMetric) {
    setDetailedReturnHurdleMetric(metric);
    if (lastDetailedRequest) {
      void runDetailedBreakEven(
        lastDetailedRequest.terms,
        lastDetailedRequest.detailedOperatingInputs,
        detailedTargetLeveredIrrPercent,
        detailedTargetEquityMultiple,
        detailedTargetHeadlineDscr,
        metric,
      );
    }
  }

  async function handleDetailedSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    resetDetailedDownstreamAnalysisState();

    let terms;
    let detailedOperatingInputs;
    try {
      terms = buildAcquisitionTermsRequest(detailedValues.terms);
      detailedOperatingInputs = buildDetailedOperatingInputsRequest(detailedValues.operating);
    } catch (validationError) {
      if (validationError instanceof FormValidationError) {
        setDetailedError(validationError.message);
        return;
      }
      throw validationError;
    }

    setIsDetailedSubmitting(true);
    try {
      const nextResults = await analyzeDetailedAcquisition(terms, detailedOperatingInputs);
      setDetailedResults(nextResults);
      // Owner Return Metrics V3 Gate A6: silently refresh the persisted
      // analysis snapshot for an already-saved, not-dirty deal -- fired
      // without blocking (never awaited inline), so it never delays the
      // sensitivity/break-even calls below, never marks the deal dirty
      // (touches no snapshot/dealName/values/dealContext state), and
      // never requires an explicit Save. Skipped entirely for a new
      // unsaved deal, or one with unsaved assumption edits (`isDetailedDirty`)
      // -- caching a snapshot for assumptions that were never actually
      // saved would violate the "snapshot always matches saved assumptions"
      // invariant.
      if (currentDetailedDealId !== null && !isDetailedDirty) {
        // Owner Return Metrics V3 Gate A7: the provenance token is fetched
        // fresh from the exact `terms`/`detailedOperatingInputs`/Deal
        // Context just analyzed, never cached across calls -- the backend
        // remains the sole authority on what a valid fingerprint is.
        void (async () => {
          try {
            const fingerprint = await fetchDetailedDealFingerprint(
              terms,
              detailedOperatingInputs,
              detailedDealContext.trim() || null,
            );
            await updateDealAnalysisSnapshot(
              currentDetailedDealId,
              nextResults,
              fingerprint.financial_input_fingerprint,
            );
            clearSaveDetailedDealError();
          } catch {
            setSaveDetailedDealError(
              'Could not save the latest analysis automatically. Results are shown but may not persist if you reload.',
            );
          }
        })();
      }
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setDetailedError(apiError.message);
      } else {
        setDetailedError('An unexpected error occurred while analyzing the deal.');
      }
      setIsDetailedSubmitting(false);
      return;
    }
    setIsDetailedSubmitting(false);
    setLastDetailedRequest({ terms, detailedOperatingInputs });

    setIsDetailedSensitivityLoading(true);
    try {
      const presets = await fetchDetailedSensitivityPresets(terms, detailedOperatingInputs);
      setDetailedSensitivity(presets);
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setDetailedSensitivityError(apiError.message);
      } else {
        setDetailedSensitivityError('An unexpected error occurred while calculating sensitivity.');
      }
    } finally {
      setIsDetailedSensitivityLoading(false);
    }

    await runDetailedBreakEven(
      terms,
      detailedOperatingInputs,
      detailedTargetLeveredIrrPercent,
      detailedTargetEquityMultiple,
      detailedTargetHeadlineDscr,
      detailedReturnHurdleMetric,
    );
  }

  /**
   * Detailed Operating Model V2.1 Gate 9: generates an AI Analyst
   * interpretation of the current Detailed deal, sending the same
   * `terms`/`detailedOperatingInputs` just analyzed (never re-derived or
   * re-typed) plus the fixed default hurdle targets. Gate 14 added a
   * break-even panel with its own independently-edited targets
   * (`detailedTargetLeveredIrrPercent` etc.), but this call intentionally
   * keeps using the original fixed defaults, unchanged -- Gate 14 is a
   * wiring-only gate that explicitly excludes AI changes, so the AI
   * Analyst's own target-sourcing behavior is left exactly as Gate 9 built
   * it. Mirrors `handleGenerateAiAnalysis`'s shape exactly, over Detailed's
   * own independent state.
   */
  async function handleGenerateDetailedAiAnalysis() {
    if (!detailedResults) {
      return;
    }

    let terms;
    let detailedOperatingInputs;
    let targetLeveredIrr: number;
    let targetEquityMultipleValue: number;
    let targetHeadlineDscrValue: number;
    try {
      terms = buildAcquisitionTermsRequest(detailedValues.terms);
      detailedOperatingInputs = buildDetailedOperatingInputsRequest(detailedValues.operating);
      targetLeveredIrr = parsePercent('Target Levered IRR', DEFAULT_TARGET_LEVERED_IRR_PERCENT);
      targetEquityMultipleValue = parseNumber(
        'Target Equity Multiple',
        DEFAULT_TARGET_EQUITY_MULTIPLE,
      );
      targetHeadlineDscrValue = parseNumber('Target Year 1 DSCR', DEFAULT_TARGET_HEADLINE_DSCR);
    } catch (validationError) {
      if (validationError instanceof FormValidationError) {
        setDetailedAiAnalysis(null);
        setDetailedAiAnalysisError(validationError.message);
        return;
      }
      throw validationError;
    }

    setIsDetailedAiAnalysisLoading(true);
    setDetailedAiAnalysisError(null);
    try {
      const analysis = await fetchDetailedAIAnalysis(
        terms,
        detailedOperatingInputs,
        targetLeveredIrr,
        targetEquityMultipleValue,
        targetHeadlineDscrValue,
        'levered_irr',
        detailedDealContext.trim() || null,
      );
      setDetailedAiAnalysis(analysis);
      // Owner Return Metrics V3 Gate A6/A7: mirrors handleGenerateAiAnalysis's
      // silent background AI-snapshot cache refresh exactly, now fetching
      // the provenance token fresh from the exact terms/context this AI
      // output was just generated under.
      if (currentDetailedDealId !== null && !isDetailedDirty) {
        void (async () => {
          try {
            const fingerprint = await fetchDetailedDealFingerprint(
              terms,
              detailedOperatingInputs,
              detailedDealContext.trim() || null,
            );
            await updateDealAiSnapshot(
              currentDetailedDealId,
              analysis,
              fingerprint.ai_context_fingerprint,
            );
            clearSaveDetailedDealError();
          } catch {
            setSaveDetailedDealError(
              'Could not save the latest AI analysis automatically. It is shown but may not persist if you reload.',
            );
          }
        })();
      }
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setDetailedAiAnalysisError(apiError.message);
      } else {
        setDetailedAiAnalysisError('An unexpected error occurred while generating the AI analysis.');
      }
    } finally {
      setIsDetailedAiAnalysisLoading(false);
    }
  }

  const [values, setValues] = useState<AcquisitionFormValues>(BLANK_FORM_VALUES);
  const [results, setResults] = useState<AcquisitionResults | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [sensitivity, setSensitivity] = useState<StandardSensitivityPresets | null>(null);
  const [isSensitivityLoading, setIsSensitivityLoading] = useState(false);
  const [sensitivityError, setSensitivityError] = useState<string | null>(null);

  const [lastRequest, setLastRequest] = useState<AcquisitionRequest | null>(null);
  const [targetLeveredIrrPercent, setTargetLeveredIrrPercent] = useState(
    DEFAULT_TARGET_LEVERED_IRR_PERCENT,
  );
  const [targetEquityMultiple, setTargetEquityMultiple] = useState(DEFAULT_TARGET_EQUITY_MULTIPLE);
  const [targetHeadlineDscr, setTargetHeadlineDscr] = useState(DEFAULT_TARGET_HEADLINE_DSCR);
  const [returnHurdleMetric, setReturnHurdleMetric] = useState<ReturnHurdleMetric>('levered_irr');
  const [breakEven, setBreakEven] = useState<StandardBreakEvenAnalysis | null>(null);
  const [isBreakEvenLoading, setIsBreakEvenLoading] = useState(false);
  const [breakEvenError, setBreakEvenError] = useState<string | null>(null);

  const [aiAnalysis, setAiAnalysis] = useState<AIAnalysis | null>(null);
  const [isAiAnalysisLoading, setIsAiAnalysisLoading] = useState(false);
  const [aiAnalysisError, setAiAnalysisError] = useState<string | null>(null);

  const [ocrExtraction, setOcrExtraction] = useState<ExtractionResult | null>(null);
  const [isExtracting, setIsExtracting] = useState(false);
  const [extractionError, setExtractionError] = useState<string | null>(null);

  const [isUploadingExcel, setIsUploadingExcel] = useState(false);
  const [excelUploadError, setExcelUploadError] = useState<string | null>(null);
  const [excelUploadSuccessMessage, setExcelUploadSuccessMessage] = useState<string | null>(null);

  // Excel ingestion review (analyst-control parity with OM ingestion, R9/R11
  // equivalent): a successful workbook parse never touches `values` -- it
  // lands here as a temporary, analyst-editable proposal. Nothing here is
  // read by dirty tracking, Save, or Analyze; only `handleApproveExcelReview`
  // ever copies it into `values`. `excelReview` is replaced wholesale (never
  // merged) by a second upload, and cleared by both approval and cancel.
  interface ExcelReviewState {
    fileName: string;
    values: AcquisitionFormValues;
    requiredV2FieldIds: V2FieldId[];
  }
  const [excelReview, setExcelReview] = useState<ExcelReviewState | null>(null);
  const [excelReviewError, setExcelReviewError] = useState<string | null>(null);

  // Persistence Phase B/C -- Deal Bar / Deal Library. `currentDealId` is set
  // only after a deal is created or opened (never guessed at); it is what
  // decides whether Save Deal calls POST /deals (null) or PUT /deals/{id}
  // (set). No AcquisitionResults is ever part of this state -- reopening a
  // deal always means resubmitting its inputs to the existing /analyze.
  const [view, setView] = useState<'workspace' | 'library'>('workspace');
  const [dealName, setDealName] = useState('');
  const [currentDealId, setCurrentDealId] = useState<string | null>(null);
  const [isSavingDeal, setIsSavingDeal] = useState(false);
  const [saveDealError, setSaveDealError] = useState<string | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  // Owner Return Metrics V3 Gate A4: mirrors detailedDealContext exactly.
  const [dealContext, setDealContext] = useState('');

  const [savedDeals, setSavedDeals] = useState<Deal[]>([]);
  const [isDealsLoading, setIsDealsLoading] = useState(false);
  const [dealsError, setDealsError] = useState<string | null>(null);

  // Phase C -- unsaved-changes tracking. `savedSnapshot` is the
  // {dealName, values, dealContext} pair as of the last successful Save or
  // Open (or the blank starting point). Dirty-ness is a single
  // deterministic comparison against it -- deliberately not a scattered
  // set of manual "mark dirty" calls sprinkled through every handler, so
  // it can never drift out of sync with a handler someone forgets to
  // update. Analyze/sensitivity/break-even/AI-analyst never touch this
  // snapshot, so they can never affect dirty state, by construction rather
  // than by remembering not to.
  interface DealSnapshot {
    dealName: string;
    values: AcquisitionFormValues;
    dealContext: string;
  }
  const BLANK_SNAPSHOT: DealSnapshot = {
    dealName: '',
    values: BLANK_FORM_VALUES,
    dealContext: '',
  };
  const [savedSnapshot, setSavedSnapshot] = useState<DealSnapshot>(BLANK_SNAPSHOT);

  function isSameSnapshot(a: DealSnapshot, b: DealSnapshot): boolean {
    if (a.dealName !== b.dealName || a.dealContext !== b.dealContext) {
      return false;
    }
    const fieldKeys = Object.keys(a.values) as (keyof AcquisitionFormValues)[];
    return fieldKeys.every((key) => a.values[key] === b.values[key]);
  }

  const isDirty = !isSameSnapshot({ dealName, values, dealContext }, savedSnapshot);
  const saveStatus: SaveStatus =
    currentDealId === null ? 'unsaved-deal' : isDirty ? 'unsaved-changes' : 'saved';

  /** Prompts before a New Deal / Open Deal action would discard unsaved
   * work; returns true if it is safe to proceed (nothing to lose, or the
   * analyst confirmed). Cancelling leaves the workspace exactly as-is. */
  function confirmDiscardIfDirty(): boolean {
    if (!isDirty) {
      return true;
    }
    return window.confirm('You have unsaved changes that will be lost. Continue?');
  }

  function clearSaveDealError() {
    setSaveDealError(null);
  }

  function clearIntakeFeedback() {
    setOcrExtraction(null);
    setExtractionError(null);
    setExcelUploadSuccessMessage(null);
    setExcelUploadError(null);
    setExcelReview(null);
    setExcelReviewError(null);
  }

  function resetDownstreamAnalysisState() {
    setResults(null);
    setError(null);
    setSensitivity(null);
    setSensitivityError(null);
    setLastRequest(null);
    setBreakEven(null);
    setBreakEvenError(null);
    setAiAnalysis(null);
    setAiAnalysisError(null);
  }

  function handleFieldChange(key: keyof AcquisitionFormValues, value: string) {
    setValues((previous) => ({ ...previous, [key]: value }));
    resetDownstreamAnalysisState();
    clearSaveDealError();
  }

  async function handleUploadOm(file: File) {
    setIsExtracting(true);
    setExtractionError(null);
    setOcrExtraction(null);
    try {
      const extraction = await uploadOm(file);
      setOcrExtraction(extraction);
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setExtractionError(apiError.message);
      } else {
        setExtractionError('An unexpected error occurred while extracting the OM.');
      }
    } finally {
      setIsExtracting(false);
    }
  }

  function handleFinishOmReview(approvedValues: Partial<Record<AcquisitionFieldId, string>>) {
    const formValues = buildApprovedFormValues(approvedValues);
    if (Object.keys(formValues).length === 0) {
      return;
    }
    setValues((previous) => ({ ...previous, ...formValues }));
    resetDownstreamAnalysisState();
    clearSaveDealError();
  }

  /**
   * Parses the workbook and stores it as a temporary Excel review proposal
   * only -- deliberately never calls `setValues`, `resetDownstreamAnalysisState`,
   * or `clearSaveDealError` here. Active assumptions, dirty state, Save
   * state, and Analyze state must all remain exactly as they were until the
   * analyst explicitly approves (`handleApproveExcelReview`). A second
   * upload while a review is already pending replaces it wholesale, never
   * merges two workbooks.
   */
  async function handleUploadExcel(file: File) {
    setIsUploadingExcel(true);
    setExcelUploadError(null);
    setExcelUploadSuccessMessage(null);
    setExcelReviewError(null);
    try {
      const report = await uploadExcel(file);
      setExcelReview({
        fileName: file.name,
        values: buildFormValuesFromExcelIntakeReport(report),
        requiredV2FieldIds: report.defaulted_v2_field_ids,
      });
      setExcelUploadSuccessMessage(
        'Workbook parsed successfully. Review the imported assumptions below before loading them ' +
          'into the deal.',
      );
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setExcelUploadError(apiError.message);
      } else {
        setExcelUploadError('An unexpected error occurred while parsing the workbook.');
      }
    } finally {
      setIsUploadingExcel(false);
    }
  }

  function handleExcelReviewFieldChange(key: keyof AcquisitionFormValues, value: string) {
    setExcelReview((previous) =>
      previous ? { ...previous, values: { ...previous.values, [key]: value } } : previous,
    );
    setExcelReviewError(null);
  }

  /**
   * Validates and converts the review state using the exact same
   * `buildAcquisitionRequest`/`buildFormValuesFromAcquisitionInputs`
   * round trip `handleSubmit`/`handleSaveDeal` already use -- no duplicate
   * financial validation lives here. A blank required field (including any
   * still-defaulted Underwriting V2 field, explicit `0` aside) surfaces the
   * existing "X is required." error and blocks approval. Only on success
   * does this touch `values`, so dirty tracking and Save/Analyze state only
   * ever change here, never on upload. Never auto-runs Analyze.
   */
  function handleApproveExcelReview() {
    if (!excelReview) {
      return;
    }
    let request: AcquisitionRequest;
    try {
      request = buildAcquisitionRequest(excelReview.values);
    } catch (validationError) {
      if (validationError instanceof FormValidationError) {
        setExcelReviewError(validationError.message);
        return;
      }
      throw validationError;
    }
    setValues(buildFormValuesFromAcquisitionInputs(request));
    resetDownstreamAnalysisState();
    clearSaveDealError();
    setExcelReview(null);
    setExcelReviewError(null);
    setExcelUploadSuccessMessage(
      'Excel assumptions approved and loaded. Review the deal assumptions, then click Analyze Deal.',
    );
    document.querySelector('.assumptions-form')?.scrollIntoView?.({
      behavior: 'smooth',
      block: 'start',
    });
  }

  /** Discards the pending Excel review without touching the active deal --
   * leaves `values`, dirty state, and saved/clean status exactly as they
   * were before the upload. */
  function handleCancelExcelReview() {
    setExcelReview(null);
    setExcelReviewError(null);
    setExcelUploadSuccessMessage(null);
  }

  // ===========================================================================
  // Persistence Phase B/C -- Deal Bar / Deal Library handlers.
  //
  // Save persists exactly the nine assumptions already converged onto
  // `values` via `buildAcquisitionRequest` (the same conversion/validation
  // `handleSubmit` already uses) -- it never cares whether they arrived by
  // typing, Excel, or OM, and it never calls `/analyze`. Opening a deal
  // populates the form via the existing `buildFormValuesFromAcquisitionInputs`
  // conversion and clears stale analysis state, but likewise never calls
  // `/analyze` -- the analyst clicks Analyze Deal explicitly, same as today.
  // New Deal and Open Deal both discard unsaved work, so both are guarded
  // by `confirmDiscardIfDirty()` first. Duplicate/delete never touch the
  // engine and never mark the *current* workspace saved/dirty by
  // themselves -- only Save/Open/New change `savedSnapshot`.
  // ===========================================================================

  function handleDealNameChange(value: string) {
    setDealName(value);
  }

  /** Owner Return Metrics V3 Gate A4: mirrors
   * `handleDetailedDealContextChange` exactly -- marks the deal dirty via
   * the snapshot comparison, but deliberately does not touch
   * `results`/`sensitivity`/`breakEven` (Deal Context is not a financial
   * input, so those stay valid). Only the now-stale AI Analyst output is
   * cleared; AI is never automatically re-run. */
  function handleDealContextChange(value: string) {
    setDealContext(value);
    clearAiAnalysis();
  }

  /** Shared by New Deal and by deleting the currently-open deal: both end
   * in the same blank, never-saved workspace state. */
  function resetToBlankDeal() {
    setValues(BLANK_FORM_VALUES);
    setDealName('');
    setDealContext('');
    setCurrentDealId(null);
    setLastSavedAt(null);
    setSavedSnapshot(BLANK_SNAPSHOT);
    resetDownstreamAnalysisState();
    clearSaveDealError();
    clearIntakeFeedback();
  }

  async function handleSaveDeal() {
    let request: AcquisitionRequest;
    try {
      request = buildAcquisitionRequest(values);
    } catch (validationError) {
      if (validationError instanceof FormValidationError) {
        setSaveDealError(validationError.message);
        return;
      }
      throw validationError;
    }

    const name = dealName.trim() || 'Untitled Deal';
    const dealContextToSave = dealContext.trim() || null;

    setIsSavingDeal(true);
    setSaveDealError(null);
    try {
      // Owner Return Metrics V3 Gate A7: this route persists assumptions/
      // Deal Context only -- it never accepts a snapshot in the same write
      // (a stale snapshot can never be relabeled as valid for freshly-
      // submitted assumptions). Deal-level state is updated immediately on
      // success, before any snapshot is attached, so a subsequent Save
      // retry can never create a second deal even if the snapshot-
      // attachment step below fails.
      const deal = currentDealId
        ? await updateDeal(currentDealId, name, request, dealContextToSave)
        : await createDeal(name, request, dealContextToSave);
      setCurrentDealId(deal.id);
      setDealName(deal.name);
      setDealContext(deal.deal_context ?? '');
      setLastSavedAt(deal.updated_at);
      setSavedSnapshot({ dealName: deal.name, values, dealContext: deal.deal_context ?? '' });

      // `results`/`aiAnalysis` are always either null or already valid for
      // the current `values`/`dealContext` by construction (any assumption
      // edit clears both via resetDownstreamAnalysisState; a Deal-Context-
      // only edit clears only aiAnalysis, via clearAiAnalysis) -- so
      // attaching them here, through the provenance-validated dedicated
      // endpoints whenever non-null, is always correct: it persists a
      // current valid snapshot on first Save, and is a harmless re-attach
      // (identical fingerprint) across a Deal-Context-only Save, where the
      // analysis snapshot was already preserved automatically by the
      // backend's own read-time fingerprint check.
      if (results !== null) {
        const fingerprint = await fetchDealFingerprint(request, dealContextToSave);
        await updateDealAnalysisSnapshot(deal.id, results, fingerprint.financial_input_fingerprint);
        if (aiAnalysis !== null) {
          await updateDealAiSnapshot(deal.id, aiAnalysis, fingerprint.ai_context_fingerprint);
        }
      }
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setSaveDealError(apiError.message);
      } else {
        setSaveDealError('An unexpected error occurred while saving the deal.');
      }
    } finally {
      setIsSavingDeal(false);
    }
  }

  async function loadSavedDeals() {
    setIsDealsLoading(true);
    setDealsError(null);
    try {
      const deals = await listDeals();
      setSavedDeals(deals);
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setDealsError(apiError.message);
      } else {
        setDealsError('An unexpected error occurred while loading the deal library.');
      }
    } finally {
      setIsDealsLoading(false);
    }
  }

  function handleOpenLibrary() {
    setView('library');
    void loadSavedDeals();
  }

  function handleCloseLibrary() {
    setView('workspace');
  }

  /**
   * Detailed Operating Model V2.1 Gate 11: dispatches by `deal.operating_mode`
   * -- a Quick deal populates `values`/`savedSnapshot` and switches to Quick
   * mode; a Detailed deal populates `detailedValues`/`detailedSavedSnapshot`
   * and switches to Detailed mode, never the other. Only the target mode's
   * own state is touched (its stale review/results/AI state is cleared, and
   * its own discard guard applies before replacing same-mode unsaved work);
   * the other mode's currently-open deal, if any, is left completely
   * untouched in the background -- exactly like switching the Underwriting
   * Mode tab already preserves each mode's state independently (Gate 6), so
   * opening a deal of one mode can never lose or leak the other mode's
   * assumptions/results.
   */
  async function handleOpenDeal(deal: Deal) {
    if (deal.operating_mode === 'detailed') {
      if (!confirmDiscardIfDetailedDirty()) {
        return;
      }
      setDealsError(null);
      try {
        const fullDeal = await getDeal(deal.id);
        if (fullDeal.terms === null || fullDeal.detailed_operating_inputs === null) {
          throw new Error('Detailed deal is missing terms/detailed_operating_inputs.');
        }
        const openedValues: DetailedFormValues = {
          terms: buildDetailedTermsFormValuesFromRequest(fullDeal.terms),
          operating: buildDetailedOperatingFormValuesFromRequest(
            fullDeal.detailed_operating_inputs,
          ),
        };
        setDetailedValues(openedValues);
        setDetailedDealName(fullDeal.name);
        setDetailedDealContext(fullDeal.deal_context ?? '');
        setCurrentDetailedDealId(fullDeal.id);
        setLastDetailedSavedAt(fullDeal.updated_at);
        setDetailedSavedSnapshot({
          dealName: fullDeal.name,
          values: openedValues,
          dealContext: fullDeal.deal_context ?? '',
        });
        resetDetailedDownstreamAnalysisState();
        // Owner Return Metrics V3 Gate A6: hydrate the SAME state a live
        // Analyze/Generate AI Analysis populates -- never a separate
        // "historical snapshot viewer" render path. `lastDetailedRequest`
        // is also restored alongside a valid analysis snapshot (not just
        // `detailedResults`) so "Generate AI Analysis" works immediately
        // on the reopened deal without first requiring a fresh Analyze
        // click -- it is exactly the terms/detailedOperatingInputs that
        // produced the restored snapshot, since a snapshot is only ever
        // returned when it matches the deal's current assumptions.
        // Deliberately does not touch sensitivity/break-even state, which
        // Gate A6 does not persist -- those remain empty until recomputed.
        if (
          fullDeal.analysis_snapshot !== null &&
          isDetailedAnalysisSnapshot(fullDeal.analysis_snapshot)
        ) {
          setDetailedResults(fullDeal.analysis_snapshot);
          setLastDetailedRequest({
            terms: fullDeal.terms,
            detailedOperatingInputs: fullDeal.detailed_operating_inputs,
          });
        }
        if (fullDeal.ai_snapshot !== null) {
          setDetailedAiAnalysis(fullDeal.ai_snapshot);
        }
        clearSaveDetailedDealError();
        clearDetailedIntakeFeedback();
        setOperatingMode('detailed');
        setView('workspace');
      } catch (apiError) {
        if (apiError instanceof ApiError) {
          setDealsError(apiError.message);
        } else {
          setDealsError('An unexpected error occurred while opening the deal.');
        }
      }
      return;
    }

    if (!confirmDiscardIfDirty()) {
      return;
    }
    setDealsError(null);
    try {
      const fullDeal = await getDeal(deal.id);
      if (fullDeal.inputs === null) {
        throw new Error('Quick deal is missing inputs.');
      }
      const openedValues = buildFormValuesFromAcquisitionInputs(fullDeal.inputs);
      setValues(openedValues);
      setDealName(fullDeal.name);
      setDealContext(fullDeal.deal_context ?? '');
      setCurrentDealId(fullDeal.id);
      setLastSavedAt(fullDeal.updated_at);
      setSavedSnapshot({
        dealName: fullDeal.name,
        values: openedValues,
        dealContext: fullDeal.deal_context ?? '',
      });
      resetDownstreamAnalysisState();
      // Owner Return Metrics V3 Gate A6: mirrors the Detailed branch above
      // exactly -- see its comment.
      if (
        fullDeal.analysis_snapshot !== null &&
        !isDetailedAnalysisSnapshot(fullDeal.analysis_snapshot)
      ) {
        setResults(fullDeal.analysis_snapshot);
        setLastRequest(fullDeal.inputs);
      }
      if (fullDeal.ai_snapshot !== null) {
        setAiAnalysis(fullDeal.ai_snapshot);
      }
      clearSaveDealError();
      clearIntakeFeedback();
      setOperatingMode('quick');
      setView('workspace');
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setDealsError(apiError.message);
      } else {
        setDealsError('An unexpected error occurred while opening the deal.');
      }
    }
  }

  function handleNewDeal() {
    if (!confirmDiscardIfDirty()) {
      return;
    }
    resetToBlankDeal();
    setView('workspace');
  }

  /** Duplicates a saved deal and refreshes the library in place. Chosen
   * over auto-opening the copy: staying in the library is the simpler,
   * less surprising result -- it never touches the current workspace
   * (so it can never trigger/bypass the unsaved-changes guard) and lets
   * the analyst see the new copy appear in context, right next to the
   * original, before deciding whether to open it. */
  async function handleDuplicateDeal(deal: Deal) {
    setDealsError(null);
    try {
      await duplicateDeal(deal.id);
      await loadSavedDeals();
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setDealsError(apiError.message);
      } else {
        setDealsError('An unexpected error occurred while duplicating the deal.');
      }
    }
  }

  /** Confirmation happens in `DealLibraryPanel` itself (window.confirm)
   * before `onDelete` is ever called -- by the time this runs, the analyst
   * has already agreed. If the deleted deal is the one currently open --
   * checked against both `currentDealId` and `currentDetailedDealId`,
   * exactly one of which can ever match a given id -- that mode's workspace
   * is reset to a blank, never-saved deal rather than left pointing at an
   * id that no longer exists (a later Save would otherwise 404 against a
   * deleted id). Deleting a deal never changes which mode is currently
   * selected; only that mode's own state resets. */
  async function handleDeleteDeal(deal: Deal) {
    setDealsError(null);
    try {
      await deleteDeal(deal.id);
      if (currentDealId === deal.id) {
        resetToBlankDeal();
      }
      if (currentDetailedDealId === deal.id) {
        resetToBlankDetailedDeal();
      }
      await loadSavedDeals();
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setDealsError(apiError.message);
      } else {
        setDealsError('An unexpected error occurred while deleting the deal.');
      }
    }
  }

  async function runBreakEven(
    request: AcquisitionRequest,
    leveredIrrPercentInput: string,
    equityMultipleInput: string,
    headlineDscrInput: string,
    metric: ReturnHurdleMetric,
  ) {
    let targetLeveredIrr: number;
    let targetEquityMultipleValue: number;
    let targetHeadlineDscrValue: number;
    try {
      targetLeveredIrr = parsePercent('Target Levered IRR', leveredIrrPercentInput);
      targetEquityMultipleValue = parseNumber('Target Equity Multiple', equityMultipleInput);
      targetHeadlineDscrValue = parseNumber('Target Year 1 DSCR', headlineDscrInput);
    } catch (validationError) {
      if (validationError instanceof FormValidationError) {
        setBreakEven(null);
        setBreakEvenError(validationError.message);
        return;
      }
      throw validationError;
    }

    setIsBreakEvenLoading(true);
    setBreakEvenError(null);
    try {
      const analysis = await fetchBreakEvenAnalysis(
        request,
        targetLeveredIrr,
        targetEquityMultipleValue,
        targetHeadlineDscrValue,
        metric,
      );
      setBreakEven(analysis);
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setBreakEvenError(apiError.message);
      } else {
        setBreakEvenError('An unexpected error occurred while calculating break-even results.');
      }
    } finally {
      setIsBreakEvenLoading(false);
    }
  }

  function clearAiAnalysis() {
    setAiAnalysis(null);
    setAiAnalysisError(null);
  }

  function handleTargetLeveredIrrChange(value: string) {
    setTargetLeveredIrrPercent(value);
    clearAiAnalysis();
    if (lastRequest) {
      void runBreakEven(lastRequest, value, targetEquityMultiple, targetHeadlineDscr, returnHurdleMetric);
    }
  }

  function handleTargetEquityMultipleChange(value: string) {
    setTargetEquityMultiple(value);
    clearAiAnalysis();
    if (lastRequest) {
      void runBreakEven(
        lastRequest,
        targetLeveredIrrPercent,
        value,
        targetHeadlineDscr,
        returnHurdleMetric,
      );
    }
  }

  function handleTargetHeadlineDscrChange(value: string) {
    setTargetHeadlineDscr(value);
    clearAiAnalysis();
    if (lastRequest) {
      void runBreakEven(
        lastRequest,
        targetLeveredIrrPercent,
        targetEquityMultiple,
        value,
        returnHurdleMetric,
      );
    }
  }

  function handleReturnHurdleMetricChange(metric: ReturnHurdleMetric) {
    setReturnHurdleMetric(metric);
    clearAiAnalysis();
    if (lastRequest) {
      void runBreakEven(
        lastRequest,
        targetLeveredIrrPercent,
        targetEquityMultiple,
        targetHeadlineDscr,
        metric,
      );
    }
  }

  async function handleGenerateAiAnalysis() {
    if (!lastRequest) {
      return;
    }

    let targetLeveredIrr: number;
    let targetEquityMultipleValue: number;
    let targetHeadlineDscrValue: number;
    try {
      targetLeveredIrr = parsePercent('Target Levered IRR', targetLeveredIrrPercent);
      targetEquityMultipleValue = parseNumber('Target Equity Multiple', targetEquityMultiple);
      targetHeadlineDscrValue = parseNumber('Target Year 1 DSCR', targetHeadlineDscr);
    } catch (validationError) {
      if (validationError instanceof FormValidationError) {
        setAiAnalysis(null);
        setAiAnalysisError(validationError.message);
        return;
      }
      throw validationError;
    }

    setIsAiAnalysisLoading(true);
    setAiAnalysisError(null);
    try {
      const analysis = await fetchAIAnalysis(
        lastRequest,
        targetLeveredIrr,
        targetEquityMultipleValue,
        targetHeadlineDscrValue,
        returnHurdleMetric,
        dealContext.trim() || null,
      );
      setAiAnalysis(analysis);
      // Owner Return Metrics V3 Gate A6/A7: silently refresh the persisted
      // AI snapshot for an already-saved, not-dirty deal -- mirrors the
      // analysis-snapshot auto-cache in handleSubmit exactly, now fetching
      // the provenance token fresh from the exact assumptions/context this
      // AI output was just generated under. Skipped for a new unsaved deal
      // or one with unsaved assumption/context edits, for the same "never
      // cache against never-saved state" reason.
      if (currentDealId !== null && !isDirty) {
        void (async () => {
          try {
            const fingerprint = await fetchDealFingerprint(lastRequest, dealContext.trim() || null);
            await updateDealAiSnapshot(currentDealId, analysis, fingerprint.ai_context_fingerprint);
            clearSaveDealError();
          } catch {
            setSaveDealError(
              'Could not save the latest AI analysis automatically. It is shown but may not persist if you reload.',
            );
          }
        })();
      }
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setAiAnalysisError(apiError.message);
      } else {
        setAiAnalysisError('An unexpected error occurred while generating the AI analysis.');
      }
    } finally {
      setIsAiAnalysisLoading(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setResults(null);
    setError(null);
    setSensitivity(null);
    setSensitivityError(null);
    setLastRequest(null);
    setBreakEven(null);
    setBreakEvenError(null);
    setAiAnalysis(null);
    setAiAnalysisError(null);

    let request;
    try {
      request = buildAcquisitionRequest(values);
    } catch (validationError) {
      if (validationError instanceof FormValidationError) {
        setError(validationError.message);
        return;
      }
      throw validationError;
    }

    setIsSubmitting(true);
    try {
      const nextResults = await analyzeAcquisition(request);
      setResults(nextResults);
      // Owner Return Metrics V3 Gate A6/A7: mirrors handleDetailedSubmit's
      // silent background cache refresh exactly -- see its comment.
      if (currentDealId !== null && !isDirty) {
        void (async () => {
          try {
            const fingerprint = await fetchDealFingerprint(request, dealContext.trim() || null);
            await updateDealAnalysisSnapshot(
              currentDealId,
              nextResults,
              fingerprint.financial_input_fingerprint,
            );
            clearSaveDealError();
          } catch {
            setSaveDealError(
              'Could not save the latest analysis automatically. Results are shown but may not persist if you reload.',
            );
          }
        })();
      }
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setError(apiError.message);
      } else {
        setError('An unexpected error occurred while analyzing the deal.');
      }
      setIsSubmitting(false);
      return;
    }
    setIsSubmitting(false);
    setLastRequest(request);

    setIsSensitivityLoading(true);
    try {
      const presets = await fetchSensitivityPresets(request);
      setSensitivity(presets);
    } catch (apiError) {
      if (apiError instanceof ApiError) {
        setSensitivityError(apiError.message);
      } else {
        setSensitivityError('An unexpected error occurred while calculating sensitivity.');
      }
    } finally {
      setIsSensitivityLoading(false);
    }

    await runBreakEven(
      request,
      targetLeveredIrrPercent,
      targetEquityMultiple,
      targetHeadlineDscr,
      returnHurdleMetric,
    );
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header-brand">
          <img className="app-header-logo" src="/anchor-mark.png" alt="" />
          <div>
            <h1>Anchor</h1>
            <p>Commercial Real Estate Acquisition Analysis</p>
          </div>
        </div>
      </header>

      <main className="app-main">
        <div className="operating-mode-toggle" role="tablist" aria-label="Underwriting Mode">
          <button
            type="button"
            role="tab"
            aria-selected={operatingMode === 'quick'}
            className={
              operatingMode === 'quick'
                ? 'mode-toggle-button mode-toggle-button-active'
                : 'mode-toggle-button'
            }
            onClick={() => setOperatingMode('quick')}
          >
            Quick Underwrite
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={operatingMode === 'detailed'}
            className={
              operatingMode === 'detailed'
                ? 'mode-toggle-button mode-toggle-button-active'
                : 'mode-toggle-button'
            }
            onClick={() => setOperatingMode('detailed')}
          >
            Detailed Underwrite
          </button>
        </div>

        {view === 'library' ? (
          <DealLibraryPanel
            deals={savedDeals}
            isLoading={isDealsLoading}
            error={dealsError}
            onOpen={(deal) => void handleOpenDeal(deal)}
            onDuplicate={(deal) => void handleDuplicateDeal(deal)}
            onDelete={(deal) => void handleDeleteDeal(deal)}
            onClose={handleCloseLibrary}
          />
        ) : operatingMode === 'detailed' ? (
          <>
            <DealBar
              dealName={detailedDealName}
              onDealNameChange={handleDetailedDealNameChange}
              isSavedDeal={currentDetailedDealId !== null}
              isSaving={isSavingDetailedDeal}
              error={saveDetailedDealError}
              saveStatus={detailedSaveStatus}
              lastSavedAt={lastDetailedSavedAt}
              onSaveDeal={() => void handleSaveDetailedDeal()}
              onOpenLibrary={handleOpenLibrary}
              onNewDeal={handleNewDetailedDeal}
            />

            <DealContextField
              value={detailedDealContext}
              onChange={handleDetailedDealContextChange}
            />

            <div className="intake-section">
              <h2 className="section-heading">Deal Intake</h2>
              <div className="intake-grid">
                <ExcelUploadPanel
                  isLoading={isUploadingDetailedExcel}
                  error={detailedExcelUploadError}
                  successMessage={detailedExcelUploadSuccessMessage}
                  onUpload={(file) => void handleUploadDetailedExcel(file)}
                />

                <DetailedOmReviewPanel
                  extraction={detailedOcrExtraction}
                  isLoading={isDetailedExtracting}
                  error={detailedExtractionError}
                  onUpload={(file) => void handleUploadDetailedOm(file)}
                  onFinishReview={handleFinishDetailedOmReview}
                  onCancel={handleCancelDetailedOmReview}
                />
              </div>

              {detailedExcelReview && (
                <DetailedExcelReviewPanel
                  fileName={detailedExcelReview.fileName}
                  termsValues={detailedExcelReview.values.terms}
                  operatingValues={detailedExcelReview.values.operating}
                  error={detailedExcelReviewError}
                  onTermsFieldChange={handleDetailedExcelReviewTermsFieldChange}
                  onOperatingFieldChange={handleDetailedExcelReviewOperatingFieldChange}
                  onApprove={handleApproveDetailedExcelReview}
                  onCancel={handleCancelDetailedExcelReview}
                />
              )}
            </div>

            <DetailedAssumptionsForm
              termsValues={detailedValues.terms}
              operatingValues={detailedValues.operating}
              onTermsFieldChange={handleDetailedTermsFieldChange}
              onOperatingFieldChange={handleDetailedOperatingFieldChange}
              onSubmit={(event) => void handleDetailedSubmit(event)}
              isSubmitting={isDetailedSubmitting}
            />

            <div className="results-column">
              {detailedError && <div className="error-banner">{detailedError}</div>}

              {!detailedResults && !detailedError && (
                <div className="empty-state">
                  Enter assumptions and click <strong>Analyze Deal</strong> to see results.
                </div>
              )}

              {detailedResults && lastDetailedRequest && (
                <OwnerSummaryPanel
                  data={buildOwnerSummaryData({
                    operatingMode: 'detailed',
                    dealName: detailedDealName,
                    dealContext: detailedDealContext,
                    terms: lastDetailedRequest.terms,
                    detailedOperatingInputs: lastDetailedRequest.detailedOperatingInputs,
                    results: detailedResults.results,
                    breakEven: detailedBreakEven,
                  })}
                />
              )}

              {detailedResults && <ResultsPanel results={detailedResults.results} />}

              {detailedResults && (
                <OperatingStatementTable
                  operatingProjection={detailedResults.operating_projection}
                  results={detailedResults.results}
                />
              )}

              {detailedResults && (
                <SensitivityPanel
                  presets={detailedSensitivity}
                  isLoading={isDetailedSensitivityLoading}
                  error={detailedSensitivityError}
                />
              )}

              {detailedResults && (
                <BreakEvenPanel
                  analysis={detailedBreakEven}
                  isLoading={isDetailedBreakEvenLoading}
                  error={detailedBreakEvenError}
                  targetLeveredIrrPercent={detailedTargetLeveredIrrPercent}
                  targetEquityMultiple={detailedTargetEquityMultiple}
                  targetHeadlineDscr={detailedTargetHeadlineDscr}
                  returnHurdleMetric={detailedReturnHurdleMetric}
                  onTargetLeveredIrrChange={handleDetailedTargetLeveredIrrChange}
                  onTargetEquityMultipleChange={handleDetailedTargetEquityMultipleChange}
                  onTargetHeadlineDscrChange={handleDetailedTargetHeadlineDscrChange}
                  onReturnHurdleMetricChange={handleDetailedReturnHurdleMetricChange}
                />
              )}

              {detailedResults && (
                <AiAnalystPanel
                  analysis={detailedAiAnalysis}
                  isLoading={isDetailedAiAnalysisLoading}
                  error={detailedAiAnalysisError}
                  onGenerate={() => void handleGenerateDetailedAiAnalysis()}
                />
              )}
            </div>
          </>
        ) : (
          <>
            <DealBar
              dealName={dealName}
              onDealNameChange={handleDealNameChange}
              isSavedDeal={currentDealId !== null}
              isSaving={isSavingDeal}
              error={saveDealError}
              saveStatus={saveStatus}
              lastSavedAt={lastSavedAt}
              onSaveDeal={() => void handleSaveDeal()}
              onOpenLibrary={handleOpenLibrary}
              onNewDeal={handleNewDeal}
            />

            <DealContextField value={dealContext} onChange={handleDealContextChange} />

            <div className="intake-section">
              <h2 className="section-heading">Deal Intake</h2>
              <div className="intake-grid">
                <ExcelUploadPanel
                  isLoading={isUploadingExcel}
                  error={excelUploadError}
                  successMessage={excelUploadSuccessMessage}
                  onUpload={(file) => void handleUploadExcel(file)}
                />

                <OmReviewPanel
                  extraction={ocrExtraction}
                  isLoading={isExtracting}
                  error={extractionError}
                  onUpload={(file) => void handleUploadOm(file)}
                  onFinishReview={handleFinishOmReview}
                />
              </div>

              {excelReview && (
                <ExcelReviewPanel
                  fileName={excelReview.fileName}
                  values={excelReview.values}
                  requiredV2FieldIds={excelReview.requiredV2FieldIds}
                  error={excelReviewError}
                  onFieldChange={handleExcelReviewFieldChange}
                  onApprove={handleApproveExcelReview}
                  onCancel={handleCancelExcelReview}
                />
              )}
            </div>

            <AssumptionsForm
              values={values}
              onFieldChange={handleFieldChange}
              onSubmit={handleSubmit}
              isSubmitting={isSubmitting}
            />

            <div className="results-column">
              {error && <div className="error-banner">{error}</div>}

              {!results && !error && (
                <div className="empty-state">
                  Enter assumptions and click <strong>Analyze Deal</strong> to see results.
                </div>
              )}

              {results && lastRequest && (
                <OwnerSummaryPanel
                  data={buildOwnerSummaryData({
                    operatingMode: 'quick',
                    dealName,
                    dealContext,
                    inputs: lastRequest,
                    results,
                    breakEven,
                  })}
                />
              )}

              {results && <ResultsPanel results={results} />}

              {results && (
                <SensitivityPanel
                  presets={sensitivity}
                  isLoading={isSensitivityLoading}
                  error={sensitivityError}
                />
              )}

              {results && (
                <BreakEvenPanel
                  analysis={breakEven}
                  isLoading={isBreakEvenLoading}
                  error={breakEvenError}
                  targetLeveredIrrPercent={targetLeveredIrrPercent}
                  targetEquityMultiple={targetEquityMultiple}
                  targetHeadlineDscr={targetHeadlineDscr}
                  returnHurdleMetric={returnHurdleMetric}
                  onTargetLeveredIrrChange={handleTargetLeveredIrrChange}
                  onTargetEquityMultipleChange={handleTargetEquityMultipleChange}
                  onTargetHeadlineDscrChange={handleTargetHeadlineDscrChange}
                  onReturnHurdleMetricChange={handleReturnHurdleMetricChange}
                />
              )}

              {results && (
                <AiAnalystPanel
                  analysis={aiAnalysis}
                  isLoading={isAiAnalysisLoading}
                  error={aiAnalysisError}
                  onGenerate={() => void handleGenerateAiAnalysis()}
                />
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
