import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  createDeal,
  deleteDeal,
  duplicateDeal,
  getDeal,
  listDeals,
  updateDeal,
  uploadExcel,
  uploadOm,
} from './api';
import type { AcquisitionRequest, Deal, ExcelIntakeReport, ExtractionResult } from './types';

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
    inputs: GOLDEN_INPUTS,
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
