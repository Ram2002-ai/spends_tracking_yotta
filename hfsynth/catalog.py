"""Merchant catalogue, alias table, effective-dated category rules and the
rule-based classifier (the 'system under test' that produces category_code)."""
import bisect
import datetime as dt
import re

from . import ids, reference as R

TOKEN_RE = re.compile(r"[A-Z0-9]+")
PREFIX_RE = re.compile(
    r"^(?:POS PURCHASE|DEBIT CARD PURCHASE|CARD PURCHASE|SQ \*|TST\*|PAYPAL \*|ACH CREDIT PAYROLL|"
    r"ACH DEBIT RENT|RECURRING PMT|BILL PAY|AUTOPAY|REFUND)\s*")
RULE_START = "2025-01-01"


def alias_base(name):
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", name.upper()).split())


def mangle(name, rng):
    """Produce a descriptor that is NOT in the alias table (vowel-stripped)."""
    toks = alias_base(name).split()
    strip = lambda t: t[0] + re.sub(r"[AEIOU]", "", t[1:])
    if rng.random() < 0.5 and len(toks) > 1:
        return " ".join([strip(t) for t in toks[:-1]] + [toks[-1]])
    return " ".join(strip(t) for t in toks)


class Merchant:
    __slots__ = ("id", "name", "mtype", "mcc", "default_cat", "shares", "ambiguous", "aliases",
                 "opened", "closed", "om", "cm", "prices", "cadence")

    def active(self, month):
        return self.om <= month <= self.cm


class Catalog:
    def __init__(self, cfg, rng):
        self.cfg = cfg
        y = cfg.year
        self.merchants = []
        self.retail = {}            # cat -> [Merchant]
        self.ambiguous = []
        self.subs = []              # Merchant with prices/cadence
        self.util = {}              # kind -> [Merchant]
        self.insurers, self.landlords, self.employers = [], [], []

        def add(name, mtype, cat, mcc, shares=None):
            m = Merchant()
            m.id = ids.merchant_id(len(self.merchants) + 1)
            m.name, m.mtype, m.mcc = name, mtype, mcc
            m.shares = shares or {cat: 1.0}
            m.ambiguous = shares is not None
            m.default_cat = max(m.shares, key=lambda c: (m.shares[c], c)) if shares else cat
            m.aliases, m.opened, m.closed, m.om, m.cm = [], None, None, 1, 12
            m.prices, m.cadence = None, None
            self.merchants.append(m)
            return m

        for cat, names in R.RETAIL.items():
            self.retail[cat] = [add(n, R.TYPE_BY_CAT[cat], cat, R.MCC[cat]) for n in names]
        for name, shares in R.AMBIGUOUS:
            self.ambiguous.append(add(name, "MULTI_CATEGORY", None, "5399", shares))
        for name, prices, cad in R.SUBSCRIPTIONS:
            m = add(name, "SUBSCRIPTION", "SUB", R.MCC["SUB"])
            m.prices, m.cadence = prices, cad
            self.subs.append(m)
        for kind, spec in R.UTILITIES.items():
            self.util[kind] = [add(n, "UTILITY", "UTL", R.MCC["UTL"]) for n in spec["providers"]]
        self.insurers = [add(n, "INSURER", "INS", R.MCC["INS"]) for n in R.INSURERS]
        self.landlords = [add(n, "LANDLORD", "HOU", R.MCC["HOU"]) for n in R.LANDLORDS]
        self.employers = [add(n, "EMPLOYER", "SAL", None) for n in R.EMPLOYERS]

        # Lifecycle: a few retailers close / open during the year (month granularity).
        cats = [c for c, v in self.retail.items() if len(v) >= 4]
        rng.shuffle(cats)
        for c in cats[:4]:
            m = rng.choice(self.retail[c])
            mm = rng.randint(5, 10)
            m.cm, m.closed = mm, R_last(y, mm)
        for c in cats[4:7]:
            cand = [m for m in self.retail[c] if m.cm == 12]
            m = rng.choice(cand)
            mm = rng.randint(3, 8)
            m.om, m.opened = mm, dt.date(y, mm, 1)

        # Aliases (unique across the whole catalogue).
        used = set()
        for m in self.merchants:
            base = alias_base(m.name)
            m.aliases = [base]
            used.add(base)
        self.alias_rows = []
        for m in self.merchants:
            if m.mtype not in ("LANDLORD", "EMPLOYER"):
                short = m.aliases[0].split()[0]
                if len(short) >= 6 and short not in used:
                    m.aliases.append(short)
                    used.add(short)
            for i, a in enumerate(m.aliases):
                self.alias_rows.append([ids.alias_id(len(self.alias_rows) + 1), m.id, a, "FULL" if i == 0 else "SHORT_NAME"])
        self.alias_map = {r[2]: r[1] for r in self.alias_rows}
        self.by_id = {m.id: m for m in self.merchants}
        self.default_by_id = {m.id: m.default_cat for m in self.merchants}

        # Per (category, month) weighted candidate lists for discretionary spend.
        self.cands = {}
        for c in R.DISCRETIONARY:
            for mo in range(1, 13):
                ms, cum, t = [], [], 0.0
                for m in self.retail.get(c, []):
                    if m.active(mo):
                        t += 1.0
                        ms.append(m); cum.append(t)
                for m in self.ambiguous:
                    if c in m.shares:
                        t += 3.0 * m.shares[c]
                        ms.append(m); cum.append(t)
                self.cands[(c, mo)] = (ms, cum)

    def merchant_rows(self):
        rows = []
        for m in self.merchants:
            rows.append([m.id, m.name, m.mtype, m.mcc, m.default_cat, int(m.ambiguous),
                         (m.opened or dt.date(2015, 1, 1)).isoformat(),
                         m.closed.isoformat() if m.closed else None,
                         "CLOSED" if m.closed else "ACTIVE"])
        return rows

    def merchant_category_rows(self):
        rows = []
        for m in self.merchants:
            for c, s in sorted(m.shares.items()):
                rows.append([m.id, c, round(s, 4), int(c == m.default_cat)])
        return rows


