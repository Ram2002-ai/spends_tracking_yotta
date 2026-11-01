"""Derived layers: budgets, exception cases (detection rules), insights, issue registry.
Everything here is computed from source records and documented rules - never drawn
independently at random (randomness only affects timing / planning noise)."""
import bisect
import datetime as dt
import math
from collections import defaultdict

from . import ids, reference as R
from .generate import rng_for
from .recurring import expected_dates

D = dt.date
ROLE = {"CR1": "RISK_REVIEWER", "CR2": "RISK_REVIEWER", "CR3": "OPS_ANALYST", "CR4": "SYSTEM_ADMIN", "CR5": "OPS_ANALYST"}
SLA = {"CR1": 7, "CR2": 7, "CR3": 14, "CR4": 30, "CR5": 10}
RES = {"CR1": "EXCLUDED_FROM_SPEND", "CR2": "RECLASSIFIED_AS_REFUND", "CR3": "RECATEGORIZED",
       "CR4": "MAPPED_TO_TAXONOMY", "CR5": "CUSTOMER_NOTIFIED"}
CASE_TYPE = {"CR1": "TRANSFER_DOUBLE_COUNT", "CR2": "CREDIT_AS_PURCHASE", "CR3": "UNCATEGORIZED_HIGH_VALUE",
             "CR4": "BUDGET_CATEGORY_UNMAPPED", "CR5": "RECURRING_MISSED"}
SPEND_TYPES = ("PURCHASE", "REFUND", "RECURRING_DEBIT")


def _ceil5(cents):
    return math.ceil(cents / 100 / 5) * 5


# ------------------------------------------------------------------- budgets
def build_budgets(b):
    cfg, y = b.cfg, b.year
    by_user = defaultdict(list)
    for s in b.series:
        by_user[s.uid].append(s)
    rows, events, issues = [], [], []
    for u in b.users:
        r = rng_for(cfg, "budget", u.uid)
        legacy = r.random() < cfg.budget_mismatch_user_share
        extra = [c for c, p in (("TRV", .5), ("EDU", .2), ("HME", .5), ("PET", .35), ("GFT", .4)) if r.random() < p]
        dcats = [c for c in R.DISCRETIONARY if c in ("GRO", "DIN", "TRN", "FUE", "SHP", "ENT", "HLT") or c in extra]
        wsum = sum(R.CAT_MODEL[c][0] * u.pmult.get(c, 1.0) for c in R.DISCRETIONARY)
        plan = {}
        for c in dcats:
            w, med, sig = R.CAT_MODEL[c]
            mean = med * math.exp(sig * sig / 2) * u.spend_factor * u.inc_factor
            plan[c] = max(10, _ceil5(100 * (u.n_disc / 12) * (w * u.pmult.get(c, 1.0) / wsum) * mean * r.uniform(0.85, 1.2)))
        for m in range(1, 13):
            first, last = D(y, m, 1), D(y, m, 28)
            last = D(y, m, 1) + dt.timedelta(days=31)
            last = D(last.year, last.month, 1) - dt.timedelta(days=1)
            act = [s for s in by_user[u.uid] if s.start <= last and (s.end is None or s.end >= first)]
            fixed = {
                "HOU": sum(s.amount_at(first) for s in act if s.stype == "RENT") * 1.03,
                "UTL": sum(s.base for s in act if s.stype == "UTILITY") * 1.05,
                "INS": sum(s.base for s in act if s.stype == "INSURANCE") * 1.03,
                "SUB": sum(s.amount_at(first) for s in act if s.stype == "SUBSCRIPTION" and s.cadence == "MONTHLY") * 1.10,
            }
            lines = [(c, max(5, _ceil5(v))) for c, v in fixed.items() if v > 0] + [(c, plan[c]) for c in dcats]
            for code, amt in lines:
                out = R.LEGACY_CODES.get(code, code) if legacy else code
                bid = ids.budget_id(u.uid, y, m, out)
                rev = 1
                if r.random() < 0.04:
                    new = max(5, _ceil5(100 * amt * (r.uniform(1.1, 1.4) if r.random() < 0.7 else r.uniform(0.8, 0.95))))
                    if new != amt:
                        events.append([bid, "ADJUSTED", (first + dt.timedelta(days=r.randint(4, 20))).isoformat(),
                                       float(amt), float(new)])
                        amt, rev = new, 2
                rows.append([bid, u.uid, out, f"{y}-{m:02d}", first.isoformat(), last.isoformat(), float(amt), "USD",
                             rev, "ACTIVE" if m == 12 else "CLOSED"])
                if out != code:
                    issues.append(["BUDGET_CATEGORY_MISMATCH", "BUDGET", bid, u.uid, code, out,
                                   "legacy budget code is not in the category taxonomy"])
    return rows, events, issues


