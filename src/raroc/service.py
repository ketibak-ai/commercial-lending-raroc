"""Portfolio service: one cached simulation + JSON-safe query functions.

Shared by the REST API and the LLM agent's tools so both see identical numbers.
"""

from __future__ import annotations

import json
from functools import lru_cache

import pandas as pd

from . import config as C
from .engine import run
from .pricing import DealRequest, price_deal
from .rag import search
from .simulate import simulate


@lru_cache(maxsize=1)
def portfolio() -> dict[str, pd.DataFrame]:
    book = simulate(C.SEED)
    return {**book, **{f"result_{k}": v for k, v in run(book).items()}}


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.round(4).to_json(orient="records"))  # native JSON types


def portfolio_summary() -> dict:
    p = portfolio()
    rels = p["result_relationships"]
    return {
        "as_of": C.AS_OF_DATE,
        "hurdle_rate": C.CAPITAL.hurdle_rate,
        "by_product": _records(p["result_products"]),
        "relationships_total": int(len(rels)),
        "relationships_below_hurdle": int((~rels.meets_hurdle).sum()),
    }


KEY_COLS = ["relationship_id", "name", "industry", "rating", "total_revenue",
            "economic_capital", "net_income", "eva", "raroc", "lending_raroc",
            "ancillary_uplift", "meets_hurdle"]


def key_relationships() -> list[dict]:
    rels = portfolio()["result_relationships"]
    key = rels[rels.segment == "Key Relationship"].sort_values("raroc", ascending=False)
    out = _records(key[KEY_COLS])
    for r in out:
        r["watch_list"] = r["raroc"] < 0.15
    return out


def relationship_detail(relationship_id: str) -> dict:
    p = portfolio()
    rels = p["result_relationships"]
    row = rels[rels.relationship_id == relationship_id]
    if row.empty:
        raise KeyError(f"relationship {relationship_id} not found")
    acc = p["result_accounts"]
    acc = acc[acc.relationship_id == relationship_id]
    by_product = acc.groupby("product").agg(
        accounts=("account_id", "count"), exposure=("exposure", "sum"),
        revenue=("total_revenue", "sum"), expected_loss=("expected_loss", "sum"),
        economic_capital=("economic_capital", "sum"), net_income=("net_income", "sum"),
        eva=("eva", "sum"))
    by_product["raroc"] = by_product.net_income / by_product.economic_capital
    worst = acc[acc["product"].isin(["Term Loan", "Revolver"])].nsmallest(5, "eva")
    summary = _records(row[KEY_COLS + ["segment"]])[0]
    summary["watch_list"] = summary["raroc"] < 0.15
    return {
        "summary": summary,
        "by_product": _records(by_product.reset_index()),
        "lowest_eva_credit_accounts": _records(
            worst[["account_id", "product", "sub_type", "exposure", "raroc", "eva"]]),
    }


def price(**kwargs) -> dict:
    req = DealRequest(**kwargs)
    return price_deal(req, portfolio()["result_accounts"])


def policy_search(query: str, k: int = 3) -> list[dict]:
    return search(query, k)
