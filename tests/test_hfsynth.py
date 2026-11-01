"""Test-suite (stdlib unittest; also runs under pytest).  Run:  python -m unittest discover -s tests -v"""
import copy
import datetime as dt
import os
import re
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hfsynth import cli, evaluate, export, ids, schema, timeutil, validate  # noqa: E402
from hfsynth.catalog import Catalog, Engine, build_rules  # noqa: E402
from hfsynth.config import Config  # noqa: E402
from hfsynth.generate import rng_for  # noqa: E402
from hfsynth.recurring import expected_dates  # noqa: E402

CFG = Config(seed=20261022, users=30, txns=12_000)
DS = REP = None


def setUpModule():
    global DS, REP
    DS, REP = cli.pipeline(CFG)


class TestFoundations(unittest.TestCase):
    def test_id_formats(self):
        self.assertEqual(ids.user_id(1), "USR-000001")
        self.assertEqual(ids.account_id("USR-000001", 1), "ACC-USR-000001-01")
        self.assertEqual(ids.txn_id(2026, 1), "TXN-2026-00000001")
        self.assertEqual(ids.budget_id("USR-000001", 2026, 1, "GRO"), "BUD-USR-000001-2026-01-GRO")
        self.assertEqual(ids.series_id(1), "REC-000001")

    def test_dst_offsets_and_nonexistent_hour(self):
        utc, off, _ = timeutil.local_to_utc(dt.datetime(2026, 1, 15, 12), -300)
        self.assertEqual(off, -300)
        utc, off, _ = timeutil.local_to_utc(dt.datetime(2026, 7, 15, 12), -300)
        self.assertEqual((off, utc.hour), (-240, 16))
        _, _, loc = timeutil.local_to_utc(dt.datetime(2026, 3, 8, 2, 30), -300)   # spring-forward gap
        self.assertEqual(loc.hour, 3)

    def test_month_end_evening_crosses_utc_month(self):
        utc, _, _ = timeutil.local_to_utc(dt.datetime(2026, 12, 31, 22, 0), -480)
        self.assertEqual((utc.year, utc.month), (2027, 1))

    def test_expected_dates(self):
        y = 2026
        bw = expected_dates("BIWEEKLY", dt.date(2025, 12, 5), dt.date(2024, 1, 1), None, y)
        self.assertIn(len(bw), (26, 27))
        self.assertTrue(all((b - a).days == 14 for a, b in zip(bw, bw[1:])))
        self.assertEqual(len(expected_dates("SEMI_MONTHLY", dt.date(2025, 12, 15), dt.date(2024, 1, 1), None, y)), 24)
        self.assertEqual(len(expected_dates("MONTHLY", dt.date(2025, 12, 3), dt.date(2024, 1, 1), None, y)), 12)
        self.assertEqual(len(expected_dates("ANNUAL", dt.date(2025, 5, 9), dt.date(2025, 5, 9), None, y)), 1)
        cut = expected_dates("MONTHLY", dt.date(2025, 12, 3), dt.date(2024, 1, 1), dt.date(2026, 4, 20), y)
        self.assertEqual(len(cut), 4)

    def test_config_validation(self):
        with self.assertRaises(ValueError):
            Config(users=1000, txns=1000).validate()


class TestRuleEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cat = Catalog(CFG, rng_for(CFG, "catalog"))
        cls.e = Engine(build_rules(2026), cat.alias_map, cat.default_by_id)

    def test_alias_resolution_and_normalisation(self):
        mid, c, _ = self.e.classify("POS PURCHASE FRESHMART GROCERS #4412 BOSTON MA", "PURCHASE", "2026-03-01")
        self.assertIsNotNone(mid)
        self.assertEqual(c, "GRO")

    def test_transfer_rule_by_type(self):
        self.assertEqual(self.e.classify("ONLINE TRANSFER TO SAVINGS 123456", "TRANSFER_OUT", "2026-03-01")[1], "XFR")

    def test_unknown_descriptor_falls_back_to_uncategorized(self):
        mid, c, _ = self.e.classify("MOBILE PAYMENT REF 482913", "PURCHASE", "2026-03-01")
        self.assertEqual((mid, c), (None, "UNC"))

    def test_effective_dated_rule_drift(self):
        d = "FRSHMRT MARKET 123"          # unresolved alias, keyword MARKET
        self.assertEqual(self.e.classify(d, "PURCHASE", "2026-01-15")[1], "SHP")
        self.assertEqual(self.e.classify(d, "PURCHASE", "2026-02-15")[1], "GRO")


