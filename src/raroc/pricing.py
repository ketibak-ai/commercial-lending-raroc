"""Deal pricing: solve for the loan spread that hits a RAROC hurdle.

Two answers are produced for every new deal:
  * standalone floor     - spread at which the deal alone earns the hurdle RAROC
  * relationship floor   - spread at which the whole relationship (existing accounts +
                           new deal) earns the hurdle, i.e. the lowest defensible price
                           once deposits, payments and hedging revenue are credited.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from . import config as C
from .engine import loans_raroc, revolvers_raroc

PRODUCTS = ("Term Loan", "Revolver")


@dataclass
class DealRequest:
    product: str = "Term Loan"
    amount: float = 10_000_000
    tenor_yrs: float = 5.0
    rating: int = 5
    collateral: str = "Senior Secured"
    orig_fee_pct: float = 0.005
    utilization: float = 0.5        # revolvers only
    unused_fee: float = 0.0025      # revolvers only
    relationship_id: str | None = None
    target_raroc: float = C.CAPITAL.hurdle_rate

    def validate(self) -> None:
        if self.product not in PRODUCTS:
            raise ValueError(f"product must be one of {PRODUCTS}")
        if not 1 <= int(self.rating) <= 10:
            raise ValueError("rating must be 1..10")
        if self.collateral not in C.LGD_BY_COLLATERAL:
            raise ValueError(f"collateral must be one of {list(C.LGD_BY_COLLATERAL)}")
        if not (0 < self.amount <= 5e9 and 0 < self.tenor_yrs <= 30):
            raise ValueError("amount must be in (0, 5bn] and tenor in (0, 30] years")
        if not 0 <= self.utilization <= 1:
            raise ValueError("utilization must be in [0, 1]")


def _deal_metrics(req: DealRequest, spread: float) -> pd.Series:
    row = {"account_id": "NEW", "relationship_id": req.relationship_id or "NEW",
           "product": req.product, "sub_type": "New Deal", "tenor_yrs": req.tenor_yrs,
           "remaining_yrs": req.tenor_yrs, "spread": spread, "rating": int(req.rating),
           "collateral": req.collateral, "orig_fee_pct": req.orig_fee_pct}
    if req.product == "Term Loan":
        row.update(balance=req.amount, commitment=req.amount)
        return loans_raroc(pd.DataFrame([row])).iloc[0]
    row.update(commitment=req.amount, balance=req.amount * req.utilization,
               unused_fee=req.unused_fee)
    return revolvers_raroc(pd.DataFrame([row])).iloc[0]


def _solve(eva_at, lo: float = -0.05, hi: float = 0.25, tol: float = 1e-7) -> float:
    """Bisection on spread; EVA is monotonic increasing in spread."""
    for _ in range(200):
        mid = (lo + hi) / 2
        if eva_at(mid) < 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return hi


def price_deal(req: DealRequest, accounts: pd.DataFrame | None = None) -> dict:
    req.validate()
    h = req.target_raroc
    cap = C.CAPITAL

    def deal_eva(s: float) -> float:
        m = _deal_metrics(req, s)
        return m.net_income - h * m.economic_capital

    standalone = _solve(deal_eva)
    result = {"request": asdict(req), "standalone_floor_spread": round(standalone, 5)}

    if req.relationship_id and accounts is not None:
        existing = accounts[accounts.relationship_id == req.relationship_id]
        if existing.empty:
            raise ValueError(f"unknown relationship_id {req.relationship_id}")
        ni, ec = existing.net_income.sum(), existing.economic_capital.sum()

        def rel_eva(s: float) -> float:
            m = _deal_metrics(req, s)
            return (ni + m.net_income) - h * (ec + m.economic_capital)

        # Floor at zero: if the relationship clears the hurdle at any positive spread,
        # the relationship constraint is not binding and the cost floor governs.
        rel_floor = _solve(rel_eva, lo=0.0)
        # Never price below the funding + liquidity + expected-loss break-even
        pd_ = C.PD_BY_RATING[int(req.rating)]
        el_rate = pd_ * C.LGD_BY_COLLATERAL[req.collateral]
        cost_floor = el_rate + C.COSTS.loan_liquidity_premium + C.COSTS.loan_opex_bps
        recommended = max(rel_floor, cost_floor)
        result.update({
            "relationship_raroc_before": round(ni / ec, 4) if ec else None,
            "relationship_floor_spread": round(rel_floor, 5),
            "relationship_floor_binding": rel_floor > cost_floor,
            "cost_floor_spread": round(cost_floor, 5),
            "recommended_spread": round(recommended, 5),
            "relationship_concession_bps": round((standalone - recommended) * 1e4, 1),
        })
    else:
        result["recommended_spread"] = round(standalone, 5)

    m = _deal_metrics(req, result["recommended_spread"])
    result["at_recommended"] = {
        "deal_raroc": round(float(m.raroc), 4),
        "annual_revenue": round(float(m.total_revenue), 2),
        "expected_loss": round(float(m.expected_loss), 2),
        "economic_capital": round(float(m.economic_capital), 2),
        "eva": round(float(m.eva), 2),
    }
    result["hurdle"] = h
    result["tax_rate"] = cap.tax_rate
    return result
