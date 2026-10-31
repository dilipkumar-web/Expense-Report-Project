"""Unit tests for the data and analysis layers.

Run with:  python -m unittest -v
(No Streamlit needed. Each test uses a throwaway database.)
"""

import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

import analytics as an
import db


class DbTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_path = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "test.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.original_path
        self.tmp.cleanup()


class TestExpenses(DbTestCase):
    def test_add_and_read(self):
        db.add_expense("2026-10-05", "Groceries", 450.5, "UPI", "Milk")
        df = db.get_expenses()
        self.assertEqual(len(df), 1)
        self.assertEqual(df.loc[0, "category"], "Groceries")
        self.assertAlmostEqual(df.loc[0, "amount"], 450.5)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(df["date"]))

    def test_empty_table_has_datetime_column(self):
        df = db.get_expenses()
        self.assertTrue(df.empty)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(df["date"]))
        an.with_month(df)  # must not raise on an empty frame

    def test_validation(self):
        for bad in [("2026-10-05", "Food", 0), ("2026-10-05", "Food", -5),
                    ("2026-10-05", "Food", "abc"), ("2026-10-05", "", 10),
                    ("not a date", "Food", 10), (None, "Food", 10),
                    ("2026-10-05", "Food", float("nan"))]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                db.add_expense(*bad)
        self.assertTrue(db.get_expenses().empty)

    def test_update_and_delete(self):
        a = db.add_expense("2026-10-01", "Food & Dining", 100)
        b = db.add_expense("2026-10-02", "Transport", 50)
        db.update_expense(a, "2026-10-03", "Shopping", 999, "Cash", "Shirt")
        row = db.get_expenses().set_index("id").loc[a]
        self.assertEqual((row["category"], row["amount"], row["payment_method"]),
                         ("Shopping", 999.0, "Cash"))
        self.assertEqual(db.delete_expenses([b]), 1)
        self.assertEqual(db.delete_expenses([]), 0)
        self.assertEqual(len(db.get_expenses()), 1)

    def test_filters(self):
        db.add_expense("2026-09-30", "Food & Dining", 100, note="Pizza")
        db.add_expense("2026-10-02", "Transport", 50, note="Metro")
        db.add_expense("2026-10-09", "Food & Dining", 200, note="Dinner")
        self.assertEqual(len(db.get_expenses(start="2026-10-01")), 2)
        self.assertEqual(len(db.get_expenses(end="2026-09-30")), 1)
        self.assertEqual(len(db.get_expenses(categories=["Transport"])), 1)
        self.assertEqual(len(db.get_expenses(search="pizza")), 1)
        self.assertEqual(db.get_expenses().iloc[0]["note"], "Dinner")  # newest first

    def test_sql_injection_is_inert(self):
        db.add_expense("2026-10-02", "Other", 10, note="x'); DROP TABLE expenses;--")
        self.assertEqual(len(db.get_expenses(search="'); DROP")), 1)
        self.assertEqual(len(db.get_expenses()), 1)


class TestBudgets(DbTestCase):
    def test_set_update_remove(self):
        db.set_budget("Food & Dining", 3000)
        db.set_budget("Food & Dining", 3500)
        self.assertEqual(db.get_budgets(), {"Food & Dining": 3500.0})
        db.set_budget("Food & Dining", 0)
        self.assertEqual(db.get_budgets(), {})


