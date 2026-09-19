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
  LeaseLevelOneWaySensitivitySnapshot,
  LeaseLevelTwoWaySensitivityControls,
  LeaseLevelTwoWaySensitivityResult,
  LeaseLevelTwoWaySensitivitySnapshot,
} from './leaseLevelSensitivityTypes';
import type {
  AssetPerformanceResponse,
  AssetReportIssue,
  BudgetImmutableConflict,
  ManagedAsset,
  MonthlyAssetReport,
  OperatingFigures,
} from './assetManagementTypes';
import { isBusinessPlanApiIssue } from './businessPlan';
import type { BusinessPlanApiIssue, BusinessPlanInput } from './businessPlan';
import type {
  DealScenarios,
  InvestmentScenario,
  ScenarioDraft,
  ScenarioIssue,
  ScenarioTargetCatalog,
  ScenarioVariantAnalysis,
  ScenarioVariantFingerprint,
} from './scenarioTypes';
import type {
  DealStrategies,
  InvestmentStrategy,
  StrategyDraft,
  StrategyIssue,
  StrategyTargetCatalog,
} from './strategyTypes';
import type { DecisionMatrixReport } from './decisionTypes';
import type {
  CapitalStructure,
  CapitalStructureIssue,
  DealCapitalStructure,
  InvestmentCapitalStructure,
  PositionDecisionMatrixReport,
  PositionPerspectives,
  StructuredVariantAnalysis,
  StructuredVariantFingerprint,
} from './capitalTypes';
import type {
  DealPartnership,
  InvestmentPartnership,
  PartnerDecisionMatrixReport,
  PartnerPerspectives,
  Partnership,
  PartnershipIssue,
  PartnershipVariantAnalysis,
  PartnershipVariantFingerprint,
} from './partnershipTypes';
import type {
  InvestmentAddUnitRequest,
  InvestmentCreateRequest,
  InvestmentDecisionMatrixReport,
  InvestmentDetailsRequest,
  InvestmentIssue,
  InvestmentUnitDisplayRequest,
  InvestmentVariantAnalysis,
  InvestmentVariantIssue,
  VisibleInvestment,
} from './investmentTypes';

// Phase 6 Gate D6.6 -- every request that carries deal state carries the deal's
// Business Plan as a top-level `business_plan`, taken from a required
// `businessPlan` parameter placed right after the mode's own deal inputs.
// Required, never optional or defaulted: an absent plan means an EMPTY plan to
// the backend (D6.5), so a request that silently dropped it would clear a
// saved plan on the next write. Omitting it is therefore a compile error here,
// and `businessPlanRequests.test.ts` pins every body.

const API_BASE_URL = 'http://127.0.0.1:8000';

/** The single unreachable-backend message, shared by the D5.5A client
 * functions. Identical wording to the one the existing functions inline. */
const NETWORK_ERROR_MESSAGE =
  'Could not reach the Anchor API. Confirm the backend is running at ' +
  `${API_BASE_URL}.`;

export class ApiError extends Error {
  issues: ValidationIssue[];
  /** D6.6: the Business Plan entries of a structured 422, each carrying the
   * `business_plan.capital_items[2].month`-style path the backend rooted at the
   * request, so the editor can place it on its row. Empty for every other
   * refusal. Read structurally off whatever detail array the caller passed. */
  businessPlanIssues: BusinessPlanApiIssue[];

  constructor(message: string, issues: ValidationIssue[] = []) {
    super(message);
    this.name = 'ApiError';
    this.issues = issues;
    this.businessPlanIssues = (issues as readonly unknown[]).filter(isBusinessPlanApiIssue);
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
  businessPlan: BusinessPlanInput,
): Promise<AcquisitionResults> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...request, business_plan: businessPlan }),
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
  businessPlan: BusinessPlanInput,
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
        business_plan: businessPlan,
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
  businessPlan: BusinessPlanInput,
): Promise<StandardSensitivityPresets> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/sensitivity/presets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inputs, business_plan: businessPlan }),
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
  businessPlan: BusinessPlanInput,
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
        business_plan: businessPlan,
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
  businessPlan: BusinessPlanInput,
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
        business_plan: businessPlan,
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
  businessPlan: BusinessPlanInput,
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
        business_plan: businessPlan,
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
  businessPlan: BusinessPlanInput,
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
        business_plan: businessPlan,
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
  businessPlan: BusinessPlanInput,
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
        business_plan: businessPlan,
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
  businessPlan: BusinessPlanInput,
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
        business_plan: businessPlan,
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
  businessPlan: BusinessPlanInput,
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
        business_plan: businessPlan,
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
  businessPlan: BusinessPlanInput,
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
        business_plan: businessPlan,
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
  businessPlan: BusinessPlanInput,
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
        business_plan: businessPlan,
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
  businessPlan: BusinessPlanInput,
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
        business_plan: businessPlan,
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
  businessPlan: BusinessPlanInput,
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
        business_plan: businessPlan,
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
  const error = new LeaseLevelApiError(message, issues, leaseIssues);
  // D6.6: a Business Plan issue has neither Lease-Level shape -- no severity, no
  // field_id -- so both filters above drop it. It is carried separately, in the
  // one field every mode's editor reads.
  error.businessPlanIssues = entries.filter(isBusinessPlanApiIssue);
  return error;
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
  businessPlan: BusinessPlanInput,
): Promise<LeaseLevelAcquisitionResults> {
  const response = await postJson('/analyze', {
    operating_mode: 'lease_level',
    terms,
    ...inputs,
    business_plan: businessPlan,
  });
  return (await response.json()) as LeaseLevelAcquisitionResults;
}

