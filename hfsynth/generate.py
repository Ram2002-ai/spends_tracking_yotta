"""Core generator: master data first, then dependent ledger/event records.

Stages (all randomness comes from per-stage seeded streams, so output is
byte-for-byte reproducible for a given seed and scale):
  1 users/accounts/series -> 2 scheduled (recurring) rows -> 3 discretionary purchases
  4 labelled edge cases (tz boundary, refunds) -> 5 card statements/payments (derived)
  6 transfer duplicates -> 7 IDs, classification, balances -> 8 tables + ground truth
"""
import bisect
import datetime as dt
import math
import random
from collections import defaultdict

from . import ids, reference as R
from .catalog import Catalog, Engine, build_rules, mangle
from .recurring import SKIP_TYPES, build_user_series, expected_dates
from .schema import Dataset
from .timeutil import iso_utc, last_day, local_to_utc

D = dt.date


def rng_for(cfg, *parts):
    return random.Random(f"{cfg.seed}:" + ":".join(str(p) for p in parts))


class User:
    __slots__ = ("idx", "uid", "age_band", "persona", "spend_factor", "pmult", "tz", "region", "std_off",
                 "cities", "city", "income", "hh", "pay_freq", "signup", "sav_open", "card_open",
                 "acct_chk", "acct_sav", "acct_card", "inc_factor", "disc_weight", "fav", "n_disc",
                 "card_months")


def make_user(cfg, i):
    r = rng_for(cfg, "user", i)
    u = User()
    u.idx, u.uid = i, ids.user_id(i)
    u.age_band = r.choices([a for a, _ in R.AGE_BANDS], [w for _, w in R.AGE_BANDS])[0]
    pn = list(R.PERSONAS)
    u.persona = r.choices(pn, [R.PERSONAS[p][0] for p in pn])[0]
    u.spend_factor, u.pmult = R.PERSONAS[u.persona][1], R.PERSONAS[u.persona][2]
    tz = r.choices(R.TIMEZONES, [t[3] for t in R.TIMEZONES])[0]
    u.tz, u.region, u.std_off = tz[0], tz[1], tz[2]
    u.cities = R.CITIES[u.tz]
    u.city = r.choice(u.cities)
    u.income = int(round(min(15000, max(2200, r.lognormvariate(math.log(4800), 0.45))) / 10) * 10)
    u.hh = r.choices([1, 2, 3, 4, 5], [0.25, 0.30, 0.20, 0.15, 0.10])[0]
    u.pay_freq = r.choices(["BIWEEKLY", "SEMI_MONTHLY", "MONTHLY"], [0.55, 0.25, 0.20])[0]
    u.signup = D(cfg.year - 3, 1, 1) + dt.timedelta(days=r.randint(0, 1095))
    cap = D(cfg.year - 1, 12, 31)
    u.sav_open = min(u.signup + dt.timedelta(days=r.randint(0, 60)), cap)
    has_card = r.random() < 0.55
    u.card_open = min(u.signup + dt.timedelta(days=r.randint(30, 400)), cap) if has_card else None
    u.acct_chk = ids.account_id(u.uid, 1)
    u.acct_sav = ids.account_id(u.uid, 2)
    u.acct_card = ids.account_id(u.uid, 3) if has_card else None
    u.inc_factor = (u.income / 4800) ** 0.4
    u.disc_weight = u.spend_factor * (u.income / 4800) ** 0.35 * r.lognormvariate(0, 0.25)
    u.fav, u.n_disc, u.card_months = {}, 0, set()
    return u


class Txn:
    __slots__ = ("seq", "u", "acct", "ttype", "local", "utc", "off", "cents", "merch", "core", "desc", "channel",
                 "true_cat", "true_type", "issue", "group", "rel", "series", "resolved", "txn_id", "gid", "pref",
                 "mid", "cat", "rid")

    def set_local(self, local):
        self.utc, self.off, self.local = local_to_utc(local, self.u.std_off)


def largest_remainder(total, weights):
    s = float(sum(weights))
    q = [total * w / s for w in weights]
    base = [int(x) for x in q]
    rem = total - sum(base)
    order = sorted(range(len(q)), key=lambda i: (-(q[i] - base[i]), i))
    for i in order[:rem]:
        base[i] += 1
    return base


