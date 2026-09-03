import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  analyzeDetailedAcquisition,
  ApiError,
  createDeal,
  createDetailedDeal,
  deleteDeal,
  duplicateDeal,
  fetchDetailedAIAnalysis,
  getDeal,
  listDeals,
  updateDeal,
  updateDetailedDeal,
  uploadExcel,
  uploadOm,
} from './api';
import type {
  AcquisitionRequest,
  AcquisitionTermsRequest,
  Deal,
  DetailedAcquisitionResults,
  DetailedOperatingInputsRequest,
  ExcelIntakeReport,
  ExtractionResult,
} from './types';

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function extractionFixture(): ExtractionResult {
  const missing = (field_id: string) => ({ field_id, candidates: [] });
  return {
    purchase_price: {
      field_id: 'purchase_price',
      candidates: [
        {
          value: '1000000',
          status: 'stated',
          provenance: { page: 1, anchor: 'paragraph:0', snippet: '$1,000,000' },
        },
      ],
    },
    current_noi: missing('current_noi'),
    occupancy: missing('occupancy'),
    noi_growth: missing('noi_growth'),
    hold_period: missing('hold_period'),
    exit_cap_rate: missing('exit_cap_rate'),
    ltv: missing('ltv'),
    interest_rate: missing('interest_rate'),
    amortization: missing('amortization'),
    deal_context: {
      property_name: missing('property_name'),
      address: missing('address'),
      property_type: missing('property_type'),
      unit_count_or_building_area: missing('unit_count_or_building_area'),
      year_built: missing('year_built'),
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('uploadOm', () => {
  it('returns the parsed ExtractionResult on a successful upload', async () => {
    const extraction = extractionFixture();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, extraction));
    vi.stubGlobal('fetch', fetchMock);

    const file = new File([new Uint8Array([1, 2, 3])], 'om.pdf', { type: 'application/pdf' });
    const result = await uploadOm(file);

    expect(result).toEqual(extraction);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/ingestion/om');
    expect(init.method).toBe('POST');
    expect(init.body).toBeInstanceOf(FormData);
    // The browser must set the multipart boundary itself.
    expect(init.headers).toBeUndefined();
  });

  it('surfaces a distinct message for a 503 configuration failure', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse(503, { detail: 'AZURE_DOCUMENTINTELLIGENCE_KEY is not configured.' }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const file = new File([new Uint8Array([1])], 'om.pdf', { type: 'application/pdf' });

    await expect(uploadOm(file)).rejects.toThrow('AZURE_DOCUMENTINTELLIGENCE_KEY is not configured.');
  });

  it('surfaces a distinct message for a 502 provider failure', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(502, { detail: 'The Azure Document Intelligence request failed.' }));
    vi.stubGlobal('fetch', fetchMock);

    const file = new File([new Uint8Array([1])], 'om.pdf', { type: 'application/pdf' });

    await expect(uploadOm(file)).rejects.toThrow('The Azure Document Intelligence request failed.');
  });

  it('surfaces the 502 message distinctly from the 503 message', async () => {
    const fetchMock503 = vi.fn().mockResolvedValue(jsonResponse(503, {}));
    vi.stubGlobal('fetch', fetchMock503);
    const file = new File([new Uint8Array([1])], 'om.pdf', { type: 'application/pdf' });
    let message503 = '';
    try {
      await uploadOm(file);
    } catch (error) {
      message503 = (error as ApiError).message;
    }

    const fetchMock502 = vi.fn().mockResolvedValue(jsonResponse(502, {}));
    vi.stubGlobal('fetch', fetchMock502);
    let message502 = '';
    try {
      await uploadOm(file);
    } catch (error) {
      message502 = (error as ApiError).message;
    }

    expect(message503).not.toBe(message502);
  });

  it('rejects a malformed/rejected upload with a 4xx message', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(400, { detail: 'Uploaded file does not appear to be a valid PDF.' }));
    vi.stubGlobal('fetch', fetchMock);

    const file = new File([new Uint8Array([1])], 'om.pdf', { type: 'application/pdf' });

    await expect(uploadOm(file)).rejects.toThrow('Uploaded file does not appear to be a valid PDF.');
  });

  it('throws an ApiError on a network failure', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);

    const file = new File([new Uint8Array([1])], 'om.pdf', { type: 'application/pdf' });

    await expect(uploadOm(file)).rejects.toBeInstanceOf(ApiError);
    await expect(uploadOm(file)).rejects.toThrow(/Could not reach the Anchor API/);
  });
});

