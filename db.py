"""Database layer for the Personal Expense Tracker (SQLite).

All SQL lives in this file so the rest of the app never touches the database
directly. Only the Python standard library and pandas are needed here.
"""

import os
import random
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# The database file sits next to this script (override with EXPENSE_DB).
DB_PATH = Path(os.environ.get("EXPENSE_DB", Path(__file__).with_name("expenses.db")))

CATEGORIES = [
    "Food & Dining", "Groceries", "Transport", "Rent & Bills", "Shopping",
    "Entertainment", "Health", "Education", "Travel", "Other",
]
PAYMENT_METHODS = ["UPI", "Cash", "Debit Card", "Credit Card", "Net Banking", "Wallet"]
COLUMNS = ["id", "date", "category", "amount", "payment_method", "note"]


# ----------------------------------------------------------------------
# Connection / schema
# ----------------------------------------------------------------------
@contextmanager
def connect():
    """Open a connection, commit on success, always close."""
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS expenses (
                   id             INTEGER PRIMARY KEY AUTOINCREMENT,
                   date           TEXT NOT NULL,
                   category       TEXT NOT NULL,
                   amount         REAL NOT NULL CHECK (amount > 0),
                   payment_method TEXT NOT NULL DEFAULT 'UPI',
                   note           TEXT NOT NULL DEFAULT ''
               )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS budgets (
                   category      TEXT PRIMARY KEY,
                   monthly_limit REAL NOT NULL CHECK (monthly_limit > 0)
               )"""
        )


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------
def _text(value, default: str = "") -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return default
    return str(value).strip() or default


def _clean(day, category, amount, payment_method="UPI", note="") -> tuple:
    """Validate one expense and return (date_iso, category, amount, method, note)."""
    try:
        ts = pd.to_datetime(day)
    except (ValueError, TypeError):
        raise ValueError("Invalid date") from None
    if pd.isna(ts):
        raise ValueError("Invalid date")

    category = _text(category)
    if not category:
        raise ValueError("Category is required")

    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        raise ValueError("Amount must be a number") from None
    if not amount > 0:  # also rejects NaN
        raise ValueError("Amount must be greater than 0")

    return (
        ts.date().isoformat(),
        category,
        amount,
        _text(payment_method, "UPI"),
        _text(note),
    )


# ----------------------------------------------------------------------
# Expenses: create / read / update / delete
# ----------------------------------------------------------------------
def add_expense(day, category, amount, payment_method="UPI", note="") -> int:
    row = _clean(day, category, amount, payment_method, note)
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO expenses (date, category, amount, payment_method, note) "
            "VALUES (?, ?, ?, ?, ?)",
            row,
        )
        return cur.lastrowid


def update_expense(expense_id: int, day, category, amount, payment_method="UPI", note="") -> None:
    row = _clean(day, category, amount, payment_method, note)
    with connect() as conn:
        conn.execute(
            "UPDATE expenses SET date=?, category=?, amount=?, payment_method=?, note=? "
            "WHERE id=?",
            (*row, int(expense_id)),
        )


def delete_expenses(ids) -> int:
    ids = [int(i) for i in ids]
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    with connect() as conn:
        cur = conn.execute(f"DELETE FROM expenses WHERE id IN ({marks})", ids)
        return cur.rowcount


def get_expenses(start=None, end=None, categories=None, search=None) -> pd.DataFrame:
    """Return expenses (newest first) as a DataFrame, optionally filtered."""
    sql = "SELECT id, date, category, amount, payment_method, note FROM expenses WHERE 1=1"
    params: list = []
    if start is not None:
        sql += " AND date >= ?"
        params.append(pd.to_datetime(start).date().isoformat())
    if end is not None:
        sql += " AND date <= ?"
        params.append(pd.to_datetime(end).date().isoformat())
    if categories:
        sql += f" AND category IN ({','.join('?' * len(categories))})"
        params.extend(categories)
    if search:
        sql += " AND (note LIKE ? OR category LIKE ?)"
        params.extend([f"%{search}%"] * 2)
    sql += " ORDER BY date DESC, id DESC"

    with connect() as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    df["date"] = pd.to_datetime(df["date"])
    return df


def clear_all() -> None:
    with connect() as conn:
        conn.execute("DELETE FROM expenses")
        conn.execute("DELETE FROM budgets")


# ----------------------------------------------------------------------
# Budgets
# ----------------------------------------------------------------------
def set_budget(category: str, monthly_limit: float) -> None:
    """Create/update a monthly budget. A limit of 0 (or less) removes it."""
    with connect() as conn:
        if monthly_limit and monthly_limit > 0:
            conn.execute(
                "INSERT INTO budgets (category, monthly_limit) VALUES (?, ?) "
                "ON CONFLICT(category) DO UPDATE SET monthly_limit=excluded.monthly_limit",
                (category, float(monthly_limit)),
            )
        else:
            conn.execute("DELETE FROM budgets WHERE category=?", (category,))


def get_budgets() -> dict:
    with connect() as conn:
        rows = conn.execute("SELECT category, monthly_limit FROM budgets ORDER BY category").fetchall()
    return {cat: limit for cat, limit in rows}


# ----------------------------------------------------------------------
# CSV import
# ----------------------------------------------------------------------
def import_dataframe(df: pd.DataFrame) -> tuple[int, int]:
    """Insert rows from a DataFrame. Returns (imported, skipped).

    Required columns: date, category, amount. Optional: payment_method, note.
    Invalid rows are skipped instead of aborting the whole import.
    """
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    missing = {"date", "category", "amount"} - set(df.columns)
    if missing:
        raise ValueError(f"Missing column(s): {', '.join(sorted(missing))}")

    rows, skipped = [], 0
    for rec in df.to_dict("records"):
        try:
            rows.append(
                _clean(rec["date"], rec["category"], rec["amount"],
                       rec.get("payment_method"), rec.get("note"))
            )
        except ValueError:
            skipped += 1

    if rows:
        with connect() as conn:
            conn.executemany(
                "INSERT INTO expenses (date, category, amount, payment_method, note) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
    return len(rows), skipped


# ----------------------------------------------------------------------
# Demo data
# ----------------------------------------------------------------------
# category -> (min amount, max amount, chance of an expense on any given day, notes)
_SAMPLE_SPEC = {
    "Food & Dining": (80, 600, 0.45, ["Lunch", "Dinner", "Cafe", "Snacks", "Biryani"]),
    "Groceries": (150, 1500, 0.12, ["Vegetables", "Supermarket", "Milk & eggs"]),
    "Transport": (30, 400, 0.35, ["Auto", "Metro", "Cab", "Petrol"]),
    "Shopping": (300, 3000, 0.05, ["Clothes", "Headphones", "Online order"]),
    "Entertainment": (150, 900, 0.07, ["Movie", "Gaming", "Concert"]),
    "Health": (100, 1200, 0.03, ["Pharmacy", "Doctor visit"]),
    "Education": (200, 2000, 0.02, ["Books", "Online course"]),
    "Travel": (500, 4000, 0.01, ["Train ticket", "Weekend trip"]),
}
_SAMPLE_BUDGETS = {
    "Food & Dining": 5000, "Groceries": 2500, "Transport": 2000,
    "Shopping": 2000, "Entertainment": 1000,
}


def add_sample_data(days: int = 90, seed: int = 42) -> int:
    """Fill the database with realistic random expenses for demos. Returns rows added."""
    rng = random.Random(seed)
    today = date.today()
    rows = []
    for offset in range(days):
        day = today - timedelta(days=offset)
        for category, (lo, hi, chance, notes) in _SAMPLE_SPEC.items():
            if rng.random() < chance:
                amount = round(rng.uniform(lo, hi) / 10) * 10
                method = rng.choices(PAYMENT_METHODS, weights=[60, 15, 10, 8, 2, 5])[0]
                rows.append(_clean(day, category, max(amount, 10), method, rng.choice(notes)))
        if day.day == 1:
            rows.append(_clean(day, "Rent & Bills", 4500, "UPI", "Room rent"))
        if day.day == 5:
            rows.append(_clean(day, "Rent & Bills", 299, "UPI", "Mobile recharge"))

    with connect() as conn:
        conn.executemany(
            "INSERT INTO expenses (date, category, amount, payment_method, note) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
    if not get_budgets():
        for category, limit in _SAMPLE_BUDGETS.items():
            set_budget(category, limit)
    return len(rows)