# ------------------------------------------------------------ spend aggregates
def _maps(ds):
    spending = {r[0]: bool(r[4]) for r in ds.tables["category"]}
    acct_user = {r[0]: r[1] for r in ds.tables["account"]}
    return spending, acct_user


def ledger_spend(ds, excluded=frozenset()):
    """Policy-compliant spend: internal transfers and income excluded, refunds net
    against spend (sign-based, so a mistyped refund still offsets), LOCAL month,
    rows flagged as transfer duplicates removed."""
    spending, au = _maps(ds)
    out = defaultdict(int)
    for r in ds.tables["transaction"]:
        if r[11] in SPEND_TYPES and spending[r[3]] and r[0] not in excluded:
            out[(au[r[1]], r[7][:7], r[3])] -= round(r[9] * 100)
    return out


def naive_spend(ds):
    """Legacy pipeline: sum |amount| of PURCHASE/RECURRING_DEBIT rows, bucketed by UTC month."""
    spending, au = _maps(ds)
    out = defaultdict(int)
    for r in ds.tables["transaction"]:
        if r[11] in ("PURCHASE", "RECURRING_DEBIT") and spending[r[3]]:
            out[(au[r[1]], r[5][:7], r[3])] += abs(round(r[9] * 100))
    return out


def true_spend(ds):
    au = _maps(ds)[1]
    acct = {r[0]: r[1] for r in ds.tables["transaction"]}
    out = defaultdict(int)
    for g in ds.gt["gt_transaction"]:
        if g[4]:
            out[(au[acct[g[0]]], g[5], g[1])] += round(g[4] * 100)
    return out


# --------------------------------------------------------------------- cases
def detect_cases(ds, cfg):
    tr = ds.tables["transaction"]
    cases = []
    out_keys = {(r[1], round(r[9] * 100), r[7]) for r in tr if r[11] == "TRANSFER_OUT"}
    au = _maps(ds)[1]
    for r in tr:
        c = round(r[9] * 100)
        rule = None
        if r[11] == "PURCHASE" and c < 0 and (r[1], c, r[7]) in out_keys:
            rule = "CR1"
        elif r[11] == "PURCHASE" and c > 0:
            rule = "CR2"
        elif r[3] == "UNC" and abs(c) >= 10000:
            rule = "CR3"
        if rule:
            a = abs(c)
            hi, mid = (20000, 5000) if rule != "CR3" else (50000, 20000)
            cases.append((rule, "TRANSACTION", r[0], au[r[1]], r[7], "HIGH" if a >= hi else "MEDIUM" if a >= mid else "LOW"))
    tax = {r[0] for r in ds.tables["category"]}
    seen = set()
    for b in ds.tables["budget"]:
        if b[2] not in tax and (b[1], b[2]) not in seen:
            seen.add((b[1], b[2]))
            cases.append(("CR4", "BUDGET", b[0], b[1], b[4], "MEDIUM"))
    # CR5: registered series occurrence without a matching ledger row in [-3d, +7d]
    sr = ds.tables["recurring_series"]
    merch = {s[4] for s in sr if s[4]}
    counters = {s[3] for s in sr if s[3]}
    idx = defaultdict(list)
    for r in tr:
        if r[2] in merch:
            idx[(r[1], r[2])].append(D.fromisoformat(r[7]).toordinal())
        elif r[11] == "TRANSFER_IN" and r[1] in counters:
            idx[(r[1], None)].append(D.fromisoformat(r[7]).toordinal())
    for v in idx.values():
        v.sort()
    for s in sr:
        key = (s[2], s[4]) if s[4] else (s[3], None)
        lst = idx.get(key, [])
        dates = expected_dates(s[7], D.fromisoformat(s[8]), D.fromisoformat(s[9]),
                               D.fromisoformat(s[10]) if s[10] else None, cfg.year)
        for d in dates:
            o = d.toordinal()
            i = bisect.bisect_left(lst, o - 3)
            if not (i < len(lst) and lst[i] <= o + 7):
                cases.append(("CR5", "SERIES", s[0], s[1], d.isoformat(), "HIGH" if s[5] in ("SALARY", "RENT") else "MEDIUM"))
    cases.sort(key=lambda c: (c[4], c[0], c[2]))
    return cases


