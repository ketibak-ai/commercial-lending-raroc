"""Portfolio service: one cached simulation + JSON-safe query functions.

Shared by the REST API and the LLM agent's tools so both see identical numbers.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from functools import lru_cache

import pandas as pd

from . import config as C
from .config import DEFAULT_SETTINGS, ModelSettings
from .engine import ecap_factor_table, pit_pd, run
from .pricing import DealRequest, price_deal
from .rag import search
from .simulate import simulate


@lru_cache(maxsize=1)
def book() -> dict[str, pd.DataFrame]:
    return simulate(C.SEED)


@lru_cache(maxsize=32)
def portfolio(settings: ModelSettings = DEFAULT_SETTINGS) -> dict[str, pd.DataFrame]:
    b = book()
    return {**b, **{f"result_{k}": v for k, v in run(b, settings).items()}}


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.round(4).to_json(orient="records"))  # native JSON types


def portfolio_summary(settings: ModelSettings = DEFAULT_SETTINGS) -> dict:
    p = portfolio(settings)
    rels = p["result_relationships"]
    return {
        "as_of": C.AS_OF_DATE,
        "hurdle_rate": C.CAPITAL.hurdle_rate,
        "model_settings": asdict(settings),
        "by_product": _records(p["result_products"]),
        "relationships_total": int(len(rels)),
        "relationships_below_hurdle": int((~rels.meets_hurdle).sum()),
    }


KEY_COLS = ["relationship_id", "name", "industry", "rating", "total_revenue",
            "capital", "economic_capital", "reg_capital", "net_income", "eva", "raroc", "lending_raroc",
            "ancillary_uplift", "meets_hurdle"]


def key_relationships(settings: ModelSettings = DEFAULT_SETTINGS) -> list[dict]:
    rels = portfolio(settings)["result_relationships"]
    key = rels[rels.segment == "Key Relationship"].sort_values("raroc", ascending=False)
    out = _records(key[KEY_COLS])
    for r in out:
        r["watch_list"] = r["raroc"] < C.WATCH_LIST_RAROC
    return out


def relationship_detail(relationship_id: str, settings: ModelSettings = DEFAULT_SETTINGS) -> dict:
    p = portfolio(settings)
    rels = p["result_relationships"]
    row = rels[rels.relationship_id == relationship_id]
    if row.empty:
        raise KeyError(f"relationship {relationship_id} not found")
    acc = p["result_accounts"]
    acc = acc[acc.relationship_id == relationship_id]
    by_product = acc.groupby("product").agg(
        accounts=("account_id", "count"), exposure=("exposure", "sum"),
        revenue=("total_revenue", "sum"), expected_loss=("expected_loss", "sum"),
        economic_capital=("economic_capital", "sum"), reg_capital=("reg_capital", "sum"),
        capital=("capital", "sum"), net_income=("net_income", "sum"), eva=("eva", "sum"))
    by_product["raroc"] = by_product.net_income / by_product.capital
    worst = acc[acc["product"].isin(["Term Loan", "Revolver"])].nsmallest(5, "eva")
    summary = _records(row[KEY_COLS + ["segment"]])[0]
    summary["watch_list"] = summary["raroc"] < C.WATCH_LIST_RAROC
    return {
        "summary": summary,
        "by_product": _records(by_product.reset_index()),
        "lowest_eva_credit_accounts": _records(
            worst[["account_id", "product", "sub_type", "exposure", "raroc", "eva"]]),
    }


def price(settings: ModelSettings = DEFAULT_SETTINGS, **kwargs) -> dict:
    req = DealRequest(**kwargs)
    rels = book()["relationships"].set_index("relationship_id")
    industry = rels.industry.get(req.relationship_id, "") if req.relationship_id else ""
    return price_deal(req, portfolio(settings)["result_accounts"], settings, industry)


def ecap_factors() -> dict:
    t = ecap_factor_table()
    return {"confidence": C.ECAP_FACTOR_CONFIDENCE, "diversification": C.ECAP_DIVERSIFICATION,
            "note": "Economic capital per $1 EAD at 100% LGD; multiply by LGD and industry multiplier",
            "industry_multipliers": C.ECAP_INDUSTRY_MULTIPLIER,
            "table": {str(r): {str(m): round(float(v), 6) for m, v in row.items()}
                      for r, row in t.iterrows()}}


def pit_factors(cycle_shift: float = 0.0) -> list[dict]:
    out = []
    for industry, z in sorted(C.CREDIT_CYCLE_Z.items(), key=lambda kv: kv[1]):
        row = {"industry": industry, "z": z + cycle_shift}
        for rating in (3, 5, 7):
            ttc = C.PD_BY_RATING[rating]
            row[f"pd_pit_rating_{rating}"] = round(float(pit_pd([ttc], [z + cycle_shift])[0]), 6)
            row[f"pd_ttc_rating_{rating}"] = ttc
        out.append(row)
    return out


def policy_search(query: str, k: int = 3) -> list[dict]:
    return search(query, k)
