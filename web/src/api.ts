import type {
  AcquisitionRequest,
  AcquisitionResults,
  AcquisitionTermsRequest,
  AIAnalysis,
  Deal,
  DetailedAcquisitionResults,
  DetailedExcelIntakeReport,
  DetailedExtractionResult,
  DetailedOperatingInputsRequest,
  ExcelIntakeReport,
  ExtractionResult,
  ReturnHurdleMetric,
  StandardBreakEvenAnalysis,
  StandardDetailedBreakEvenAnalysis,
  StandardDetailedSensitivityPresets,
  StandardSensitivityPresets,
  ValidationIssue,
} from './types';
import type {
  LeaseLevelAcquisitionResults,
  LeaseLevelInputsRequest,
  LeaseLevelIssue,
} from './leaseLevelTypes';
import type {
  LeaseLevelOneWaySensitivityControls,
  LeaseLevelOneWaySensitivityResult,
  LeaseLevelTwoWaySensitivityControls,
  LeaseLevelTwoWaySensitivityResult,
} from './leaseLevelSensitivityTypes';

const API_BASE_URL = 'http://127.0.0.1:8000';

/** The single unreachable-backend message, shared by the D5.5A client
 * functions. Identical wording to the one the existing functions inline. */
const NETWORK_ERROR_MESSAGE =
  'Could not reach the Anchor API. Confirm the backend is running at ' +
  `${API_BASE_URL}.`;

export class ApiError extends Error {
  issues: ValidationIssue[];

  constructor(message: string, issues: ValidationIssue[] = []) {
    super(message);
    this.name = 'ApiError';
    this.issues = issues;
  }
}

/**
 * D5.5A -- a 422 from a Lease-Level request, carrying whichever issue shape the
 * backend actually returned.
 *
 * A single Lease-Level endpoint can fail in two different vocabularies:
 * `terms` goes through the shared `validate_acquisition_terms` and produces
 * `ValidationIssue`s keyed by `field_id`, while the Lease-Level parser and
 * validators produce `LeaseLevelIssue`s keyed by `path`. Rather than guess from
 * the mode, the client reads the detail array's own shape and reports both.
 *
 * Extends `ApiError` so every existing `catch (error) { if (error instanceof
 * ApiError) ... }` site keeps working unchanged and still sees a real message.
 */
export class LeaseLevelApiError extends ApiError {
  leaseIssues: LeaseLevelIssue[];

  constructor(message: string, issues: ValidationIssue[], leaseIssues: LeaseLevelIssue[]) {
    super(message, issues);
    this.name = 'LeaseLevelApiError';
    this.leaseIssues = leaseIssues;
  }
}

/**
 * POSTs an acquisition request to the FastAPI ``/analyze`` endpoint and
 * returns the raw ``AcquisitionResults`` JSON. Performs no financial
 * calculation or validation of its own -- the backend is authoritative.
 */
export async function analyzeAcquisition(
  request: AcquisitionRequest,
): Promise<AcquisitionResults> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  if (response.status === 422) {
    const body = await response.json().catch(() => null);
    const issues: ValidationIssue[] = Array.isArray(body?.detail) ? body.detail : [];
    const message =
      issues.length > 0
        ? issues.map((issue) => issue.message).join(' ')
        : 'The submitted assumptions failed validation.';
    throw new ApiError(message, issues);
  }

  if (!response.ok) {
    throw new ApiError(`The analysis request failed (HTTP ${response.status}).`);
  }

  return (await response.json()) as AcquisitionResults;
}

/**
 * Detailed Operating Model V2.1 Gate 6: POSTs an ``operating_mode:
 * "detailed"`` request (``terms`` + ``detailed_operating_inputs``) to the
 * same FastAPI ``/analyze`` endpoint and returns the raw
 * ``DetailedAcquisitionResults`` JSON -- the operating projection alongside
 * the same ``AcquisitionResults`` shape a Quick request returns. Performs
 * no financial calculation or validation of its own -- the backend is
 * authoritative, exactly like ``analyzeAcquisition``.
 */
export async function analyzeDetailedAcquisition(
  terms: AcquisitionTermsRequest,
  detailedOperatingInputs: DetailedOperatingInputsRequest,
): Promise<DetailedAcquisitionResults> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        operating_mode: 'detailed',
        terms,
        detailed_operating_inputs: detailedOperatingInputs,
      }),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  if (response.status === 422) {
    const body = await response.json().catch(() => null);
    const issues: ValidationIssue[] = Array.isArray(body?.detail) ? body.detail : [];
    const message =
      issues.length > 0
        ? issues.map((issue) => issue.message).join(' ')
        : 'The submitted assumptions failed validation.';
    throw new ApiError(message, issues);
  }

  if (!response.ok) {
    throw new ApiError(`The analysis request failed (HTTP ${response.status}).`);
  }

  return (await response.json()) as DetailedAcquisitionResults;
}

/**
 * POSTs an acquisition input set to the FastAPI ``/sensitivity/presets``
 * endpoint and returns the raw ``StandardSensitivityPresets`` JSON. Performs
 * no sensitivity calculation of its own -- the backend analysis layer is
 * authoritative.
 */