function acquisitionRequestFixture(): AcquisitionRequest {
  return {
    purchase_price: 50_000_000,
    current_noi: 2_500_000,
    occupancy: 0.95,
    noi_growth: 0.03,
    hold_period: 5,
    exit_cap_rate: 0.055,
    ltv: 0.65,
    interest_rate: 0.0525,
    amortization: 30,
    acquisition_cost_pct: 0,
    financing_fee_pct: 0,
    disposition_cost_pct: 0,
    annual_capex_reserve: 0,
    io_period: 0,
  };
}

const XLSX_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

describe('uploadExcel', () => {
  it('returns the ExcelIntakeReport (inputs + defaulted_v2_field_ids) on a successful upload', async () => {
    const report: ExcelIntakeReport = {
      inputs: acquisitionRequestFixture(),
      defaulted_v2_field_ids: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, report));
    vi.stubGlobal('fetch', fetchMock);

    const file = new File([new Uint8Array([1, 2, 3])], 'anchor_input.xlsx', { type: XLSX_TYPE });
    const result = await uploadExcel(file);

    expect(result).toEqual(report);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/ingestion/excel');
    expect(init.method).toBe('POST');
    expect(init.body).toBeInstanceOf(FormData);
    // The browser must set the multipart boundary itself.
    expect(init.headers).toBeUndefined();
  });

  it('surfaces the 422 validation issue list with the same shape /analyze uses', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(422, {
        detail: [
          {
            field_id: 'purchase_price',
            category: 'blank_value',
            message: "Value for Field ID 'purchase_price' is blank at Inputs!C2.",
          },
        ],
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const file = new File([new Uint8Array([1])], 'anchor_input.xlsx', { type: XLSX_TYPE });

    let caught: ApiError | null = null;
    try {
      await uploadExcel(file);
    } catch (error) {
      caught = error as ApiError;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect(caught?.issues).toHaveLength(1);
    expect(caught?.issues[0].field_id).toBe('purchase_price');
    expect(caught?.message).toBe("Value for Field ID 'purchase_price' is blank at Inputs!C2.");
  });

  it('rejects a malformed/rejected upload with a 4xx message', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(400, { detail: 'Uploaded file must be a .xlsx workbook.' }));
    vi.stubGlobal('fetch', fetchMock);

    const file = new File([new Uint8Array([1])], 'not-a-workbook.csv', { type: 'text/csv' });

    await expect(uploadExcel(file)).rejects.toThrow('Uploaded file must be a .xlsx workbook.');
  });

  it('throws an ApiError on a network failure', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);

    const file = new File([new Uint8Array([1])], 'anchor_input.xlsx', { type: XLSX_TYPE });

    await expect(uploadExcel(file)).rejects.toBeInstanceOf(ApiError);
    await expect(uploadExcel(file)).rejects.toThrow(/Could not reach the Anchor API/);
  });
});

const GOLDEN_INPUTS: AcquisitionRequest = {
  purchase_price: 50_000_000,
  current_noi: 2_500_000,
  occupancy: 0.95,
  noi_growth: 0.03,
  hold_period: 5,
  exit_cap_rate: 0.055,
  ltv: 0.65,
  interest_rate: 0.0525,
  amortization: 30,
  acquisition_cost_pct: 0,
  financing_fee_pct: 0,
  disposition_cost_pct: 0,
  annual_capex_reserve: 0,
  io_period: 0,
};

function dealFixture(overrides: Partial<Deal> = {}): Deal {
  return {
    id: 'deal-1',
    name: '111 Main St',
    operating_mode: 'quick',
    inputs: GOLDEN_INPUTS,
    terms: null,
    detailed_operating_inputs: null,
    created_at: '2026-09-03T12:00:00+00:00',
    updated_at: '2026-09-03T12:00:00+00:00',
    ...overrides,
  };
}

/** Detailed Operating Model V2.1 Gate 11 -- a saved Detailed deal fixture.
 * `inputs` stays `null` -- never a fabricated `AcquisitionInputs`. */