def build_cases(ds, cfg):
    y = cfg.year
    r = rng_for(cfg, "cases")
    as_of = dt.datetime(y, 12, 31, 23, 59, 59)
    crow, erow = [], []
    for rule, st, sid, uid, ref, sev in detect_cases(ds, cfg):
        cid = ids.case_id(len(crow) + 1)
        opened = min(dt.datetime.combine(D.fromisoformat(ref) + dt.timedelta(days=1), dt.time(6, 0)),
                     dt.datetime(y, 12, 31, 23, 0, 0))
        assigned = opened + dt.timedelta(hours=1)
        closed = (opened + dt.timedelta(days=SLA[rule] * r.uniform(0.3, 1.0))).replace(microsecond=0)
        f = lambda x: x.isoformat()
        ev = [("OPENED", opened, "SYSTEM", f"RULE_{rule}")]
        status, role, closed_at, res = "OPEN", None, None, None
        if assigned <= as_of:
            ev.append(("ASSIGNED", assigned, "SYSTEM", "ROUTED_BY_POLICY"))
            status, role = "ASSIGNED", ROLE[rule]
            if closed <= as_of:
                res, closed_at, status = RES[rule], f(closed), "RESOLVED"
                ev.append(("RESOLVED", closed, role, res))
        crow.append([cid, CASE_TYPE[rule], st, sid, uid, ref, rule, sev, status, role, f(opened), closed_at, res])
        for et, ts, actor, note in ev:
            erow.append([ids.case_event_id(len(erow) + 1), cid, et, f(ts), actor, note])
    return crow, erow


# ------------------------------------------------------------------ insights
def build_insights(ds, cfg, excluded):
    y = cfg.year
    L = ledger_spend(ds, excluded)
    tax = {r[0] for r in ds.tables["category"]}
    tot, unmapped = defaultdict(int), defaultdict(int)
    for (u, p, c), v in L.items():
        tot[(u, p)] += v
    au = _maps(ds)[1]
    income = defaultdict(int)
    for r in ds.tables["transaction"]:
        if r[3] == "SAL" and r[9] > 0:
            income[(au[r[1]], r[7][:7])] += round(r[9] * 100)
    recs = []   # (user, period, order, cat, row-without-id)
    for b in ds.tables["budget"]:
        u, p, code, bud = b[1], b[3], b[2], round(b[6] * 100)
        end = b[5]
        if code not in tax:
            unmapped[(u, p)] += 1
            continue
        a = L.get((u, p, code), 0)
        ratio = a / bud
        if ratio > 1.0:
            recs.append((u, p, 1, code, [u, p, "BUDGET_OVER", code, b[0], a / 100, bud / 100, round(ratio, 4),
                                         "ALERT" if ratio >= 1.5 else "WARN", "IN1", end]))
        elif ratio >= 0.85:
            recs.append((u, p, 2, code, [u, p, "BUDGET_NEAR", code, b[0], a / 100, bud / 100, round(ratio, 4),
                                         "INFO", "IN2", end]))
    for (u, p), v in tot.items():
        inc = income.get((u, p), 0)
        ratio = round(v / inc, 4) if inc > 0 else None
        recs.append((u, p, 0, "", [u, p, "MONTHLY_SUMMARY", None, None, v / 100, inc / 100 if inc else None, ratio,
                                    "WARN" if (ratio or 0) > 1 else "INFO", "IN3",
                                    f"{p}-{_last(y, int(p[5:]))}"]))
    for (u, p), n in unmapped.items():
        recs.append((u, p, 3, "", [u, p, "BUDGET_CATEGORY_UNMAPPED", None, None, float(n), None, None, "WARN", "IN4",
                                    f"{p}-{_last(y, int(p[5:]))}"]))
    recs.sort(key=lambda x: x[:4])
    return [[ids.insight_id(i)] + x[4] for i, x in enumerate(recs, 1)]


def _last(y, m):
    return f"{(D(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day:02d}"


# --------------------------------------------------------------------- driver
def finish(ds, b):
    cfg = b.cfg
    brow, bev, bissues = build_budgets(b)
    ds.tables["budget"] = brow
    ds.tables["budget_event"] = [[ids.budget_event_id(i)] + e for i, e in enumerate(bev, 1)]
    crow, erow = build_cases(ds, cfg)
    ds.tables["exception_case"], ds.tables["case_event"] = crow, erow
    excluded = {c[3] for c in crow if c[6] == "CR1"}
    ds.tables["insight"] = build_insights(ds, cfg, excluded)
    issues = ds.meta.pop("_issues") + bissues
    ds.gt["gt_issue"] = [[ids.issue_id(i)] + x for i, x in enumerate(issues, 1)]
    ds.meta.pop("_builder", None)
    return ds
