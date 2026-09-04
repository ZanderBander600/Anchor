# Owner Return Metrics V3 — Golden Case

## Status

Companion to `docs/owner_return_metrics_v3_financial_conventions.md`. Every
number below is derived by **independent arithmetic** against the formulas
that document defines — none of it is produced by running the production
engine. Production code, when implemented, must derive these values from
`AcquisitionTerms`/`AcquisitionResults` fields; it must never hardcode any
number on this page.

Two cases are used, per the Sprint A charter (Section 9):

1. **Detailed golden case** — the existing V2.1 Detailed bridge case, to
   exercise transaction costs, CapEx, and an IO period.
2. **Quick golden case** — the existing Phase 2 golden case
   (`tests/test_engine_golden_case.py`), to demonstrate the shared downstream
   architecture (Section 8 of the conventions doc) produces the same metrics
   from Quick's inputs with no formula change — no transaction costs, no
   CapEx, no IO period, so it also exercises the "neutral defaults reduce to
   the simple formula" path.

---

## Case 1: Detailed golden case (V2.1 bridge case)

### Inputs

```
purchase_price          = 10,000,000
hold_period              = 5
exit_cap_rate            = 0.065
ltv                       = 0.60
interest_rate             = 0.05
amortization              = 30
acquisition_cost_pct      = 0.02
financing_fee_pct         = 0.01
disposition_cost_pct      = 0.025
annual_capex_reserve      = 50,000
io_period                 = 2
```

Detailed operating inputs (`gross_potential_rent = 800,000`, etc.) are
restated in `docs/detailed_operating_model_v2_1_golden_case.md`; only their
authoritative downstream outputs are needed here.

### Authoritative upstream values (already verified elsewhere, restated)

```
loan_amount        = purchase_price * ltv = 10,000,000 * 0.60 = 6,000,000
acquisition_costs  = purchase_price * acquisition_cost_pct = 10,000,000 * 0.02 = 200,000
financing_fee      = loan_amount * financing_fee_pct = 6,000,000 * 0.01 = 60,000
initial_equity     = 10,000,000 - 6,000,000 + 200,000 + 60,000 = 4,260,000   ✓ matches stated authoritative value

NOI:  Y1 600,000.000   Y2 618,000.000   Y3 636,540.000   Y4 655,636.200   Y5 675,305.286
CapEx: 50,000.000 in every year
ADS:  Y1 300,000.000   Y2 300,000.000   Y3 386,511.5685687402   Y4 386,511.5685687402   Y5 386,511.5685687402
```

(`Y1`/`Y2` debt service is flat at `300,000` — the interest-only payment
during the 2-year `io_period`; `Y3` onward is the fully-amortizing PMT.)

### Recurring Levered Cash Flow (`NOI_y - CapEx_y - ADS_y`)

| Year | NOI | CapEx | ADS | Recurring Levered CF |
|---|---|---|---|---|
| 1 | 600,000.000 | 50,000 | 300,000.000 | **250,000.000** |
| 2 | 618,000.000 | 50,000 | 300,000.000 | **268,000.000** |
| 3 | 636,540.000 | 50,000 | 386,511.5685687402 | **200,028.4314312598** |
| 4 | 655,636.200 | 50,000 | 386,511.5685687402 | **219,124.6314312598** |
| 5 | 675,305.286 | 50,000 | 386,511.5685687402 | **238,793.7174312598** |

### 1. Levered Cash-on-Cash Return (`Recurring Levered CF_y / 4,260,000`)

| Year | Levered CoC |
|---|---|
| 1 | 0.0586854460... (**5.8685%**) |
| 2 | 0.0629107981... (**6.2911%**) |
| 3 | 0.0469550309... (**4.6955%**) |
| 4 | 0.0514377069... (**5.1438%**) |
| 5 | 0.0560548632... (**5.6055%**) |

Note Year 5 uses `238,793.7174312598 / 4,260,000`, **not**
`levered_cash_flows[5]` (which would additionally include
`net_sale_proceeds` and produce a CoC well over 100%).

### Recurring Unlevered Cash Flow (`NOI_y - CapEx_y`)

| Year | Recurring Unlevered CF |
|---|---|
| 1 | 550,000.000 |
| 2 | 568,000.000 |
| 3 | 586,540.000 |
| 4 | 605,636.200 |
| 5 | 625,305.286 |

### 2. Unlevered Cash Yield (`Recurring Unlevered CF_y / 10,200,000`)

Basis `= purchase_price + acquisition_costs = 10,000,000 + 200,000 = 10,200,000`.

| Year | Unlevered Cash Yield |
|---|---|
| 1 | 0.0539215686... (**5.3922%**) |
| 2 | 0.0556862745... (**5.5686%**) |
| 3 | 0.0575039216... (**5.7504%**) |
| 4 | 0.0593760980... (**5.9376%**) |
| 5 | 0.0613044398... (**6.1304%**) |

### 3. Cumulative Operating Distributions

| Through Year | Cumulative Operating Distributions |
|---|---|
| 1 | 250,000.000 |
| 2 | 518,000.000 |
| 3 | 718,028.4314312598 |
| 4 | 937,153.0628625196 |
| 5 | 1,175,946.7802937794 |

### 4. Debt Yield

```
Year 1 Debt Yield = 600,000 / 6,000,000 = 0.10  (10.0000%)
```

Annual debt-yield schedule (Years 2–5): **deferred** per Section 4 of the
conventions doc — no per-year beginning loan balance is exposed by the
current `DebtSchedule` contract.

---

## Case 2: Quick golden case (Phase 2 golden case)