function detailedDealFixture(overrides: Partial<Deal> = {}): Deal {
  return {
    id: 'detailed-deal-1',
    name: 'Golden Detailed Deal',
    operating_mode: 'detailed',
    inputs: null,
    terms: {
      purchase_price: 10_000_000,
      hold_period: 5,
      exit_cap_rate: 0.065,
      ltv: 0.6,
      interest_rate: 0.05,
      amortization: 30,
      acquisition_cost_pct: 0.02,
      financing_fee_pct: 0.01,
      disposition_cost_pct: 0.025,
      annual_capex_reserve: 50_000,
      io_period: 2,
    },
    detailed_operating_inputs: {
      gross_potential_rent: 800_000,
      other_income: 20_000,
      vacancy_credit_loss_pct: 0.05,
      property_taxes: 60_000,
      insurance: 20_000,
      utilities: 25_000,
      repairs_maintenance: 20_000,
      other_operating_expenses: 16_000,
      management_fee_pct: 0.05,
      revenue_growth: 0.03,
      expense_growth: 0.03,
    },
    created_at: '2026-09-03T12:00:00+00:00',
    updated_at: '2026-09-03T12:00:00+00:00',
    ...overrides,
  };
}

describe('createDeal', () => {
  it('POSTs the name and inputs to /deals and returns the created deal', async () => {
    const deal = dealFixture();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, deal));
    vi.stubGlobal('fetch', fetchMock);

    const result = await createDeal('111 Main St', GOLDEN_INPUTS);

    expect(result).toEqual(deal);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/deals');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ name: '111 Main St', inputs: GOLDEN_INPUTS });
  });

  it('surfaces a 422 validation failure with the issue-list shape', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(422, {
        detail: [{ field_id: 'purchase_price', category: 'out_of_domain_value', message: 'bad price' }],
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    let caught: ApiError | undefined;
    try {
      await createDeal('Bad Deal', { ...GOLDEN_INPUTS, purchase_price: -1 });
    } catch (error) {
      caught = error as ApiError;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect(caught?.issues[0].field_id).toBe('purchase_price');
  });

  it('throws an ApiError on a network failure', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);

    await expect(createDeal('Deal', GOLDEN_INPUTS)).rejects.toBeInstanceOf(ApiError);
  });
});

describe('updateDeal', () => {
  it('PUTs the name and inputs to /deals/{id} and returns the updated deal', async () => {
    const deal = dealFixture({ name: 'Renamed Deal' });
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, deal));
    vi.stubGlobal('fetch', fetchMock);

    const result = await updateDeal('deal-1', 'Renamed Deal', GOLDEN_INPUTS);

    expect(result).toEqual(deal);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/deals/deal-1');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({ name: 'Renamed Deal', inputs: GOLDEN_INPUTS });
  });

  it('surfaces a 404 for an unknown deal id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(404, { detail: 'not found' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(updateDeal('missing', 'Deal', GOLDEN_INPUTS)).rejects.toThrow(/could not be found/);
  });
});

// =============================================================================
// Detailed Operating Model V2.1 Gate 11 -- createDetailedDeal/updateDetailedDeal
// =============================================================================

describe('createDetailedDeal', () => {
  it('POSTs the name, operating_mode, terms, and detailed_operating_inputs to /deals', async () => {
    const deal = detailedDealFixture();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, deal));
    vi.stubGlobal('fetch', fetchMock);

    const result = await createDetailedDeal(
      'Golden Detailed Deal',
      GOLDEN_TERMS,
      GOLDEN_DETAILED_OPERATING_INPUTS,
    );

    expect(result).toEqual(deal);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/deals');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      name: 'Golden Detailed Deal',
      operating_mode: 'detailed',
      terms: GOLDEN_TERMS,
      detailed_operating_inputs: GOLDEN_DETAILED_OPERATING_INPUTS,
    });
  });

  it('surfaces a 422 validation failure with the issue-list shape', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(422, {
        detail: [{ field_id: 'ltv', category: 'out_of_domain_value', message: 'bad ltv' }],
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    let caught: ApiError | undefined;
    try {
      await createDetailedDeal(
        'Bad Deal',
        { ...GOLDEN_TERMS, ltv: 1.5 },
        GOLDEN_DETAILED_OPERATING_INPUTS,
      );
    } catch (error) {
      caught = error as ApiError;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect(caught?.issues[0].field_id).toBe('ltv');
  });

  it('throws an ApiError on a network failure', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      createDetailedDeal('Deal', GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS),
    ).rejects.toBeInstanceOf(ApiError);
  });
});

