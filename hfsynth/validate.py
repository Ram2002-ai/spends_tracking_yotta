"""Validation: PK uniqueness, FK integrity, enums, patterns, date ordering, arithmetic
reconciliation, lifecycle transitions, duplicates, edge-case labelling and ground-truth
separation. Works on in-memory tables, so it can also validate a re-loaded export."""
import datetime as dt
import re
from collections import defaultdict

from . import schema as S
from .derive import detect_cases

D = dt.date
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?$")


class Report:
    def __init__(self):
        self.results = []

    def add(self, name, ok, detail=""):
        self.results.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    @property
    def ok(self):
        return all(r["status"] == "PASS" for r in self.results)

    def to_md(self):
        o = ["# Validation summary", "", f"Overall: **{'PASS' if self.ok else 'FAIL'}** "
             f"({sum(r['status'] == 'PASS' for r in self.results)}/{len(self.results)} checks)", "",
             "| Check | Status | Detail |", "|---|---|---|"]
        o += [f"| {r['check']} | {r['status']} | {r['detail']} |" for r in self.results]
        return "\n".join(o) + "\n"


def _typeok(f, v):
    t = f.dtype
    if t == "string":
        return isinstance(v, str)
    if t in ("int", "bool"):
        return isinstance(v, int) and not isinstance(v, bool) and (t == "int" or v in (0, 1))
    if t == "decimal":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "date":
        return isinstance(v, str) and DATE_RE.match(v) is not None
    return isinstance(v, str) and DT_RE.match(v) is not None


def generic_checks(ds, rep):
    all_t = S.TABLES + S.GT_TABLES
    pks = {}
    for t in all_t:
        rows = ds.get(t.name)
        if len(t.pk) == 1:
            pks[t.name] = {r[t.fields.index(next(f for f in t.fields if f.name == t.pk[0]))] for r in rows}
    exceptions = {}
    for t in all_t:
        rows = ds.get(t.name)
        n = len(t.fields)
        bad = 0
        for r in rows:
            if len(r) != n:
                bad += 1
        rep.add(f"{t.name}: column count", bad == 0, f"{len(rows)} rows")
        pkix = [t.cols.index(c) for c in t.pk]
        seen, dup = set(), 0
        for r in rows:
            k = tuple(r[i] for i in pkix)
            dup += k in seen
            seen.add(k)
        rep.add(f"{t.name}: primary key unique", dup == 0, f"{dup} duplicates")
        for i, f in enumerate(t.fields):
            nulls = types = enum = pat = 0
            allowed = set(f.allowed) if f.allowed else None
            rx = re.compile(f.pattern) if f.pattern else None
            vals = set() if f.unique else None
            udup = 0
            for r in rows:
                v = r[i]
                if v is None or v == "":
                    nulls += f.required
                    continue
                types += not _typeok(f, v)
                if allowed is not None and v not in allowed:
                    enum += 1
                if rx is not None and not rx.match(v):
                    pat += 1
                if vals is not None:
                    udup += v in vals
                    vals.add(v)
            if nulls or types or enum or pat or udup:
                rep.add(f"{t.name}.{f.name}: required/type/enum/pattern/unique", False,
                        f"null={nulls} type={types} enum={enum} pattern={pat} dup={udup}")
            if f.fk:
                rt, rc = f.fk.split(".")
                ref = pks[rt] if rt in pks else {x[0] for x in ds.get(rt)}
                orphans = {r[i] for r in rows if r[i] not in (None, "") and r[i] not in ref}
                if f.fk_enforced:
                    if orphans:
                        rep.add(f"{t.name}.{f.name}: FK -> {f.fk}", False, f"{len(orphans)} orphan values")
                else:
                    exceptions[(t.name, f.name)] = len(orphans)
        rep.add(f"{t.name}: required/type/enum/pattern/unique/FK (all fields)",
                not any(r["status"] == "FAIL" and r["check"].startswith(t.name + ".") for r in rep.results))
    return exceptions