export async function fetchSensitivityPresets(
  inputs: AcquisitionRequest,
): Promise<StandardSensitivityPresets> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/sensitivity/presets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inputs }),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  if (response.status === 422) {
    const body = await response.json().catch(() => null);
    const issues: ValidationIssue[] = Array.isArray(body?.detail) ? body.detail : [];
    const message =
      issues.length > 0
        ? issues.map((issue) => issue.message).join(' ')
        : 'The submitted assumptions failed sensitivity validation.';
    throw new ApiError(message, issues);
  }

  if (!response.ok) {
    throw new ApiError(`The sensitivity request failed (HTTP ${response.status}).`);
  }

  return (await response.json()) as StandardSensitivityPresets;
}

/**
 * Detailed Operating Model V2.1 Gate 14: POSTs an ``operating_mode:
 * "detailed"`` request (``terms`` + ``detailed_operating_inputs``) to the
 * same FastAPI ``/sensitivity/presets`` endpoint and returns the raw
 * ``StandardDetailedSensitivityPresets`` JSON. Performs no sensitivity
 * calculation of its own -- the backend analysis layer is authoritative,
 * exactly like ``fetchSensitivityPresets``.
 */
export async function fetchDetailedSensitivityPresets(
  terms: AcquisitionTermsRequest,
  detailedOperatingInputs: DetailedOperatingInputsRequest,
): Promise<StandardDetailedSensitivityPresets> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/sensitivity/presets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        operating_mode: 'detailed',
        terms,
        detailed_operating_inputs: detailedOperatingInputs,
      }),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  if (response.status === 422) {
    const body = await response.json().catch(() => null);
    const issues: ValidationIssue[] = Array.isArray(body?.detail) ? body.detail : [];
    const message =
      issues.length > 0
        ? issues.map((issue) => issue.message).join(' ')
        : 'The submitted assumptions failed sensitivity validation.';
    throw new ApiError(message, issues);
  }

  if (!response.ok) {
    throw new ApiError(`The sensitivity request failed (HTTP ${response.status}).`);
  }

  return (await response.json()) as StandardDetailedSensitivityPresets;
}

/**
 * POSTs an acquisition input set, the three hurdle targets, and the
 * selected return-hurdle metric to the FastAPI ``/break-even`` endpoint and
 * returns the raw ``StandardBreakEvenAnalysis`` JSON. Performs no threshold
 * search of its own -- the backend analysis layer is authoritative.
 */
export async function fetchBreakEvenAnalysis(
  inputs: AcquisitionRequest,
  targetLeveredIrr: number,
  targetEquityMultiple: number,
  targetHeadlineDscr: number,
  returnHurdleMetric: ReturnHurdleMetric,
): Promise<StandardBreakEvenAnalysis> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/break-even`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        inputs,
        target_levered_irr: targetLeveredIrr,
        target_equity_multiple: targetEquityMultiple,
        target_headline_dscr: targetHeadlineDscr,
        return_hurdle_metric: returnHurdleMetric,
      }),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  if (response.status === 422) {
    const body = await response.json().catch(() => null);
    const issues: ValidationIssue[] = Array.isArray(body?.detail) ? body.detail : [];
    const message =
      issues.length > 0
        ? issues.map((issue) => issue.message).join(' ')
        : 'The submitted break-even request failed validation.';
    throw new ApiError(message, issues);
  }

  if (!response.ok) {
    throw new ApiError(`The break-even request failed (HTTP ${response.status}).`);
  }

  return (await response.json()) as StandardBreakEvenAnalysis;
}

/**
 * Detailed Operating Model V2.1 Gate 14: POSTs an ``operating_mode:
 * "detailed"`` request (``terms`` + ``detailed_operating_inputs``), the
 * three hurdle targets, and the selected return-hurdle metric to the same
 * FastAPI ``/break-even`` endpoint and returns the raw
 * ``StandardDetailedBreakEvenAnalysis`` JSON. Performs no threshold search
 * of its own -- the backend analysis layer is authoritative, exactly like
 * ``fetchBreakEvenAnalysis``.
 */
export async function fetchDetailedBreakEvenAnalysis(
  terms: AcquisitionTermsRequest,
  detailedOperatingInputs: DetailedOperatingInputsRequest,
  targetLeveredIrr: number,
  targetEquityMultiple: number,
  targetHeadlineDscr: number,
  returnHurdleMetric: ReturnHurdleMetric,
): Promise<StandardDetailedBreakEvenAnalysis> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/break-even`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        operating_mode: 'detailed',
        terms,
        detailed_operating_inputs: detailedOperatingInputs,
        target_levered_irr: targetLeveredIrr,
        target_equity_multiple: targetEquityMultiple,
        target_headline_dscr: targetHeadlineDscr,
        return_hurdle_metric: returnHurdleMetric,
      }),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  if (response.status === 422) {
    const body = await response.json().catch(() => null);
    const issues: ValidationIssue[] = Array.isArray(body?.detail) ? body.detail : [];
    const message =
      issues.length > 0
        ? issues.map((issue) => issue.message).join(' ')
        : 'The submitted break-even request failed validation.';
    throw new ApiError(message, issues);
  }

  if (!response.ok) {
    throw new ApiError(`The break-even request failed (HTTP ${response.status}).`);
  }

  return (await response.json()) as StandardDetailedBreakEvenAnalysis;
}