describe('updateDetailedDeal', () => {
  it('PUTs the name, operating_mode, terms, and detailed_operating_inputs to /deals/{id}', async () => {
    const deal = detailedDealFixture({ name: 'Renamed Detailed Deal' });
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, deal));
    vi.stubGlobal('fetch', fetchMock);

    const result = await updateDetailedDeal(
      'detailed-deal-1',
      'Renamed Detailed Deal',
      GOLDEN_TERMS,
      GOLDEN_DETAILED_OPERATING_INPUTS,
    );

    expect(result).toEqual(deal);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/deals/detailed-deal-1');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({
      name: 'Renamed Detailed Deal',
      operating_mode: 'detailed',
      terms: GOLDEN_TERMS,
      detailed_operating_inputs: GOLDEN_DETAILED_OPERATING_INPUTS,
    });
  });

  it('surfaces a 404 for an unknown deal id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(404, { detail: 'not found' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      updateDetailedDeal('missing', 'Deal', GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS),
    ).rejects.toThrow(/could not be found/);
  });
});

describe('getDeal', () => {
  it('GETs one deal by id', async () => {
    const deal = dealFixture();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, deal));
    vi.stubGlobal('fetch', fetchMock);

    const result = await getDeal('deal-1');

    expect(result).toEqual(deal);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain('/deals/deal-1');
  });

  it('surfaces a 404 for an unknown deal id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(404, { detail: 'not found' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(getDeal('missing')).rejects.toThrow(/could not be found/);
  });
});

describe('listDeals', () => {
  it('GETs /deals and returns the array as-is', async () => {
    const deals = [dealFixture({ id: 'a' }), dealFixture({ id: 'b' })];
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, deals));
    vi.stubGlobal('fetch', fetchMock);

    const result = await listDeals();

    expect(result).toEqual(deals);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain('/deals');
  });

  it('throws an ApiError on a network failure', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);

    await expect(listDeals()).rejects.toBeInstanceOf(ApiError);
  });
});

describe('duplicateDeal', () => {
  it('POSTs to /deals/{id}/duplicate with no body when no name is given', async () => {
    const copy = dealFixture({ id: 'deal-2', name: '111 Main St (Copy)' });
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, copy));
    vi.stubGlobal('fetch', fetchMock);

    const result = await duplicateDeal('deal-1');

    expect(result).toEqual(copy);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/deals/deal-1/duplicate');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({});
  });

  it('POSTs the name override when one is given', async () => {
    const copy = dealFixture({ id: 'deal-2', name: '222 Oak Ave' });
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, copy));
    vi.stubGlobal('fetch', fetchMock);

    await duplicateDeal('deal-1', '222 Oak Ave');

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ name: '222 Oak Ave' });
  });

  it('surfaces a 404 for an unknown deal id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(404, { detail: 'not found' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(duplicateDeal('missing')).rejects.toThrow(/could not be found/);
  });
});

describe('deleteDeal', () => {
  it('DELETEs /deals/{id} and resolves with no value on success', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(204, undefined));
    vi.stubGlobal('fetch', fetchMock);

    await expect(deleteDeal('deal-1')).resolves.toBeUndefined();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/deals/deal-1');
    expect(init.method).toBe('DELETE');
  });

  it('surfaces a 404 for an unknown deal id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(404, { detail: 'not found' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(deleteDeal('missing')).rejects.toThrow(/could not be found/);
  });

  it('throws an ApiError on a network failure', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);

    await expect(deleteDeal('deal-1')).rejects.toBeInstanceOf(ApiError);
  });
});

// =============================================================================
// Detailed Operating Model V2.1 Gate 6
// =============================================================================

const GOLDEN_TERMS: AcquisitionTermsRequest = {
  purchase_price: 10_000_000,
  hold_period: 5,
  exit_cap_rate: 0.065,
  ltv: 0.6,
  interest_rate: 0.05,
  amortization: 30,
  acquisition_cost_pct: 0.02,
  financing_fee_pct: 0.01,
  disposition_cost_pct: 0.025,
  annual_capex_reserve: 50_000,
  io_period: 2,
};