class TestGeneratedDataset(unittest.TestCase):
    def test_all_validation_checks_pass(self):
        failed = [r for r in REP.results if r["status"] == "FAIL"]
        self.assertEqual(failed, [], failed)

    def test_exact_volume(self):
        self.assertEqual(len(DS.tables["transaction"]), CFG.txns)
        self.assertEqual(len(DS.tables["user_profile"]), CFG.users)

    def test_all_edge_cases_present_and_labelled(self):
        kinds = {i[1] for i in DS.gt["gt_issue"]}
        self.assertEqual(kinds, set(schema.ISSUE_TYPES))

    def test_ground_truth_is_separate(self):
        for t in schema.TABLES:
            for f in t.fields:
                self.assertFalse(re.match(r"^(true_|gt_|issue_|expected_|persona)", f.name), (t.name, f.name))
        self.assertEqual(len(DS.gt["gt_transaction"]), CFG.txns)

    def test_ledger_reconciles_per_account(self):
        tot = {}
        for r in DS.tables["transaction"]:
            tot[r[1]] = tot.get(r[1], 0) + round(r[9] * 100)
        for a in DS.tables["account"]:
            self.assertEqual(round(a[5] * 100) + tot.get(a[0], 0), round(a[6] * 100), a[0])

    def test_categorization_metrics_are_calculable_and_imperfect(self):
        m = evaluate.categorization(DS)
        self.assertTrue(0.85 < m["accuracy"] < 1.0)
        self.assertIn("ambiguous_merchant", m["accuracy_by_segment"])
        self.assertTrue(m["accuracy_by_segment"]["clean"]["accuracy"] > 0.99)

    def test_recurring_detection_has_labelled_examples(self):
        r = evaluate.recurring(DS)
        self.assertGreater(r["occurrences_skipped_labelled"], 0)
        self.assertGreater(r["baseline_detector"]["recall"], 0.9)

    def test_ledger_policy_beats_naive_spend(self):
        s = evaluate.spend(DS)
        self.assertLess(s["ledger_policy_pipeline"]["abs_error_usd"], s["naive_utc_abs_pipeline"]["abs_error_usd"])

    def test_transfers_never_count_as_spend_in_policy(self):
        L = evaluate.ledger_spend(DS) if hasattr(evaluate, "ledger_spend") else None
        self.assertIsNotNone(L)
        self.assertNotIn("XFR", {k[2] for k in L})


class TestNegativeValidation(unittest.TestCase):
    def _mutated(self, fn):
        ds = copy.copy(DS)
        ds.tables = {k: [list(r) for r in v] if k in ("transaction", "account", "budget") else v for k, v in DS.tables.items()}
        fn(ds)
        return validate.run(ds, CFG)

    def test_detects_broken_balance(self):
        rep = self._mutated(lambda d: d.tables["transaction"][100].__setitem__(15, 1.0))
        self.assertFalse(rep.ok)

    def test_detects_orphan_foreign_key(self):
        rep = self._mutated(lambda d: d.tables["transaction"][5].__setitem__(1, "ACC-USR-999999-01"))
        self.assertFalse(rep.ok)

    def test_detects_unlabelled_budget_mismatch(self):
        rep = self._mutated(lambda d: d.tables["budget"][0].__setitem__(2, "ZZZ"))
        self.assertFalse(rep.ok)


class TestExportAndReproducibility(unittest.TestCase):
    def test_csv_roundtrip_revalidates(self):
        with tempfile.TemporaryDirectory() as d:
            export.export(DS, CFG, d, ("csv",), REP, None, "test")
            ds2 = export.load_dataset(d)
            self.assertTrue(validate.run(ds2, CFG).ok)

    def test_sql_seed_loads_with_foreign_keys_on(self):
        with tempfile.TemporaryDirectory() as d:
            export.export(DS, CFG, d, ("sql",), None, None, "test")
            db = sqlite3.connect(":memory:")
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript(open(os.path.join(d, "sql", "seed.sql"), encoding="utf-8").read())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM "transaction"').fetchone()[0], CFG.txns)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_same_seed_same_checksums(self):
        with tempfile.TemporaryDirectory() as d:
            same, _ = export.reproducibility(CFG, d, ("csv", "json", "sql"), lambda c: cli.pipeline(c))
            self.assertTrue(same)

    def test_different_seed_changes_data(self):
        other = Config(seed=1, users=30, txns=12_000)
        ds, _ = cli.pipeline(other)
        self.assertNotEqual(ds.tables["transaction"][10][8:10], DS.tables["transaction"][10][8:10])


if __name__ == "__main__":
    unittest.main()