/**
 * POSTs an acquisition input set, the three hurdle targets, and the
 * selected return-hurdle metric to the FastAPI ``/ai/analysis`` endpoint
 * and returns the raw ``AIAnalysis`` JSON. Performs no interpretation or
 * calculation of its own -- the backend AI Analyst layer is authoritative,
 * and this function never talks to OpenAI directly (no provider secret is
 * ever available to the browser).
 */
export async function fetchAIAnalysis(
  inputs: AcquisitionRequest,
  targetLeveredIrr: number,
  targetEquityMultiple: number,
  targetHeadlineDscr: number,
  returnHurdleMetric: ReturnHurdleMetric,
  dealContext?: string | null,
): Promise<AIAnalysis> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/ai/analysis`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        inputs,
        target_levered_irr: targetLeveredIrr,
        target_equity_multiple: targetEquityMultiple,
        target_headline_dscr: targetHeadlineDscr,
        return_hurdle_metric: returnHurdleMetric,
        deal_context: dealContext ?? null,
      }),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  if (response.status === 422) {
    const body = await response.json().catch(() => null);
    const issues: ValidationIssue[] = Array.isArray(body?.detail) ? body.detail : [];
    const message =
      issues.length > 0
        ? issues.map((issue) => issue.message).join(' ')
        : 'The submitted AI analysis request failed validation.';
    throw new ApiError(message, issues);
  }

  if (response.status === 503) {
    const body = await response.json().catch(() => null);
    const message =
      typeof body?.detail === 'string' ? body.detail : 'The AI Analyst is not configured.';
    throw new ApiError(message);
  }

  if (response.status === 502) {
    const body = await response.json().catch(() => null);
    const message =
      typeof body?.detail === 'string' ? body.detail : 'The AI Analyst request failed.';
    throw new ApiError(message);
  }

  if (!response.ok) {
    throw new ApiError(`The AI analysis request failed (HTTP ${response.status}).`);
  }

  return (await response.json()) as AIAnalysis;
}

/**
 * Detailed Operating Model V2.1 Gate 9: POSTs an ``operating_mode:
 * "detailed"`` request (``terms`` + ``detailed_operating_inputs``, the
 * three hurdle targets, and the selected return-hurdle metric) to the same
 * FastAPI ``/ai/analysis`` endpoint and returns the raw ``AIAnalysis``
 * JSON -- the identical response shape ``fetchAIAnalysis`` returns for
 * Quick mode. Performs no interpretation or calculation of its own -- the
 * backend AI Analyst layer is authoritative, and this function never talks
 * to OpenAI directly.
 */
export async function fetchDetailedAIAnalysis(
  terms: AcquisitionTermsRequest,
  detailedOperatingInputs: DetailedOperatingInputsRequest,
  targetLeveredIrr: number,
  targetEquityMultiple: number,
  targetHeadlineDscr: number,
  returnHurdleMetric: ReturnHurdleMetric,
  dealContext?: string | null,
): Promise<AIAnalysis> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/ai/analysis`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        operating_mode: 'detailed',
        terms,
        detailed_operating_inputs: detailedOperatingInputs,
        target_levered_irr: targetLeveredIrr,
        target_equity_multiple: targetEquityMultiple,
        target_headline_dscr: targetHeadlineDscr,
        return_hurdle_metric: returnHurdleMetric,
        deal_context: dealContext ?? null,
      }),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  if (response.status === 422) {
    const body = await response.json().catch(() => null);
    const issues: ValidationIssue[] = Array.isArray(body?.detail) ? body.detail : [];
    const message =
      issues.length > 0
        ? issues.map((issue) => issue.message).join(' ')
        : 'The submitted AI analysis request failed validation.';
    throw new ApiError(message, issues);
  }

  if (response.status === 503) {
    const body = await response.json().catch(() => null);
    const message =
      typeof body?.detail === 'string' ? body.detail : 'The AI Analyst is not configured.';
    throw new ApiError(message);
  }

  if (response.status === 502) {
    const body = await response.json().catch(() => null);
    const message =
      typeof body?.detail === 'string' ? body.detail : 'The AI Analyst request failed.';
    throw new ApiError(message);
  }

  if (!response.ok) {
    throw new ApiError(`The AI analysis request failed (HTTP ${response.status}).`);
  }

  return (await response.json()) as AIAnalysis;
}

/**
 * Uploads an Offering Memorandum PDF to the FastAPI ``POST /ingestion/om``
 * endpoint as multipart form data and returns the raw ``ExtractionResult``
 * JSON. Performs no extraction, classification, or provenance verification
 * of its own -- the backend ingestion layer is authoritative -- and never
 * talks to Azure/OpenAI directly (no provider credential is ever available
 * to the browser). The browser sets the multipart ``Content-Type`` boundary
 * itself, so this function must not set that header explicitly.
 */