const GOLDEN_DETAILED_OPERATING_INPUTS: DetailedOperatingInputsRequest = {
  gross_potential_rent: 800_000,
  other_income: 20_000,
  vacancy_credit_loss_pct: 0.05,
  property_taxes: 60_000,
  insurance: 20_000,
  utilities: 25_000,
  repairs_maintenance: 20_000,
  other_operating_expenses: 16_000,
  management_fee_pct: 0.05,
  revenue_growth: 0.03,
  expense_growth: 0.03,
};

function detailedResultsFixture(): DetailedAcquisitionResults {
  return {
    operating_projection: {
      gross_potential_rent_by_year: [800_000, 824_000, 848_720, 874_181.6, 900_407.05],
      other_income_by_year: [20_000, 20_600, 21_218, 21_854.54, 22_510.18],
      vacancy_credit_loss_by_year: [40_000, 41_200, 42_436, 43_709.08, 45_020.35],
      effective_gross_income_by_year: [780_000, 803_400, 827_502, 852_327.06, 877_896.87],
      property_taxes_by_year: [60_000, 61_800, 63_654, 65_563.62, 67_530.53],
      insurance_by_year: [20_000, 20_600, 21_218, 21_854.54, 22_510.18],
      utilities_by_year: [25_000, 25_750, 26_522.5, 27_318.18, 28_137.72],
      repairs_maintenance_by_year: [20_000, 20_600, 21_218, 21_854.54, 22_510.18],
      other_operating_expenses_by_year: [16_000, 16_480, 16_974.4, 17_483.63, 18_008.14],
      management_fee_by_year: [39_000, 40_170, 41_375.1, 42_616.35, 43_894.84],
      total_operating_expenses_by_year: [180_000, 185_400, 190_962, 196_690.86, 202_591.59],
      noi_by_year: [600_000, 618_000, 636_540, 655_636.2, 675_305.29],
      exit_noi: 695_564.44,
      going_in_cap_rate: 0.06,
    },
    results: {
      going_in_cap_rate: 0.06,
      loan_amount: 6_000_000,
      acquisition_costs: 200_000,
      financing_fee: 60_000,
      initial_equity: 4_260_000,
      monthly_debt_service: 32_209.3,
      annual_debt_service: [300_000, 300_000, 386_511.57, 386_511.57, 386_511.57],
      remaining_loan_balance: 5_720_615.68,
      noi_by_year: [600_000, 618_000, 636_540, 655_636.2, 675_305.29],
      capex_by_year: [50_000, 50_000, 50_000, 50_000, 50_000],
      exit_noi: 695_564.44,
      exit_value: 10_700_991.46,
      disposition_costs: 267_524.79,
      net_sale_proceeds: 4_712_850.99,
      unlevered_cash_flows: [-10_200_000, 550_000, 568_000, 586_540, 605_636.2, 11_058_771.95],
      levered_cash_flows: [-4_260_000, 250_000, 268_000, 200_028.43, 219_124.63, 4_951_644.71],
      unlevered_irr: 0.061388,
      levered_irr: 0.073802,
      equity_multiple: 1.38235,
      dscr_by_year: [2.0, 2.06, 1.64688, 1.69629, 1.74718],
      headline_dscr: 2.0,
      min_dscr: 1.64688,
    },
  };
}

describe('analyzeDetailedAcquisition', () => {
  it('POSTs operating_mode "detailed" with terms and detailed_operating_inputs', async () => {
    const detailedResults = detailedResultsFixture();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, detailedResults));
    vi.stubGlobal('fetch', fetchMock);

    const result = await analyzeDetailedAcquisition(
      GOLDEN_TERMS,
      GOLDEN_DETAILED_OPERATING_INPUTS,
    );

    expect(result).toEqual(detailedResults);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/analyze');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      operating_mode: 'detailed',
      terms: GOLDEN_TERMS,
      detailed_operating_inputs: GOLDEN_DETAILED_OPERATING_INPUTS,
    });
  });

  it('surfaces a 422 validation failure with the issue-list shape', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(422, {
        detail: [{ field_id: 'ltv', category: 'out_of_domain_value', message: 'bad ltv' }],
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    let caught: ApiError | undefined;
    try {
      await analyzeDetailedAcquisition(
        { ...GOLDEN_TERMS, ltv: 1.5 },
        GOLDEN_DETAILED_OPERATING_INPUTS,
      );
    } catch (error) {
      caught = error as ApiError;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect(caught?.issues[0].field_id).toBe('ltv');
  });

  it('throws an ApiError on a network failure', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      analyzeDetailedAcquisition(GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it('throws an ApiError on a generic non-ok response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(500, {}));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      analyzeDetailedAcquisition(GOLDEN_TERMS, GOLDEN_DETAILED_OPERATING_INPUTS),
    ).rejects.toBeInstanceOf(ApiError);
  });
});


