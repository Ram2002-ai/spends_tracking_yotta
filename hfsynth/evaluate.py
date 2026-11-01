"""Evaluation: shows the generated data supports measurable outputs.
Ground truth is read ONLY here (and in validation), never by the generator's input tables."""
import datetime as dt
import json
from collections import Counter, defaultdict

from .derive import ledger_spend, naive_spend, true_spend

D = dt.date


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"precision": p, "recall": r, "f1": f, "tp": tp, "fp": fp, "fn": fn}


def categorization(ds):
    gt = {g[0]: g for g in ds.gt["gt_transaction"]}
    conf = defaultdict(Counter)
    seg = defaultdict(lambda: [0, 0])
    tot = ok = 0
    for r in ds.tables["transaction"]:
        g = gt[r[0]]
        t, p = g[1], r[3]
        conf[t][p] += 1
        hit = t == p
        tot += 1
        ok += hit
        key = ("ambiguous_merchant" if g[8] else "unresolvable_descriptor" if (g[2] and not g[7]) else
               "injected_anomaly" if g[6] != "NONE" else "clean")
        seg[key][0] += 1
        seg[key][1] += hit
    cats = sorted(set(conf) | {p for c in conf.values() for p in c})
    per, f1s = {}, []
    for c in cats:
        tp = conf[c][c]
        fn = sum(conf[c].values()) - tp
        fp = sum(conf[o][c] for o in conf if o != c)
        per[c] = {**_prf(tp, fp, fn), "support": tp + fn}
        if tp + fn:
            f1s.append(per[c]["f1"] or 0.0)
    unc = sum(1 for r in ds.tables["transaction"] if r[3] == "UNC")
    errs = Counter((t, p) for t, c in conf.items() for p, n in c.items() if t != p for _ in range(n))
    return {"rows": tot, "accuracy": ok / tot, "macro_f1": sum(f1s) / len(f1s), "uncategorized_rate": unc / tot,
            "per_category": per,
            "accuracy_by_segment": {k: {"rows": v[0], "accuracy": v[1] / v[0]} for k, v in seg.items()},
            "top_confusions": [{"true": t, "predicted": p, "rows": n} for (t, p), n in errs.most_common(8)]}


def merchants(ds):
    gt = {g[0]: g for g in ds.gt["gt_transaction"]}
    n = right = wrong = missed = 0
    for r in ds.tables["transaction"]:
        tm = gt[r[0]][2]
        if tm:
            n += 1
            if r[2] == tm:
                right += 1
            elif r[2] is None:
                missed += 1
            else:
                wrong += 1
    return {"rows_with_true_merchant": n, "resolved_correctly": right / n, "unresolved": missed / n,
            "resolved_wrongly": wrong / n}


def spend(ds):
    T, N, L = true_spend(ds), naive_spend(ds), ledger_spend(ds, _dups(ds))
    keys = set(T) | set(N) | set(L)

    def err(X):
        e = [abs(X.get(k, 0) - T.get(k, 0)) for k in keys]
        return {"total_usd": round(sum(X.values()) / 100, 2),
                "abs_error_usd": round(sum(e) / 100, 2),
                "wape_cell_level": round(sum(e) / max(1, sum(T.values())), 4),
                "cells_exact_pct": round(sum(1 for x in e if x == 0) / len(keys), 4)}
    gt = ds.gt["gt_transaction"]
    return {"cells(user,month,category)": len(keys), "true_total_usd": round(sum(T.values()) / 100, 2),
            "naive_utc_abs_pipeline": err(N), "ledger_policy_pipeline": err(L),
            "edge_case_exposure": {
                "transfer_duplicates": sum(1 for g in gt if g[6] == "TRANSFER_DOUBLE_COUNT"),
                "misclassified_refunds": sum(1 for g in gt if g[6] == "REFUND_MISCLASSIFIED"),
                "rows_in_different_utc_month": sum(1 for r in ds.tables["transaction"] if r[5][:7] != r[7][:7])}}


def _dups(ds):
    return {c[3] for c in ds.tables["exception_case"] if c[6] == "CR1"}