def R_last(y, m):
    from .timeutil import last_day
    return last_day(y, m)


def build_rules(year):
    """Rule table rows. The MARKET keyword changes SHP->GRO on 1 Feb of `year`
    (rule drift) so categorisation depends on the effective date."""
    rows = []
    pro = f"{year}-02-01"

    def add(rtype, match, cat, prio, frm=RULE_START, to=None, status="ACTIVE"):
        rows.append([ids.rule_id(len(rows) + 1), rtype, match, cat, prio, frm, to, status])

    add("TXN_TYPE", "TRANSFER_OUT|TRANSFER_IN", "XFR", 10)
    add("KEYWORD", "PAYROLL", "SAL", 20)
    add("KEYWORD", "RENT", "HOU", 30)
    add("MERCHANT_ALIAS", "*", None, 40)
    prio = 100
    for cat, toks in R.KEYWORDS:
        for t in toks:
            if t == "MARKET":
                add("KEYWORD", t, "SHP", prio, RULE_START, pro, "RETIRED")
                add("KEYWORD", t, cat, prio, pro, None)
            else:
                add("KEYWORD", t, cat, prio)
            prio += 1
    add("FALLBACK", "*", "UNC", 999)
    return rows


class Engine:
    """Deterministic classifier. Order: txn-type rules -> high-priority keywords
    (PAYROLL, RENT) -> merchant alias default -> keywords -> fallback UNC."""

    def __init__(self, rule_rows, alias_map, default_by_id):
        self.rules = rule_rows
        self.alias_map = alias_map
        self.default_by_id = default_by_id
        self.cities = sorted({c for v in R.CITIES.values() for c in v}, key=len, reverse=True)
        self.bounds = sorted({r[5] for r in rule_rows} | {r[6] for r in rule_rows if r[6]})
        self._cache = {}

    def _compile(self, d):
        act = [r for r in self.rules if r[5] <= d and (r[6] is None or d < r[6])]
        c = {"type": {}, "hi": {}, "lo": {}, "alias": None, "fb": None}
        for rid, rtype, match, cat, prio, *_ in act:
            if rtype == "TXN_TYPE":
                for t in match.split("|"):
                    c["type"][t] = (cat, rid)
            elif rtype == "KEYWORD":
                c["hi" if prio < 40 else "lo"][match] = (prio, cat, rid)
            elif rtype == "MERCHANT_ALIAS":
                c["alias"] = rid
            else:
                c["fb"] = (cat, rid)
        return c

    def normalize(self, desc):
        s = desc.upper().strip()
        while True:
            m = PREFIX_RE.match(s)
            if m and m.end() > 0:
                s = s[m.end():]
            else:
                break
        s = " ".join(t for t in s.split() if not any(ch.isdigit() for ch in t))
        for city in self.cities:
            if s.endswith(" " + city):
                s = s[: -len(city) - 1]
                break
        return s

    def resolve_merchant(self, desc):
        return self.alias_map.get(self.normalize(desc))

    def classify(self, desc, ttype, date_iso):
        ep = bisect.bisect_right(self.bounds, date_iso)
        c = self._cache.get(ep)
        if c is None:
            c = self._cache[ep] = self._compile(date_iso)
        if ttype in c["type"]:
            cat, rid = c["type"][ttype]
            return None, cat, rid
        toks = TOKEN_RE.findall(desc.upper())
        mid = self.resolve_merchant(desc)
        best = None
        for t in toks:
            h = c["hi"].get(t)
            if h and (best is None or h[0] < best[0]):
                best = h
        if best:
            return mid, best[1], best[2]
        if mid and c["alias"]:
            return mid, self.default_by_id[mid], c["alias"]
        for t in toks:
            h = c["lo"].get(t)
            if h and (best is None or h[0] < best[0]):
                best = h
        if best:
            return mid, best[1], best[2]
        return mid, c["fb"][0], c["fb"][1]