/** `POST /deals` with `operating_mode: "lease_level"`. */
export async function createLeaseLevelDeal(
  name: string,
  terms: AcquisitionTermsRequest,
  inputs: LeaseLevelInputsRequest,
  businessPlan: BusinessPlanInput,
  dealContext: string | null,
): Promise<Deal> {
  const response = await postJson('/deals', {
    operating_mode: 'lease_level',
    name,
    terms,
    ...inputs,
    business_plan: businessPlan,
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
  businessPlan: BusinessPlanInput,
  dealContext: string | null,
): Promise<Deal> {
  const response = await sendJson('PUT', `/deals/${dealId}`, {
    operating_mode: 'lease_level',
    name,
    terms,
    ...inputs,
    business_plan: businessPlan,
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
  businessPlan: BusinessPlanInput,
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
        business_plan: businessPlan,
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
  businessPlan: BusinessPlanInput,
  controls: LeaseLevelOneWaySensitivityControls,
): Promise<LeaseLevelOneWaySensitivityResult> {
  const response = await postJson('/sensitivity/one-way', {
    operating_mode: 'lease_level',
    terms,
    ...inputs,
    business_plan: businessPlan,
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
  businessPlan: BusinessPlanInput,
  controls: LeaseLevelTwoWaySensitivityControls,
): Promise<LeaseLevelTwoWaySensitivityResult> {
  const response = await postJson('/sensitivity', {
    operating_mode: 'lease_level',
    terms,
    ...inputs,
    business_plan: businessPlan,
    ...controls,
  });
  return (await response.json()) as LeaseLevelTwoWaySensitivityResult;
}

// =============================================================================
// D5.8A -- Lease-Level derived-analysis persistence
//
// Three additions, all following the shapes Gate A6/A7 already established for
// Quick and Detailed: one fingerprint fetch (the frontend never computes a
// fingerprint -- it transports the opaque token this endpoint returns) and two
// narrow snapshot writes that touch nothing but their own stored row.
// =============================================================================

/** Lease-Level counterpart of `fetchDealFingerprint` -- mirrors it exactly,
 * over the same `terms`/`inputs` body every other Lease-Level call sends.
 *
 * The returned tokens are opaque. `financial_input_fingerprint` unlocks a
 * sensitivity-snapshot write; `ai_context_fingerprint` unlocks an AI-snapshot
 * write. The backend independently recomputes both from the deal's own stored
 * assumptions and refuses a write it does not already agree with, so a token
 * can never certify a snapshot as current when it is not. */
export async function fetchLeaseLevelDealFingerprint(
  terms: AcquisitionTermsRequest,
  inputs: LeaseLevelInputsRequest,
  businessPlan: BusinessPlanInput,
  dealContext?: string | null,
): Promise<DealFingerprint> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/deals/fingerprint`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        operating_mode: 'lease_level',
        terms,
        ...inputs,
        business_plan: businessPlan,
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

/** `PUT /deals/{id}/sensitivity-snapshot/one-way` -- persists the latest
 * SUCCESSFUL one-way run for an already-saved, not-dirty deal.
 *
 * Writes that one stored row and nothing else: never the assumptions, the name,
 * Deal Context, the AI snapshot, the two-way snapshot, or the deal's save
 * timestamp. Never called for a failed run, so a refusal can never replace the
 * last good snapshot. */
export async function updateDealOneWaySensitivitySnapshot(
  dealId: string,
  snapshot: LeaseLevelOneWaySensitivitySnapshot,
  financialInputFingerprint: string,
): Promise<Deal> {
  return _putSensitivitySnapshot(dealId, 'one-way', snapshot, financialInputFingerprint);
}

/** `PUT /deals/{id}/sensitivity-snapshot/two-way` -- the two-way counterpart,
 * with exactly the same contract and the same isolation guarantees. */
export async function updateDealTwoWaySensitivitySnapshot(
  dealId: string,
  snapshot: LeaseLevelTwoWaySensitivitySnapshot,
  financialInputFingerprint: string,
): Promise<Deal> {
  return _putSensitivitySnapshot(dealId, 'two-way', snapshot, financialInputFingerprint);
}

async function _putSensitivitySnapshot(
  dealId: string,
  kind: 'one-way' | 'two-way',
  snapshot: LeaseLevelOneWaySensitivitySnapshot | LeaseLevelTwoWaySensitivitySnapshot,
  financialInputFingerprint: string,
): Promise<Deal> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE_URL}/deals/${encodeURIComponent(dealId)}/sensitivity-snapshot/${kind}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sensitivity_snapshot: snapshot,
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

  return _handleDealResponse(response, 'The sensitivity analysis could not be cached');
}

// =============================================================================
// Phase 7 Gate P7.3 -- the Scenario client.
//
// The P7.2 Scenario routes, plus the P7.3 read-only target catalog. Each
// function sends a typed body and returns what the backend returned. None of
// them resolves a Scenario, validates one beyond its shape, or computes a
// figure. The backend decides what a Scenario may say, and produces every
// number it shows.
//
// **One refusal shape.** A Scenario 422 carries the P7.1 issues, each with its
// stage, its stable code and the validator's own message. A Lease-Level analysis
// may instead refuse in the rent-roll vocabulary. `ScenarioApiError` reports
// whichever arrived, recognised by shape rather than guessed from the mode, and
// keeps every message the backend sent. A refusal is never flattened into a
// generic sentence.
// =============================================================================

/** A refused Scenario request. `status` 422 means the backend judged the
 * Scenario, or its variant over the saved Deal, invalid; `reasons` then holds
 * the validators' own words. */
export class ScenarioApiError extends ApiError {
  status: number;
  scenarioIssues: ScenarioIssue[];
  leaseIssues: LeaseLevelIssue[];
  /** Every reason the backend gave, in its order and in its own words. */
  reasons: string[];

  constructor(
    message: string,
    status: number,
    detail: {
      issues: ValidationIssue[];
      scenarioIssues: ScenarioIssue[];
      leaseIssues: LeaseLevelIssue[];
      reasons: string[];
    },
  ) {
    super(message, detail.issues);
    this.name = 'ScenarioApiError';
    this.status = status;
    this.scenarioIssues = detail.scenarioIssues;
    this.leaseIssues = detail.leaseIssues;
    this.reasons = detail.reasons;
  }
}

/** Narrows one 422 detail entry to the P7.1 issue shape `api.py` serializes. */
function isScenarioIssue(entry: unknown): entry is ScenarioIssue {
  if (typeof entry !== 'object' || entry === null) {
    return false;
  }
  const candidate = entry as Record<string, unknown>;
  return (
    (candidate.stage === 'scenario' || candidate.stage === 'resolved_inputs') &&
    typeof candidate.code === 'string' &&
    typeof candidate.message === 'string'
  );
}

/** A 404's backend detail names internal ids, so it is said in the analyst's
 * words instead. */
const SCENARIO_NOT_FOUND_MESSAGE =
  'That scenario or deal could not be found. It may have been deleted.';

async function scenarioRequestError(
  response: Response,
  failureMessage: string,
): Promise<ScenarioApiError> {
  const payload: unknown = await response.json().catch(() => null);
  const detail: unknown =
    typeof payload === 'object' && payload !== null
      ? (payload as Record<string, unknown>).detail
      : null;
  const entries: unknown[] = Array.isArray(detail) ? detail : [];
  const messages = entries
    .map((entry) =>
      typeof entry === 'object' && entry !== null
        ? (entry as Record<string, unknown>).message
        : null,
    )
    .filter((message): message is string => typeof message === 'string');
  const stringDetail = typeof detail === 'string' && detail.trim() !== '' ? detail : null;
  const reasons =
    messages.length > 0
      ? messages
      : response.status === 404
        ? [SCENARIO_NOT_FOUND_MESSAGE]
        : stringDetail === null
          ? []
          : [stringDetail];
  const message =
    reasons.length > 0 ? reasons.join(' ') : `${failureMessage} (HTTP ${response.status}).`;
  return new ScenarioApiError(message, response.status, {
    issues: entries.filter(isValidationIssue),
    scenarioIssues: entries.filter(isScenarioIssue),
    leaseIssues: entries.filter(isLeaseLevelIssue),
    reasons,
  });
}

async function scenarioFetch(
  path: string,
  init: RequestInit,
  failureMessage: string,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(NETWORK_ERROR_MESSAGE);
  }
  if (!response.ok) {
    throw await scenarioRequestError(response, failureMessage);
  }
  return response;
}

/** Exactly the three keys a Scenario body may carry. The backend refuses any
 * other key rather than ignoring it. */
function scenarioBody(method: 'POST' | 'PUT', draft: ScenarioDraft): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: draft.name,
      description: draft.description,
      overrides: draft.overrides,
    }),
  };
}

function investmentScenarioPath(investmentId: string, scenarioId: string): string {
  return `/investments/${encodeURIComponent(investmentId)}/scenarios/${encodeURIComponent(scenarioId)}`;
}

/** `GET /scenario-targets` -- each operating mode's Scenario targets, their
 * operation whitelists and their units, projected from the P7.1 registry. */
export async function fetchScenarioTargetCatalog(): Promise<ScenarioTargetCatalog> {
  const response = await scenarioFetch(
    '/scenario-targets',
    { method: 'GET' },
    'The scenario assumptions could not be loaded',
  );
  return (await response.json()) as ScenarioTargetCatalog;
}

/** `GET /deals/{id}/scenarios`. Read-only: a standalone Deal reports no
 * Investment and no Scenarios, and gains neither. */
export async function listDealScenarios(dealId: string): Promise<DealScenarios> {
  const response = await scenarioFetch(
    `/deals/${encodeURIComponent(dealId)}/scenarios`,
    { method: 'GET' },
    'The scenarios could not be loaded',
  );
  return (await response.json()) as DealScenarios;
}

/** `POST /deals/{id}/scenarios`. The Deal's first Scenario materializes its
 * hidden Investment in the same transaction; later ones reuse it. An invalid
 * Scenario leaves nothing behind. */
export async function createDealScenario(
  dealId: string,
  draft: ScenarioDraft,
): Promise<InvestmentScenario> {
  const response = await scenarioFetch(
    `/deals/${encodeURIComponent(dealId)}/scenarios`,
    scenarioBody('POST', draft),
    'The scenario could not be saved',
  );
  return (await response.json()) as InvestmentScenario;
}

/** `GET /investments/{id}/scenarios/{id}`. */
export async function getInvestmentScenario(
  investmentId: string,
  scenarioId: string,
): Promise<InvestmentScenario> {
  const response = await scenarioFetch(
    investmentScenarioPath(investmentId, scenarioId),
    { method: 'GET' },
    'The scenario could not be loaded',
  );
  return (await response.json()) as InvestmentScenario;
}

/** `PUT /investments/{id}/scenarios/{id}` -- replaces the name, description
 * and whole override set; the Scenario keeps its id. */
export async function updateInvestmentScenario(
  investmentId: string,
  scenarioId: string,
  draft: ScenarioDraft,
): Promise<InvestmentScenario> {
  const response = await scenarioFetch(
    investmentScenarioPath(investmentId, scenarioId),
    scenarioBody('PUT', draft),
    'The scenario could not be saved',
  );
  return (await response.json()) as InvestmentScenario;
}

/** `DELETE /investments/{id}/scenarios/{id}`. Deleting the last Scenario
 * removes the hidden Investment too, so the Deal is a plain Deal again. */
export async function deleteInvestmentScenario(
  investmentId: string,
  scenarioId: string,
): Promise<void> {
  await scenarioFetch(
    investmentScenarioPath(investmentId, scenarioId),
    { method: 'DELETE' },
    'The scenario could not be deleted',
  );
}

/** `GET /investments/{id}/scenarios/{id}/fingerprint` -- the opaque
 * resolved-input fingerprint the backend computes. Transported, never computed
 * or interpreted here. */
export async function fetchScenarioVariantFingerprint(
  investmentId: string,
  scenarioId: string,
): Promise<ScenarioVariantFingerprint> {
  const response = await scenarioFetch(
    `${investmentScenarioPath(investmentId, scenarioId)}/fingerprint`,
    { method: 'GET' },
    'The scenario fingerprint could not be retrieved',
  );
  return (await response.json()) as ScenarioVariantFingerprint;
}

/** `POST /investments/{id}/scenarios/{id}/analysis` -- the Scenario resolved
 * over the Deal's saved inputs and run through the existing deterministic
 * pipeline. A Lease-Level variant is always recomputed. */
export async function analyzeInvestmentScenario(
  investmentId: string,
  scenarioId: string,
): Promise<ScenarioVariantAnalysis> {
  const response = await scenarioFetch(
    `${investmentScenarioPath(investmentId, scenarioId)}/analysis`,
    { method: 'POST' },
    'The scenario analysis could not be completed',
  );
  return (await response.json()) as ScenarioVariantAnalysis;
}

// =============================================================================
// Phase 7 Gate P7.5 -- the Strategy client and the Decision Matrix.
//
// The P7.4 Strategy routes, the P7.5 read-only Strategy target catalog, and the
// one Decision Matrix request. Each function sends a typed body and returns
// what the backend returned. None resolves a Strategy, validates one beyond its
// shape, or computes a figure: the backend decides what a Strategy may say, and
// produces every number of the matrix, cross-cell figures included.
//
// **One refusal shape.** A Strategy 422 carries the P7.4 issues, each with its
// stage, stable code, domain and the validator's own message. A Business Plan
// overlay is refused in the D6 vocabulary, with a path rooted at the overlay;
// `StrategyApiError` re-roots that path at `business_plan` so the one Business
// Plan placement (`placeBusinessPlanApiIssues`) puts each issue on its row.
// =============================================================================

/** A refused Strategy or Decision Matrix request. `status` 422 means the
 * backend judged the Strategy invalid; `reasons` holds the validators' words. */
export class StrategyApiError extends ApiError {
  status: number;
  strategyIssues: StrategyIssue[];
  /** Business Plan overlay refusals, each path re-rooted at `business_plan`. */
  planIssues: BusinessPlanApiIssue[];
  /** Every reason the backend gave, in its order and in its own words. */
  reasons: string[];

  constructor(
    message: string,
    status: number,
    detail: {
      issues: ValidationIssue[];
      strategyIssues: StrategyIssue[];
      planIssues: BusinessPlanApiIssue[];
      reasons: string[];
    },
  ) {
    super(message, detail.issues);
    this.name = 'StrategyApiError';
    this.status = status;
    this.strategyIssues = detail.strategyIssues;
    this.planIssues = detail.planIssues;
    this.reasons = detail.reasons;
  }
}

/** Narrows one 422 detail entry to the P7.4 issue shape `api.py` serializes.
 * The `domain` key tells it apart from a Scenario issue. */
function isStrategyIssue(entry: unknown): entry is StrategyIssue {
  if (typeof entry !== 'object' || entry === null) {
    return false;
  }
  const candidate = entry as Record<string, unknown>;
  return (
    (candidate.stage === 'strategy' || candidate.stage === 'resolved_inputs') &&
    typeof candidate.code === 'string' &&
    typeof candidate.message === 'string' &&
    'domain' in candidate
  );
}

const OVERLAY_CONTENT_PATH = /^overlays\[\d+\]\.content(?=\.|$)/;

/** A Business Plan overlay refusal (`overlays[2].content.capital_items[0].month`)
 * as the D6 shape rooted at `business_plan`, or `null` for any other entry. */
function strategyPlanIssue(entry: unknown): BusinessPlanApiIssue | null {
  if (typeof entry !== 'object' || entry === null) {
    return null;
  }
  const candidate = entry as Record<string, unknown>;
  if (
    typeof candidate.code !== 'string' ||
    typeof candidate.message !== 'string' ||
    typeof candidate.path !== 'string' ||
    !OVERLAY_CONTENT_PATH.test(candidate.path)
  ) {
    return null;
  }
  const rerooted = {
    code: candidate.code,
    message: candidate.message,
    path: candidate.path.replace(OVERLAY_CONTENT_PATH, 'business_plan'),
  };
  return isBusinessPlanApiIssue(rerooted) ? rerooted : null;
}

/** A 404's backend detail names internal ids, so it is said in the analyst's
 * words instead. */
const STRATEGY_NOT_FOUND_MESSAGE =
  'That strategy or deal could not be found. It may have been deleted.';

async function strategyRequestError(
  response: Response,
  failureMessage: string,
): Promise<StrategyApiError> {
  const payload: unknown = await response.json().catch(() => null);
  const detail: unknown =
    typeof payload === 'object' && payload !== null
      ? (payload as Record<string, unknown>).detail
      : null;
  const entries: unknown[] = Array.isArray(detail) ? detail : [];
  const messages = entries
    .map((entry) =>
      typeof entry === 'object' && entry !== null
        ? (entry as Record<string, unknown>).message
        : null,
    )
    .filter((message): message is string => typeof message === 'string');
  const stringDetail = typeof detail === 'string' && detail.trim() !== '' ? detail : null;
  const reasons =
    messages.length > 0
      ? messages
      : response.status === 404
        ? [STRATEGY_NOT_FOUND_MESSAGE]
        : stringDetail === null
          ? []
          : [stringDetail];
  const message =
    reasons.length > 0 ? reasons.join(' ') : `${failureMessage} (HTTP ${response.status}).`;
  return new StrategyApiError(message, response.status, {
    issues: entries.filter(isValidationIssue),
    strategyIssues: entries.filter(isStrategyIssue),
    planIssues: entries
      .map(strategyPlanIssue)
      .filter((issue): issue is BusinessPlanApiIssue => issue !== null),
    reasons,
  });
}

async function strategyFetch(
  path: string,
  init: RequestInit,
  failureMessage: string,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(NETWORK_ERROR_MESSAGE);
  }
  if (!response.ok) {
    throw await strategyRequestError(response, failureMessage);
  }
  return response;
}

/** Exactly the three keys a Strategy body may carry. */
function strategyBody(method: 'POST' | 'PUT', draft: StrategyDraft): RequestInit {
  // P7.8B adds a fourth, `root_overlays`, sent **only when the Strategy states
  // one**. Sending an empty array would say "this Strategy replaces the Base
  // Capital Structure with nothing", which is a different decision from
  // inheriting it -- so omitting the key is how a Strategy inherits.
  const stated =
    draft.root_overlays === undefined ? {} : { root_overlays: draft.root_overlays };
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: draft.name,
      description: draft.description,
      overlays: draft.overlays,
      ...stated,
    }),
  };
}

function investmentStrategyPath(investmentId: string, strategyId: string): string {
  return `/investments/${encodeURIComponent(investmentId)}/strategies/${encodeURIComponent(strategyId)}`;
}

/** `GET /strategy-targets` -- each operating mode's operating-outcome targets
 * and their units, projected from the P7.4 whitelist and the P7.1 registry. */
export async function fetchStrategyTargetCatalog(): Promise<StrategyTargetCatalog> {
  const response = await strategyFetch(
    '/strategy-targets',
    { method: 'GET' },
    'The strategy assumptions could not be loaded',
  );
  return (await response.json()) as StrategyTargetCatalog;
}

/** `GET /deals/{id}/strategies`. Read-only: a standalone Deal reports no
 * Investment and no Strategies, and gains neither. */
export async function listDealStrategies(dealId: string): Promise<DealStrategies> {
  const response = await strategyFetch(
    `/deals/${encodeURIComponent(dealId)}/strategies`,
    { method: 'GET' },
    'The strategies could not be loaded',
  );
  return (await response.json()) as DealStrategies;
}

/** `POST /deals/{id}/strategies`. A standalone Deal's first Strategy
 * materializes its hidden Investment; a Deal whose Scenarios already created
 * one reuses it. An invalid Strategy leaves nothing behind. */
export async function createDealStrategy(
  dealId: string,
  draft: StrategyDraft,
): Promise<InvestmentStrategy> {
  const response = await strategyFetch(
    `/deals/${encodeURIComponent(dealId)}/strategies`,
    strategyBody('POST', draft),
    'The strategy could not be saved',
  );
  return (await response.json()) as InvestmentStrategy;
}

/** `PUT /investments/{id}/strategies/{id}` -- replaces the name, description
 * and whole overlay set; the Strategy keeps its id. */
export async function updateInvestmentStrategy(
  investmentId: string,
  strategyId: string,
  draft: StrategyDraft,
): Promise<InvestmentStrategy> {
  const response = await strategyFetch(
    investmentStrategyPath(investmentId, strategyId),
    strategyBody('PUT', draft),
    'The strategy could not be saved',
  );
  return (await response.json()) as InvestmentStrategy;
}

/** `DELETE /investments/{id}/strategies/{id}`. When no Strategy and no
 * Scenario remains, the hidden Investment is removed too. */
export async function deleteInvestmentStrategy(
  investmentId: string,
  strategyId: string,
): Promise<void> {
  await strategyFetch(
    investmentStrategyPath(investmentId, strategyId),
    { method: 'DELETE' },
    'The strategy could not be deleted',
  );
}

/** `POST /investments/{id}/decision-matrix` -- every Strategy x Scenario
 * variant of the Deal's hidden Investment, with the backend's cross-cell
 * figures. An invalid variant is one cell of a successful response; a request
 * failure refuses the whole package. */
export async function analyzeDecisionMatrix(investmentId: string): Promise<DecisionMatrixReport> {
  const response = await strategyFetch(
    `/investments/${encodeURIComponent(investmentId)}/decision-matrix`,
    { method: 'POST' },
    'The decision matrix could not be completed',
  );
  return (await response.json()) as DecisionMatrixReport;
}

// =============================================================================
// Phase 7 Gate P7.8B -- the Capital Structure client.
//
// The P7.8B routes: the persisted Base Capital Structure (through the Deal's
// own door or the Investment's), the structured variant's two fingerprints and
// its analysis, the addressable Position perspectives, and the POSITION
// Decision Matrix. Each function sends a typed body and returns what the
// backend returned.
//
// **Nothing here calculates.** Every funded amount, IRR, MOIC, attachment,
// coverage, Funding Requirement and Common Equity figure is the backend's; this
// client carries JSON.
//
// **Refusals keep their structure.** A refused Capital Structure carries the
// issues that refused it -- the P7.7 contract rules, the P7.8A execution rules
// or a position-identity conflict -- so the editor can show them against the
// position they concern instead of one flattened sentence.
// =============================================================================

/** A refused Capital Structure request, with the backend's own issues. */
export class CapitalStructureError extends Error {
  readonly issues: CapitalStructureIssue[];

  constructor(message: string, issues: CapitalStructureIssue[] = []) {
    super(message);
    this.name = 'CapitalStructureError';
    this.issues = issues;
  }
}

function capitalIssues(detail: unknown): CapitalStructureIssue[] {
  if (!Array.isArray(detail)) {
    return [];
  }
  return detail.flatMap((entry) => {
    if (typeof entry !== 'object' || entry === null || !('message' in entry)) {
      return [];
    }
    const issue = entry as Partial<CapitalStructureIssue> & { path?: string | null };
    return [
      {
        code: typeof issue.code === 'string' ? issue.code : '',
        message: String(issue.message),
        position_id: typeof issue.position_id === 'string' ? issue.position_id : null,
        field: typeof issue.field === 'string' ? issue.field : (issue.path ?? null),
      },
    ];
  });
}

function capitalMessage(detail: unknown, issues: CapitalStructureIssue[], failureMessage: string): string {
  if (typeof detail === 'string' && detail !== '') {
    return detail;
  }
  return issues.length === 0 ? failureMessage : issues.map((issue) => issue.message).join('\n');
}

async function capitalFetch(
  path: string,
  init: RequestInit,
  failureMessage: string,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new CapitalStructureError(NETWORK_ERROR_MESSAGE);
  }
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail ?? null;
    } catch {
      detail = null;
    }
    const issues = capitalIssues(detail);
    throw new CapitalStructureError(capitalMessage(detail, issues, failureMessage), issues);
  }
  return response;
}

function structureBody(capitalStructure: CapitalStructure): RequestInit {
  return {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ positions: capitalStructure.positions }),
  };
}

/** `GET /deals/{id}/capital-structure`. Read-only: a Deal with no structured
 * capital reports the neutral empty structure and no Investment, and asking
 * gives it neither. */
export async function readDealCapitalStructure(dealId: string): Promise<DealCapitalStructure> {
  const response = await capitalFetch(
    `/deals/${encodeURIComponent(dealId)}/capital-structure`,
    { method: 'GET' },
    'The capital structure could not be loaded',
  );
  return (await response.json()) as DealCapitalStructure;
}

/** `PUT /deals/{id}/capital-structure`. The first non-empty save materializes
 * the Deal's hidden one-unit Investment; an empty save clears the structure and
 * releases the Deal when nothing else is held. */
export async function saveDealCapitalStructure(
  dealId: string,
  capitalStructure: CapitalStructure,
): Promise<DealCapitalStructure> {
  const response = await capitalFetch(
    `/deals/${encodeURIComponent(dealId)}/capital-structure`,
    structureBody(capitalStructure),
    'The capital structure could not be saved',
  );
  return (await response.json()) as DealCapitalStructure;
}

/** `GET /investments/{id}/capital-structure`. */
export async function readInvestmentCapitalStructure(
  investmentId: string,
): Promise<InvestmentCapitalStructure> {
  const response = await capitalFetch(
    `/investments/${encodeURIComponent(investmentId)}/capital-structure`,
    { method: 'GET' },
    'The capital structure could not be loaded',
  );
  return (await response.json()) as InvestmentCapitalStructure;
}

/** `PUT /investments/{id}/capital-structure`. */
export async function saveInvestmentCapitalStructure(
  investmentId: string,
  capitalStructure: CapitalStructure,
): Promise<InvestmentCapitalStructure> {
  const response = await capitalFetch(
    `/investments/${encodeURIComponent(investmentId)}/capital-structure`,
    structureBody(capitalStructure),
    'The capital structure could not be saved',
  );
  return (await response.json()) as InvestmentCapitalStructure;
}

function structuredVariantPath(
  investmentId: string,
  strategyId: string,
  scenarioId: string,
): string {
  return `/investments/${encodeURIComponent(investmentId)}/structured-variants/${encodeURIComponent(
    strategyId,
  )}/${encodeURIComponent(scenarioId)}`;
}

/** The variant's two fingerprints, without executing anything. */
export async function readStructuredVariantFingerprint(
  investmentId: string,
  strategyId: string,
  scenarioId: string,
): Promise<StructuredVariantFingerprint> {
  const response = await capitalFetch(
    `${structuredVariantPath(investmentId, strategyId, scenarioId)}/fingerprint`,
    { method: 'GET' },
    'The capital structure fingerprint could not be read',
  );
  return (await response.json()) as StructuredVariantFingerprint;
}

/** The structured analysis: the existing Project analysis, then the approved
 * executor. An unresolved Funding Requirement is a successful analysis with N/A
 * returns, never an error. */
export async function analyzeStructuredVariant(
  investmentId: string,
  strategyId: string,
  scenarioId: string,
): Promise<StructuredVariantAnalysis> {
  const response = await capitalFetch(
    `${structuredVariantPath(investmentId, strategyId, scenarioId)}/analysis`,
    { method: 'POST' },
    'The capital structure analysis could not be completed',
  );
  return (await response.json()) as StructuredVariantAnalysis;
}

/** `GET /investments/{id}/position-perspectives` -- the addressable positions,
 * by name, for the Position matrix selector. */
export async function listPositionPerspectives(
  investmentId: string,
): Promise<PositionPerspectives> {
  const response = await capitalFetch(
    `/investments/${encodeURIComponent(investmentId)}/position-perspectives`,
    { method: 'GET' },
    'The capital positions could not be loaded',
  );
  return (await response.json()) as PositionPerspectives;
}

/** `POST /investments/{id}/position-decision-matrix/{position_id}`. */
export async function analyzePositionDecisionMatrix(
  investmentId: string,
  positionId: string,
): Promise<PositionDecisionMatrixReport> {
  const response = await capitalFetch(
    `/investments/${encodeURIComponent(investmentId)}/position-decision-matrix/${encodeURIComponent(
      positionId,
    )}`,
    { method: 'POST' },
    'The position decision matrix could not be completed',
  );
  return (await response.json()) as PositionDecisionMatrixReport;
}

// =============================================================================
// Phase 7 Gate P7.6 -- the visible Investment client.
//
// The P7.6 routes: the visible Investment's lifecycle, its Units, its
// consolidated variant analysis and its Decision Matrix, plus the
// Investment-scoped Strategy and Scenario routes a visible Investment must use
// (the Deal-scoped ones refuse a Unit of a visible Investment with 409). Each
// function sends a typed body and returns what the backend returned. None
// validates beyond shape, derives a price, or computes a figure: the backend
// owns the $0.01 reconciliation, every consolidated number and every rule.
//
// **One refusal shape.** An Investment 422 carries `InvestmentIssue`s (the
// Investment validator's own words, each naming its Unit), a variant 422
// carries `InvestmentVariantIssue`s, and a Business Plan refusal carries the
// D6 `code`/`path`/`message`. A 409 is one sentence. `InvestmentApiError`
// reports whichever arrived, recognised by shape, and keeps every message.
// =============================================================================

/** A refused visible Investment request. `status` 422 means the backend
 * judged the Investment (or one of its variants) invalid; 409 means the
 * structure refused the change. `reasons` holds every backend message. */
export class InvestmentApiError extends ApiError {
  status: number;
  investmentIssues: InvestmentIssue[];
  variantIssues: InvestmentVariantIssue[];
  /** D6 Business Plan refusals, each path rooted at `business_plan`. */
  planIssues: BusinessPlanApiIssue[];
  reasons: string[];

  constructor(
    message: string,
    status: number,
    detail: {
      investmentIssues: InvestmentIssue[];
      variantIssues: InvestmentVariantIssue[];
      planIssues: BusinessPlanApiIssue[];
      reasons: string[];
    },
  ) {
    super(message);
    this.name = 'InvestmentApiError';
    this.status = status;
    this.investmentIssues = detail.investmentIssues;
    this.variantIssues = detail.variantIssues;
    this.planIssues = detail.planIssues;
    this.reasons = detail.reasons;
  }
}

/** Narrows one 422 detail entry to the `InvestmentIssue` shape `api.py`
 * serializes. The `source_code` key tells it apart from a variant issue. */
function isInvestmentIssue(entry: unknown): entry is InvestmentIssue {
  if (typeof entry !== 'object' || entry === null) {
    return false;
  }
  const candidate = entry as Record<string, unknown>;
  return (
    typeof candidate.code === 'string' &&
    typeof candidate.message === 'string' &&
    'unit_id' in candidate &&
    'source_code' in candidate
  );
}

const INVESTMENT_VARIANT_SOURCES = new Set(['strategy', 'scenario', 'lease_level', 'investment']);

/** Narrows one 422 detail entry to the `InvestmentVariantIssue` shape. */
function isInvestmentVariantIssue(entry: unknown): entry is InvestmentVariantIssue {
  if (typeof entry !== 'object' || entry === null) {
    return false;
  }
  const candidate = entry as Record<string, unknown>;
  return (
    typeof candidate.source === 'string' &&
    INVESTMENT_VARIANT_SOURCES.has(candidate.source) &&
    typeof candidate.code === 'string' &&
    typeof candidate.message === 'string' &&
    'unit_id' in candidate
  );
}

/** A 404's backend detail names internal ids, so it is said in the analyst's
 * words instead. */
const INVESTMENT_NOT_FOUND_MESSAGE =
  'That investment, unit or deal could not be found. It may have been deleted.';

/** The detail array of a refusal, or an empty one. */
function refusalEntries(detail: unknown): unknown[] {
  return Array.isArray(detail) ? detail : [];
}

/** Every reason a refusal gave, in its order and in its own words: each
 * entry's message, a one-sentence detail, or the analyst's 404 wording. */
function refusalReasons(detail: unknown, status: number, notFoundMessage: string): string[] {
  const messages = refusalEntries(detail)
    .map((entry) =>
      typeof entry === 'object' && entry !== null
        ? (entry as Record<string, unknown>).message
        : null,
    )
    .filter((message): message is string => typeof message === 'string');
  if (messages.length > 0) {
    return messages;
  }
  if (status === 404) {
    return [notFoundMessage];
  }
  return typeof detail === 'string' && detail.trim() !== '' ? [detail] : [];
}

function refusalDetail(payload: unknown): unknown {
  return typeof payload === 'object' && payload !== null
    ? (payload as Record<string, unknown>).detail
    : null;
}

async function investmentRequestError(
  response: Response,
  failureMessage: string,
): Promise<InvestmentApiError> {
  const payload: unknown = await response.json().catch(() => null);
  const detail = refusalDetail(payload);
  const entries = refusalEntries(detail);
  const reasons = refusalReasons(detail, response.status, INVESTMENT_NOT_FOUND_MESSAGE);
  const message =
    reasons.length > 0 ? reasons.join(' ') : `${failureMessage} (HTTP ${response.status}).`;
  return new InvestmentApiError(message, response.status, {
    investmentIssues: entries.filter(isInvestmentIssue),
    variantIssues: entries.filter(isInvestmentVariantIssue),
    planIssues: entries.filter(isBusinessPlanApiIssue),
    reasons,
  });
}

async function investmentFetch(
  path: string,
  init: RequestInit,
  failureMessage: string,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(NETWORK_ERROR_MESSAGE);
  }
  if (!response.ok) {
    throw await investmentRequestError(response, failureMessage);
  }
  return response;
}

function investmentPath(investmentId: string): string {
  return `/investments/${encodeURIComponent(investmentId)}`;
}

function investmentUnitPath(investmentId: string, unitId: string): string {
  return `${investmentPath(investmentId)}/units/${encodeURIComponent(unitId)}`;
}

function jsonRequest(method: 'POST' | 'PUT', body: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

/** Exactly the five keys a create or promote body may carry, and exactly the
 * keys of each Unit and cost. */
function investmentCreateBody(request: InvestmentCreateRequest): RequestInit {
  return jsonRequest('POST', {
    name: request.name,
    transaction_price: request.transaction_price,
    units: request.units.map((unit) => ({
      unit_id: unit.unit_id,
      label: unit.label,
      unit_kind: unit.unit_kind,
    })),
    business_plan: request.business_plan,
    transaction_costs: request.transaction_costs.map((cost) => ({
      cost_id: cost.cost_id,
      description: cost.description,
      category: cost.category,
      amount: cost.amount,
      model_month: cost.model_month,
    })),
  });
}

/** `GET /investments` -- every visible Investment, most recently updated
 * first. Hidden one-unit wrappers are never listed. */
export async function listVisibleInvestments(): Promise<VisibleInvestment[]> {
  const response = await investmentFetch(
    '/investments',
    { method: 'GET' },
    'The investments could not be loaded',
  );
  return (await response.json()) as VisibleInvestment[];
}

/** `GET /investments/{id}/details` -- one visible Investment and everything it
 * states beyond its Units. */
export async function getVisibleInvestment(investmentId: string): Promise<VisibleInvestment> {
  const response = await investmentFetch(
    `${investmentPath(investmentId)}/details`,
    { method: 'GET' },
    'The investment could not be loaded',
  );
  return (await response.json()) as VisibleInvestment;
}

/** `POST /investments` -- a visible Investment over one or more standalone
 * Deals, in one transaction. An invalid request leaves nothing behind. */
export async function createVisibleInvestment(
  request: InvestmentCreateRequest,
): Promise<VisibleInvestment> {
  const response = await investmentFetch(
    '/investments',
    investmentCreateBody(request),
    'The investment could not be created',
  );
  return (await response.json()) as VisibleInvestment;
}

/** `POST /investments/{id}/promote` -- a Deal's hidden wrapper becomes the
 * visible Investment: the same Investment, its Strategies and Scenarios kept,
 * never a second parent. `request.units` lists every Unit of the result. */
export async function promoteHiddenInvestment(
  investmentId: string,
  request: InvestmentCreateRequest,
): Promise<VisibleInvestment> {
  const response = await investmentFetch(
    `${investmentPath(investmentId)}/promote`,
    investmentCreateBody(request),
    'The investment could not be created',
  );
  return (await response.json()) as VisibleInvestment;
}

/** `PUT /investments/{id}/details` -- the name, transaction price, Investment
 * Business Plan and transaction costs, replaced together in one request. */
export async function updateVisibleInvestmentDetails(
  investmentId: string,
  request: InvestmentDetailsRequest,
): Promise<VisibleInvestment> {
  const response = await investmentFetch(
    `${investmentPath(investmentId)}/details`,
    jsonRequest('PUT', {
      name: request.name,
      transaction_price: request.transaction_price,
      business_plan: request.business_plan,
      transaction_costs: request.transaction_costs.map((cost) => ({
        cost_id: cost.cost_id,
        description: cost.description,
        category: cost.category,
        amount: cost.amount,
        model_month: cost.model_month,
      })),
    }),
    'The investment could not be saved',
  );
  return (await response.json()) as VisibleInvestment;
}

/** `DELETE /investments/{id}` -- deletes the Investment and what it owns (its
 * Strategies, Scenarios, plan and costs) and releases its Deals, unchanged. */
export async function deleteVisibleInvestment(investmentId: string): Promise<void> {
  await investmentFetch(
    investmentPath(investmentId),
    { method: 'DELETE' },
    'The investment could not be deleted',
  );
}

/** `POST /investments/{id}/units` -- adds a standalone Deal as a Unit, with
 * the analyst's resulting transaction price in the same request. */
export async function addInvestmentUnit(
  investmentId: string,
  request: InvestmentAddUnitRequest,
): Promise<VisibleInvestment> {
  const response = await investmentFetch(
    `${investmentPath(investmentId)}/units`,
    jsonRequest('POST', {
      unit_id: request.unit_id,
      label: request.label,
      unit_kind: request.unit_kind,
      transaction_price: request.transaction_price,
    }),
    'The unit could not be added',
  );
  return (await response.json()) as VisibleInvestment;
}

/** `PUT /investments/{id}/units/{unit_id}` -- one Unit's display metadata:
 * label, kind and presentation order. None of them is economic. */
export async function updateInvestmentUnitDisplay(
  investmentId: string,
  unitId: string,
  request: InvestmentUnitDisplayRequest,
): Promise<VisibleInvestment> {
  const response = await investmentFetch(
    investmentUnitPath(investmentId, unitId),
    jsonRequest('PUT', {
      label: request.label,
      unit_kind: request.unit_kind,
      ordinal: request.ordinal,
    }),
    'The unit could not be updated',
  );
  return (await response.json()) as VisibleInvestment;
}

/** `DELETE /investments/{id}/units/{unit_id}?transaction_price=...` -- ONE
 * request that removes the Unit, releasing its Deal unchanged, and restates the
 * Investment's transaction price as the analyst stated it. The remaining Units
 * must reconcile to that price, or nothing changes (422). The price is never
 * derived from the removed Unit's. */
export async function removeInvestmentUnit(
  investmentId: string,
  unitId: string,
  transactionPrice: number,
): Promise<VisibleInvestment> {
  const response = await investmentFetch(
    `${investmentUnitPath(investmentId, unitId)}?transaction_price=${encodeURIComponent(String(transactionPrice))}`,
    { method: 'DELETE' },
    'The unit could not be removed',
  );
  return (await response.json()) as VisibleInvestment;
}

/** `POST /investments/{id}/investment-variants/{strategy_id}/{scenario_id}/analysis`
 * -- every Unit through the existing engine, then consolidation. `base`/`base`
 * is the Base variant. Always recomputed. */
export async function analyzeInvestmentVariant(
  investmentId: string,
  strategyId: string,
  scenarioId: string,
): Promise<InvestmentVariantAnalysis> {
  const response = await investmentFetch(
    `${investmentPath(investmentId)}/investment-variants/${encodeURIComponent(strategyId)}/${encodeURIComponent(scenarioId)}/analysis`,
    { method: 'POST' },
    'The consolidated analysis could not be completed',
  );
  return (await response.json()) as InvestmentVariantAnalysis;
}

/** `POST /investments/{id}/investment-decision-matrix` -- every Strategy x
 * Scenario variant of a visible Investment over consolidated Project metrics,
 * with the backend's cross-cell figures. Never the one-unit matrix route. */
export async function analyzeInvestmentDecisionMatrix(
  investmentId: string,
): Promise<InvestmentDecisionMatrixReport> {
  const response = await investmentFetch(
    `${investmentPath(investmentId)}/investment-decision-matrix`,
    { method: 'POST' },
    'The decision matrix could not be completed',
  );
  return (await response.json()) as InvestmentDecisionMatrixReport;
}

/** `GET /investments/{id}/scenarios` -- a visible Investment's Scenarios. */
export async function listInvestmentScenarios(investmentId: string): Promise<InvestmentScenario[]> {
  const response = await scenarioFetch(
    `${investmentPath(investmentId)}/scenarios`,
    { method: 'GET' },
    'The scenarios could not be loaded',
  );
  return (await response.json()) as InvestmentScenario[];
}

/** `POST /investments/{id}/scenarios` -- a Scenario of a visible Investment,
 * each override addressed to one of its Units. */
export async function createInvestmentScenario(
  investmentId: string,
  draft: ScenarioDraft,
): Promise<InvestmentScenario> {
  const response = await scenarioFetch(
    `${investmentPath(investmentId)}/scenarios`,
    scenarioBody('POST', draft),
    'The scenario could not be saved',
  );
  return (await response.json()) as InvestmentScenario;
}

/** `GET /investments/{id}/strategies` -- a visible Investment's Strategies. */
export async function listInvestmentStrategies(investmentId: string): Promise<InvestmentStrategy[]> {
  const response = await strategyFetch(
    `${investmentPath(investmentId)}/strategies`,
    { method: 'GET' },
    'The strategies could not be loaded',
  );
  return (await response.json()) as InvestmentStrategy[];
}

/** A refused multi-unit Strategy save. `planIssueOverlays[i]` is the index,
 * in the request's `overlays`, of the Business Plan overlay `planIssues[i]`
 * names -- so an editor can place the refusal on its own Unit's plan. */
export class InvestmentStrategyApiError extends StrategyApiError {
  planIssueOverlays: number[];

  constructor(
    message: string,
    status: number,
    detail: {
      issues: ValidationIssue[];
      strategyIssues: StrategyIssue[];
      planIssues: BusinessPlanApiIssue[];
      reasons: string[];
    },
    planIssueOverlays: number[],
  ) {
    super(message, status, detail);
    this.name = 'InvestmentStrategyApiError';
    this.planIssueOverlays = planIssueOverlays;
  }
}

const OVERLAY_INDEX = /^overlays\[(\d+)\]\.content/;

async function investmentStrategyRequestError(
  response: Response,
  failureMessage: string,
): Promise<InvestmentStrategyApiError> {
  const payload: unknown = await response.json().catch(() => null);
  const detail = refusalDetail(payload);
  const entries = refusalEntries(detail);
  const reasons = refusalReasons(detail, response.status, STRATEGY_NOT_FOUND_MESSAGE);
  const message =
    reasons.length > 0 ? reasons.join(' ') : `${failureMessage} (HTTP ${response.status}).`;
  const placed = entries.flatMap((entry) => {
    const issue = strategyPlanIssue(entry);
    const path = (entry as Record<string, unknown>).path;
    const match = typeof path === 'string' ? OVERLAY_INDEX.exec(path) : null;
    return issue === null || match === null ? [] : [{ issue, overlay: Number(match[1]) }];
  });
  return new InvestmentStrategyApiError(
    message,
    response.status,
    {
      issues: entries.filter(isValidationIssue),
      strategyIssues: entries.filter(isStrategyIssue),
      planIssues: placed.map((entry) => entry.issue),
      reasons,
    },
    placed.map((entry) => entry.overlay),
  );
}

/** `POST /investments/{id}/strategies` when `strategyId` is `null`, otherwise
 * `PUT /investments/{id}/strategies/{strategy_id}` -- a visible Investment's
 * Strategy, whose overlays each name one of its Units. Always the
 * Investment-scoped routes: the Deal-scoped ones refuse a visible Investment. */
export async function saveInvestmentStrategy(
  investmentId: string,
  strategyId: string | null,
  draft: StrategyDraft,
): Promise<InvestmentStrategy> {
  const path =
    strategyId === null
      ? `${investmentPath(investmentId)}/strategies`
      : investmentStrategyPath(investmentId, strategyId);
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE_URL}${path}`,
      strategyBody(strategyId === null ? 'POST' : 'PUT', draft),
    );
  } catch {
    throw new ApiError(NETWORK_ERROR_MESSAGE);
  }
  if (!response.ok) {
    throw await investmentStrategyRequestError(response, 'The strategy could not be saved');
  }
  return (await response.json()) as InvestmentStrategy;
}

// =============================================================================
// Phase 7 Gate P7.9 Stage 3 -- the Partnership client.
//
// The Stage 2 routes: the persisted Base Partnership of a Deal or of a visible
// Investment, one Partnership variant's fingerprints and analysis, the
// addressable Partner perspectives and the PARTNER Decision Matrix. Each
// function sends a typed body and returns what the backend returned.
//
// **Nothing here calculates.** Every contribution, distribution, IRR, MOIC,
// profit, distribution difference, Promote Earned and benchmark capital
// subordination figure is the Stage 1 engine's; this client carries JSON.
//
// **`null` is sent and read as a statement.** A `partnership` of `null` is the
// explicit "this owner states no Partnership", which the backend stores as such.
// It is never conflated with an empty object: a Partnership always has at least
// one partner, so there is no empty Partnership to mean it with.
//
// **Refusals keep their structure.** A refused Partnership carries the issues
// that refused it -- the Stage 1 contract rules, or the Stage 1 execution rules
// over this variant's Common Equity Cash Flow -- so the editor can show them
// against the partner or tier they concern instead of one flattened sentence.
// =============================================================================

/** A refused Partnership request, with the backend's own issues. */
export class PartnershipError extends Error {
  readonly issues: PartnershipIssue[];

  constructor(message: string, issues: PartnershipIssue[] = []) {
    super(message);
    this.name = 'PartnershipError';
    this.issues = issues;
  }
}

/** The issues of a structured 422, normalized to one shape.
 *
 * A Stage 1 *validation* issue carries `partner_id`, `tier_id` and `field`; a
 * Stage 1 *execution* issue carries `tier_id` and `period`. Each is read for
 * what it states, and the fields the other kind does not carry are `null` --
 * absent, never invented. */
function partnershipIssues(detail: unknown): PartnershipIssue[] {
  if (!Array.isArray(detail)) {
    return [];
  }
  return detail.flatMap((entry) => {
    if (typeof entry !== 'object' || entry === null || !('message' in entry)) {
      return [];
    }
    const issue = entry as Partial<PartnershipIssue>;
    return [
      {
        code: typeof issue.code === 'string' ? issue.code : '',
        message: String(issue.message),
        partner_id: typeof issue.partner_id === 'string' ? issue.partner_id : null,
        tier_id: typeof issue.tier_id === 'string' ? issue.tier_id : null,
        field: typeof issue.field === 'string' ? issue.field : null,
        period: typeof issue.period === 'number' ? issue.period : null,
      },
    ];
  });
}

function partnershipMessage(
  detail: unknown,
  issues: PartnershipIssue[],
  failureMessage: string,
): string {
  if (typeof detail === 'string' && detail !== '') {
    return detail;
  }
  return issues.length === 0 ? failureMessage : issues.map((issue) => issue.message).join('\n');
}

async function partnershipFetch(
  path: string,
  init: RequestInit,
  failureMessage: string,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new PartnershipError(NETWORK_ERROR_MESSAGE);
  }
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail ?? null;
    } catch {
      detail = null;
    }
    const issues = partnershipIssues(detail);
    throw new PartnershipError(partnershipMessage(detail, issues, failureMessage), issues);
  }
  return response;
}

