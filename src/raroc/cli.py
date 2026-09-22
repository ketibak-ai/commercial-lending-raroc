"""Command line: `raroc simulate | price | ask`."""

from __future__ import annotations

import argparse
import json

from . import service


def _fmt_pct(v: float) -> str:
    return f"{v * 100:6.1f}%"


def cmd_simulate(_: argparse.Namespace) -> None:
    from .report import write_all

    paths = write_all()
    print("\nProduct RAROC")
    for r in service.portfolio_summary()["by_product"]:
        print(f"  {r['product']:<26} accounts {int(r['accounts']):>5}   RAROC {_fmt_pct(r['raroc'])}")
    print("\nKey relationships (relationship RAROC | lending-only RAROC)")
    for r in service.key_relationships():
        flag = "  WATCH" if r["watch_list"] else ""
        print(f"  {r['relationship_id']} {r['name']:<32} {_fmt_pct(r['raroc'])} | "
              f"{_fmt_pct(r['lending_raroc'])}{flag}")
    print("\nOutputs:")
    for k, p in paths.items():
        print(f"  {k:<10} {p}")


def cmd_price(a: argparse.Namespace) -> None:
    args = {k: v for k, v in vars(a).items() if k not in {"func", "cmd"} and v is not None}
    print(json.dumps(service.price(**args), indent=2))


def cmd_ask(a: argparse.Namespace) -> None:
    from .agent import ask

    r = ask(a.question)
    print(r.answer)
    print(f"\n[{r.model} · {len(r.tool_calls)} tool calls · {r.usage['input_tokens']} in / "
          f"{r.usage['output_tokens']} out tokens · {r.latency_s}s]")


def main() -> None:
    p = argparse.ArgumentParser(prog="raroc", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("simulate", help="simulate the book and write CSV/Excel/dashboard")
    s.set_defaults(func=cmd_simulate)

    pr = sub.add_parser("price", help="price a new deal")
    pr.add_argument("--product", choices=["Term Loan", "Revolver"], default="Term Loan")
    pr.add_argument("--amount", type=float, default=10e6)
    pr.add_argument("--tenor-yrs", dest="tenor_yrs", type=float, default=5)
    pr.add_argument("--rating", type=int, default=5)
    pr.add_argument("--collateral", default="Senior Secured")
    pr.add_argument("--utilization", type=float)
    pr.add_argument("--relationship-id", dest="relationship_id")
    pr.set_defaults(func=cmd_price)

    q = sub.add_parser("ask", help="ask the AI pricing copilot (needs ANTHROPIC_API_KEY)")
    q.add_argument("question")
    q.set_defaults(func=cmd_ask)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
