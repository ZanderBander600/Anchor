export interface AcquisitionFormValues {
  purchasePrice: string;
  currentNoi: string;
  occupancy: string;
  noiGrowth: string;
  holdPeriod: string;
  exitCapRate: string;
  ltv: string;
  interestRate: string;
  amortization: string;
}

export interface AcquisitionRequest {
  purchase_price: number;
  current_noi: number;
  occupancy: number;
  noi_growth: number;
  hold_period: number;
  exit_cap_rate: number;
  ltv: number;
  interest_rate: number;
  amortization: number;
}

/** Mirrors ``AcquisitionResults`` in ``src/mini_anchor/engine/contracts.py``. */
export interface AcquisitionResults {
  going_in_cap_rate: number;
  loan_amount: number;
  initial_equity: number;
  monthly_debt_service: number;
  annual_debt_service: number[];
  remaining_loan_balance: number;
  noi_by_year: number[];
  exit_noi: number;
  exit_value: number;
  net_sale_proceeds: number;
  unlevered_cash_flows: number[];
  levered_cash_flows: number[];
  unlevered_irr: number | null;
  levered_irr: number | null;
  equity_multiple: number | null;
  dscr_by_year: (number | null)[];
  headline_dscr: number | null;
}

export interface ValidationIssue {
  field_id: string | null;
  category: string;
  message: string;
}
