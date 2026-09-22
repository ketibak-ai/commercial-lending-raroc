"""Portfolio assumptions: FTP curve, risk parameters, capital and cost settings.

All figures are illustrative and synthetic. Rates are decimals (0.04 = 4%).
"""

from dataclasses import dataclass, field

AS_OF_DATE = "2026-09-30"
SEED = 42

# Account counts requested for the simulation
N_TERM_LOANS = 1000
N_REVOLVERS = 2000
N_IRDS = 20
N_DEPOSITS = 2000
N_PAYMENTS = 2000
N_KEY_RELATIONSHIPS = 10
N_OTHER_RELATIONSHIPS = 490

# Funds transfer pricing curve (tenor in years -> matched-maturity rate)
FTP_CURVE = {
    0.25: 0.0410,
    1.0: 0.0385,
    2.0: 0.0370,
    3.0: 0.0365,
    5.0: 0.0370,
    7.0: 0.0380,
    10.0: 0.0395,
}
SOFR = 0.0420

# Internal risk rating 1 (best) .. 10 (worst) -> one-year probability of default
PD_BY_RATING = {
    1: 0.0003, 2: 0.0006, 3: 0.0012, 4: 0.0025, 5: 0.0050,
    6: 0.0090, 7: 0.0160, 8: 0.0300, 9: 0.0700, 10: 0.1500,
}

LGD_BY_COLLATERAL = {
    "Senior Secured": 0.30,
    "Real Estate": 0.35,
    "Unsecured": 0.45,
}

REVOLVER_CCF = 0.75          # credit conversion factor on undrawn commitments
IRD_ADDON_BY_TENOR = [(1, 0.005), (5, 0.015), (99, 0.030)]  # simplified SA-CCR add-on
SA_CCR_ALPHA = 1.4


@dataclass(frozen=True)
class CapitalAssumptions:
    hurdle_rate: float = 0.12           # RAROC hurdle (cost of equity)
    tax_rate: float = 0.24
    capital_credit_rate: float = 0.0385  # return credited on allocated equity (1y FTP)
    confidence: float = 0.999            # IRB confidence level
    ec_multiplier: float = 1.06          # economic capital scaler over regulatory K
    op_risk_pct_revenue: float = 0.15    # basic-indicator op-risk capital
    deposit_op_capital_pct: float = 0.004  # op/ALM capital on deposit balances


@dataclass(frozen=True)
class CostAssumptions:
    loan_opex_bps: float = 0.0045       # annual opex as % of committed amount
    revolver_opex_bps: float = 0.0035
    ird_opex_per_trade: float = 25_000
    deposit_opex_bps: float = 0.0015
    payments_cost_to_income: float = 0.55
    loan_liquidity_premium: float = 0.0025
    revolver_liquidity_premium: float = 0.0040  # contingent liquidity on undrawn
    deposit_runoff_haircut: dict = field(default_factory=lambda: {
        "Operating": 0.25, "Non-Operating": 0.40, "Time Deposit": 0.10,
    })


CAPITAL = CapitalAssumptions()
COSTS = CostAssumptions()