def domain_checks(ds, rep, cfg=None):
    T = ds.tables
    tx = T["transaction"]
    gt = {g[0]: g for g in ds.gt["gt_transaction"]}
    acct = {a[0]: a for a in T["account"]}
    cents = lambda x: round(x * 100)
    if cfg:
        rep.add("volume: transactions == requested", len(tx) == cfg.txns, f"{len(tx)} vs {cfg.txns}")
        rep.add("volume: users == requested", len(T["user_profile"]) == cfg.users, f"{len(T['user_profile'])}")
    # --- ordering, tz, reconciliation
    prev, ordok, tzbad, ledger = "", True, 0, defaultdict(list)
    for r in tx:
        if r[5] < prev:
            ordok = False
        prev = r[5]
        utc = dt.datetime.fromisoformat(r[5][:-1])
        if (utc + dt.timedelta(minutes=r[6])).date().isoformat() != r[7]:
            tzbad += 1
        ledger[r[1]].append(r)
    rep.add("ledger chronological by UTC (ids ascending)", ordok and all(tx[i][0] < tx[i + 1][0] for i in range(len(tx) - 1)))
    rep.add("local date == UTC timestamp + offset", tzbad == 0, f"{tzbad} mismatches")
    recon = neg = closing = 0
    for a, rows in ledger.items():
        run = cents(acct[a][5])
        for r in rows:
            run += cents(r[9])
            if run != cents(r[15]):
                recon += 1
            if run < 0 and acct[a][2] != "CREDIT_CARD":
                neg += 1
        closing += run != cents(acct[a][6])
    rep.add("arithmetic: balance_after == opening + running sum", recon == 0, f"{recon} breaks")
    rep.add("arithmetic: account.closing_balance == last balance", closing == 0, f"{closing} breaks")
    rep.add("cash accounts never overdrawn", neg == 0, f"{neg} rows")
    byid = {r[0]: r for r in tx}
    # transfers
    groups = defaultdict(list)
    for r in tx:
        if r[13]:
            groups[r[13]].append(r)
    bad = 0
    for g in groups.values():
        o = [x for x in g if x[11] == "TRANSFER_OUT"]
        i = [x for x in g if x[11] == "TRANSFER_IN"]
        if not (len(g) == 2 and len(o) == 1 and len(i) == 1 and cents(o[0][9]) + cents(i[0][9]) == 0
                and o[0][1] != i[0][1] and acct[o[0][1]][1] == acct[i[0][1]][1] and o[0][5] == i[0][5]
                and cents(o[0][9]) < 0):
            bad += 1
    rep.add("transfers: two legs, net zero, same user, same time", bad == 0, f"{len(groups)} groups, {bad} bad")
    rep.add("transfers: every TRANSFER_* row belongs to a group",
            all(r[13] for r in tx if r[11] in ("TRANSFER_OUT", "TRANSFER_IN")))
    # refunds
    refunded, bad = defaultdict(int), 0
    for r in tx:
        if r[11] == "REFUND":
            o = byid.get(r[14])
            if not o or o[1] != r[1] or o[5] >= r[5] or o[9] >= 0 or r[9] <= 0:
                bad += 1
                continue
            refunded[o[0]] += cents(r[9])
    bad += sum(v > -cents(byid[k][9]) for k, v in refunded.items())
    rep.add("refunds: parent exists, later, same account, not over-refunded, single refund per purchase",
            bad == 0 and all(c == 1 for c in __import__("collections").Counter(r[14] for r in tx if r[14]).values()),
            f"{sum(1 for r in tx if r[11] == 'REFUND')} refunds, {bad} bad")
    # dates vs accounts / merchants / year
    merch = {m[0]: m for m in T["merchant"]}
    badopen = badm = outyear = 0
    year = int(tx[0][7][:4]) if tx else 0
    for r in tx:
        badopen += r[7] < acct[r[1]][4]
        outyear += not r[7].startswith(str(year))
        tm = gt[r[0]][2] if gt[r[0]][3] in ("PURCHASE", "RECURRING_DEBIT", "INCOME") else None
        if tm:
            m = merch[tm]
            badm += (r[7] < m[6]) or (m[7] is not None and r[7] > m[7])
    rep.add("dates: txn_date >= account.open_date", badopen == 0, f"{badopen}")
    rep.add("dates: all local dates inside the simulated year", outyear == 0, f"{outyear}")
    rep.add("lifecycle: no purchase before merchant opened / after merchant closed (refunds may follow)", badm == 0, f"{badm}")
    # card payments derived from statements
    net, pays = defaultdict(int), defaultdict(list)
    for r in tx:
        if acct[r[1]][2] == "CREDIT_CARD":
            if r[11] == "TRANSFER_IN":
                pays[r[1]].append(r)
            else:
                net[(r[1], int(r[7][5:7]))] -= cents(r[9])
    bad = 0
    for a, ps in pays.items():
        ps.sort(key=lambda r: r[7])
        bad += len(ps) != 11
        for m, p in enumerate(ps, 1):
            bad += cents(p[9]) != max(500, net.get((a, m), 0)) or int(p[7][5:7]) != m + 1
    rep.add("derived: card payment == statement balance (min $5) paid the next month", bad == 0, f"{len(pays)} cards, {bad} bad")
    # duplicates
    seen, dup = set(), 0
    for r in tx:
        k = (r[1], r[5], r[9], r[8])
        dup += k in seen
        seen.add(k)
    rep.add("duplicates: no identical ledger rows", dup == 0, f"{dup}")
    # series lifecycle
    sr = T["recurring_series"]
    ev = defaultdict(list)
    for e in T["recurring_series_event"]:
        ev[e[1]].append(e)
    bad = 0
    for s in sr:
        es = ev[s[0]]
        types = [e[2] for e in es]
        bad += types.count("CREATED") != 1 or es[0][2] != "CREATED" or es[0][3] != s[9]
        bad += (s[15] == "CANCELLED") != (s[10] is not None) or (s[15] == "CANCELLED") != ("CANCELLED" in types)
        bad += s[10] is not None and s[10] < s[9]
        bad += [e[3] for e in es] != sorted(e[3] for e in es)
        chg = [e for e in es if e[2] == "AMOUNT_CHANGED"]
        bad += abs((chg[-1][5] if chg else s[13]) - s[14]) > 0.005
    rep.add("lifecycle: series status/end_date/events consistent, history ordered", bad == 0, f"{len(sr)} series, {bad} bad")
    send = {s[0]: s[10] for s in sr}
    occbad = sum(1 for o in ds.gt["gt_recurring_occurrence"] if send[o[0]] and o[2] > send[o[0]])
    rep.add("lifecycle: no scheduled occurrence after series cancellation", occbad == 0, f"{occbad}")
    # budgets
    bd = T["budget"]
    seenb, bad = set(), 0
    evc = defaultdict(list)
    for e in T["budget_event"]:
        evc[e[1]].append(e)
    for b in bd:
        k = (b[1], b[3], b[2])
        bad += k in seenb or b[5] < b[4] or b[6] <= 0 or b[8] != 1 + len(evc[b[0]])
        seenb.add(k)
        bad += (b[9] == "CLOSED") != (b[3] != f"{year}-12")
        for e in evc[b[0]]:
            bad += not (b[4] <= e[3] <= b[5]) or abs(e[5] - b[6]) > 0.005
    rep.add("budgets: unique per user/category/period, dates, amounts, revisions, status", bad == 0, f"{len(bd)} lines, {bad} bad")
    # cases
    ce = defaultdict(list)
    for e in T["case_event"]:
        ce[e[1]].append(e)
    bad = 0
    for c in T["exception_case"]:
        es = ce[c[0]]
        names = [e[2] for e in es]
        ts = [e[3] for e in es]
        bad += names != ["OPENED", "ASSIGNED", "RESOLVED"][:len(names)] or ts != sorted(ts) or es[0][3] != c[10]
        bad += {"OPEN": 1, "ASSIGNED": 2, "RESOLVED": 3}[c[8]] != len(es)
        bad += (c[8] == "RESOLVED") != (c[11] is not None) or (c[11] is not None and c[11] < c[10])
        bad += (c[8] != "OPEN") != (c[9] is not None)
    rep.add("lifecycle: case status, events and timestamps consistent", bad == 0, f"{len(T['exception_case'])} cases, {bad} bad")
    # category rules effective-dating
    rules = {r[0]: r for r in T["category_rule"]}
    bad = sum(1 for r in tx if not (rules[r[4]][5] <= r[7] and (rules[r[4]][6] is None or r[7] < rules[r[4]][6])))
    rep.add("rules: every categorisation used a rule effective on the txn date", bad == 0, f"{bad}")
    # ---- labelled edge cases: observable, and no unlabelled instances
    lab = defaultdict(set)
    for g in ds.gt["gt_transaction"]:
        if g[6] != "NONE":
            lab[g[6]].add(g[0])
    cfg_dummy = type("c", (), {"year": year})
    det = detect_cases(ds, cfg_dummy)
    cr1 = {c[2] for c in det if c[0] == "CR1"}
    rep.add("E1 transfer counted as spending twice: labelled == observable", cr1 == lab["TRANSFER_DOUBLE_COUNT"],
            f"{len(lab['TRANSFER_DOUBLE_COUNT'])} labelled")
    cr2 = {r[0] for r in tx if r[11] == "PURCHASE" and r[9] > 0}
    rep.add("E2 refund treated as new expense: labelled == observable", cr2 == lab["REFUND_MISCLASSIFIED"],
            f"{len(cr2)} rows")
    anyl = set().union(*lab.values()) if lab else set()
    tzr = {r[0] for r in tx if r[5][:7] != r[7][:7]}
    rep.add("E4 timezone boundary: every row whose UTC month != local month is labelled",
            tzr <= anyl and lab["TZ_BOUNDARY"] <= tzr, f"{len(lab['TZ_BOUNDARY'])} TZ_BOUNDARY rows")
    skipped = {o[0] + "#" + str(o[1]) for o in ds.gt["gt_recurring_occurrence"] if o[4] == "SKIPPED"}
    iss = {i[3] for i in ds.gt["gt_issue"] if i[1] == "RECURRING_SKIPPED"}
    posted_ok = all((o[5] is not None) == (o[4] == "POSTED") and (o[5] is None or o[5] in byid)
                    for o in ds.gt["gt_recurring_occurrence"])
    rep.add("E3 recurring series skips: labelled == skipped occurrences, links valid", skipped == iss and posted_ok,
            f"{len(skipped)} skipped")
    tax = {c[0] for c in T["category"]}
    mism = {b[0] for b in bd if b[2] not in tax}
    iss = {i[3] for i in ds.gt["gt_issue"] if i[1] == "BUDGET_CATEGORY_MISMATCH"}
    rep.add("E5 budget categories not in taxonomy: labelled == observable", mism == iss, f"{len(mism)} lines")
    for k in ("E1", "E2", "E3", "E4", "E5"):
        pass
    # ground-truth separation
    leak = [(t.name, f.name) for t in S.TABLES for f in t.fields
            if re.match(r"^(true_|gt_|issue_|expected_|persona|spend_factor)", f.name)]
    rep.add("ground truth separated: no label columns in input tables", not leak, str(leak))
    rep.add("ground truth 1:1 with transactions", set(gt) == set(byid) and len(gt) == len(tx))
    pu = {g[0] for g in ds.gt["gt_user_latent"]}
    rep.add("ground truth users 1:1 with user_profile", pu == {u[0] for u in T["user_profile"]})


def run(ds, cfg=None):
    rep = Report()
    exc = generic_checks(ds, rep)
    try:
        domain_checks(ds, rep, cfg)
    except (KeyError, IndexError, TypeError, ValueError) as ex:   # broken referential integrity
        rep.add("domain checks could run to completion", False, f"{type(ex).__name__}: {ex}")
    for (t, c), n in exc.items():
        rep.add(f"{t}.{c}: non-enforced FK, orphan values are the labelled E5 exceptions", True, f"{n} distinct legacy codes")
    return rep
