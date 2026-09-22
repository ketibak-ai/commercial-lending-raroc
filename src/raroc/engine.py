"""RAROC engine: account-level profitability, relationship roll-up and portfolio summary.

RAROC = (Revenue - Opex - Expected Loss + Capital Credit) x (1 - tax) / Economic Capital
EVA   = Net Income - Hurdle x Economic Capital
"""

from __future__ import annotations

from statistics import NormalDist

import numpy as np
import pandas as pd

from . import config as C

_N = NormalDist()
RESULT_COLS = [
    "account_id", "relationship_id", "product", "sub_type", "exposure", "ead",
    "nii", "fee_revenue", "total_revenue", "opex", "expected_loss",
    "credit_capital", "op_capital", "economic_capital", "net_income", "raroc", "eva",
]


def ftp_rate(tenor: float | np.ndarray) -> np.ndarray:
    """Linear interpolation on the matched-maturity FTP curve."""
    xs, ys = zip(*sorted(C.FTP_CURVE.items()), strict=True)
    return np.interp(np.asarray(tenor, dtype=float), xs, ys)


def irb_capital_k(pd_: np.ndarray, lgd: np.ndarray, maturity: np.ndarray) -> np.ndarray:
    """Basel IRB corporate capital requirement K per unit of EAD."""
    pd_ = np.clip(np.asarray(pd_, dtype=float), 0.0003, 0.9999)
    lgd = np.asarray(lgd, dtype=float)
    m = np.clip(np.asarray(maturity, dtype=float), 1.0, 5.0)
    w = (1 - np.exp(-50 * pd_)) / (1 - np.exp(-50))
    r = 0.12 * w + 0.24 * (1 - w)
    b = (0.11852 - 0.05478 * np.log(pd_)) ** 2
    inv = np.vectorize(_N.inv_cdf)
    cdf = np.vectorize(_N.cdf)
    cond_pd = cdf((inv(pd_) + np.sqrt(r) * _N.inv_cdf(C.CAPITAL.confidence)) / np.sqrt(1 - r))
    return lgd * (cond_pd - pd_) * (1 + (m - 2.5) * b) / (1 - 1.5 * b)


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    cap = C.CAPITAL
    df["total_revenue"] = df.nii + df.fee_revenue
    df["op_capital"] = df.get("op_capital", 0.0) + cap.op_risk_pct_revenue * df.total_revenue.clip(lower=0)
    df["economic_capital"] = df.credit_capital + df.op_capital
    pre_tax = df.total_revenue - df.opex - df.expected_loss + cap.capital_credit_rate * df.economic_capital
    df["net_income"] = pre_tax * (1 - cap.tax_rate)
    df["raroc"] = df.net_income / df.economic_capital.replace(0, np.nan)
    df["eva"] = df.net_income - cap.hurdle_rate * df.economic_capital
    return df[RESULT_COLS]


def _credit(df: pd.DataFrame, ead: pd.Series, lgd: pd.Series, maturity: pd.Series) -> pd.DataFrame:
    pd_ = df.rating.map(C.PD_BY_RATING)
    df["ead"] = ead
    df["expected_loss"] = pd_ * lgd * ead
    df["credit_capital"] = irb_capital_k(pd_, lgd, maturity) * ead * C.CAPITAL.ec_multiplier
    return df


def loans_raroc(loans: pd.DataFrame) -> pd.DataFrame:
    df = loans.copy()
    lp = C.COSTS.loan_liquidity_premium * np.minimum(df.remaining_yrs, 5) / 5
    df["exposure"] = df.balance
    df["nii"] = df.balance * (df.spread - lp)
    df["fee_revenue"] = df.balance * df.orig_fee_pct / df.tenor_yrs
    df["opex"] = df.commitment * C.COSTS.loan_opex_bps
    df = _credit(df, df.balance, df.collateral.map(C.LGD_BY_COLLATERAL), df.remaining_yrs)
    return _finish(df)


def revolvers_raroc(rev: pd.DataFrame) -> pd.DataFrame:
    df = rev.copy()
    undrawn = df.commitment - df.balance
    df["exposure"] = df.commitment
    df["nii"] = df.balance * (df.spread - C.COSTS.loan_liquidity_premium * 0.5) \
        - undrawn * C.COSTS.revolver_liquidity_premium * 0.25
    df["fee_revenue"] = undrawn * df.unused_fee + df.commitment * df.orig_fee_pct / df.tenor_yrs
    df["opex"] = df.commitment * C.COSTS.revolver_opex_bps
    ead = df.balance + C.REVOLVER_CCF * undrawn
    df = _credit(df, ead, df.collateral.map(C.LGD_BY_COLLATERAL), df.remaining_yrs)
    return _finish(df)