Source: `tests/test_engine_golden_case.py::make_golden_inputs`. Chosen
specifically because it has **no** transaction costs, **no** CapEx, and
**no** IO period — a useful complement to Case 1, and a direct exercise of
"neutral defaults reduce to the simple formula" for every metric.

### Inputs

```
purchase_price = 50,000,000     current_noi = 2,500,000     occupancy = 0.95
noi_growth     = 0.03           hold_period = 5              exit_cap_rate = 0.055
ltv            = 0.65           interest_rate = 0.0525        amortization = 30
(acquisition_cost_pct, financing_fee_pct, disposition_cost_pct, annual_capex_reserve, io_period: all defaulted to 0)
```

### Authoritative upstream values (from the existing test file, restated)

```
loan_amount    = 32,500,000.0
initial_equity = 17,500,000.0
acquisition_costs = 0.0   (basis = purchase_price + 0 = 50,000,000.0)

NOI:  Y1 2,500,000.000       Y2 2,575,000.000       Y3 2,652,250.000
      Y4 2,731,817.500       Y5 2,813,772.0250000004
CapEx: 0.0 in every year
ADS:  2,153,594.438353404 in every year (fully amortizing from Year 1 — no IO period)
```

### Recurring Levered Cash Flow / Levered Cash-on-Cash Return

| Year | Recurring Levered CF (`NOI_y - 0 - ADS_y`) | Levered CoC (`/ 17,500,000`) |
|---|---|---|
| 1 | 346,405.561647 | 0.0197946035... (**1.9795%**) |
| 2 | 421,405.561647 | 0.0240803178... (**2.4080%**) |
| 3 | 498,655.561647 | 0.0284946035... (**2.8495%**) |
| 4 | 578,223.061647 | 0.0330413178... (**3.3041%**) |
| 5 | 660,177.586647 | 0.0377244335... (**3.7724%**) |

### Recurring Unlevered Cash Flow / Unlevered Cash Yield

| Year | Recurring Unlevered CF (`NOI_y - 0`) | Unlevered Cash Yield (`/ 50,000,000`) |
|---|---|---|
| 1 | 2,500,000.000 | 0.05000000 (**5.0000%**) |
| 2 | 2,575,000.000 | 0.05150000 (**5.1500%**) |
| 3 | 2,652,250.000 | 0.05304500 (**5.3045%**) |
| 4 | 2,731,817.500 | 0.05463635 (**5.4636%**) |
| 5 | 2,813,772.025 | 0.05627544 (**5.6275%**) |

Note Year 1 Unlevered Cash Yield (`5.0000%`) exactly equals the golden
case's `going_in_cap_rate` (`0.05`, restated from
`tests/test_engine_golden_case.py::test_golden_case_going_in_cap_rate`) —
expected, since with zero CapEx and zero acquisition costs, Year 1
Unlevered Cash Yield reduces exactly to `NOI_1 / purchase_price`, the
going-in cap rate formula. This is a useful implementation-time sanity
check for the neutral-defaults path, not a general identity (it does not
hold once `acquisition_cost_pct` or `annual_capex_reserve` is nonzero, as
Case 1 shows).

### Cumulative Operating Distributions

| Through Year | Cumulative Operating Distributions |
|---|---|
| 1 | 346,405.561647 |
| 2 | 767,811.123293 |
| 3 | 1,266,466.684940 |
| 4 | 1,844,689.746586 |
| 5 | 2,504,867.333233 |

### Debt Yield

```
Year 1 Debt Yield = 2,500,000 / 32,500,000 = 0.0769230769... (7.6923%)
```

---

## Edge-case matrix (Sprint A charter Section 10)

| Edge case | Where it's specified | Behavior |
|---|---|---|
| All-cash acquisition (`ltv = 0`) | Conventions §1 | `ADS_y = 0`, `financing_fee = 0`; `Levered CoC_y == Unlevered Cash Yield_y` for every year (denominators coincide) |
| `initial_equity = 0` | Conventions §1, §8 | `Levered CoC_y = None` (reachable at `ltv = 1.0`, zero transaction costs) |
| `loan_amount = 0` | Conventions §4, §8 | `Year 1 Debt Yield = None` |
| Negative recurring levered cash flow | Conventions §1 | Reported as negative; never floored |
| Negative recurring unlevered cash flow | Conventions §2 | Reported as negative; never floored (only when `CapEx_y > NOI_y`) |
| Zero CapEx (explicit) | Conventions §1, §2 | No special case — `capex_by_year` all-zero flows through unchanged |
| IO period | Conventions, "Shared building block" | No special case — `annual_debt_service` already reflects IO-period payments |
| No IO period (`io_period = 0`) | Case 2 above | No special case — exercised directly by the Quick golden case |
| One-year hold (`hold_period = 1`) | Conventions, "Shared building block" | No special case — the recurring formula never branches on `y == H`, so Year 1 is simultaneously the only year and the final year with no code path difference |
| Final-year sale proceeds excluded from annual CoC | Conventions, "Shared building block" | Verified above: Case 1 Year 5 Levered CoC uses `238,793.72`, not `levered_cash_flows[5]` |
| Transaction costs | Conventions §1, §2 | `acquisition_costs` included in both Initial Equity and Unlevered Basis; `financing_fee` included in Initial Equity only |
| Financing fee treatment | Conventions §2 | Excluded from Unlevered Basis (debt-related); included in Initial Equity (equity-funded) |
| Explicit zero values | throughout | No metric here divides by an operating-flow value, only by fixed denominators (`initial_equity`, basis, `loan_amount`) — those are the only zero-guarded cases |
| Rounding/display vs. internal precision | Conventions §9 | Full `float` precision internally; rounding is presentation-layer only |