export async function uploadOm(file: File): Promise<ExtractionResult> {
  const formData = new FormData();
  formData.append('file', file);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/ingestion/om`, {
      method: 'POST',
      body: formData,
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  if (response.status === 503) {
    const body = await response.json().catch(() => null);
    const message =
      typeof body?.detail === 'string' ? body.detail : 'The OM ingestion service is not configured.';
    throw new ApiError(message);
  }

  if (response.status === 502) {
    const body = await response.json().catch(() => null);
    const message =
      typeof body?.detail === 'string' ? body.detail : 'The OM extraction request failed.';
    throw new ApiError(message);
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message =
      typeof body?.detail === 'string'
        ? body.detail
        : `The OM upload was rejected (HTTP ${response.status}).`;
    throw new ApiError(message);
  }

  return (await response.json()) as ExtractionResult;
}

/**
 * Detailed Operating Model V2.1 Gate 12: uploads an Offering Memorandum
 * PDF to the FastAPI ``POST /ingestion/om/detailed`` endpoint as multipart
 * form data and returns the raw ``DetailedExtractionResult`` JSON. Mirrors
 * ``uploadOm`` exactly, over the separate Detailed endpoint (Gate 12's
 * Option B) -- performs no extraction, classification, or financial
 * calculation of its own, and never talks to Azure/OpenAI directly.
 */
export async function uploadDetailedOm(file: File): Promise<DetailedExtractionResult> {
  const formData = new FormData();
  formData.append('file', file);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/ingestion/om/detailed`, {
      method: 'POST',
      body: formData,
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  if (response.status === 503) {
    const body = await response.json().catch(() => null);
    const message =
      typeof body?.detail === 'string' ? body.detail : 'The OM ingestion service is not configured.';
    throw new ApiError(message);
  }

  if (response.status === 502) {
    const body = await response.json().catch(() => null);
    const message =
      typeof body?.detail === 'string' ? body.detail : 'The OM extraction request failed.';
    throw new ApiError(message);
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message =
      typeof body?.detail === 'string'
        ? body.detail
        : `The OM upload was rejected (HTTP ${response.status}).`;
    throw new ApiError(message);
  }

  return (await response.json()) as DetailedExtractionResult;
}

/**
 * Uploads an Anchor Excel acquisition workbook to the FastAPI
 * ``POST /ingestion/excel`` endpoint as multipart form data and returns the
 * fourteen validated ``AcquisitionRequest`` fields plus which Underwriting
 * V2 fields were absent from the workbook and therefore defaulted
 * (``ExcelIntakeReport``, Gate 5). Performs no workbook parsing or
 * financial validation of its own -- the backend Excel reader (shared with
 * the CLI) is authoritative. The browser sets the multipart
 * ``Content-Type`` boundary itself, so this function must not set that
 * header explicitly. Unlike ``uploadOm``, a successful response is already
 * a complete, validated input set -- there is no candidate/evidence review
 * step -- and a malformed workbook fails with the exact same 422 issue-list
 * shape ``analyzeAcquisition`` already handles.
 */
export async function uploadExcel(file: File): Promise<ExcelIntakeReport> {
  const formData = new FormData();
  formData.append('file', file);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/ingestion/excel`, {
      method: 'POST',
      body: formData,
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  if (response.status === 422) {
    const body = await response.json().catch(() => null);
    const issues: ValidationIssue[] = Array.isArray(body?.detail) ? body.detail : [];
    const message =
      issues.length > 0
        ? issues.map((issue) => issue.message).join(' ')
        : 'The uploaded workbook failed validation.';
    throw new ApiError(message, issues);
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message =
      typeof body?.detail === 'string'
        ? body.detail
        : `The Excel upload was rejected (HTTP ${response.status}).`;
    throw new ApiError(message);
  }

  return (await response.json()) as ExcelIntakeReport;
}

/**
 * Detailed Operating Model V2.1 Gate 10: uploads a Detailed Anchor Excel
 * workbook to the FastAPI ``POST /ingestion/excel/detailed`` endpoint as
 * multipart form data and returns the parsed ``AcquisitionTerms``/
 * ``DetailedOperatingInputs`` plus the workbook's declared schema/version
 * (``DetailedExcelIntakeReport``). Performs no workbook parsing, financial
 * validation, or workbook-schema classification of its own -- the backend
 * Detailed Excel reader is authoritative, including rejecting a Quick
 * workbook uploaded here with the same 422 issue-list shape
 * ``analyzeDetailedAcquisition`` already handles. Mirrors ``uploadExcel``
 * exactly, over the separate Detailed endpoint (Gate 10's Option B).
 */
export async function uploadDetailedExcel(file: File): Promise<DetailedExcelIntakeReport> {
  const formData = new FormData();
  formData.append('file', file);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/ingestion/excel/detailed`, {
      method: 'POST',
      body: formData,
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  if (response.status === 422) {
    const body = await response.json().catch(() => null);
    const issues: ValidationIssue[] = Array.isArray(body?.detail) ? body.detail : [];
    const message =
      issues.length > 0
        ? issues.map((issue) => issue.message).join(' ')
        : 'The uploaded workbook failed validation.';
    throw new ApiError(message, issues);
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message =
      typeof body?.detail === 'string'
        ? body.detail
        : `The Excel upload was rejected (HTTP ${response.status}).`;
    throw new ApiError(message);
  }

  return (await response.json()) as DetailedExcelIntakeReport;
}

// =============================================================================
// Persistence Phase B -- Deal Library
//
// Each function mirrors the shape of ``analyzeAcquisition`` above: POST/PUT
// send the same fourteen-field ``AcquisitionRequest`` shape ``/analyze``
// already accepts, and a 422 response carries the identical issue-list shape,
// because both endpoints validate through the same backend function. These
// functions never call ``/analyze`` themselves -- saving is not analyzing.
// =============================================================================

async function _handleDealResponse(response: Response, failureMessage: string): Promise<Deal> {
  if (response.status === 422) {
    const body = await response.json().catch(() => null);
    const issues: ValidationIssue[] = Array.isArray(body?.detail) ? body.detail : [];
    const message =
      issues.length > 0
        ? issues.map((issue) => issue.message).join(' ')
        : 'The submitted deal failed validation.';
    throw new ApiError(message, issues);
  }

  if (response.status === 404) {
    throw new ApiError('That deal could not be found. It may have been deleted.');
  }

  if (!response.ok) {
    throw new ApiError(`${failureMessage} (HTTP ${response.status}).`);
  }

  return (await response.json()) as Deal;
}

/**
 * POSTs a new deal (name + the fourteen assumptions) to ``/deals``. Used for
 * a deal that has never been saved -- ``currentDealId`` is still ``null``.
 *
 * Owner Return Metrics V3 Gate A7: this route persists assumptions/Deal
 * Context only -- it never accepts ``analysis_snapshot``/``ai_snapshot`` (a
 * generic assumptions write can never be paired with an unverified derived-
 * results payload in the same call). To persist a *current, valid*
 * analysis/AI immediately after creating an unsaved, already-analyzed deal,
 * call ``updateDealAnalysisSnapshot``/``updateDealAiSnapshot`` against the
 * id this returns -- both are independently provenance-validated.
 */
export async function createDeal(
  name: string,
  inputs: AcquisitionRequest,
  dealContext?: string | null,
): Promise<Deal> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/deals`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        inputs,
        deal_context: dealContext ?? null,
      }),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  return _handleDealResponse(response, 'The deal could not be saved');
}

/**
 * PUTs an already-saved deal's name and assumptions to ``/deals/{id}``.
 *
 * Owner Return Metrics V3 Gate A7: mirrors ``createDeal``'s
 * never-accepts-a-snapshot contract exactly -- this route never touches the
 * deal's cached snapshots. Preservation across a Deal-Context-only edit and
 * invalidation across an assumption edit both happen automatically on the
 * backend via its unchanged read-time fingerprint check.
 */
export async function updateDeal(
  dealId: string,
  name: string,
  inputs: AcquisitionRequest,
  dealContext?: string | null,
): Promise<Deal> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/deals/${encodeURIComponent(dealId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        inputs,
        deal_context: dealContext ?? null,
      }),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  return _handleDealResponse(response, 'The deal could not be updated');
}

/**
 * Detailed Operating Model V2.1 Gate 11: POSTs a new Detailed deal
 * (name + ``operating_mode: "detailed"`` + ``terms`` +
 * ``detailed_operating_inputs``) to ``/deals``. A dedicated function
 * (mirroring ``createDeal``'s shape exactly) rather than an
 * overloaded/discriminated ``createDeal`` -- Quick's existing call sites
 * and tests are unaffected. Used for a Detailed deal that has never been
 * saved -- ``currentDetailedDealId`` is still ``null``.
 */
export async function createDetailedDeal(
  name: string,
  terms: AcquisitionTermsRequest,
  detailedOperatingInputs: DetailedOperatingInputsRequest,
  dealContext?: string | null,
): Promise<Deal> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/deals`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        operating_mode: 'detailed',
        terms,
        detailed_operating_inputs: detailedOperatingInputs,
        deal_context: dealContext ?? null,
      }),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  return _handleDealResponse(response, 'The deal could not be saved');
}

