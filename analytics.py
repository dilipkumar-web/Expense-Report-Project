"""Analysis helpers for the Expense Tracker. Pure pandas, no Streamlit or SQL."""

from datetime import date

import pandas as pd

ALL_TIME = "All time"


def with_month(df: pd.DataFrame) -> pd.DataFrame:
    """Add a 'month' column such as '2026-10'."""
    out = df.copy()
    out["month"] = out["date"].dt.strftime("%Y-%m")
    return out


def month_label(month: str) -> str:
    return month if month == ALL_TIME else pd.Period(month, "M").strftime("%B %Y")


def filter_period(df: pd.DataFrame, selection: str) -> pd.DataFrame:
    return df if selection == ALL_TIME else df[df["month"] == selection]


def period_days(selection: str, view: pd.DataFrame, today: date) -> int:
    """Number of days to average over (for the current month: days so far)."""
    if selection == ALL_TIME:
        if view.empty:
            return 1
        return max((view["date"].max() - view["date"].min()).days + 1, 1)
    period = pd.Period(selection, "M")
    start, end = period.start_time.date(), period.end_time.date()
    if today < start:
        return 1
    if today <= end:
        end = today
    return max((end - start).days + 1, 1)


def category_totals(view: pd.DataFrame) -> pd.Series:
    return view.groupby("category")["amount"].sum().sort_values(ascending=False)


def method_totals(view: pd.DataFrame) -> pd.Series:
    return view.groupby("payment_method")["amount"].sum().sort_values(ascending=False)


def daily_totals(view: pd.DataFrame) -> pd.DataFrame:
    return view.groupby(view["date"].dt.date)["amount"].sum().reset_index()


def monthly_totals(df: pd.DataFrame, last: int = 12) -> pd.DataFrame:
    out = df.groupby("month")["amount"].sum().reset_index().sort_values("month")
    return out.tail(last)


def summarize(view: pd.DataFrame, all_df: pd.DataFrame, selection: str, today: date) -> dict:
    """Headline numbers for the dashboard."""
    total = float(view["amount"].sum())
    days = period_days(selection, view, today)
    by_cat = category_totals(view)

    prev_total = None
    projected = None
    if selection != ALL_TIME:
        period = pd.Period(selection, "M")
        prev = float(all_df.loc[all_df["month"] == str(period - 1), "amount"].sum())
        prev_total = prev if prev > 0 else None
        if period.start_time.date() <= today <= period.end_time.date():
            projected = total / days * period.days_in_month

    return {
        "total": total,
        "count": int(len(view)),
        "days": days,
        "avg_per_day": total / days,
        "top_category": by_cat.index[0] if len(by_cat) else "-",
        "top_amount": float(by_cat.iloc[0]) if len(by_cat) else 0.0,
        "prev_total": prev_total,
        "projected": projected,
    }


def budget_status(by_cat: pd.Series, budgets: dict) -> list[dict]:
    """Compare spending per category with its monthly limit."""
    out = []
    for category, limit in budgets.items():
        spent = float(by_cat.get(category, 0.0))
        ratio = spent / limit
        level = "over" if ratio > 1 else "warn" if ratio >= 0.8 else "ok"
        out.append({"category": category, "spent": spent, "limit": float(limit),
                    "ratio": ratio, "level": level})
    return sorted(out, key=lambda r: r["ratio"], reverse=True)


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Export expenses in the same format the importer accepts."""
    out = df[["date", "category", "amount", "payment_method", "note"]].copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out.to_csv(index=False).encode("utf-8")