/** The PUT body. `null` is sent as `null`: the explicit "no Partnership". */
function partnershipRequestBody(partnership: Partnership | null): RequestInit {
  return {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ partnership }),
  };
}

/** `GET /deals/{id}/partnership`. Read-only: a Deal with no Partnership reports
 * `null` and no Investment, and asking gives it neither. */
export async function readDealPartnership(dealId: string): Promise<DealPartnership> {
  const response = await partnershipFetch(
    `/deals/${encodeURIComponent(dealId)}/partnership`,
    { method: 'GET' },
    'The partnership could not be loaded',
  );
  return (await response.json()) as DealPartnership;
}

/** `PUT /deals/{id}/partnership`. The first save of a Partnership materializes
 * the Deal's hidden one-unit Investment; saving `null` clears it and releases
 * the Deal when nothing else is held. */
export async function saveDealPartnership(
  dealId: string,
  partnership: Partnership | null,
): Promise<DealPartnership> {
  const response = await partnershipFetch(
    `/deals/${encodeURIComponent(dealId)}/partnership`,
    partnershipRequestBody(partnership),
    'The partnership could not be saved',
  );
  return (await response.json()) as DealPartnership;
}

/** `GET /investments/{id}/partnership`. */
export async function readInvestmentPartnership(
  investmentId: string,
): Promise<InvestmentPartnership> {
  const response = await partnershipFetch(
    `/investments/${encodeURIComponent(investmentId)}/partnership`,
    { method: 'GET' },
    'The partnership could not be loaded',
  );
  return (await response.json()) as InvestmentPartnership;
}