/** PUTs an already-saved Detailed deal's name, terms, and detailed
 * operating inputs to ``/deals/{id}``. Mirrors ``updateDeal`` exactly. */
export async function updateDetailedDeal(
  dealId: string,
  name: string,
  terms: AcquisitionTermsRequest,
  detailedOperatingInputs: DetailedOperatingInputsRequest,
  dealContext?: string | null,
): Promise<Deal> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/deals/${encodeURIComponent(dealId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        operating_mode: 'detailed',
        terms,
        detailed_operating_inputs: detailedOperatingInputs,
        deal_context: dealContext ?? null,
      }),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  return _handleDealResponse(response, 'The deal could not be updated');
}

/**
 * Owner Return Metrics V3 Gate A7 -- the backend-authoritative provenance
 * lookup. Given the same assumptions (and, for the AI fingerprint, Deal
 * Context) just analyzed/interpreted, returns the exact canonical
 * fingerprint(s) the backend will independently recompute at snapshot-write
 * time. The frontend never computes (or duplicates in TypeScript) this
 * algorithm itself -- it only ever transports the opaque string this
 * endpoint returns back to ``updateDealAnalysisSnapshot``/
 * ``updateDealAiSnapshot`` below.
 */
export interface DealFingerprint {
  financial_input_fingerprint: string;
  ai_context_fingerprint: string;
}