// =============================================================================
// Detailed Operating Model V2.1 Gate 9 -- fetchDetailedAIAnalysis
// =============================================================================

describe('fetchDetailedAIAnalysis', () => {
  const AI_ANALYSIS = {
    executive_summary: 'Summary.',
    investment_view: 'View.',
    strengths: ['Strength.'],
    risks: ['Risk.'],
    return_drivers: ['Driver.'],
    downside_analysis: 'Downside.',
    capital_structure_analysis: 'Capital.',
    break_even_analysis: 'Break-even.',
    questions_to_investigate: ['Question.'],
    confidence_notes: ['Note.'],
  };

  it('POSTs operating_mode "detailed" with terms, detailed_operating_inputs, and hurdle targets', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, AI_ANALYSIS));
    vi.stubGlobal('fetch', fetchMock);

    const result = await fetchDetailedAIAnalysis(
      GOLDEN_TERMS,
      GOLDEN_DETAILED_OPERATING_INPUTS,
      0.1,
      1.5,
      1.2,
      'levered_irr',
    );

    expect(result).toEqual(AI_ANALYSIS);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/ai/analysis');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      operating_mode: 'detailed',
      terms: GOLDEN_TERMS,
      detailed_operating_inputs: GOLDEN_DETAILED_OPERATING_INPUTS,
      target_levered_irr: 0.1,
      target_equity_multiple: 1.5,
      target_headline_dscr: 1.2,
      return_hurdle_metric: 'levered_irr',
    });
  });

  it('surfaces a distinct message for a 503 configuration failure', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(503, { detail: 'OPENAI_API_KEY is not configured.' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      fetchDetailedAIAnalysis(
        GOLDEN_TERMS,
        GOLDEN_DETAILED_OPERATING_INPUTS,
        0.1,
        1.5,
        1.2,
        'levered_irr',
      ),
    ).rejects.toThrow('OPENAI_API_KEY is not configured.');
  });

  it('surfaces a distinct message for a 502 provider failure', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(502, { detail: 'The AI provider request failed.' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      fetchDetailedAIAnalysis(
        GOLDEN_TERMS,
        GOLDEN_DETAILED_OPERATING_INPUTS,
        0.1,
        1.5,
        1.2,
        'levered_irr',
      ),
    ).rejects.toThrow('The AI provider request failed.');
  });

  it('surfaces a 422 validation failure with the issue-list shape', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(422, {
        detail: [{ field_id: 'ltv', category: 'out_of_domain_value', message: 'bad ltv' }],
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    let caught: ApiError | undefined;
    try {
      await fetchDetailedAIAnalysis(
        { ...GOLDEN_TERMS, ltv: 1.5 },
        GOLDEN_DETAILED_OPERATING_INPUTS,
        0.1,
        1.5,
        1.2,
        'levered_irr',
      );
    } catch (error) {
      caught = error as ApiError;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect(caught?.issues[0].field_id).toBe('ltv');
  });

  it('throws an ApiError on a network failure', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);

    await expect(
      fetchDetailedAIAnalysis(
        GOLDEN_TERMS,
        GOLDEN_DETAILED_OPERATING_INPUTS,
        0.1,
        1.5,
        1.2,
        'levered_irr',
      ),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it('never includes current_noi or noi_growth in the request body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, AI_ANALYSIS));
    vi.stubGlobal('fetch', fetchMock);

    await fetchDetailedAIAnalysis(
      GOLDEN_TERMS,
      GOLDEN_DETAILED_OPERATING_INPUTS,
      0.1,
      1.5,
      1.2,
      'levered_irr',
    );

    const [, init] = fetchMock.mock.calls[0];
    expect(init.body).not.toContain('current_noi');
    expect(init.body).not.toContain('"noi_growth"');
  });
});