/** `PUT /investments/{id}/partnership`. */
export async function saveInvestmentPartnership(
  investmentId: string,
  partnership: Partnership | null,
): Promise<InvestmentPartnership> {
  const response = await partnershipFetch(
    `/investments/${encodeURIComponent(investmentId)}/partnership`,
    partnershipRequestBody(partnership),
    'The partnership could not be saved',
  );
  return (await response.json()) as InvestmentPartnership;
}

function partnershipVariantPath(
  investmentId: string,
  strategyId: string,
  scenarioId: string,
): string {
  return `/investments/${encodeURIComponent(investmentId)}/partnership-variants/${encodeURIComponent(
    strategyId,
  )}/${encodeURIComponent(scenarioId)}`;
}

/** The variant's three layered fingerprints, without executing anything. The
 * Partnership fingerprint is `null` when the variant resolves none (FP-2). */
export async function readPartnershipVariantFingerprint(
  investmentId: string,
  strategyId: string,
  scenarioId: string,
): Promise<PartnershipVariantFingerprint> {
  const response = await partnershipFetch(
    `${partnershipVariantPath(investmentId, strategyId, scenarioId)}/fingerprint`,
    { method: 'GET' },
    'The partnership fingerprint could not be read',
  );
  return (await response.json()) as PartnershipVariantFingerprint;
}

