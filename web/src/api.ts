import type {
  AcquisitionRequest,
  AcquisitionResults,
  AIAnalysis,
  ExtractionResult,
  ReturnHurdleMetric,
  StandardBreakEvenAnalysis,
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
 * Uploads an Anchor Excel acquisition workbook to the FastAPI
 * ``POST /ingestion/excel`` endpoint as multipart form data and returns the
 * nine validated ``AcquisitionRequest`` fields. Performs no workbook
 * parsing or financial validation of its own -- the backend Excel reader
 * (shared with the CLI) is authoritative. The browser sets the multipart
 * ``Content-Type`` boundary itself, so this function must not set that
 * header explicitly. Unlike ``uploadOm``, a successful response is already
 * a complete, validated input set -- there is no candidate/evidence review
 * step -- and a malformed workbook fails with the exact same 422 issue-list
 * shape ``analyzeAcquisition`` already handles.
 */
export async function uploadExcel(file: File): Promise<AcquisitionRequest> {
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

  return (await response.json()) as AcquisitionRequest;
}
