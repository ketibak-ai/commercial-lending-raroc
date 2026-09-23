"""Write outputs: CSVs, an Excel workbook and the static web app (GitHub Pages)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

from . import config as C
from . import service
from .config import ModelSettings
from .engine import ecap_factor_table

ROOT = Path(__file__).resolve().parents[2]
WEB = Path(__file__).with_name("web")

SAMPLE_DEALS = [
    dict(product="Term Loan", amount=25e6, tenor_yrs=5, rating=4, collateral="Senior Secured",
         relationship_id="R004"),
    dict(product="Term Loan", amount=60e6, tenor_yrs=7, rating=5, collateral="Real Estate",
         relationship_id="R005"),
    dict(product="Revolver", amount=40e6, tenor_yrs=3, rating=7, collateral="Unsecured",
         relationship_id="R007", utilization=0.3),
    dict(product="Revolver", amount=30e6, tenor_yrs=3, rating=3, collateral="Senior Secured",
         relationship_id="R002", utilization=0.4),
    dict(product="Term Loan", amount=15e6, tenor_yrs=5, rating=6, collateral="Senior Secured",
         relationship_id="R008"),
]


def sample_pricing() -> list[dict]:
    names = service.portfolio()["relationships"].set_index("relationship_id").name
    out = []
    for d in SAMPLE_DEALS:
        r = service.price(**d)
        out.append({
            "relationship": names[d["relationship_id"]], "product": d["product"],
            "amount": d["amount"], "tenor_yrs": d["tenor_yrs"], "rating": d["rating"],
            "standalone_bps": round(r["standalone_floor_spread"] * 1e4),
            "relationship_bps": round(r["relationship_floor_spread"] * 1e4),
            "cost_floor_bps": round(r["cost_floor_spread"] * 1e4),
            "recommended_bps": round(r["recommended_spread"] * 1e4),
            "concession_bps": r["relationship_concession_bps"],
            "deal_raroc": r["at_recommended"]["deal_raroc"],
        })
    return out


EXPORT_FIELDS = {
    "relationships": ["relationship_id", "name", "industry", "segment", "rating"],
    "loans": ["account_id", "relationship_id", "sub_type", "balance", "commitment", "tenor_yrs",
              "remaining_yrs", "rate_type", "spread", "orig_fee_pct", "rating", "collateral"],
    "revolvers": ["account_id", "relationship_id", "sub_type", "commitment", "utilization", "balance",
                  "tenor_yrs", "remaining_yrs", "spread", "unused_fee", "orig_fee_pct", "rating",
                  "collateral"],
    "irds": ["account_id", "relationship_id", "sub_type", "notional", "tenor_yrs", "remaining_yrs",
             "mtm", "sales_credit_bps", "rating"],
    "deposits": ["account_id", "relationship_id", "sub_type", "deposit_type", "balance", "rate_paid",
                 "tenor_yrs"],
    "payments": ["account_id", "relationship_id", "sub_type", "monthly_volume", "unit_price",
                 "monthly_card_spend", "monthly_revenue", "ecr_offset_pct"],
}


def engine_config() -> dict:
    """Every assumption the browser engine needs, taken from config.py (single source of truth)."""
    cap, cost = C.CAPITAL, C.COSTS
    return {
        "hurdle": cap.hurdle_rate, "taxRate": cap.tax_rate,
        "capitalCreditRate": cap.capital_credit_rate, "confidence": cap.confidence,
        "ecMultiplier": cap.ec_multiplier, "opRiskPct": cap.op_risk_pct_revenue,
        "depositOpCapPct": cap.deposit_op_capital_pct,
        "ftpCurve": sorted(C.FTP_CURVE.items()), "sofr": C.SOFR,
        "pd": {str(k): v for k, v in C.PD_BY_RATING.items()}, "lgd": C.LGD_BY_COLLATERAL,
        "ccf": C.REVOLVER_CCF, "irdAddon": C.IRD_ADDON_BY_TENOR, "saccrAlpha": C.SA_CCR_ALPHA,
        "irdLgd": C.IRD_LGD, "cvaMultiplier": C.CVA_MULTIPLIER,
        "paymentsLossRate": C.PAYMENTS_LOSS_RATE, "depositDuration": C.DEPOSIT_DURATION,
        "volatileFtpShare": C.VOLATILE_FTP_SHARE,
        "revolverDrawnLpFactor": C.REVOLVER_DRAWN_LP_FACTOR,
        "revolverUndrawnLpFactor": C.REVOLVER_UNDRAWN_LP_FACTOR,
        "loanOpex": cost.loan_opex_bps, "revolverOpex": cost.revolver_opex_bps,
        "irdOpexPerTrade": cost.ird_opex_per_trade, "depositOpex": cost.deposit_opex_bps,
        "paymentsCostToIncome": cost.payments_cost_to_income,
        "loanLiquidityPremium": cost.loan_liquidity_premium,
        "revolverLiquidityPremium": cost.revolver_liquidity_premium,
        "runoff": cost.deposit_runoff_haircut, "watchList": C.WATCH_LIST_RAROC,
        # risk and capital models
        "cycleZ": C.CREDIT_CYCLE_Z, "ecapConfidence": C.ECAP_FACTOR_CONFIDENCE,
        "ecapBuckets": C.ECAP_MATURITY_BUCKETS, "ecapMaxMaturity": C.ECAP_MAX_MATURITY,
        "ecapDiversification": C.ECAP_DIVERSIFICATION, "ecapIndustryMult": C.ECAP_INDUSTRY_MULTIPLIER,
        "cet1Target": C.CET1_TARGET, "outputFloor": C.OUTPUT_FLOOR, "irbPdFloor": C.IRB_PD_FLOOR,
        "saCommitmentCcf": C.SA_COMMITMENT_CCF,
        "saCorporateRw": {str(k): v for k, v in C.SA_CORPORATE_RW.items()}, "saCreRw": C.SA_CRE_RW,
        "firbLgd": C.FIRB_LGD, "airbLgdFloor": C.AIRB_LGD_FLOOR, "firbMaturity": C.FIRB_MATURITY,
        "downturnLgd": C.DOWNTURN_LGD, "smaBicRate": C.SMA_BIC_RATE,
    }


def export_data() -> dict:
    """Account-level inputs + assumptions; the browser re-runs the engine on these."""
    p = service.portfolio()
    out = {"asOf": C.AS_OF_DATE, "config": engine_config()}
    for name, cols in EXPORT_FIELDS.items():
        out[name] = {"fields": cols, "rows": json.loads(p[name][cols].to_json(orient="values"))}
    return out


def build_site(site: Path) -> None:
    """Static web app for GitHub Pages: shell + engine + app code + data."""
    site.mkdir(parents=True, exist_ok=True)
    for f in ("index.html", "engine.js", "app.js"):
        shutil.copyfile(WEB / f, site / f)
    payload = json.dumps(export_data(), separators=(",", ":"))
    (site / "data.js").write_text(f"window.RAROC_DATA={payload};\n", encoding="utf-8")


def write_all(root: Path = ROOT) -> dict[str, Path]:
    p = service.portfolio()
    data_dir, rep_dir = root / "data", root / "reports"
    data_dir.mkdir(exist_ok=True)
    rep_dir.mkdir(exist_ok=True)
    for name in ["relationships", "loans", "revolvers", "irds", "deposits", "payments"]:
        p[name].to_csv(data_dir / f"{name}.csv", index=False)
    p["result_accounts"].to_csv(rep_dir / "account_raroc.csv", index=False)
    p["result_relationships"].to_csv(rep_dir / "relationship_raroc.csv", index=False)
    p["result_products"].to_csv(rep_dir / "product_raroc.csv", index=False)

    xlsx = rep_dir / "portfolio_raroc.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        p["result_products"].to_excel(xw, sheet_name="Product Summary", index=False)
        key = p["result_relationships"]
        key[key.segment == "Key Relationship"].to_excel(xw, sheet_name="Key Relationships", index=False)
        pd.DataFrame(sample_pricing()).to_excel(xw, sheet_name="Deal Pricing", index=False)
        key.to_excel(xw, sheet_name="All Relationships", index=False)
        p["result_accounts"].to_excel(xw, sheet_name="Account RAROC", index=False)
        for name in ["loans", "revolvers", "irds", "deposits", "payments"]:
            p[name].to_excel(xw, sheet_name=name.capitalize(), index=False)
        assumptions = pd.DataFrame(
            [("Hurdle rate", C.CAPITAL.hurdle_rate), ("Tax rate", C.CAPITAL.tax_rate),
             ("Capital credit rate", C.CAPITAL.capital_credit_rate),
             ("IRB confidence", C.CAPITAL.confidence), ("EC multiplier", C.CAPITAL.ec_multiplier),
             ("Op-risk capital % revenue", C.CAPITAL.op_risk_pct_revenue),
             ("Revolver CCF", C.REVOLVER_CCF), ("SOFR", C.SOFR)]
            + [(f"PD rating {k}", v) for k, v in C.PD_BY_RATING.items()]
            + [(f"LGD {k}", v) for k, v in C.LGD_BY_COLLATERAL.items()]
            + [(f"FTP {k}y", v) for k, v in C.FTP_CURVE.items()],
            columns=["Assumption", "Value"])
        assumptions.to_excel(xw, sheet_name="Assumptions", index=False)
        ecap_factor_table().reset_index().rename(columns=lambda c: f"{c}y" if isinstance(c, int) else c) \
            .to_excel(xw, sheet_name="ECAP Factors", index=False)
        pd.DataFrame(service.pit_factors()).to_excel(xw, sheet_name="PIT Factors", index=False)
        pd.DataFrame([
            {"approach": label, **{k: row[k] for k in ("capital", "rwa", "raroc", "eva")}}
            for label, s in [
                ("Economic, analytic", ModelSettings()),
                ("Economic, factor table", ModelSettings(ecap_method="factor")),
                ("Regulatory, SA", ModelSettings(capital_basis="regulatory", basel_approach="SA")),
                ("Regulatory, F-IRB", ModelSettings(capital_basis="regulatory", basel_approach="FIRB")),
                ("Regulatory, A-IRB", ModelSettings(capital_basis="regulatory", basel_approach="AIRB")),
                ("Regulatory, A-IRB + floor", ModelSettings(capital_basis="regulatory", output_floor=True)),
            ]
            for row in [service.portfolio(s)["result_products"].set_index("product").loc["Total Portfolio"]]
        ]).to_excel(xw, sheet_name="Capital Approaches", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(
                    max(len(str(c.value or "")) for c in col[:50]) + 2, 40)
            ws.freeze_panes = "A2"

    site = root / "docs"
    build_site(site)
    return {"data": data_dir, "reports": rep_dir, "excel": xlsx, "web app": site / "index.html"}
