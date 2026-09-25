"""RAROC engine: account-level profitability, relationship roll-up and portfolio summary.

RAROC = (Revenue - Opex - Expected Loss + Capital Credit) x (1 - tax) / Capital
EVA   = Net Income - Hurdle x Capital

Capital is economic capital, Basel III regulatory capital, or the higher of the two
(`ModelSettings.capital_basis`). Every account also carries both measures, RWA, TTC and
point-in-time PD, one-year and lifetime expected loss.
"""

from __future__ import annotations

from statistics import NormalDist

import numpy as np
import pandas as pd

from . import config as C
from .config import DEFAULT_SETTINGS, ModelSettings

_N = NormalDist()
_inv = np.vectorize(_N.inv_cdf)
_cdf = np.vectorize(_N.cdf)

RESULT_COLS = [
    "account_id", "relationship_id", "product", "sub_type", "exposure", "ead",
    "pd_ttc", "pd_pit", "lgd", "nii", "fee_revenue", "total_revenue", "opex",
    "expected_loss", "el_lifetime", "credit_capital", "op_capital", "economic_capital",
    "rwa", "reg_capital", "capital", "net_income", "raroc", "eva", "all_in_rate",
]


def curve_rate(curve: dict, tenor: float | np.ndarray) -> np.ndarray:
    """Linear interpolation on a rate curve {tenor_years: rate}, flat beyond the ends."""
    xs, ys = zip(*sorted(curve.items()), strict=True)
    return np.interp(np.asarray(tenor, dtype=float), xs, ys)


def liquidity_premium(tenor: float | np.ndarray) -> np.ndarray:
    return curve_rate(C.LIQUIDITY_PREMIUM_CURVE, tenor)


def ftp_rate(tenor: float | np.ndarray) -> np.ndarray:
    """Matched-maturity funds transfer price = SOFR curve + term liquidity premium."""
    return curve_rate(C.SOFR_CURVE, tenor) + liquidity_premium(tenor)


def all_in_rate(df: pd.DataFrame) -> np.ndarray:
    """Client coupon: floating = 1M Term SOFR + spread; fixed = SOFR swap (original tenor) + spread."""
    index = np.where(df.get("rate_type", "Floating") == "Fixed",
                     curve_rate(C.SOFR_CURVE, df.tenor_yrs),
                     curve_rate(C.SOFR_CURVE, C.FLOATING_INDEX_TENOR))
    return index + df.spread


def asset_correlation(pd_: np.ndarray) -> np.ndarray:
    """Basel corporate asset correlation, 12%-24% decreasing in PD."""
    w = (1 - np.exp(-50 * pd_)) / (1 - np.exp(-50))
    return 0.12 * w + 0.24 * (1 - w)


def irb_capital_k(pd_: np.ndarray, lgd: np.ndarray, maturity: np.ndarray,
                  confidence: float = C.CAPITAL.confidence, max_maturity: float = 5.0) -> np.ndarray:
    """Basel IRB corporate capital requirement K per unit of EAD (maturity capped at 5y by Basel)."""
    pd_ = np.clip(np.asarray(pd_, dtype=float), 0.0003, 0.9999)
    lgd = np.asarray(lgd, dtype=float)
    m = np.clip(np.asarray(maturity, dtype=float), 1.0, max_maturity)
    r = asset_correlation(pd_)
    b = (0.11852 - 0.05478 * np.log(pd_)) ** 2
    cond_pd = _cdf((_inv(pd_) + np.sqrt(r) * _N.inv_cdf(confidence)) / np.sqrt(1 - r))
    return lgd * (cond_pd - pd_) * (1 + (m - 2.5) * b) / (1 - 1.5 * b)


