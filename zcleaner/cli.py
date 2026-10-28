"""Command-line interface.

    zcleaner generate --out sample_data
    zcleaner clean --leads Leads.csv --contacts Contacts.csv --accounts Accounts.csv --out cleaned/
    zcleaner evaluate --data sample_data
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from . import match as M
from .pipeline import run
from .report import summary_markdown, write_outputs
from .schema import read_export


def _load(args) -> dict[str, pd.DataFrame]:
    frames = {}
    for module in ("leads", "contacts", "accounts"):
        path = getattr(args, module, None)
        if path:
            frames[module.capitalize()] = read_export(path)
    if not frames:
        sys.exit("Give at least one of --leads, --contacts or --accounts.")
    return frames


def cmd_generate(args):
    from .synth import write_sample
    out = write_sample(args.out, n_accounts=args.accounts, n_people=args.people, seed=args.seed)
    print(f"Wrote fake Zoho exports to {out}/ (Leads.csv, Contacts.csv, Accounts.csv, _truth.csv)")


def cmd_clean(args):
    result = run(_load(args), high=args.high, review=args.review)
    approved = {c.cid for c in result.clusters if c.band == "High" or args.approve_review}
    out = write_outputs(result, args.out, approved)
    print(summary_markdown(result, approved))
    print(f"Files written to {out}/")


def cmd_evaluate(args):
    from .evaluate import evaluate
    data = Path(args.data)
    frames = {m: read_export(data / f"{m}.csv") for m in ("Leads", "Contacts", "Accounts")}
    truth = pd.read_csv(data / "_truth.csv", dtype=str)
    print(evaluate(run(frames, high=args.high, review=args.review), truth).to_string(index=False))


def main(argv=None):
    p = argparse.ArgumentParser(prog="zcleaner", description="Clean and deduplicate Zoho CRM exports.")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="create realistic fake exports to play with")
    g.add_argument("--out", default="sample_data")
    g.add_argument("--accounts", type=int, default=60)
    g.add_argument("--people", type=int, default=320)
    g.add_argument("--seed", type=int, default=42)
    g.set_defaults(func=cmd_generate)

    for name, func, help_ in (("clean", cmd_clean, "clean exports and write a merge plan"),
                              ("evaluate", cmd_evaluate, "score matching against _truth.csv")):
        c = sub.add_parser(name, help=help_)
        if name == "clean":
            c.add_argument("--leads")
            c.add_argument("--contacts")
            c.add_argument("--accounts")
            c.add_argument("--out", default="cleaned")
            c.add_argument("--approve-review", action="store_true",
                           help="also approve lower-confidence matches (review them first!)")
        else:
            c.add_argument("--data", default="sample_data")
        c.add_argument("--high", type=float, default=M.HIGH, help="auto-approve threshold (default %(default)s)")
        c.add_argument("--review", type=float, default=M.REVIEW, help="review threshold (default %(default)s)")
        c.set_defaults(func=func)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