/** The Partnership analysis: the structured variant, then the accepted Stage 1
 * engine on its Common Equity Cash Flow. An unavailable Common Equity Cash Flow
 * is a successful analysis with an `unavailable` result, never an error. */
export async function analyzePartnershipVariant(
  investmentId: string,
  strategyId: string,
  scenarioId: string,
): Promise<PartnershipVariantAnalysis> {
  const response = await partnershipFetch(
    `${partnershipVariantPath(investmentId, strategyId, scenarioId)}/analysis`,
    { method: 'POST' },
    'The partnership analysis could not be completed',
  );
  return (await response.json()) as PartnershipVariantAnalysis;
}

/** `GET /investments/{id}/partner-perspectives` -- the addressable partners, by
 * their stable ids, for the Partner matrix selector. */
export async function listPartnerPerspectives(
  investmentId: string,
): Promise<PartnerPerspectives> {
  const response = await partnershipFetch(
    `/investments/${encodeURIComponent(investmentId)}/partner-perspectives`,
    { method: 'GET' },
    'The partners could not be loaded',
  );
  return (await response.json()) as PartnerPerspectives;
}

/** `POST /investments/{id}/partner-decision-matrix/{partner_id}`. */
export async function analyzePartnerDecisionMatrix(
  investmentId: string,
  partnerId: string,
): Promise<PartnerDecisionMatrixReport> {
  const response = await partnershipFetch(
    `/investments/${encodeURIComponent(investmentId)}/partner-decision-matrix/${encodeURIComponent(
      partnerId,
    )}`,
    { method: 'POST' },
    'The partner decision matrix could not be completed',
  );
  return (await response.json()) as PartnerDecisionMatrixReport;
}


