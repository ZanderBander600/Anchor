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

const API_BASE_URL = 'http://127.0.0.1:8000';

export class ApiError extends Error {
  issues: ValidationIssue[];

  constructor(message: string, issues: ValidationIssue[] = []) {
    super(message);
    this.name = 'ApiError';
    this.issues = issues;
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

/** POSTs a new deal (name + the fourteen assumptions) to ``/deals``. Used for a
 * deal that has never been saved -- ``currentDealId`` is still ``null``. */
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
      body: JSON.stringify({ name, inputs, deal_context: dealContext ?? null }),
    });
  } catch {
    throw new ApiError(
      'Could not reach the Anchor API. Confirm the backend is running at ' +
        `${API_BASE_URL}.`,
    );
  }

  return _handleDealResponse(response, 'The deal could not be saved');
}

/** PUTs an already-saved deal's name and assumptions to ``/deals/{id}``. */
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
      body: JSON.stringify({ name, inputs, deal_context: dealContext ?? null }),
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