export async function fetchDealFingerprint(
  inputs: AcquisitionRequest,
  dealContext?: string | null,
): Promise<DealFingerprint> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/deals/fingerprint`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        operating_mode: 'quick',
        inputs,
        deal_context: dealContext ?? null,
      }),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }
  if (!response.ok) {
    throw new ApiError(`The deal fingerprint could not be retrieved (HTTP ${response.status}).`);
  }
  return (await response.json()) as DealFingerprint;
}

/** Detailed counterpart of ``fetchDealFingerprint`` -- mirrors it exactly,
 * over ``terms``/``detailedOperatingInputs`` instead of ``inputs``. */
export async function fetchDetailedDealFingerprint(
  terms: AcquisitionTermsRequest,
  detailedOperatingInputs: DetailedOperatingInputsRequest,
  dealContext?: string | null,
): Promise<DealFingerprint> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/deals/fingerprint`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        operating_mode: 'detailed',
        terms,
        detailed_operating_inputs: detailedOperatingInputs,
        deal_context: dealContext ?? null,
      }),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }
  if (!response.ok) {
    throw new ApiError(`The deal fingerprint could not be retrieved (HTTP ${response.status}).`);
  }
  return (await response.json()) as DealFingerprint;
}

/**
 * Owner Return Metrics V3 Gate A6/A7 -- silent background cache refresh.
 * PUTs only the cached deterministic-analysis snapshot to
 * ``/deals/{id}/analysis-snapshot``; never touches name, assumptions, Deal
 * Context, the AI snapshot, or the deal's save timestamp. Used after a
 * successful Analyze on an already-saved, not-dirty deal -- never marks
 * the deal dirty and never requires an explicit Save. One shape for both
 * modes' callers: pass an ``AcquisitionResults`` for Quick or a
 * ``DetailedAcquisitionResults`` for Detailed, matching whichever mode
 * ``dealId`` actually is.
 *
 * Gate A7: also requires ``financialInputFingerprint`` -- the opaque
 * provenance token obtained from ``fetchDealFingerprint``/
 * ``fetchDetailedDealFingerprint`` using the exact same assumptions that
 * produced ``analysisSnapshot``. The backend independently verifies it
 * against the deal's own currently-stored assumptions and rejects (422) a
 * mismatch rather than persisting it.
 */
export async function updateDealAnalysisSnapshot(
  dealId: string,
  analysisSnapshot: AcquisitionResults | DetailedAcquisitionResults,
  financialInputFingerprint: string,
): Promise<Deal> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE_URL}/deals/${encodeURIComponent(dealId)}/analysis-snapshot`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          analysis_snapshot: analysisSnapshot,
          financial_input_fingerprint: financialInputFingerprint,
        }),
      },
    );
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  return _handleDealResponse(response, 'The analysis could not be cached');
}

/**
 * Owner Return Metrics V3 Gate A6/A7 -- silent background cache refresh, AI
 * counterpart to ``updateDealAnalysisSnapshot`` above. PUTs only the
 * cached AI Analyst snapshot; never touches anything else. Used after a
 * successful Generate AI Analysis on an already-saved, not-dirty deal.
 *
 * Gate A7: also requires ``aiContextFingerprint`` -- mirrors
 * ``updateDealAnalysisSnapshot``'s provenance-token contract exactly.
 */
export async function updateDealAiSnapshot(
  dealId: string,
  aiSnapshot: AIAnalysis,
  aiContextFingerprint: string,
): Promise<Deal> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/deals/${encodeURIComponent(dealId)}/ai-snapshot`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ai_snapshot: aiSnapshot,
        ai_context_fingerprint: aiContextFingerprint,
      }),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  return _handleDealResponse(response, 'The AI analysis could not be cached');
}

/** GETs one saved deal by id, for reopening it into the assumptions form. */
export async function getDeal(dealId: string): Promise<Deal> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/deals/${encodeURIComponent(dealId)}`);
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  return _handleDealResponse(response, 'The deal could not be loaded');
}

/** GETs every saved deal for the Deal Library, most recently updated
 * first (the backend's own ordering -- this function does not re-sort). */
export async function listDeals(): Promise<Deal[]> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/deals`);
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  if (!response.ok) {
    throw new ApiError(`The deal library could not be loaded (HTTP ${response.status}).`);
  }

  return (await response.json()) as Deal[];
}

// =============================================================================
// Persistence Phase C -- duplicate / delete
// =============================================================================

/** POSTs to ``/deals/{id}/duplicate`` and returns the newly created copy
 * (a new id, fresh timestamps, the same nine inputs). Never triggers
 * `/analyze` -- the caller decides what to do with the copy. */
export async function duplicateDeal(dealId: string, name?: string): Promise<Deal> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/deals/${encodeURIComponent(dealId)}/duplicate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(name ? { name } : {}),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  return _handleDealResponse(response, 'The deal could not be duplicated');
}

