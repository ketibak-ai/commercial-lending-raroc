"""Offline retrieval eval (runs in CI, no API key): does policy search surface the right section?

Usage: python evals/retrieval_eval.py [--min-hit3 1.0]
"""

import argparse
import json
import sys
from pathlib import Path

from raroc.rag import search

CASES = [
    ("Who approves a deal priced 40 bps below the relationship floor?", "Pricing Exceptions and Approvals"),
    ("Can a loan be priced below the cost floor if deposits are large?", "Cost Floor"),
    ("Can promised future deposits justify a pricing concession?", "Relationship Pricing Concessions"),
    ("What is the hurdle rate?", "Hurdle Rate"),
    ("How is exposure at default calculated for a revolver?", "Exposure at Default"),
    ("What credit conversion factor applies to undrawn commitments?", "Exposure at Default"),
    ("Runoff haircut for operating deposits", "Deposit Types and Runoff"),
    ("How do deposits get FTP credit?", "FTP Credit for Deposits"),
    ("When does a relationship go on the pricing watch list?", "Repricing and Watch List"),
    ("How is counterparty exposure on swaps measured?", "Counterparty Credit Risk"),
    ("Does the bank keep market risk on client swaps?", "Market Risk"),
    ("What is the cost-to-income ratio for payments?", "Profitability"),
    ("How does the earnings credit rate affect fee income?", "Earnings Credit Rate"),
    ("What confidence level is used for economic capital?", "Economic Capital"),
    ("How is expected loss calculated?", "Expected Loss"),
    ("What is ancillary uplift?", "Relationship RAROC"),
    ("How are unused fees on revolvers treated?", "Revolving Credit Facilities"),
    ("Which derivative products can clients buy?", "Permitted Products"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-hit3", type=float, default=1.0)
    ap.add_argument("--out", default="evals/results/retrieval.json")
    args = ap.parse_args()

    rows, hit1, hit3 = [], 0, 0
    for q, expected in CASES:
        got = [r["citation"] for r in search(q, k=3)]
        h1 = bool(got) and got[0].endswith(expected)
        h3 = any(c.endswith(expected) for c in got)
        hit1, hit3 = hit1 + h1, hit3 + h3
        rows.append({"query": q, "expected": expected, "retrieved": got, "hit@1": h1, "hit@3": h3})
        print(f"{'PASS' if h3 else 'FAIL'}  hit@1={int(h1)}  {q}")

    n = len(CASES)
    summary = {"cases": n, "hit@1": round(hit1 / n, 3), "hit@3": round(hit3 / n, 3)}
    print(json.dumps(summary))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    return 0 if summary["hit@3"] >= args.min_hit3 else 1


if __name__ == "__main__":
    sys.exit(main())