// ===========================================================================
// Gate AM1 -- Managed Assets and Monthly Performance.
//
// Transport only. Nothing here computes a financial result: every total,
// variance, percentage, assessment, attention item and trend point arrives
// already computed by `anchor.asset_management.performance`.
//
// Two refusals are told apart deliberately, because the product must react to
// them differently:
//
//   * `AssetManagementError` carries structural issues (422) -- "fix these
//     numbers";
//   * `BudgetImmutableError` carries the frozen-budget conflict (409) -- the
//     submitted budget may be perfectly well-formed, and what is refused is the
//     authority to change it.
// ===========================================================================

/** A structural refusal, carrying the API's own issues in its own order. */
export class AssetManagementError extends Error {
  readonly issues: AssetReportIssue[];

  constructor(message: string, issues: AssetReportIssue[] = []) {
    super(message);
    this.name = 'AssetManagementError';
    this.issues = issues;
  }
}

/** The typed "this month already has a report" conflict (`409
 * monthly_report_exists`). A subclass of `AssetManagementError`, so every caller
 * that already handles that keeps working; the type lets the month form tell
 * this one refusal -- which a different month resolves -- apart from a
 * validation failure that a month change does not. */
export class MonthlyReportExistsError extends AssetManagementError {
  constructor(message: string) {
    super(message);
    this.name = 'MonthlyReportExistsError';
  }
}

