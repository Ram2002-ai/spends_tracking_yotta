"""Command line interface:  python -m hfsynth <generate|validate|repro|docs> [options]"""
import argparse
import dataclasses
import json
import os
import sys
import time

from . import evaluate as E, export as X, schema as S, validate as V
from .config import Config
from .derive import finish
from .generate import build

SCALES = {"tiny": (30, 12_000), "starter": (100, 30_000), "full": (1000, 500_000)}


def make_config(a):
    users, txns = SCALES[a.scale]
    return Config(seed=a.seed, users=a.users or users, txns=a.txns or txns, out=a.out)


def pipeline(cfg, log=lambda m: None):
    t = time.time()
    ds = build(cfg)
    ds = finish(ds, ds.meta["_builder"])
    log(f"generated {len(ds.tables['transaction']):,} transactions in {time.time() - t:.1f}s")
    rep = V.run(ds, cfg)
    log(f"validation: {'PASS' if rep.ok else 'FAIL'} ({len(rep.results)} checks) in {time.time() - t:.1f}s")
    return ds, rep


def _common(p):
    p.add_argument("--scale", choices=SCALES, default="starter")
    p.add_argument("--users", type=int, help="override user count")
    p.add_argument("--txns", type=int, help="override exact transaction count")
    p.add_argument("--seed", type=int, default=20261022)
    p.add_argument("--out", default="output")
    p.add_argument("--formats", default="csv,json,sql")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hfsynth", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    _common(sub.add_parser("generate", help="generate, validate, evaluate and export a dataset"))
    sub.add_parser("validate", help="validate an exported CSV dataset").add_argument("--out", default="output")
    _common(sub.add_parser("repro", help="generate twice with the same seed and compare checksums"))
    sub.add_parser("docs", help="write docs/DATA_DICTIONARY.md and docs/schema.sql").add_argument("--dir", default="docs")
    a = ap.parse_args(argv)
    log = lambda m: print(m, flush=True)

    if a.cmd == "docs":
        os.makedirs(a.dir, exist_ok=True)
        open(os.path.join(a.dir, "DATA_DICTIONARY.md"), "w", encoding="utf-8", newline="\n").write(S.data_dictionary_md())
        open(os.path.join(a.dir, "schema.sql"), "w", encoding="utf-8", newline="\n").write(S.ddl())
        log(f"wrote {a.dir}/DATA_DICTIONARY.md and {a.dir}/schema.sql")
        return 0
    if a.cmd == "validate":
        ds = X.load_dataset(a.out)
        rep = V.run(ds)
        print(rep.to_md())
        return 0 if rep.ok else 1
    cfg = make_config(a)
    formats = tuple(f for f in a.formats.split(",") if f)
    if a.cmd == "generate":
        ds, rep = pipeline(cfg, log)
        ev = E.evaluate(ds)
        cmd = "python -m hfsynth " + " ".join(sys.argv[1:] if argv is None else argv)
        X.export(ds, cfg, cfg.out, formats, rep, ev, cmd)
        log(E.to_md(ev))
        log(f"exported to {os.path.abspath(cfg.out)}")
        return 0 if rep.ok else 1
    if a.cmd == "repro":
        same, report = X.reproducibility(cfg, cfg.out, formats, lambda c: pipeline(c, log))
        log(report)
        return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
