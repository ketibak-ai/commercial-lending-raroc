"""Write outputs: CSVs, an Excel workbook and the static HTML dashboard (GitHub Pages)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import config as C
from . import service

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).with_name("dashboard_template.html")

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


def revenue_mix() -> list[dict]:
    p = service.portfolio()
    acc = p["result_accounts"]
    key_ids = [r["relationship_id"] for r in service.key_relationships()]
    mix = acc[acc.relationship_id.isin(key_ids)].pivot_table(
        index="relationship_id", columns="product", values="total_revenue", aggfunc="sum",
        fill_value=0)
    return json.loads(mix.reindex(key_ids).reset_index().to_json(orient="records"))


def build_dashboard(path: Path) -> None:
    data = {
        "as_of": C.AS_OF_DATE,
        "hurdle": C.CAPITAL.hurdle_rate,
        "summary": service.portfolio_summary(),
        "key": service.key_relationships(),
        "mix": revenue_mix(),
        "deals": sample_pricing(),
    }
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "__DATA__", json.dumps(data).replace("</", "<\\/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


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
        for ws in xw.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(
                    max(len(str(c.value or "")) for c in col[:50]) + 2, 40)
            ws.freeze_panes = "A2"

    dashboard = root / "docs" / "index.html"
    build_dashboard(dashboard)
    return {"data": data_dir, "reports": rep_dir, "excel": xlsx, "dashboard": dashboard}