/** The typed frozen-budget conflict. Never a subclass of
 * `AssetManagementError`: a caller that treats every failure as "invalid input"
 * would tell the analyst to correct a budget that is not theirs to correct. */
export class BudgetImmutableError extends Error {
  readonly changedFields: string[];
  readonly reportingMonth: string;

  constructor(conflict: BudgetImmutableConflict) {
    super(conflict.message);
    this.name = 'BudgetImmutableError';
    this.changedFields = conflict.changed_fields;
    this.reportingMonth = conflict.reporting_month;
  }
}

/** A Managed Asset already exists for this Deal. Carries the existing asset's
 * id so the product can open it rather than report a dead end. */
export class ManagedAssetExistsError extends Error {
  readonly managedAssetId: string;

  constructor(message: string, managedAssetId: string) {
    super(message);
    this.name = 'ManagedAssetExistsError';
    this.managedAssetId = managedAssetId;
  }
}

function assetIssues(detail: unknown): AssetReportIssue[] {
  if (!Array.isArray(detail)) {
    return [];
  }
  return detail.filter(
    (issue): issue is AssetReportIssue =>
      typeof issue === 'object' && issue !== null && typeof (issue as AssetReportIssue).code === 'string',
  );
}

async function assetFetch(
  path: string,
  init: RequestInit,
  failureMessage: string,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new AssetManagementError(NETWORK_ERROR_MESSAGE);
  }
  if (response.ok) {
    return response;
  }

  let detail: unknown = null;
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail ?? null;
  } catch {
    detail = null;
  }

  if (detail !== null && typeof detail === 'object' && !Array.isArray(detail)) {
    const conflict = detail as { code?: string };
    if (conflict.code === 'budget_immutable') {
      throw new BudgetImmutableError(detail as BudgetImmutableConflict);
    }
    if (conflict.code === 'managed_asset_exists') {
      const existing = detail as { message?: string; managed_asset_id?: string };
      throw new ManagedAssetExistsError(
        existing.message ?? failureMessage,
        existing.managed_asset_id ?? '',
      );
    }
    if (conflict.code === 'monthly_report_exists') {
      throw new MonthlyReportExistsError(
        (detail as { message?: string }).message ?? failureMessage,
      );
    }
  }

  const issues = assetIssues(detail);
  if (issues.length > 0) {
    throw new AssetManagementError(issues.map((issue) => issue.message).join('\n'), issues);
  }
  throw new AssetManagementError(typeof detail === 'string' ? detail : failureMessage);
}

