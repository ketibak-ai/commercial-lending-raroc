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

# ---- Rate curves (tenor in years -> rate). Illustrative levels as of AS_OF_DATE, not market data.
SOFR = 0.0420                      # overnight SOFR
SOFR_CURVE = {                     # <= 1y: CME Term SOFR style; >= 1y: SOFR OIS swap rates
    1 / 12: 0.041500,
    0.25: 0.040875,
    1.0: 0.038000,
    2.0: 0.036000,
    3.0: 0.035000,
    5.0: 0.034500,
    7.0: 0.035500,
    10.0: 0.037000,
}
LIQUIDITY_PREMIUM_CURVE = {        # bank term funding spread over SOFR: 5 bps per year, capped at 25 bps
    0.0: 0.0,
    5.0: 0.0025,
    10.0: 0.0025,
}
UST_CURVE = {                      # US Treasury par yields (reference; swap spread = SOFR swap - UST)
    0.25: 0.0418, 0.5: 0.0410, 1.0: 0.0392, 2.0: 0.0372, 3.0: 0.0366,
    5.0: 0.0368, 7.0: 0.0378, 10.0: 0.0392,
}
PRIME_RATE = 0.0750                # WSJ Prime style reference rate
FLOATING_INDEX_TENOR = 1 / 12      # floating loans reset on 1M Term SOFR


def _interp(curve: dict, t: float) -> float:
    xs = sorted(curve)
    if t <= xs[0]:
        return curve[xs[0]]
    for lo, hi in zip(xs, xs[1:], strict=False):
        if t <= hi:
            return curve[lo] + (t - lo) / (hi - lo) * (curve[hi] - curve[lo])
    return curve[xs[-1]]


# Funds transfer pricing = SOFR curve + term liquidity premium (matched maturity)
FTP_CURVE = {t: r + _interp(LIQUIDITY_PREMIUM_CURVE, t) for t, r in SOFR_CURVE.items()}

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
IRD_LGD = 0.40
CVA_MULTIPLIER = 1.25            # CVA capital add-on on derivative credit capital
PAYMENTS_LOSS_RATE = 0.005       # fraud / operational losses as % of gross fees
DEPOSIT_DURATION = {"Operating": 3.0, "Non-Operating": 0.5}  # CDs use contractual tenor
VOLATILE_FTP_SHARE = 0.85        # share of 3m FTP credited on the volatile deposit portion
REVOLVER_DRAWN_LP_FACTOR = 0.5   # drawn revolver balances carry half the term liquidity premium
REVOLVER_UNDRAWN_LP_FACTOR = 0.25  # contingent liquidity charge on undrawn commitments
WATCH_LIST_RAROC = 0.15          # key relationships below this go on the pricing watch list

# ---- Point-in-time (PIT) credit-cycle factors ---------------------------------------------
# Single-factor Z-shift: PD_PIT = N(N^-1(PD_TTC) - sqrt(rho) * Z), rho = Basel asset correlation.
# Z is the industry's credit-cycle index in standard deviations: 0 = long-run average,
# negative = worse than average (PD above TTC), positive = better.
CREDIT_CYCLE_Z = {
    "Energy": -0.60, "Commercial Real Estate": -0.50, "Retail": -0.30, "Construction": -0.30,
    "Transportation & Logistics": -0.20, "Agriculture": -0.10, "Industrial Manufacturing": 0.00,
    "Wholesale Trade": 0.00, "Food Distribution": 0.10, "Healthcare": 0.20,
    "Aerospace & Defense": 0.20, "Professional Services": 0.20, "Education": 0.20, "Technology": 0.30,
}

# ---- Economic capital factor tables ---------------------------------------------------------
ECAP_FACTOR_CONFIDENCE = 0.9995        # AA-target solvency standard used to calibrate factors
ECAP_MATURITY_BUCKETS = [1, 2, 3, 5, 7]  # remaining life rounded up to a bucket (years)
ECAP_MAX_MATURITY = 7.0                # economic model extends the maturity adjustment past 5y
ECAP_DIVERSIFICATION = 0.85            # portfolio diversification benefit on stand-alone factors
ECAP_INDUSTRY_MULTIPLIER = {           # concentration add-ons by industry
    "Commercial Real Estate": 1.15, "Energy": 1.20, "Construction": 1.10, "Retail": 1.05,
    "Technology": 0.95, "Healthcare": 0.95, "Education": 0.95,
}

# ---- Regulatory capital (Basel III) -----------------------------------------------------------
CET1_TARGET = 0.105                    # 4.5% minimum + 2.5% conservation buffer + 3.5% management buffer
OUTPUT_FLOOR = 0.725                   # Basel III final: IRB RWA >= 72.5% of standardized RWA
IRB_PD_FLOOR = 0.0005                  # Basel III final corporate PD floor (5 bps)
SA_COMMITMENT_CCF = 0.40               # standardized / F-IRB CCF on committed undrawn lines
SA_CORPORATE_RW = {                    # internal rating -> external-equivalent risk weight
    1: 0.20, 2: 0.50, 3: 0.50, 4: 0.75, 5: 0.75, 6: 1.00, 7: 1.00, 8: 1.50, 9: 1.50, 10: 1.50,
}
SA_CRE_RW = 1.00                       # income-producing real estate (no LTV split)
FIRB_LGD = {"Senior Secured": 0.25, "Real Estate": 0.20, "Unsecured": 0.40}
AIRB_LGD_FLOOR = {"Senior Secured": 0.15, "Real Estate": 0.10, "Unsecured": 0.25}
FIRB_MATURITY = 2.5
DOWNTURN_LGD = (0.08, 0.92)            # downturn LGD = a + b x expected LGD (A-IRB)
SMA_BIC_RATE = 0.12                    # op-risk business indicator component, bucket 1


@dataclass(frozen=True)
class ModelSettings:
    """Model choices. The defaults reproduce the original economic-capital RAROC exactly."""
    capital_basis: str = "economic"    # "economic" | "regulatory" | "max"
    basel_approach: str = "AIRB"       # "SA" | "FIRB" | "AIRB"
    output_floor: bool = False         # apply the 72.5% Basel III output floor to IRB RWA
    cet1_target: float = CET1_TARGET
    el_pd_basis: str = "TTC"           # "TTC" | "PIT": PD used for expected loss in RAROC
    ecap_method: str = "analytic"      # "analytic" (ASRF at 99.9%) | "factor" (calibrated table)
    cycle_shift: float = 0.0           # added to every industry's credit-cycle Z

    def validate(self) -> None:
        if self.capital_basis not in {"economic", "regulatory", "max"}:
            raise ValueError("capital_basis must be economic, regulatory or max")
        if self.basel_approach not in {"SA", "FIRB", "AIRB"}:
            raise ValueError("basel_approach must be SA, FIRB or AIRB")
        if self.el_pd_basis not in {"TTC", "PIT"}:
            raise ValueError("el_pd_basis must be TTC or PIT")
        if self.ecap_method not in {"analytic", "factor"}:
            raise ValueError("ecap_method must be analytic or factor")
        if not 0.04 <= self.cet1_target <= 0.30:
            raise ValueError("cet1_target must be between 4% and 30%")
        if not -3 <= self.cycle_shift <= 3:
            raise ValueError("cycle_shift must be between -3 and 3")


DEFAULT_SETTINGS = ModelSettings()


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