def pit_pd(pd_ttc: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Single-factor Z-shift, TTC -> point-in-time PD: N(N^-1(PD_TTC) - sqrt(rho) * Z).

    Z = 0 reproduces the long-run (TTC) PD; Z < 0 is a downturn (higher PD), Z > 0 a benign year.
    """
    pd_ = np.clip(np.asarray(pd_ttc, dtype=float), 1e-6, 0.9999)
    rho = asset_correlation(pd_)
    return _cdf(_inv(pd_) - np.sqrt(rho) * np.asarray(z, dtype=float))


def maturity_bucket(m: np.ndarray) -> np.ndarray:
    buckets = np.array(C.ECAP_MATURITY_BUCKETS, dtype=float)
    idx = np.searchsorted(buckets, np.asarray(m, dtype=float), side="left")
    return buckets[np.clip(idx, 0, len(buckets) - 1)]


def ecap_factor(pd_: np.ndarray, maturity: np.ndarray, industry: pd.Series) -> np.ndarray:
    """Economic capital per $1 of EAD at 100% LGD, from the calibrated factor table."""
    k = irb_capital_k(pd_, 1.0, maturity_bucket(maturity), C.ECAP_FACTOR_CONFIDENCE, C.ECAP_MAX_MATURITY)
    mult = industry.map(C.ECAP_INDUSTRY_MULTIPLIER).fillna(1.0).to_numpy()
    return k * C.ECAP_DIVERSIFICATION * mult


def ecap_factor_table() -> pd.DataFrame:
    """The factor table itself (rating x maturity bucket, 100% LGD, no industry add-on)."""
    rows = []
    for rating, pd_ in C.PD_BY_RATING.items():
        for m in C.ECAP_MATURITY_BUCKETS:
            k = irb_capital_k([pd_], 1.0, [m], C.ECAP_FACTOR_CONFIDENCE, C.ECAP_MAX_MATURITY)[0]
            rows.append({"rating": rating, "pd": pd_, "maturity_bucket": m,
                         "factor": k * C.ECAP_DIVERSIFICATION})
    return pd.DataFrame(rows).pivot(index="rating", columns="maturity_bucket", values="factor")


def _industry(df: pd.DataFrame) -> pd.Series:
    return df["industry"] if "industry" in df else pd.Series("", index=df.index)


def _credit(df: pd.DataFrame, s: ModelSettings, ead: pd.Series, ead_sa: pd.Series, lgd: pd.Series,
            maturity: pd.Series, collateral: pd.Series, sa_rw: pd.Series) -> pd.DataFrame:
    """Expected loss, economic capital and Basel credit RWA for credit exposures."""
    industry = _industry(df)
    pd_ttc = df.rating.map(C.PD_BY_RATING)
    z = industry.map(C.CREDIT_CYCLE_Z).fillna(0.0) + s.cycle_shift
    pd_p = pd.Series(pit_pd(pd_ttc, z), index=df.index)
    pd_el = pd_p if s.el_pd_basis == "PIT" else pd_ttc
    df["ead"], df["pd_ttc"], df["pd_pit"], df["lgd"] = ead, pd_ttc, pd_p, lgd
    df["expected_loss"] = pd_el * lgd * ead
    life = np.maximum(maturity, 1.0)
    df["el_lifetime"] = (1 - (1 - pd_p) ** life) * lgd * ead  # CECL-style, PIT PD, undiscounted

    if s.ecap_method == "factor":
        k_ec = ecap_factor(pd_ttc, maturity, industry) * lgd
    else:
        k_ec = irb_capital_k(pd_ttc, lgd, maturity) * C.CAPITAL.ec_multiplier
    df["credit_capital"] = k_ec * ead

    rwa_sa = sa_rw * ead_sa
    pd_reg = np.maximum(pd_ttc, C.IRB_PD_FLOOR)
    if s.basel_approach == "SA":
        rwa = rwa_sa
    elif s.basel_approach == "FIRB":
        rwa = irb_capital_k(pd_reg, collateral.map(C.FIRB_LGD), C.FIRB_MATURITY) * 12.5 * ead_sa
    else:  # AIRB: own LGD (downturn), own maturity, own CCF
        a, b = C.DOWNTURN_LGD
        lgd_dt = np.maximum(a + b * lgd, collateral.map(C.AIRB_LGD_FLOOR))
        rwa = irb_capital_k(pd_reg, lgd_dt, maturity) * 12.5 * ead
    if s.output_floor and s.basel_approach != "SA":
        rwa = np.maximum(rwa, C.OUTPUT_FLOOR * rwa_sa)  # applied account by account (conservative)
    df["credit_rwa"] = rwa
    return df


def _no_credit(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("pd_ttc", "pd_pit", "lgd"):
        df[col] = np.nan
    df["ead"] = df["expected_loss"] = df["el_lifetime"] = 0.0
    df["credit_capital"] = df["credit_rwa"] = 0.0
    return df


def _finish(df: pd.DataFrame, s: ModelSettings) -> pd.DataFrame:
    cap = C.CAPITAL
    df["total_revenue"] = df.nii + df.fee_revenue
    rev_pos = df.total_revenue.clip(lower=0)
    df["op_capital"] = df.get("op_capital", 0.0) + cap.op_risk_pct_revenue * rev_pos
    df["economic_capital"] = df.credit_capital + df.op_capital
    df["rwa"] = df.credit_rwa + 12.5 * C.SMA_BIC_RATE * rev_pos
    df["reg_capital"] = df.rwa * s.cet1_target
    df["capital"] = {"economic": df.economic_capital, "regulatory": df.reg_capital,
                     "max": np.maximum(df.economic_capital, df.reg_capital)}[s.capital_basis]
    pre_tax = df.total_revenue - df.opex - df.expected_loss + cap.capital_credit_rate * df.capital
    df["net_income"] = pre_tax * (1 - cap.tax_rate)
    df["raroc"] = df.net_income / df.capital.replace(0, np.nan)
    df["eva"] = df.net_income - cap.hurdle_rate * df.capital
    if "all_in_rate" not in df:
        df["all_in_rate"] = np.nan
    return df[RESULT_COLS]


def _sa_rw(df: pd.DataFrame) -> pd.Series:
    rw = df.rating.map(C.SA_CORPORATE_RW)
    if "sub_type" in df:
        rw = rw.where(df.sub_type != "CRE Term", C.SA_CRE_RW)
    return rw


def loans_raroc(loans: pd.DataFrame, s: ModelSettings = DEFAULT_SETTINGS) -> pd.DataFrame:
    df = loans.copy()
    lp = liquidity_premium(df.remaining_yrs)  # coupon - FTP = spread - term liquidity premium
    df["all_in_rate"] = all_in_rate(df)
    df["exposure"] = df.balance
    df["nii"] = df.balance * (df.spread - lp)
    df["fee_revenue"] = df.balance * df.orig_fee_pct / df.tenor_yrs
    df["opex"] = df.commitment * C.COSTS.loan_opex_bps
    df = _credit(df, s, df.balance, df.balance, df.collateral.map(C.LGD_BY_COLLATERAL),
                 df.remaining_yrs, df.collateral, _sa_rw(df))
    return _finish(df, s)


def revolvers_raroc(rev: pd.DataFrame, s: ModelSettings = DEFAULT_SETTINGS) -> pd.DataFrame:
    df = rev.copy()
    undrawn = df.commitment - df.balance
    df["exposure"] = df.commitment
    df["all_in_rate"] = all_in_rate(df)
    df["nii"] = df.balance * (df.spread - C.COSTS.loan_liquidity_premium * C.REVOLVER_DRAWN_LP_FACTOR) \
        - undrawn * C.COSTS.revolver_liquidity_premium * C.REVOLVER_UNDRAWN_LP_FACTOR
    df["fee_revenue"] = undrawn * df.unused_fee + df.commitment * df.orig_fee_pct / df.tenor_yrs
    df["opex"] = df.commitment * C.COSTS.revolver_opex_bps
    ead = df.balance + C.REVOLVER_CCF * undrawn
    ead_sa = df.balance + C.SA_COMMITMENT_CCF * undrawn
    df = _credit(df, s, ead, ead_sa, df.collateral.map(C.LGD_BY_COLLATERAL), df.remaining_yrs,
                 df.collateral, _sa_rw(df))
    return _finish(df, s)


def irds_raroc(irds: pd.DataFrame, s: ModelSettings = DEFAULT_SETTINGS) -> pd.DataFrame:
    df = irds.copy()
    addon = np.select([df.remaining_yrs <= t for t, _ in C.IRD_ADDON_BY_TENOR],
                      [f for _, f in C.IRD_ADDON_BY_TENOR])
    ead = C.SA_CCR_ALPHA * (df.mtm.clip(lower=0) + addon * df.notional)
    df["exposure"] = df.notional
    df["nii"] = 0.0
    df["fee_revenue"] = df.notional * df.sales_credit_bps / 10_000  # annualised sales credit
    df["opex"] = C.COSTS.ird_opex_per_trade
    unsecured = pd.Series("Unsecured", index=df.index)
    df = _credit(df, s, ead, ead, pd.Series(C.IRD_LGD, index=df.index), df.remaining_yrs,
                 unsecured, df.rating.map(C.SA_CORPORATE_RW))
    df["credit_capital"] *= C.CVA_MULTIPLIER
    df["credit_rwa"] *= C.CVA_MULTIPLIER
    return _finish(df, s)


def deposits_raroc(dep: pd.DataFrame, s: ModelSettings = DEFAULT_SETTINGS) -> pd.DataFrame:
    df = dep.copy()
    duration = df.deposit_type.map(C.DEPOSIT_DURATION).fillna(df.tenor_yrs)
    haircut = df.deposit_type.map(C.COSTS.deposit_runoff_haircut)
    ftp_credit = ftp_rate(duration) * (1 - haircut) + haircut * ftp_rate(0.25) * C.VOLATILE_FTP_SHARE
    df["ftp_credit"] = ftp_credit
    df["exposure"] = df.balance
    df["nii"] = df.balance * (ftp_credit - df.rate_paid)
    df["fee_revenue"] = 0.0
    df["opex"] = df.balance * C.COSTS.deposit_opex_bps
    df = _no_credit(df)
    df["op_capital"] = df.balance * C.CAPITAL.deposit_op_capital_pct
    return _finish(df, s)


def payments_raroc(pay: pd.DataFrame, s: ModelSettings = DEFAULT_SETTINGS) -> pd.DataFrame:
    df = pay.copy()
    gross = df.monthly_revenue * 12
    df["exposure"] = gross
    df["nii"] = 0.0
    df["fee_revenue"] = gross * (1 - df.ecr_offset_pct)  # ECR waives part of analysed fees
    df["opex"] = gross * C.COSTS.payments_cost_to_income
    df = _no_credit(df)
    df["expected_loss"] = gross * C.PAYMENTS_LOSS_RATE
    return _finish(df, s)


def with_industry(df: pd.DataFrame, rels: pd.DataFrame) -> pd.DataFrame:
    return df.merge(rels[["relationship_id", "industry"]], on="relationship_id", how="left")


def account_raroc(book: dict[str, pd.DataFrame], s: ModelSettings = DEFAULT_SETTINGS) -> pd.DataFrame:
    s.validate()
    rels = book["relationships"]
    parts = [loans_raroc(with_industry(book["loans"], rels), s),
             revolvers_raroc(with_industry(book["revolvers"], rels), s),
             irds_raroc(with_industry(book["irds"], rels), s),
             deposits_raroc(book["deposits"], s), payments_raroc(book["payments"], s)]
    return pd.concat(parts, ignore_index=True)


LENDING = {"Term Loan", "Revolver", "Interest Rate Derivative"}
_SUM = ["total_revenue", "opex", "expected_loss", "el_lifetime", "economic_capital", "rwa",
        "reg_capital", "capital", "net_income", "eva"]


def _ratio(g: pd.DataFrame) -> pd.Series:
    out = g[_SUM].sum()
    out["raroc"] = out.net_income / out.capital if out.capital else np.nan
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
        .join(full).join(lend[["raroc", "net_income", "capital"]]
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


def run(book: dict[str, pd.DataFrame], s: ModelSettings = DEFAULT_SETTINGS) -> dict[str, pd.DataFrame]:
    accounts = account_raroc(book, s)
    return {"accounts": accounts,
            "relationships": relationship_raroc(accounts, book["relationships"]),
            "products": product_summary(accounts)}