function jsonBody(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

/** `POST /managed-assets`. */
export async function createManagedAsset(request: {
  source_deal_id: string;
  name: string | null;
  acquisition_date: string;
  property_type: string | null;
  market: string | null;
}): Promise<ManagedAsset> {
  const response = await assetFetch(
    '/managed-assets',
    jsonBody('POST', request),
    'The managed asset could not be created',
  );
  return (await response.json()) as ManagedAsset;
}

/** `GET /managed-assets`. */
export async function listManagedAssets(): Promise<ManagedAsset[]> {
  const response = await assetFetch(
    '/managed-assets',
    { method: 'GET' },
    'The managed assets could not be loaded',
  );
  return (await response.json()) as ManagedAsset[];
}

/** `GET /managed-assets/{id}`. */
export async function readManagedAsset(managedAssetId: string): Promise<ManagedAsset> {
  const response = await assetFetch(
    `/managed-assets/${encodeURIComponent(managedAssetId)}`,
    { method: 'GET' },
    'The managed asset could not be loaded',
  );
  return (await response.json()) as ManagedAsset;
}

/** `DELETE /managed-assets/{id}` -- also removes that asset's monthly reports. */
export async function deleteManagedAsset(managedAssetId: string): Promise<void> {
  await assetFetch(
    `/managed-assets/${encodeURIComponent(managedAssetId)}`,
    { method: 'DELETE' },
    'The managed asset could not be deleted',
  );
}

/** `GET /managed-assets/{id}/reports`. */
export async function listMonthlyReports(
  managedAssetId: string,
): Promise<MonthlyAssetReport[]> {
  const response = await assetFetch(
    `/managed-assets/${encodeURIComponent(managedAssetId)}/reports`,
    { method: 'GET' },
    'The monthly reports could not be loaded',
  );
  return (await response.json()) as MonthlyAssetReport[];
}

/** `GET /managed-assets/{id}/reports/{month}`. */
export async function readMonthlyReport(
  managedAssetId: string,
  reportingMonth: string,
): Promise<MonthlyAssetReport> {
  const response = await assetFetch(
    `/managed-assets/${encodeURIComponent(managedAssetId)}/reports/${encodeURIComponent(reportingMonth)}`,
    { method: 'GET' },
    'The monthly report could not be loaded',
  );
  return (await response.json()) as MonthlyAssetReport;
}

/** `POST /managed-assets/{id}/reports` -- the only call that writes a budget. */
export async function createMonthlyReport(
  managedAssetId: string,
  request: {
    reporting_month: string;
    budget: OperatingFigures;
    actual: OperatingFigures;
    commentary: string | null;
  },
): Promise<MonthlyAssetReport> {
  const response = await assetFetch(
    `/managed-assets/${encodeURIComponent(managedAssetId)}/reports`,
    jsonBody('POST', request),
    'The monthly report could not be saved',
  );
  return (await response.json()) as MonthlyAssetReport;
}

/** `PUT /managed-assets/{id}/reports/{month}`.
 *
 * `budget` is sent as `null` on the ordinary path: the frozen budget is not
 * this call's to change, and asserting nothing about it is how the product says
 * so. It is echoed back only by a caller that deliberately wants the typed
 * conflict when it differs. */
export async function updateMonthlyReportActuals(
  managedAssetId: string,
  reportingMonth: string,
  request: {
    actual: OperatingFigures;
    commentary: string | null;
    budget: OperatingFigures | null;
  },
): Promise<MonthlyAssetReport> {
  const response = await assetFetch(
    `/managed-assets/${encodeURIComponent(managedAssetId)}/reports/${encodeURIComponent(reportingMonth)}`,
    jsonBody('PUT', request),
    'The actual results could not be saved',
  );
  return (await response.json()) as MonthlyAssetReport;
}

/** `PUT /managed-assets/{id}/reports/{month}/commentary` -- the commentary
 * alone.
 *
 * The body is exactly `{ commentary }`. It carries no figures, so saving a note
 * can never write back actual results this client loaded earlier over newer
 * ones another session saved since, and it names no budget. Actual results are
 * saved only through `updateMonthlyReportActuals`. */
export async function updateMonthlyReportCommentary(
  managedAssetId: string,
  reportingMonth: string,
  commentary: string | null,
): Promise<MonthlyAssetReport> {
  const response = await assetFetch(
    `/managed-assets/${encodeURIComponent(managedAssetId)}/reports/${encodeURIComponent(reportingMonth)}/commentary`,
    jsonBody('PUT', { commentary }),
    'The commentary could not be saved',
  );
  return (await response.json()) as MonthlyAssetReport;
}

/** `GET /managed-assets/{id}/performance/{month}` -- the authoritative result. */
export async function readAssetPerformance(
  managedAssetId: string,
  reportingMonth: string,
): Promise<AssetPerformanceResponse> {
  const response = await assetFetch(
    `/managed-assets/${encodeURIComponent(managedAssetId)}/performance/${encodeURIComponent(reportingMonth)}`,
    { method: 'GET' },
    'The monthly performance could not be loaded',
  );
  return (await response.json()) as AssetPerformanceResponse;
}
