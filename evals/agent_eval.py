"""End-to-end eval of the Claude pricing copilot (calls the live API; costs a few cents per run).

Each case is graded with deterministic checks, so no LLM judge is needed:
  * tools    - the agent must call these tools (grounding, not guessing)
  * contains - answer must mention each phrase (case-insensitive)
  * numbers  - a ground-truth value computed from the engine must appear in the answer
               (as a percentage or bps, within tolerance)

Usage: ANTHROPIC_API_KEY=... python evals/agent_eval.py [--only 3]
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from raroc import service
from raroc.agent import ask


def _rel(rid):
    return next(r for r in service.key_relationships() if r["relationship_id"] == rid)


def _price(**kw):
    return service.price(**kw)


def cases():
    blue = _rel("R007")
    summit = _rel("R004")
    top = max(service.key_relationships(), key=lambda r: r["raroc"])
    deal = _price(product="Revolver", amount=40e6, tenor_yrs=3, rating=7, collateral="Unsecured",
                  relationship_id="R007", utilization=0.3)
    rev = next(r for r in service.portfolio_summary()["by_product"] if r["product"] == "Revolver")
    return [
        {"id": "top-relationship", "q": "Which key relationship has the highest RAROC and what is it?",
         "tools": ["list_key_relationships"], "contains": [top["name"].split()[0]],
         "numbers": [("pct", top["raroc"], 0.6)]},
        {"id": "watch-list", "q": "Which key relationships are on the pricing watch list, and why?",
         "tools": ["list_key_relationships"], "contains": ["Blue Mesa"],
         "numbers": [("pct", blue["raroc"], 0.3)]},
        {"id": "revolver-hurdle", "q": "Do revolvers clear the hurdle rate on a standalone basis?",
         "tools": ["get_portfolio_summary"], "contains": ["12"],
         "numbers": [("pct", rev["raroc"], 0.3)]},
        {"id": "price-blue-mesa",
         "q": "Price a $40MM 3-year unsecured revolver for Blue Mesa Energy Services (R007), "
              "risk rating 7, expected 30% utilization. What spread do you recommend?",
         "tools": ["price_deal"], "contains": [],
         "numbers": [("bps", deal["recommended_spread"] * 1e4, 3)]},
        {"id": "ancillary-value",
         "q": "How much do deposits and payments add to Summit Ridge Software's RAROC versus lending alone?",
         "tools": ["get_relationship|list_key_relationships"], "contains": ["deposit"],
         "numbers": [("pct", summit["lending_raroc"], 0.3)]},
        {"id": "exception-approval",
         "q": "A banker wants to price 40 bps below the relationship floor. Who needs to approve it?",
         "tools": ["search_policy"], "contains": ["Chief Credit Officer"], "numbers": []},
        {"id": "future-deposits",
         "q": "Can I justify a loan discount with deposits the client promises to move next year?",
         "tools": ["search_policy"], "contains": ["existing"], "numbers": []},
        {"id": "out-of-scope", "q": "What's the weather in Chicago tomorrow?",
         "tools": [], "contains": [], "numbers": [], "max_tools": 0},
    ]


def _numbers_in(text):
    out = []
    for m in re.finditer(r"(-?\d[\d,]*\.?\d*)\s*(%|bps|basis points)", text):
        out.append((float(m.group(1).replace(",", "")), "pct" if m.group(2) == "%" else "bps"))
    return out


def grade(case, r):
    called = {c["tool"] for c in r.tool_calls}
    checks = {}
    for t in case["tools"]:
        checks[f"tool:{t}"] = any(opt in called for opt in t.split("|"))
    for phrase in case["contains"]:
        checks[f"contains:{phrase}"] = phrase.lower() in r.answer.lower()
    found = _numbers_in(r.answer)
    for kind, value, tol in case["numbers"]:
        target = value * 100 if kind == "pct" else value
        checks[f"{kind}:{target:.2f}"] = any(u == kind and abs(v - target) <= tol for v, u in found)
    if "max_tools" in case:
        checks["no_tools"] = len(r.tool_calls) <= case["max_tools"]
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, help="run only the first N cases")
    ap.add_argument("--out", default="evals/results/agent.json")
    args = ap.parse_args()

    all_cases = cases()[: args.only] if args.only else cases()
    rows, passed, tokens = [], 0, {"input": 0, "output": 0}
    t0 = time.time()
    for case in all_cases:
        r = ask(case["q"])
        checks = grade(case, r)
        ok = all(checks.values())
        passed += ok
        tokens["input"] += r.usage["input_tokens"]
        tokens["output"] += r.usage["output_tokens"]
        rows.append({"id": case["id"], "pass": ok, "checks": checks, "answer": r.answer,
                     "tool_calls": r.tool_calls, "usage": r.usage, "latency_s": r.latency_s})
        print(f"{'PASS' if ok else 'FAIL'}  {case['id']:<20} "
              f"{[k for k, v in checks.items() if not v] or ''}")

    summary = {"cases": len(all_cases), "passed": passed,
               "pass_rate": round(passed / len(all_cases), 3), "tokens": tokens,
               "wall_s": round(time.time() - t0, 1), "model": r.model}
    print(json.dumps(summary))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, default=str))
    return 0 if summary["pass_rate"] >= 0.75 else 1


if __name__ == "__main__":
    sys.exit(main())
