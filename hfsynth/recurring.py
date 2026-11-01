"""Recurring series model: schedule derivation and per-user series construction."""
import calendar
import datetime as dt

from . import reference as R

SKIP_TYPES = {"SUBSCRIPTION", "UTILITY", "INSURANCE", "SAVINGS_TRANSFER"}
D = dt.date


def expected_dates(cadence, anchor, start, end, year):
    """Scheduled dates inside `year`, bounded by [start, end]. Shared by the
    generator and the missed-payment detector so both use one schedule model."""
    ys, ye = D(year, 1, 1), D(year, 12, 31)
    out = []
    if cadence == "BIWEEKLY":
        d = anchor
        if d < ys:
            d += dt.timedelta(days=14 * ((ys - d).days // 14))
            if d < ys:
                d += dt.timedelta(days=14)
        while d <= ye:
            out.append(d)
            d += dt.timedelta(days=14)
    elif cadence == "SEMI_MONTHLY":
        for m in range(1, 13):
            out += [D(year, m, 15), D(year, m, calendar.monthrange(year, m)[1])]
    elif cadence == "MONTHLY":
        for m in range(1, 13):
            out.append(D(year, m, min(anchor.day, calendar.monthrange(year, m)[1])))
    elif cadence == "ANNUAL":
        out.append(D(year, anchor.month, min(anchor.day, calendar.monthrange(year, anchor.month)[1])))
    return [d for d in out if d >= start and (end is None or d <= end)]


class Series:
    __slots__ = ("sid", "uid", "acct", "counter", "merchant", "stype", "cat", "cadence", "anchor", "start",
                 "end", "direction", "variable", "base", "changes", "kind", "channel", "tmpl", "hours")

    def amount_at(self, d):
        amt = self.base
        for cd, _o, n in self.changes:
            if d >= cd:
                amt = n
        return amt

    @property
    def current(self):
        return self.changes[-1][2] if self.changes else self.base


def _cents(x):
    return int(round(x * 100))


def build_user_series(cfg, cat, u, r):
    y = cfg.year
    ys = D(y, 1, 1)
    out = []

    def mk(stype, merchant, acct, cadence, anchor, start, base, cat_code, direction, channel, tmpl,
           variable=False, kind=None, counter=None, end=None):
        s = Series()
        s.sid, s.uid, s.acct, s.counter, s.merchant = None, u.uid, acct, counter, merchant
        s.stype, s.cat, s.cadence, s.anchor, s.start, s.end = stype, cat_code, cadence, anchor, start, end
        s.direction, s.variable, s.base, s.changes, s.kind = direction, variable, base, [], kind
        s.channel, s.tmpl = channel, tmpl
        s.hours = R.SERIES_HOURS["SUBSCRIPTION" if stype == "SUBSCRIPTION" else stype]
        out.append(s)
        return s

    # ---- salary (optionally followed by a job change) ---------------------
    per = {"BIWEEKLY": 26, "SEMI_MONTHLY": 24, "MONTHLY": 12}[u.pay_freq]
    pay = _cents(u.income * 12 / per)
    emp = r.choice(cat.employers)
    if u.pay_freq == "BIWEEKLY":
        anchor = D(y - 1, 12, 1) + dt.timedelta(days=r.randint(0, 13))
    elif u.pay_freq == "SEMI_MONTHLY":
        anchor = D(y - 1, 12, 15)
    else:
        anchor = D(y - 1, 12, r.choice([1, 15, 28]))
    s1 = mk("SALARY", emp, u.acct_chk, u.pay_freq, anchor, D(y - 2, 1, 1), pay, "SAL", "CREDIT", "ACH",
            R.SERIES_DESC["SALARY"])
    if r.random() < 0.15:
        cd = D(y, r.randint(3, 9), 1)
        s1.changes.append((cd, pay, int(round(pay * r.uniform(1.03, 1.08)))))
    if r.random() < 0.03:
        m = r.randint(5, 9)
        s1.end = D(y, m, calendar.monthrange(y, m)[1])
        st = s1.end + dt.timedelta(days=1)
        emp2 = r.choice([e for e in cat.employers if e is not emp])
        a2 = st + dt.timedelta(days=r.randint(0, 13)) if u.pay_freq == "BIWEEKLY" else st
        mk("SALARY", emp2, u.acct_chk, u.pay_freq, a2, st, int(round(pay * r.uniform(0.9, 1.3))), "SAL",
           "CREDIT", "ACH", R.SERIES_DESC["SALARY"])

    # ---- rent ---------------------------------------------------------------
    if r.random() < 0.85:
        rent = int(round(u.income * r.uniform(0.22, 0.34) / 5)) * 500
        s = mk("RENT", r.choice(cat.landlords), u.acct_chk, "MONTHLY",
               D(y - 1, 12, r.choice([1, 1, 1, 1, 2, 3, 5])), D(y - 2, 1, 1), rent, "HOU", "DEBIT", "ACH",
               R.SERIES_DESC["RENT"])
        if r.random() < 0.10:
            s.changes.append((D(y, r.randint(6, 10), 1), rent, int(round(rent * 1.04 / 100.0)) * 100))

    # ---- utilities ----------------------------------------------------------
    for kind, spec in R.UTILITIES.items():
        if r.random() < spec["prob"]:
            prov = r.choice(cat.util[kind])
            base = spec["base"] * (0.7 + 0.15 * u.hh) * r.uniform(0.8, 1.25)
            cents = _cents(base) if spec["variable"] else _cents(round(base / 5) * 5 - 0.01)
            mk("UTILITY", prov, u.acct_chk, "MONTHLY", D(y - 1, 12, r.randint(3, 25)), D(y - 2, 1, 1), cents,
               "UTL", "DEBIT", "BILL_PAY", R.SERIES_DESC["UTILITY"], variable=spec["variable"], kind=kind)

    # ---- insurance ----------------------------------------------------------
    n = r.choices([0, 1, 2], [0.2, 0.6, 0.2])[0]
    for ins in r.sample(cat.insurers, n):
        mk("INSURANCE", ins, u.acct_chk, "MONTHLY", D(y - 1, 12, r.randint(5, 25)), D(y - 2, 1, 1),
           int(round(r.uniform(70, 260) * 2)) * 50, "INS", "DEBIT", "BILL_PAY", R.SERIES_DESC["INSURANCE"])

    # ---- subscriptions --------------------------------------------------------
    monthly = [m for m in cat.subs if m.cadence == "MONTHLY"]
    annual = [m for m in cat.subs if m.cadence == "ANNUAL"]
    k = min(r.choices(range(8), [8, 12, 18, 20, 16, 12, 8, 6])[0], len(monthly))
    for m in r.sample(monthly, k):
        price = _cents(r.choice(m.prices))
        acct = u.acct_card if (u.acct_card and r.random() < 0.5) else u.acct_chk
        if r.random() < 0.82:
            start = D(y - 1, r.randint(1, 12), r.randint(1, 28))
        else:
            start = D(y, r.randint(2, 10), r.randint(1, 28))
        s = mk("SUBSCRIPTION", m, acct, "MONTHLY", start, start, price, "SUB", "DEBIT", "CARD_ONLINE",
               R.SERIES_DESC["SUBSCRIPTION"])
        lo = 4 if start < ys else start.month + 1
        if r.random() < 0.12 and lo <= 11:
            s.end = D(y, r.randint(lo, 11), r.randint(1, 28))
        if r.random() < 0.20:
            cd = D(y, r.randint(3, 10), 1)
            if cd > start and (s.end is None or cd < s.end):
                s.changes.append((cd, price, int(round(price * r.uniform(1.05, 1.15)))))
    for m in annual:
        if r.random() < 0.15:
            a = D(y - 1, r.randint(1, 12), r.randint(1, 28))
            acct = u.acct_card if (u.acct_card and r.random() < 0.5) else u.acct_chk
            mk("SUBSCRIPTION", m, acct, "ANNUAL", a, a, _cents(r.choice(m.prices)), "SUB", "DEBIT",
               "CARD_ONLINE", R.SERIES_DESC["SUBSCRIPTION"])

    # ---- savings transfer -----------------------------------------------------
    if r.random() < 0.8:
        amt = max(2500, int(round(u.income * r.uniform(0.04, 0.12) / 25)) * 2500)
        mk("SAVINGS_TRANSFER", None, u.acct_chk, "MONTHLY", D(y - 1, 12, r.randint(2, 6)), D(y - 2, 1, 1),
           amt, "XFR", "TRANSFER", "TRANSFER", "ONLINE TRANSFER TO SAVINGS {ref}", counter=u.acct_sav)
    return out