class Builder:
    def __init__(self, cfg):
        self.cfg = cfg
        self.year = cfg.year
        self.txns, self.seq = [], 0
        self.catalog = Catalog(cfg, rng_for(cfg, "catalog"))
        self.users = [make_user(cfg, i) for i in range(1, cfg.users + 1)]
        self.series, self.occ = [], []        # occ: [series, k, expected_date, amount, txn_or_None]
        self.out_legs = []                    # transfer-out legs eligible for duplication
        self.purch = []
        self.rules = build_rules(cfg.year)
        self.engine = Engine(self.rules, self.catalog.alias_map, self.catalog.default_by_id)
        self.cat_spending = R.CAT_SPENDING

    # ------------------------------------------------------------------ util
    def new(self, u, acct, ttype, local, cents, desc, channel, true_cat, true_type, merch=None, core=None,
            resolved=0, series=None):
        t = Txn()
        self.seq += 1
        t.seq, t.u, t.acct, t.ttype, t.cents, t.desc, t.channel = self.seq, u, acct, ttype, cents, desc, channel
        t.true_cat, t.true_type, t.merch, t.core, t.resolved, t.series = true_cat, true_type, merch, core, resolved, series
        t.issue, t.group, t.rel, t.gid = "", None, None, None
        t.set_local(local)
        self.txns.append(t)
        return t

    def transfer(self, u, src, dst, local, cents, desc_out, desc_in, series=None):
        o = self.new(u, src, "TRANSFER_OUT", local, -cents, desc_out, "TRANSFER", "XFR", "TRANSFER_OUT", series=series)
        i = self.new(u, dst, "TRANSFER_IN", local, cents, desc_in, "TRANSFER", "XFR", "TRANSFER_IN", series=series)
        o.group = i.group = [o, i]
        self.out_legs.append(o)
        return o, i

    # ------------------------------------------------- stage 1/2: recurring
    def stage_series(self):
        cfg, y = self.cfg, self.year
        for u in self.users:
            r = rng_for(cfg, "series", u.uid)
            for s in build_user_series(cfg, self.catalog, u, r):
                s.sid = ids.series_id(len(self.series) + 1)
                self.series.append(s)
                self._occurrences(u, s, r)

    def _occurrences(self, u, s, r):
        cfg, y = self.cfg, self.year
        dates = expected_dates(s.cadence, s.anchor, s.start, s.end, y)
        n = len(dates)
        skippable = s.stype in SKIP_TYPES and s.cadence == "MONTHLY"
        alias = s.merchant.aliases[0] if s.merchant else ""
        for k, exp in enumerate(dates):
            if s.variable:
                amt = int(round(s.amount_at(exp) * R.UTIL_SEASON[s.kind][exp.month - 1] * r.lognormvariate(0, 0.07)))
            else:
                amt = s.amount_at(exp)
            skipped = skippable and 0 < k < n - 1 and r.random() < cfg.skip_rate
            lag = 0 if s.stype in ("SALARY", "RENT", "SAVINGS_TRANSFER") else r.choice([0, 0, 0, 1, 1, 2])
            hour = r.randint(s.hours[0], s.hours[1] - 1)
            minute, sec = r.randint(0, 59), r.randint(0, 59)
            ref = r.randint(100000, 999999)
            occ = [s, k + 1, exp, amt, None]
            self.occ.append(occ)
            if skipped:
                continue
            act = min(exp + dt.timedelta(days=lag), D(y, 12, 31))
            local = dt.datetime(act.year, act.month, act.day, hour, minute, sec)
            desc = s.tmpl.format(alias=alias, ref=ref)
            if s.stype == "SAVINGS_TRANSFER":
                o, _ = self.transfer(u, s.acct, s.counter, local, amt, desc, f"ONLINE TRANSFER FROM CHECKING {ref}", s)
                occ[4] = o
                continue
            if s.stype == "SALARY":
                t = self.new(u, s.acct, "INCOME", local, amt, desc, "ACH", "SAL", "INCOME", s.merchant, alias, 1, s)
            else:
                t = self.new(u, s.acct, "RECURRING_DEBIT", local, -amt, desc, s.channel, s.cat, "RECURRING_DEBIT",
                             s.merchant, alias, 1, s)
                if s.acct == u.acct_card:
                    u.card_months.add(t.local.month)
            occ[4] = t

    # --------------------------------------------- stage 3: discretionary
    def _cat_tables(self):
        self.catw = {}
        for p, (_pr, _f, pm) in R.PERSONAS.items():
            for m in range(1, 13):
                cats = R.DISCRETIONARY
                cum, t = [], 0.0
                for c in cats:
                    t += R.CAT_MODEL[c][0] * R.SEASON[c][m - 1] * pm.get(c, 1.0)
                    cum.append(t)
                self.catw[(p, m)] = (cats, cum)

    def _pick_merchant(self, r, u, cat, month):
        fav = u.fav.get(cat)
        if fav is None:
            reg = self.catalog.retail[cat]
            fav = u.fav[cat] = r.sample(reg, 2)
        if r.random() < 0.55:
            m = r.choice(fav)
            if m.active(month):
                return m
        ms, cum = self.catalog.cands[(cat, month)]
        return r.choices(ms, cum_weights=cum)[0]

    def stage_discretionary(self, n_disc):
        cfg, y = self.cfg, self.year
        self._cat_tables()
        counts = largest_remainder(n_disc, [u.disc_weight for u in self.users])
        for u, n in zip(self.users, counts):
            u.n_disc = n
            r = rng_for(cfg, "disc", u.uid)
            months = r.choices(range(1, 13), weights=R.MONTH_ACTIVITY, k=n)
            mine = []
            for mo in months:
                cats, cum = self.catw[(u.persona, mo)]
                cat = r.choices(cats, cum_weights=cum)[0]
                m = self._pick_merchant(r, u, cat, mo)
                resolved = 1 if (m.ambiguous or r.random() >= cfg.unresolved_rate) else 0
                core = r.choice(m.aliases) if resolved else mangle(m.name, r)
                day = r.randint(1, 28 if mo == 2 else 30 if mo in (4, 6, 9, 11) else 31)
                hour = bisect.bisect_left(R.HOUR_CUM, r.random() * R.HOUR_CUM[-1])
                local = dt.datetime(y, mo, day, min(hour, 23), r.randint(0, 59), r.randint(0, 59))
                _w, med, sig = R.CAT_MODEL[cat]
                cents = max(100, int(round(r.lognormvariate(math.log(med * u.spend_factor * u.inc_factor), sig) * 100)))
                p = r.choice(R.PREFIXES)
                desc = p + ("" if (p == "" or p.endswith("*")) else " ") + core
                if r.random() < 0.6:
                    desc += f" #{r.randint(100, 9999)}"
                if r.random() < 0.5:
                    desc += " " + u.city
                acct = u.acct_card if (u.acct_card and r.random() < 0.45) else u.acct_chk
                chan = "CARD_ONLINE" if r.random() < (0.55 if cat in ("SHP", "ENT") else 0.2) else "CARD_POS"
                t = self.new(u, acct, "PURCHASE", local, -cents, desc, chan, cat, "PURCHASE", m, core, resolved)
                mine.append(t)
            if u.acct_card:  # every month 1..11 needs a card charge so a statement exists
                have = {t.local.month for t in mine if t.acct == u.acct_card} | u.card_months
                for mo in range(1, 12):
                    if mo not in have:
                        for t in mine:
                            if t.local.month == mo:
                                t.acct = u.acct_card
                                break
            self.purch.extend(mine)

    # ------------------------------------------------ stage 4: edge cases
    def stage_edge_cases(self, n_tz, n_refund, n_mis):
        y = self.year
        r = rng_for(self.cfg, "edge")
        for i in r.sample(range(len(self.purch)), n_tz):          # E4: last local evening of a month
            t = self.purch[i]
            m = t.local.month
            t.set_local(dt.datetime(y, m, last_day(y, m).day, r.randint(21, 23), r.randint(0, 59), r.randint(0, 59)))
            t.issue = "TZ_BOUNDARY"
        cut = D(y, 12, 10)
        cand = [i for i, t in enumerate(self.purch) if t.local.date() <= cut]
        picks = r.sample(cand, n_refund + n_mis)
        for j, i in enumerate(picks):
            o = self.purch[i]
            mis = j >= n_refund
            amt = -o.cents if r.random() < 0.7 else int(round(-o.cents * r.uniform(0.3, 0.9)))
            amt = max(amt, 100)
            day = o.local.date() + dt.timedelta(days=r.randint(2, 21))
            hour = bisect.bisect_left(R.HOUR_CUM, r.random() * R.HOUR_CUM[-1])
            local = dt.datetime(day.year, day.month, day.day, min(hour, 23), r.randint(0, 59), r.randint(0, 59))
            desc = f"REFUND {o.core} {r.randint(100000, 999999)}"
            t = self.new(o.u, o.acct, "PURCHASE" if mis else "REFUND", local, amt, desc, o.channel, o.true_cat,
                         "REFUND", o.merch, o.core, o.resolved)
            t.rel = o
            if mis:
                t.issue = "REFUND_MISCLASSIFIED"

    # --------------------------------------- stage 5: card statements (derived)
    def stage_card_payments(self):
        r = rng_for(self.cfg, "cardpay")
        y = self.year
        net = defaultdict(int)
        for t in self.txns:
            if t.acct.endswith("-03"):
                net[(t.acct, t.local.month)] -= t.cents
        for u in self.users:
            if not u.acct_card:
                continue
            for m in range(1, 12):
                pay = max(500, net.get((u.acct_card, m), 0))      # statement balance, $5.00 minimum
                day = D(y, m + 1, r.randint(15, 25))
                local = dt.datetime(day.year, day.month, day.day, r.randint(8, 17), r.randint(0, 59), r.randint(0, 59))
                self.transfer(u, u.acct_chk, u.acct_card, local, pay, f"ONLINE PAYMENT TO CARD {r.randint(100000, 999999)}",
                              "PAYMENT RECEIVED THANK YOU")

    # ------------------------------------------- stage 6: transfer duplicates
    def stage_duplicates(self, n_dup):
        r = rng_for(self.cfg, "dup")
        legs = sorted(self.out_legs, key=lambda t: t.seq)
        for o in r.sample(legs, n_dup):                              # E1
            local = o.local + dt.timedelta(minutes=r.randint(1, 20))
            if local.date() != o.local.date():
                local = o.local - dt.timedelta(minutes=r.randint(1, 20))
            t = self.new(o.u, o.acct, "PURCHASE", local, o.cents, f"MOBILE PAYMENT REF {r.randint(100000, 999999)}",
                         "ACH", "XFR", "TRANSFER_DUPLICATE")
            t.rel, t.issue = o, "TRANSFER_DOUBLE_COUNT"

    # ------------------------------------------------------------ finalize
    def finalize(self):
        cfg, y = self.cfg, self.year
        tx = self.txns
        tx.sort(key=lambda t: (t.utc, t.acct, t.seq))
        k = 0
        for n, t in enumerate(tx, 1):
            t.txn_id = ids.txn_id(y, n)
            if t.group is not None and t.ttype == "TRANSFER_OUT":
                k += 1
                g = ids.transfer_group_id(k)
                t.group[0].gid = t.group[1].gid = g
        pref, mn = defaultdict(int), defaultdict(int)
        for t in tx:
            t.mid, t.cat, t.rid = self.engine.classify(t.desc, t.ttype, t.local.date().isoformat())
            if not t.issue and t.utc.month != t.local.month:   # natural month-boundary crossings are labelled too
                t.issue = "TZ_BOUNDARY"
            pref[t.acct] += t.cents
            t.pref = pref[t.acct]
            if t.pref < mn[t.acct]:
                mn[t.acct] = t.pref
        r = rng_for(cfg, "open")
        opening = {}
        for u in self.users:
            base = int(round(u.income * r.uniform(1.0, 2.5) / 100)) * 10000
            opening[u.acct_chk] = max(base, -mn[u.acct_chk] + 20000)
            opening[u.acct_sav] = r.randint(5, 200) * 10000
            if u.acct_card:
                opening[u.acct_card] = 0
        self.opening = opening
        self.final_pref = pref

    def tables(self):
        cfg, y = self.cfg, self.year
        ds = Dataset()
        T = ds.tables
        T["category"] = [[c[0], c[1], c[2], c[3], c[4], c[5]] for c in R.CATEGORIES]
        T["user_profile"] = [[u.uid, u.age_band, u.region, u.tz, u.hh, float(u.income), u.pay_freq,
                              u.signup.isoformat(), "ACTIVE"] for u in self.users]
        acc = []
        for u in self.users:
            for aid, typ, od in ((u.acct_chk, "CHECKING", u.signup), (u.acct_sav, "SAVINGS", u.sav_open),
                                 (u.acct_card, "CREDIT_CARD", u.card_open)):
                if aid:
                    o = self.opening[aid]
                    acc.append([aid, u.uid, typ, "USD", od.isoformat(), o / 100,
                                (o + self.final_pref.get(aid, 0)) / 100, "ACTIVE"])
        T["account"] = acc
        T["merchant"] = self.catalog.merchant_rows()
        T["merchant_alias"] = self.catalog.alias_rows
        T["merchant_category"] = self.catalog.merchant_category_rows()
        T["category_rule"] = self.rules
        opening = self.opening
        rows, gt = [], []
        for t in self.txns:
            rows.append([t.txn_id, t.acct, t.mid, t.cat, t.rid, iso_utc(t.utc), t.off, t.local.date().isoformat(),
                         t.desc, t.cents / 100, "USD", t.ttype, t.channel, t.gid,
                         t.rel.txn_id if (t.rel is not None and t.ttype == "REFUND") else None,
                         (opening[t.acct] + t.pref) / 100])
            spend = -t.cents if (t.true_type in ("PURCHASE", "RECURRING_DEBIT", "REFUND")
                                 and self.cat_spending[t.true_cat]) else 0
            gt.append([t.txn_id, t.true_cat, t.merch.id if t.merch else None, t.true_type, spend / 100,
                       t.local.date().isoformat()[:7], t.issue or "NONE", t.resolved,
                       int(bool(t.merch and t.merch.ambiguous)), t.rel.txn_id if t.rel is not None else None,
                       t.series.sid if t.series is not None else None])
        T["transaction"] = rows
        ds.gt["gt_transaction"] = gt
        # series + history
        srows, ev = [], []
        for s in self.series:
            srows.append([s.sid, s.uid, s.acct, s.counter, s.merchant.id if s.merchant else None, s.stype, s.cat,
                          s.cadence, s.anchor.isoformat(), s.start.isoformat(), s.end.isoformat() if s.end else None,
                          s.direction, "VARIABLE" if s.variable else "FIXED", s.base / 100, s.current / 100,
                          "CANCELLED" if s.end else "ACTIVE"])
            ev.append([s.start, 0, s.sid, "CREATED", None, s.base / 100])
            for cd, o, n in s.changes:
                ev.append([cd, 1, s.sid, "AMOUNT_CHANGED", o / 100, n / 100])
            if s.end:
                ev.append([s.end, 2, s.sid, "CANCELLED", None, None])
        ev.sort(key=lambda e: (e[2], e[0], e[1]))
        T["recurring_series"] = srows
        T["recurring_series_event"] = [[ids.series_event_id(i), e[2], e[3], e[0].isoformat(), e[4], e[5]]
                                       for i, e in enumerate(ev, 1)]
        occ = []
        for s, k, exp, amt, t in self.occ:
            occ.append([s.sid, k, exp.isoformat(), amt / 100, "POSTED" if t else "SKIPPED",
                        t.txn_id if t else None, t.local.date().isoformat() if t else None])
        ds.gt["gt_recurring_occurrence"] = occ
        ds.gt["gt_user_latent"] = [[u.uid, u.persona, u.spend_factor] for u in self.users]
        # issue registry (budget issues appended later)
        issues = []
        for t in self.txns:
            if t.issue == "TRANSFER_DOUBLE_COUNT":
                issues.append([t.issue, "TRANSACTION", t.txn_id, t.u.uid, "spend 0 (internal transfer)",
                               f"PURCHASE {t.cents / 100:.2f}", f"duplicates transfer leg {t.rel.txn_id}"])
            elif t.issue == "REFUND_MISCLASSIFIED":
                issues.append([t.issue, "TRANSACTION", t.txn_id, t.u.uid, "REFUND", "PURCHASE",
                               f"credit of original {t.rel.txn_id}"])
            elif t.issue == "TZ_BOUNDARY":
                issues.append([t.issue, "TRANSACTION", t.txn_id, t.u.uid, t.local.strftime("%Y-%m"),
                               t.utc.strftime("%Y-%m"), "local evening spills into next UTC month"])
        for s, k, exp, amt, t in self.occ:
            if t is None:
                issues.append(["RECURRING_SKIPPED", "SERIES_OCCURRENCE", f"{s.sid}#{k}", s.uid, exp.isoformat(), None,
                               f"{s.stype} occurrence not posted while series ACTIVE"])
        ds.meta["_issues"] = issues
        return ds


def build(cfg):
    cfg.validate()
    b = Builder(cfg)
    b.stage_series()
    T = cfg.txns
    sched = len(b.txns)
    cards = sum(1 for u in b.users if u.acct_card)
    S = sched + cards * 22
    n_dup = max(1, round(cfg.rate_transfer_dup * T))
    n_mis = max(1, round(cfg.rate_refund_misclassified * T))
    n_tz = max(1, round(cfg.rate_tz_boundary * T))
    avail = T - S - n_dup - n_mis
    if avail <= 0:
        raise ValueError(f"txns={T} too small: scheduled rows alone are {S}")
    n_ref = round(avail * cfg.refund_rate / (1 + cfg.refund_rate))
    n_disc = avail - n_ref
    if n_dup > sched // 4 + cards * 11:
        raise ValueError("too many duplicates requested")
    b.stage_discretionary(n_disc)
    b.stage_edge_cases(n_tz, n_ref, n_mis)
    b.stage_card_payments()
    b.stage_duplicates(n_dup)
    assert len(b.txns) == T, (len(b.txns), T)
    b.finalize()
    ds = b.tables()
    ds.meta["_builder"] = b
    return ds