def exceptions(ds):
    gt = ds.gt["gt_transaction"]
    lab = defaultdict(set)
    for g in gt:
        lab[g[6]].add(g[0])
    out = {}
    cases = defaultdict(set)
    for c in ds.tables["exception_case"]:
        cases[c[6]].add(c[3])
    for rule, lbl in (("CR1", "TRANSFER_DOUBLE_COUNT"), ("CR2", "REFUND_MISCLASSIFIED")):
        d = cases[rule]
        out[f"{rule}_{lbl}"] = _prf(len(d & lab[lbl]), len(d - lab[lbl]), len(lab[lbl] - d))
    skipped = {(o[0], o[2]) for o in ds.gt["gt_recurring_occurrence"] if o[4] == "SKIPPED"}
    det = {(c[3], c[5]) for c in ds.tables["exception_case"] if c[6] == "CR5"}
    out["CR5_RECURRING_MISSED"] = _prf(len(det & skipped), len(det - skipped), len(skipped - det))
    out["case_status"] = dict(Counter(c[8] for c in ds.tables["exception_case"]))
    return out


def recurring(ds):
    """Baseline series discovery from ledger only (account+merchant, >=3 hits, regular gaps)."""
    groups = defaultdict(list)
    for r in ds.tables["transaction"]:
        if r[2]:
            groups[(r[1], r[2])].append(D.fromisoformat(r[7]).toordinal())
    found = set()
    for k, v in groups.items():
        v = sorted(set(v))
        if len(v) < 3:
            continue
        gaps = [b - a for a, b in zip(v, v[1:])]
        mon = sum(26 <= g <= 35 for g in gaps) / len(gaps)
        bi = sum(12 <= g <= 17 for g in gaps) / len(gaps)
        if mon >= 0.8 or bi >= 0.8:
            found.add(k)
    sr = {s[0]: s for s in ds.tables["recurring_series"]}
    posted = Counter()
    for o in ds.gt["gt_recurring_occurrence"]:
        if o[4] == "POSTED":
            posted[o[0]] += 1
    truth = {(sr[s][2], sr[s][4]) for s, n in posted.items() if n >= 3 and sr[s][4]}
    single = sum(1 for s, n in posted.items() if n < 3 and sr[s][4])
    return {"series_registered": len(sr), "truth_detectable_series": len(truth),
            "not_detectable_lt3_occurrences": single, "baseline_detector": _prf(len(found & truth), len(found - truth), len(truth - found)),
            "occurrences_skipped_labelled": sum(1 for o in ds.gt["gt_recurring_occurrence"] if o[4] == "SKIPPED")}


def distributions(ds):
    tx = ds.tables["transaction"]
    mo = Counter(r[7][:7] for r in tx)
    tt = Counter(r[11] for r in tx)
    per_user = Counter(a[1] for a in ds.tables["account"] for _ in [0])
    amt = sorted(-r[9] for r in tx if r[11] == "PURCHASE" and r[9] < 0)
    q = lambda p: amt[int(p * (len(amt) - 1))]
    return {"txns_per_month": dict(sorted(mo.items())), "txn_type_mix": dict(tt),
            "purchase_amount_usd": {"p10": q(.1), "p50": q(.5), "p90": q(.9), "p99": q(.99)},
            "insights_by_type": dict(Counter(i[3] for i in ds.tables["insight"])),
            "budget_lines": len(ds.tables["budget"])}


def evaluate(ds):
    return {"categorization": categorization(ds), "merchant_resolution": merchants(ds), "spend_reconciliation": spend(ds),
            "exception_detection": exceptions(ds), "recurring_detection": recurring(ds), "distributions": distributions(ds)}


def to_md(e):
    c, s, rd = e["categorization"], e["spend_reconciliation"], e["recurring_detection"]
    f = lambda x: "n/a" if x is None else f"{x:.3f}"
    o = ["# Evaluation summary", "",
         f"- Categorisation accuracy **{c['accuracy']:.3f}**, macro-F1 **{c['macro_f1']:.3f}**, uncategorised {c['uncategorized_rate']:.3%}",
         "- Accuracy by segment: " + ", ".join(f"{k} {v['accuracy']:.3f} (n={v['rows']})" for k, v in c["accuracy_by_segment"].items()),
         f"- Merchant resolution: {e['merchant_resolution']['resolved_correctly']:.3f} correct",
         f"- Spend WAPE vs truth: naive/UTC {s['naive_utc_abs_pipeline']['wape_cell_level']:.4f} -> "
         f"ledger-policy {s['ledger_policy_pipeline']['wape_cell_level']:.4f}",
         f"- Recurring baseline detector: precision {f(rd['baseline_detector']['precision'])}, recall {f(rd['baseline_detector']['recall'])}",
         "- Exception detection: " + "; ".join(f"{k}: P={f(v['precision'])} R={f(v['recall'])}" for k, v in e["exception_detection"].items() if isinstance(v, dict) and "precision" in v),
         "", "Full detail in `evaluation_summary.json`.", ""]
    return "\n".join(o)


def dumps(e):
    return json.dumps(e, indent=2, sort_keys=True)