/** DELETEs a saved deal. No soft-delete/history -- this is permanent. */
export async function deleteDeal(dealId: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/deals/${encodeURIComponent(dealId)}`, {
      method: 'DELETE',
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  if (response.status === 404) {
    throw new ApiError('That deal could not be found. It may have already been deleted.');
  }

  if (!response.ok) {
    throw new ApiError(`The deal could not be deleted (HTTP ${response.status}).`);
  }
}

// =============================================================================
// D5.5A -- one shared request/error path for the Lease-Level client functions.
//
// The Quick and Detailed functions above each inline this same fetch/422/!ok
// sequence, which is how they were written gate by gate. Reproducing it three
// more times would be three more places for the error contract to drift, so the
// new functions share one helper. The existing functions are deliberately left
// exactly as they are -- rewriting shipped, tested code to share a helper is not
// this gate's work.
// =============================================================================

async function sendJson(
  method: 'POST' | 'PUT',
  path: string,
  body: unknown,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(NETWORK_ERROR_MESSAGE);
  }

  if (response.status === 422) {
    const payload: unknown = await response.json().catch(() => null);
    throw leaseLevelValidationError(payload);
  }
  if (response.status === 404) {
    throw new ApiError('That deal no longer exists.');
  }
  if (!response.ok) {
    throw new ApiError(`The request failed (HTTP ${response.status}).`);
  }
  return response;
}

/** Narrows one 422 detail entry to the Lease-Level issue shape.
 *
 * Structural, not positional: an entry qualifies because it carries a `path`, a
 * `code` and a valid `severity`, never because of where it appeared or which
 * endpoint returned it. An entry that matches neither shape is not silently
 * dropped -- `leaseLevelValidationError` still counts it, so an unrecognised
 * detail can never turn a refusal into a blank screen. */
function isLeaseLevelIssue(entry: unknown): entry is LeaseLevelIssue {
  if (typeof entry !== 'object' || entry === null) {
    return false;
  }
  const candidate = entry as Record<string, unknown>;
  return (
    typeof candidate.code === 'string' &&
    typeof candidate.path === 'string' &&
    typeof candidate.message === 'string' &&
    (candidate.severity === 'error' || candidate.severity === 'warning')
  );
}

/** Narrows one 422 detail entry to the shared Quick/Detailed issue shape,
 * which is what `terms` validation still produces on a Lease-Level request. */
function isValidationIssue(entry: unknown): entry is ValidationIssue {
  if (typeof entry !== 'object' || entry === null) {
    return false;
  }
  const candidate = entry as Record<string, unknown>;
  return (
    (typeof candidate.field_id === 'string' || candidate.field_id === null) &&
    typeof candidate.category === 'string' &&
    typeof candidate.message === 'string'
  );
}

function leaseLevelValidationError(payload: unknown): ApiError {
  const detail: unknown =
    typeof payload === 'object' && payload !== null
      ? (payload as Record<string, unknown>).detail
      : null;
  const entries: unknown[] = Array.isArray(detail) ? detail : [];

  const leaseIssues = entries.filter(isLeaseLevelIssue);
  const issues = entries.filter(isValidationIssue);

  // Every message the backend sent, in the order it sent them, regardless of
  // which vocabulary each one arrived in. The banner is the last line of
  // defence: an issue the workspace cannot anchor to a field must still be
  // readable somewhere.
  const messages = entries
    .map((entry) =>
      typeof entry === 'object' && entry !== null
        ? (entry as Record<string, unknown>).message
        : null,
    )
    .filter((message): message is string => typeof message === 'string');

  // D5.7: a `detail` that is a plain string is a real refusal with a real
  // sentence in it -- `SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE`, an
  // unsupported target or metric, or a row/column target repeated -- and the
  // backend is the only thing that knows which. Reporting those as the generic
  // "failed validation" would replace the authoritative answer with a shrug, so
  // the string is surfaced verbatim. A structured `detail` array is unaffected.
  const stringDetail = typeof detail === 'string' && detail.trim() !== '' ? detail : null;

  const message =
    messages.length > 0
      ? messages.join(' ')
      : (stringDetail ?? 'The submitted assumptions failed validation.');
  return new LeaseLevelApiError(message, issues, leaseIssues);
}

async function postJson(path: string, body: unknown): Promise<Response> {
  return sendJson('POST', path, body);
}

// =============================================================================
// D5.5A -- Lease-Level client functions.
//
// The same endpoints every other mode uses, discriminated by `operating_mode`
// exactly as the Detailed functions above are. No parallel endpoint family, and
// no financial calculation: these build a typed body and hand back what the
// backend returned.
//
// One function per (endpoint x mode), matching the shipped convention. That is
// what makes the mode literal a *fact about the function* rather than a runtime
// branch that could be reached with the wrong argument.
// =============================================================================

/** `POST /analyze` with `operating_mode: "lease_level"`.
 *
 * Returns the three authoritative surfaces unchanged. Nothing is reshaped here:
 * an undefined `levered_irr` stays `null`, because a mid-hold leasing-capital
 * year legitimately leaves the levered IRR undefined and reporting it as zero
 * would turn a healthy deal into a broken-looking one. */
export async function analyzeLeaseLevelAcquisition(
  terms: AcquisitionTermsRequest,
  inputs: LeaseLevelInputsRequest,
): Promise<LeaseLevelAcquisitionResults> {
  const response = await postJson('/analyze', {
    operating_mode: 'lease_level',
    terms,
    ...inputs,
  });
  return (await response.json()) as LeaseLevelAcquisitionResults;
}

/** `POST /deals` with `operating_mode: "lease_level"`. */
export async function createLeaseLevelDeal(
  name: string,
  terms: AcquisitionTermsRequest,
  inputs: LeaseLevelInputsRequest,
  dealContext: string | null,
): Promise<Deal> {
  const response = await postJson('/deals', {
    operating_mode: 'lease_level',
    name,
    terms,
    ...inputs,
    ...(dealContext === null ? {} : { deal_context: dealContext }),
  });
  return (await response.json()) as Deal;
}

/** `PUT /deals/{id}` with `operating_mode: "lease_level"`.
 *
 * `inputs` carries the caller's whole rent roll, including suites and leases it
 * never edited: the backend replaces a Lease-Level deal's input state
 * wholesale, so omitting them would delete them. */
export async function updateLeaseLevelDeal(
  dealId: string,
  name: string,
  terms: AcquisitionTermsRequest,
  inputs: LeaseLevelInputsRequest,
  dealContext: string | null,
): Promise<Deal> {
  const response = await sendJson('PUT', `/deals/${dealId}`, {
    operating_mode: 'lease_level',
    name,
    terms,
    ...inputs,
    ...(dealContext === null ? {} : { deal_context: dealContext }),
  });
  return (await response.json()) as Deal;
}

/** `POST /ai/analysis` with `operating_mode: "lease_level"` (D5.8).
 *
 * The same endpoint Quick and Detailed use, discriminated by `operating_mode`
 * exactly as every other Lease-Level function here is. There is no second AI
 * product and no second endpoint: the response is the identical `AIAnalysis`
 * shape the other two modes return, so `AiAnalystPanel` renders it unchanged.
 *
 * `inputs` carries the whole approved rent roll, because the backend
 * underwrites the deal to ground the interpretation -- the same analysis
 * `analyzeLeaseLevelAcquisition` runs, from the same body. Nothing is computed
 * here, and this function never talks to a model provider.
 *
 * A 503 (no provider configured) and a 502 (provider failed) are surfaced as
 * their own messages, exactly as the Quick and Detailed clients do, so an
 * absent API key reads as "the AI Analyst is not configured" rather than as a
 * broken deal. */
export async function fetchLeaseLevelAIAnalysis(
  terms: AcquisitionTermsRequest,
  inputs: LeaseLevelInputsRequest,
  targetLeveredIrr: number,
  targetEquityMultiple: number,
  targetHeadlineDscr: number,
  returnHurdleMetric: ReturnHurdleMetric,
  dealContext: string | null,
): Promise<AIAnalysis> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/ai/analysis`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        operating_mode: 'lease_level',
        terms,
        ...inputs,
        target_levered_irr: targetLeveredIrr,
        target_equity_multiple: targetEquityMultiple,
        target_headline_dscr: targetHeadlineDscr,
        return_hurdle_metric: returnHurdleMetric,
        deal_context: dealContext,
      }),
    });
  } catch {
    throw new ApiError(NETWORK_ERROR_MESSAGE);
  }

  // A rent roll the engine refuses is refused here in the same structured
  // shape `analyzeLeaseLevelAcquisition` uses, so a lease-level issue list
  // reaches the workspace rather than a flattened sentence.
  if (response.status === 422) {
    const payload: unknown = await response.json().catch(() => null);
    throw leaseLevelValidationError(payload);
  }

  if (response.status === 503) {
    const body = await response.json().catch(() => null);
    const message =
      typeof body?.detail === 'string' ? body.detail : 'The AI Analyst is not configured.';
    throw new ApiError(message);
  }

  if (response.status === 502) {
    const body = await response.json().catch(() => null);
    const message =
      typeof body?.detail === 'string' ? body.detail : 'The AI Analyst request failed.';
    throw new ApiError(message);
  }

  if (!response.ok) {
    throw new ApiError(`The AI analysis request failed (HTTP ${response.status}).`);
  }

  return (await response.json()) as AIAnalysis;
}