def irds_raroc(irds: pd.DataFrame) -> pd.DataFrame:
    df = irds.copy()
    addon = np.select([df.remaining_yrs <= t for t, _ in C.IRD_ADDON_BY_TENOR],
                      [f for _, f in C.IRD_ADDON_BY_TENOR])
    ead = C.SA_CCR_ALPHA * (df.mtm.clip(lower=0) + addon * df.notional)
    df["exposure"] = df.notional
    df["nii"] = 0.0
    df["fee_revenue"] = df.notional * df.sales_credit_bps / 10_000  # annualised sales credit
    df["opex"] = C.COSTS.ird_opex_per_trade
    df = _credit(df, ead, pd.Series(0.40, index=df.index), df.remaining_yrs)
    df["credit_capital"] *= 1.25  # CVA capital add-on
    return _finish(df)


def deposits_raroc(dep: pd.DataFrame) -> pd.DataFrame:
    df = dep.copy()
    duration = df.deposit_type.map({"Operating": 3.0, "Non-Operating": 0.5}).fillna(df.tenor_yrs)
    haircut = df.deposit_type.map(C.COSTS.deposit_runoff_haircut)
    ftp_credit = ftp_rate(duration) * (1 - haircut) + haircut * ftp_rate(0.25) * 0.85
    df["ftp_credit"] = ftp_credit
    df["exposure"] = df.balance
    df["ead"] = 0.0
    df["nii"] = df.balance * (ftp_credit - df.rate_paid)
    df["fee_revenue"] = 0.0
    df["opex"] = df.balance * C.COSTS.deposit_opex_bps
    df["expected_loss"] = 0.0
    df["credit_capital"] = 0.0
    df["op_capital"] = df.balance * C.CAPITAL.deposit_op_capital_pct
    return _finish(df)


def payments_raroc(pay: pd.DataFrame) -> pd.DataFrame:
    df = pay.copy()
    gross = df.monthly_revenue * 12
    df["exposure"] = gross
    df["ead"] = 0.0
    df["nii"] = 0.0
    df["fee_revenue"] = gross * (1 - df.ecr_offset_pct)  # ECR waives part of analysed fees
    df["opex"] = gross * C.COSTS.payments_cost_to_income
    df["expected_loss"] = gross * 0.005  # fraud / operational losses
    df["credit_capital"] = 0.0
    return _finish(df)


def account_raroc(book: dict[str, pd.DataFrame]) -> pd.DataFrame:
    parts = [loans_raroc(book["loans"]), revolvers_raroc(book["revolvers"]),
             irds_raroc(book["irds"]), deposits_raroc(book["deposits"]),
             payments_raroc(book["payments"])]
    return pd.concat(parts, ignore_index=True)


LENDING = {"Term Loan", "Revolver", "Interest Rate Derivative"}
_SUM = ["total_revenue", "opex", "expected_loss", "economic_capital", "net_income", "eva"]


def _ratio(g: pd.DataFrame) -> pd.Series:
    out = g[_SUM].sum()
    out["raroc"] = out.net_income / out.economic_capital if out.economic_capital else np.nan
    return out


def relationship_raroc(accounts: pd.DataFrame, rels: pd.DataFrame) -> pd.DataFrame:
    """Full relationship RAROC vs. credit-only RAROC, with per-product balances."""
    full = accounts.groupby("relationship_id").apply(_ratio, include_groups=False)
    lend = accounts[accounts["product"].isin(LENDING)].groupby("relationship_id") \
        .apply(_ratio, include_groups=False)
    counts = accounts.pivot_table(index="relationship_id", columns="product",
                                  values="account_id", aggfunc="count", fill_value=0)
    counts.columns = [f"n_{c.lower().replace(' ', '_')}" for c in counts.columns]
    expo = accounts.pivot_table(index="relationship_id", columns="product",
                                values="exposure", aggfunc="sum", fill_value=0)
    expo.columns = [f"exp_{c.lower().replace(' ', '_')}" for c in expo.columns]
    out = rels.set_index("relationship_id")[["name", "industry", "segment", "rating"]] \
        .join(full).join(lend[["raroc", "net_income", "economic_capital"]]
                         .add_prefix("lending_")).join(counts).join(expo).fillna(0)
    out["ancillary_uplift"] = out.raroc - out.lending_raroc
    out["meets_hurdle"] = out.raroc >= C.CAPITAL.hurdle_rate
    return out.reset_index().sort_values("eva", ascending=False)


def product_summary(accounts: pd.DataFrame) -> pd.DataFrame:
    g = accounts.groupby("product")
    out = g.apply(_ratio, include_groups=False)
    out.insert(0, "accounts", g.size())
    out.insert(1, "exposure", g.exposure.sum())
    total = _ratio(accounts)
    total["accounts"], total["exposure"] = len(accounts), np.nan
    out.loc["Total Portfolio"] = total
    return out.reset_index()


def run(book: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    accounts = account_raroc(book)
    return {"accounts": accounts,
            "relationships": relationship_raroc(accounts, book["relationships"]),
            "products": product_summary(accounts)}
