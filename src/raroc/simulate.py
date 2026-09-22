"""Synthetic commercial banking book generator.

Builds 500 client relationships (10 strategically important "key" relationships plus a
long tail) and the requested accounts: term loans, revolvers, interest rate derivatives,
deposits and payments / treasury management services. Everything is seeded and
reproducible; no real client data is used.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C

KEY_RELATIONSHIPS = [
    # id, name, industry, rating, lending_weight, deposit_weight, payments_weight, ird_trades
    ("R001", "Northwind Manufacturing Group", "Industrial Manufacturing", 4, 1.6, 1.2, 1.4, 3),
    ("R002", "Harborview Health Partners", "Healthcare", 3, 1.2, 1.8, 1.6, 2),
    ("R003", "Cascade Logistics Holdings", "Transportation & Logistics", 5, 1.4, 1.0, 1.8, 3),
    ("R004", "Summit Ridge Software", "Technology", 4, 0.5, 2.6, 1.5, 0),
    ("R005", "Keystone Commercial Properties", "Commercial Real Estate", 5, 2.4, 0.4, 0.3, 4),
    ("R006", "Prairie Harvest Foods", "Food Distribution", 5, 1.0, 1.1, 1.3, 2),
    ("R007", "Blue Mesa Energy Services", "Energy", 7, 1.8, 0.25, 0.3, 3),
    ("R008", "Lakeshore Retail Brands", "Retail", 6, 1.1, 0.9, 1.9, 1),
    ("R009", "Aurora Aerospace Components", "Aerospace & Defense", 4, 1.3, 1.0, 0.8, 1),
    ("R010", "Greenfield Agri Cooperative", "Agriculture", 5, 1.0, 0.8, 0.7, 1),
]

OTHER_INDUSTRIES = [
    "Industrial Manufacturing", "Healthcare", "Transportation & Logistics", "Technology",
    "Commercial Real Estate", "Food Distribution", "Energy", "Retail",
    "Professional Services", "Construction", "Wholesale Trade", "Education",
]

# Share of each product's account count booked to the 10 key relationships
KEY_SHARE = {"loans": 0.15, "revolvers": 0.10, "deposits": 0.15, "payments": 0.20}


def _relationships(rng: np.random.Generator) -> pd.DataFrame:
    key = pd.DataFrame(
        KEY_RELATIONSHIPS,
        columns=["relationship_id", "name", "industry", "rating", "lending_weight",
                 "deposit_weight", "payments_weight", "ird_trades"],
    )
    key["segment"] = "Key Relationship"
    n = C.N_OTHER_RELATIONSHIPS
    other = pd.DataFrame({
        "relationship_id": [f"R{i:03d}" for i in range(11, 11 + n)],
        "name": [f"Client {i:03d}" for i in range(11, 11 + n)],
        "industry": rng.choice(OTHER_INDUSTRIES, n),
        "rating": rng.choice(np.arange(2, 10), n, p=[.04, .10, .20, .25, .20, .12, .06, .03]),
        "lending_weight": 1.0, "deposit_weight": 1.0, "payments_weight": 1.0, "ird_trades": 0,
    })
    other["segment"] = np.where(rng.random(n) < 0.3, "Middle Market", "Business Banking")
    return pd.concat([key, other], ignore_index=True)


def _assign(rng, rels: pd.DataFrame, n: int, key_share: float, weight_col: str) -> np.ndarray:
    """Assign n accounts to relationships: key_share to key clients (by weight), rest to others."""
    key = rels[rels.segment == "Key Relationship"]
    other = rels[rels.segment != "Key Relationship"]
    n_key = int(round(n * key_share))
    p_key = key[weight_col] / key[weight_col].sum()
    out = np.concatenate([
        rng.choice(key.relationship_id, n_key, p=p_key),
        rng.choice(other.relationship_id, n - n_key),
    ])
    rng.shuffle(out)
    return out


def _size_multiplier(rels: pd.DataFrame, ids: np.ndarray) -> np.ndarray:
    seg = rels.set_index("relationship_id").segment
    return seg.loc[ids].map({"Key Relationship": 5.0, "Middle Market": 1.8,
                             "Business Banking": 0.6}).to_numpy()


def _spread_for_rating(rating: np.ndarray) -> np.ndarray:
    return 0.0110 + 0.0028 * (rating - 1)


def simulate(seed: int = C.SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    rels = _relationships(rng)
    rating_of = rels.set_index("relationship_id").rating
    is_key = rels.set_index("relationship_id").segment.eq("Key Relationship")

    # ---- Term loans -------------------------------------------------------------------
    n = C.N_TERM_LOANS
    rid = _assign(rng, rels, n, KEY_SHARE["loans"], "lending_weight")
    rating = np.clip(rating_of.loc[rid].to_numpy() + rng.choice([-1, 0, 0, 0, 1], n), 1, 10)
    sub_type = rng.choice(["C&I Term", "CRE Term", "Equipment Finance"], n, p=[.5, .3, .2])
    sub_type = np.where(rid == "R005", "CRE Term", sub_type)
    collateral = np.select(
        [sub_type == "CRE Term", sub_type == "Equipment Finance"],
        ["Real Estate", "Senior Secured"],
        rng.choice(["Senior Secured", "Unsecured"], n, p=[.7, .3]),
    )
    tenor = rng.choice([3, 5, 7, 10], n, p=[.25, .4, .25, .1]).astype(float)
    # Competitive pressure: key relationships are priced tighter on credit
    discount = np.where(is_key.loc[rid].to_numpy(), rng.uniform(0.0015, 0.0045, n), 0.0)
    loans = pd.DataFrame({
        "account_id": [f"TL{i:05d}" for i in range(1, n + 1)],
        "relationship_id": rid,
        "product": "Term Loan",
        "sub_type": sub_type,
        "balance": np.round(rng.lognormal(14.6, 0.8, n) * _size_multiplier(rels, rid), -3),
        "tenor_yrs": tenor,
        "remaining_yrs": np.round(tenor * rng.uniform(0.2, 1.0, n), 2),
        "rate_type": rng.choice(["Floating", "Fixed"], n, p=[.7, .3]),
        "spread": np.round(_spread_for_rating(rating) + rng.normal(0, 0.0025, n) - discount, 4),
        "orig_fee_pct": rng.choice([0.0025, 0.005, 0.0075, 0.01], n),
        "rating": rating,
        "collateral": collateral,
    })
    loans["spread"] = loans.spread.clip(lower=0.0075)
    loans["commitment"] = loans.balance

    # ---- Revolvers --------------------------------------------------------------------
    n = C.N_REVOLVERS
    rid = _assign(rng, rels, n, KEY_SHARE["revolvers"], "lending_weight")
    rating = np.clip(rating_of.loc[rid].to_numpy() + rng.choice([-1, 0, 0, 1], n), 1, 10)
    commitment = np.round(rng.lognormal(14.2, 0.9, n) * _size_multiplier(rels, rid), -3)
    utilization = np.clip(rng.beta(2.2, 3.5, n), 0.0, 0.95)
    discount = np.where(is_key.loc[rid].to_numpy(), rng.uniform(0.0010, 0.0035, n), 0.0)
    revolvers = pd.DataFrame({
        "account_id": [f"RV{i:05d}" for i in range(1, n + 1)],
        "relationship_id": rid,
        "product": "Revolver",
        "sub_type": rng.choice(["ABL Revolver", "Working Capital Line", "Corporate RCF"], n,
                               p=[.25, .5, .25]),
        "commitment": commitment,
        "utilization": np.round(utilization, 3),
        "balance": np.round(commitment * utilization, -2),
        "tenor_yrs": rng.choice([1, 2, 3, 5], n, p=[.3, .2, .3, .2]).astype(float),
        "rate_type": "Floating",
        "spread": np.round(np.clip(_spread_for_rating(rating) - 0.0015
                                   + rng.normal(0, 0.002, n) - discount, 0.0075, None), 4),
        "unused_fee": rng.choice([0.0015, 0.0020, 0.0025, 0.0035], n),
        "orig_fee_pct": rng.choice([0.001, 0.0025, 0.005], n),
        "rating": rating,
        "collateral": rng.choice(["Senior Secured", "Unsecured"], n, p=[.6, .4]),
    })
    revolvers["remaining_yrs"] = np.round(revolvers.tenor_yrs * rng.uniform(0.2, 1.0, n), 2)

    # ---- Interest rate derivatives (hedges for key-relationship term debt) -----------
    ird_rows = []
    i = 1
    for rel in KEY_RELATIONSHIPS:
        rel_id, trades = rel[0], rel[7]
        for _ in range(trades):
            instr = rng.choice(["Pay-Fixed Swap", "Interest Rate Cap", "Collar"], p=[.6, .25, .15])
            notional = float(np.round(rng.uniform(15e6, 120e6), -5))
            tenor_i = float(rng.choice([3, 5, 7, 10]))
            ird_rows.append({
                "account_id": f"IRD{i:03d}",
                "relationship_id": rel_id,
                "product": "Interest Rate Derivative",
                "sub_type": instr,
                "notional": notional,
                "tenor_yrs": tenor_i,
                "remaining_yrs": round(tenor_i * float(rng.uniform(0.3, 1.0)), 2),
                "mtm": float(np.round(notional * rng.normal(0.004, 0.012), -2)),
                "sales_credit_bps": float(rng.choice([8, 10, 12, 15, 20])),
                "rating": int(rating_of[rel_id]),
            })
            i += 1
    irds = pd.DataFrame(ird_rows)
    assert len(irds) == C.N_IRDS, f"expected {C.N_IRDS} IRDs, got {len(irds)}"

    # ---- Deposits -----------------------------------------------------------------------
    n = C.N_DEPOSITS
    rid = _assign(rng, rels, n, KEY_SHARE["deposits"], "deposit_weight")
    dep_type = rng.choice(["Operating", "Non-Operating", "Time Deposit"], n, p=[.55, .30, .15])
    rate_paid = np.select(
        [dep_type == "Operating", dep_type == "Non-Operating"],
        [rng.uniform(0.0, 0.0125, n), rng.uniform(0.0225, 0.0360, n)],
        rng.uniform(0.0330, 0.0410, n),
    )
    deposits = pd.DataFrame({
        "account_id": [f"DP{i:05d}" for i in range(1, n + 1)],
        "relationship_id": rid,
        "product": "Deposit",
        "sub_type": np.select(
            [dep_type == "Operating", dep_type == "Non-Operating"],
            ["Analyzed DDA", "Money Market / Sweep"], "Commercial CD"),
        "deposit_type": dep_type,
        "balance": np.round(rng.lognormal(13.6, 1.0, n) * _size_multiplier(rels, rid), -2),
        "rate_paid": np.round(rate_paid, 4),
        "tenor_yrs": np.where(dep_type == "Time Deposit", rng.choice([0.5, 1.0, 2.0], n), 0.0),
    })

    # ---- Payments / treasury management --------------------------------------------------
    n = C.N_PAYMENTS
    rid = _assign(rng, rels, n, KEY_SHARE["payments"], "payments_weight")
    services = {  # service -> (unit price, lognormal mean of monthly volume)
        "ACH Origination": (0.12, 8.5), "Wire Transfer": (18.0, 4.0), "RTP / Instant": (0.45, 6.0),
        "Lockbox": (0.65, 6.5), "Positive Pay": (0.08, 7.5), "Commercial Card": (0.0, 0.0),
        "Account Reconciliation": (0.05, 7.0), "Remote Deposit Capture": (0.20, 6.0),
    }
    svc = rng.choice(list(services), n)
    price = np.array([services[s][0] for s in svc])
    vol = np.round(np.array([rng.lognormal(services[s][1], 0.7) for s in svc])
                   * _size_multiplier(rels, rid) / 2)
    monthly = price * vol
    # Commercial card earns interchange on spend rather than per-item fees
    card = svc == "Commercial Card"
    card_spend = np.round(rng.lognormal(12.5, 0.8, n) * _size_multiplier(rels, rid), -2)
    monthly = np.where(card, card_spend * 0.0125, monthly)
    payments = pd.DataFrame({
        "account_id": [f"PM{i:05d}" for i in range(1, n + 1)],
        "relationship_id": rid,
        "product": "Payments",
        "sub_type": svc,
        "monthly_volume": np.where(card, 0, vol).astype(int),
        "unit_price": price,
        "monthly_card_spend": np.where(card, card_spend, 0.0),
        "monthly_revenue": np.round(monthly, 2),
        "ecr_offset_pct": np.where(card, 0.0, np.round(rng.uniform(0.0, 0.45, n), 2)),
    })

    return {"relationships": rels, "loans": loans, "revolvers": revolvers, "irds": irds,
            "deposits": deposits, "payments": payments}