// =============================================================================
// D5.7 -- Lease-Level sensitivity.
//
// The same two endpoints Quick and Detailed use, discriminated by
// `operating_mode` exactly as every other Lease-Level function above is. No new
// endpoint, no new backend field, and no sensitivity math: each builds a typed
// body from the *current* inputs and hands back the response unchanged.
//
// Neither function caches, batches, reorders or deduplicates anything. The
// backend performs `1 + N` complete re-underwrites for a one-way run and
// `1 + R*C` for a two-way run, and nothing here shortens that.
// =============================================================================

/** `POST /sensitivity/one-way` with `operating_mode: "lease_level"`.
 *
 * `controls.values` are **absolute** assumption values already on the wire
 * scale, in the analyst's own order, which the response preserves positionally.
 */
export async function runLeaseLevelOneWaySensitivity(
  terms: AcquisitionTermsRequest,
  inputs: LeaseLevelInputsRequest,
  controls: LeaseLevelOneWaySensitivityControls,
): Promise<LeaseLevelOneWaySensitivityResult> {
  const response = await postJson('/sensitivity/one-way', {
    operating_mode: 'lease_level',
    terms,
    ...inputs,
    ...controls,
  });
  return (await response.json()) as LeaseLevelOneWaySensitivityResult;
}

/** `POST /sensitivity` with `operating_mode: "lease_level"`.
 *
 * Rows stay rows and columns stay columns: the controls carry the analyst's
 * choice under the backend's own field names, and `matrix[row][column]` is
 * returned and rendered in that orientation. */
export async function runLeaseLevelTwoWaySensitivity(
  terms: AcquisitionTermsRequest,
  inputs: LeaseLevelInputsRequest,
  controls: LeaseLevelTwoWaySensitivityControls,
): Promise<LeaseLevelTwoWaySensitivityResult> {
  const response = await postJson('/sensitivity', {
    operating_mode: 'lease_level',
    terms,
    ...inputs,
    ...controls,
  });
  return (await response.json()) as LeaseLevelTwoWaySensitivityResult;
}