class TestImportAndSample(DbTestCase):
    def test_import_skips_bad_rows(self):
        df = pd.DataFrame({
            "Date": ["2026-10-01", "oops", "2026-10-03", "2026-10-04"],
            "Category": ["Food & Dining", "Food & Dining", "Transport", "Transport"],
            "Amount": [100, 50, -1, 75],
            "Payment Method": ["UPI", None, "Cash", None],
            "Note": ["ok", "bad date", "bad amount", None],
        })
        imported, skipped = db.import_dataframe(df)
        self.assertEqual((imported, skipped), (2, 2))
        out = db.get_expenses()
        self.assertEqual(sorted(out["note"]), ["", "ok"])
        self.assertTrue((out["payment_method"] != "nan").all())

    def test_import_requires_columns(self):
        with self.assertRaises(ValueError):
            db.import_dataframe(pd.DataFrame({"date": ["2026-10-01"], "amount": [5]}))

    def test_csv_round_trip(self):
        db.add_expense("2026-10-01", "Groceries", 12.5, "Cash", "Eggs, 6 pcs")
        raw = an.to_csv_bytes(db.get_expenses())
        db.clear_all()
        path = Path(self.tmp.name) / "out.csv"
        path.write_bytes(raw)
        self.assertEqual(db.import_dataframe(pd.read_csv(path)), (1, 0))
        self.assertEqual(db.get_expenses().loc[0, "note"], "Eggs, 6 pcs")

    def test_sample_data(self):
        added = db.add_sample_data(days=60)
        self.assertGreater(added, 30)
        self.assertEqual(len(db.get_expenses()), added)
        self.assertTrue(db.get_budgets())


class TestAnalytics(DbTestCase):
    def setUp(self):
        super().setUp()
        for d, c, a, m in [
            ("2026-09-10", "Food & Dining", 1000, "UPI"),
            ("2026-10-01", "Rent & Bills", 4500, "UPI"),
            ("2026-10-05", "Food & Dining", 600, "Cash"),
            ("2026-10-10", "Food & Dining", 900, "UPI"),
            ("2026-10-12", "Transport", 300, "Cash"),
        ]:
            db.add_expense(d, c, a, m)
        self.all_df = an.with_month(db.get_expenses())

    def test_summary_current_month(self):
        today = date(2026, 10, 15)
        view = an.filter_period(self.all_df, "2026-10")
        s = an.summarize(view, self.all_df, "2026-10", today)
        self.assertEqual(s["total"], 6300)
        self.assertEqual(s["days"], 15)
        self.assertAlmostEqual(s["avg_per_day"], 420)
        self.assertEqual(s["top_category"], "Rent & Bills")
        self.assertEqual(s["prev_total"], 1000)
        self.assertAlmostEqual(s["projected"], 420 * 31)

    def test_summary_past_month_has_no_projection(self):
        today = date(2026, 10, 15)
        view = an.filter_period(self.all_df, "2026-09")
        s = an.summarize(view, self.all_df, "2026-09", today)
        self.assertEqual(s["days"], 30)
        self.assertIsNone(s["projected"])
        self.assertIsNone(s["prev_total"])

    def test_summary_all_time_and_empty(self):
        s = an.summarize(self.all_df, self.all_df, an.ALL_TIME, date(2026, 10, 15))
        self.assertEqual(s["total"], 7300)
        self.assertIsNone(s["projected"])
        empty = an.with_month(pd.DataFrame(columns=db.COLUMNS).assign(
            date=pd.to_datetime([]), amount=pd.Series(dtype=float)))
        s = an.summarize(empty, empty, "2026-10", date(2026, 10, 15))
        self.assertEqual((s["total"], s["top_category"]), (0, "-"))

    def test_budget_status_levels(self):
        by_cat = an.category_totals(an.filter_period(self.all_df, "2026-10"))
        status = {b["category"]: b for b in an.budget_status(
            by_cat, {"Food & Dining": 1000, "Transport": 350, "Rent & Bills": 9000, "Health": 500})}
        self.assertEqual(status["Food & Dining"]["level"], "over")   # 1500 / 1000
        self.assertEqual(status["Transport"]["level"], "warn")       # 300 / 350 = 86%
        self.assertEqual(status["Rent & Bills"]["level"], "ok")      # 50%
        self.assertEqual(status["Health"]["spent"], 0.0)

    def test_monthly_and_daily_totals(self):
        monthly = an.monthly_totals(self.all_df)
        self.assertEqual(monthly["amount"].tolist(), [1000, 6300])
        view = an.filter_period(self.all_df, "2026-10")
        self.assertEqual(len(an.daily_totals(view)), 4)
        self.assertEqual(an.method_totals(view).to_dict(), {"UPI": 5400, "Cash": 900})

    def test_month_label(self):
        self.assertEqual(an.month_label("2026-10"), "October 2026")
        self.assertEqual(an.month_label(an.ALL_TIME), "All time")


if __name__ == "__main__":
    unittest.main()
