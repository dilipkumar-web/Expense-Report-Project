"""
Personal Expense Tracker
------------------------
Skill Lab Project | Python, SQLite, pandas, Plotly, Streamlit

Run with:  streamlit run app.py
"""

from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

import analytics as an
import db

st.set_page_config(page_title="Expense Tracker", page_icon="💰", layout="wide")
db.init_db()

TODAY = date.today()
CURRENT_MONTH = TODAY.strftime("%Y-%m")


def inr(x: float) -> str:
    return f"₹{x:,.0f}"


def flash_and_rerun(message: str) -> None:
    """Show a toast after the page reloads (so every tab sees fresh data)."""
    st.session_state["flash"] = message
    st.rerun()


if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"))
st.session_state.setdefault("editor_version", 0)

# ----------------------------------------------------------------------
# Load data and choose the period to look at
# ----------------------------------------------------------------------
all_df = an.with_month(db.get_expenses())

# Categories/methods typed into imported CSVs should still appear in the dropdowns.
categories = db.CATEGORIES + sorted(set(all_df["category"]) - set(db.CATEGORIES))
methods = db.PAYMENT_METHODS + sorted(set(all_df["payment_method"]) - set(db.PAYMENT_METHODS))

st.sidebar.title("💰 Expense Tracker")
months = sorted(set(all_df["month"]) | {CURRENT_MONTH}, reverse=True)
options = months + [an.ALL_TIME]
selection = st.sidebar.selectbox(
    "View period", options, index=options.index(CURRENT_MONTH), format_func=an.month_label
)
view = an.filter_period(all_df, selection)

st.sidebar.metric("Expenses recorded", len(all_df))
st.sidebar.caption(f"Data is stored locally in `{db.DB_PATH.name}`.")

st.title("Personal Expense Tracker")
tab_dash, tab_add, tab_manage, tab_budget, tab_data = st.tabs(
    ["📊 Dashboard", "➕ Add expense", "✏️ Manage", "🎯 Budgets", "📁 Import / Export"]
)

# ----------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------
with tab_dash:
    if view.empty:
        st.info(
            f"No expenses for {an.month_label(selection)} yet. Add one in the **Add expense** tab, "
            "or load demo data from **Import / Export**."
        )
    else:
        s = an.summarize(view, all_df, selection, TODAY)
        by_cat = an.category_totals(view)

        delta = None
        if s["prev_total"]:
            delta = f"{s['total'] / s['prev_total'] - 1:+.0%} vs last month"

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total spent", inr(s["total"]), delta, delta_color="inverse")
        c2.metric("Average per day", inr(s["avg_per_day"]))
        if s["projected"] is not None:
            c3.metric("Projected month-end", inr(s["projected"]), help="Current daily pace × days in month")
        else:
            c3.metric("Transactions", s["count"])
        c4.metric("Top category", s["top_category"], inr(s["top_amount"]), delta_color="off")

        # Budget alerts (only meaningful for a single month)
        budgets = db.get_budgets()
        if selection != an.ALL_TIME and budgets:
            status = an.budget_status(by_cat, budgets)
            over = [b["category"] for b in status if b["level"] == "over"]
            if over:
                st.warning("Over budget: " + ", ".join(over))
            with st.expander("Budget status", expanded=bool(over)):
                icons = {"over": "🔴", "warn": "🟠", "ok": "🟢"}
                for b in status:
                    st.progress(
                        min(b["ratio"], 1.0),
                        text=f"{icons[b['level']]} {b['category']}: {inr(b['spent'])} of "
                             f"{inr(b['limit'])} ({b['ratio']:.0%})",
                    )

        left, right = st.columns(2)
        with left:
            fig = px.pie(by_cat.reset_index(), names="category", values="amount", hole=0.5,
                         title="Spending by category")
            fig.update_traces(textinfo="percent")
            fig.update_layout(height=380, margin=dict(l=10, r=10, t=50, b=10))
            st.plotly_chart(fig)
        with right:
            if selection == an.ALL_TIME:
                fig = px.bar(an.monthly_totals(all_df), x="month", y="amount", title="Spending per month")
            else:
                fig = px.bar(an.daily_totals(view), x="date", y="amount", title="Spending per day")
            fig.update_layout(height=380, margin=dict(l=10, r=10, t=50, b=10),
                              xaxis_title=None, yaxis_title="₹")
            st.plotly_chart(fig)

        left, right = st.columns(2)
        with left:
            fig = px.line(an.monthly_totals(all_df), x="month", y="amount", markers=True,
                          title="Monthly trend (last 12 months)")
            fig.update_layout(height=320, margin=dict(l=10, r=10, t=50, b=10),
                              xaxis_title=None, yaxis_title="₹")
            st.plotly_chart(fig)
        with right:
            pay = an.method_totals(view).reset_index()
            fig = px.bar(pay, x="amount", y="payment_method", orientation="h",
                         title="By payment method")
            fig.update_layout(height=320, margin=dict(l=10, r=10, t=50, b=10),
                              xaxis_title="₹", yaxis_title=None,
                              yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig)

        st.subheader("Biggest expenses")
        top5 = view.nlargest(5, "amount")[["date", "category", "amount", "payment_method", "note"]]
        top5 = top5.assign(date=top5["date"].dt.date)
        st.dataframe(
            top5, hide_index=True,
            column_config={"amount": st.column_config.NumberColumn("Amount (₹)", format="₹%.0f")},
        )

# ----------------------------------------------------------------------
# Add expense
# ----------------------------------------------------------------------
with tab_add:
    with st.form("add_expense", clear_on_submit=True):
        c1, c2 = st.columns(2)
        day = c1.date_input("Date", TODAY)
        amount = c2.number_input("Amount (₹)", min_value=0.0, step=10.0, format="%.2f")
        c3, c4 = st.columns(2)
        category = c3.selectbox("Category", categories)
        method = c4.selectbox("Payment method", methods)
        note = st.text_input("Note (optional)", placeholder="e.g. Lunch with friends")
        submitted = st.form_submit_button("Add expense", type="primary")

    if submitted:
        try:
            db.add_expense(day, category, amount, method, note)
        except ValueError as err:
            st.error(str(err))
        else:
            flash_and_rerun(f"Added {inr(amount)} under {category}")

# ----------------------------------------------------------------------
# Manage (edit / delete)
# ----------------------------------------------------------------------
with tab_manage:
    st.caption(f"Showing: {an.month_label(selection)}. Edit cells directly, tick **Delete** to remove "
               "a row, then press **Save changes**.")
    if view.empty:
        st.info("Nothing to manage for this period.")
    else:
        f1, f2 = st.columns([2, 3])
        search = f1.text_input("Search note or category")
        chosen = f2.multiselect("Filter by category", categories)

        table = view
        if search:
            mask = (table["note"].str.contains(search, case=False, na=False)
                    | table["category"].str.contains(search, case=False, na=False))
            table = table[mask]
        if chosen:
            table = table[table["category"].isin(chosen)]
        table = table.sort_values(["date", "id"], ascending=False)

        editor_df = table[["id", "date", "category", "amount", "payment_method", "note"]].copy()
        editor_df["date"] = editor_df["date"].dt.date
        editor_df.insert(0, "Delete", False)
        editor_df = editor_df.reset_index(drop=True)

        st.caption(f"{len(editor_df)} expenses · {inr(table['amount'].sum())}")
        # The key changes after every save so old edits are never re-applied to a new table.
        editor_key = f"editor_{st.session_state['editor_version']}_{selection}_{search}_{'|'.join(chosen)}"
        edited = st.data_editor(
            editor_df, hide_index=True, key=editor_key, disabled=["id"],
            column_config={
                "Delete": st.column_config.CheckboxColumn("Delete", width="small"),
                "id": st.column_config.NumberColumn("ID", width="small"),
                "date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
                "category": st.column_config.SelectboxColumn("Category", options=categories),
                "amount": st.column_config.NumberColumn("Amount (₹)", min_value=0.01, format="%.2f"),
                "payment_method": st.column_config.SelectboxColumn("Payment", options=methods),
                "note": st.column_config.TextColumn("Note"),
            },
        )

        if st.button("Save changes", type="primary"):
            original = editor_df.set_index("id")
            updated, errors = 0, []

            to_delete = edited.loc[edited["Delete"], "id"].astype(int).tolist()
            for _, row in edited[~edited["Delete"]].iterrows():
                before = original.loc[row["id"]]
                changed = (
                    pd.Timestamp(row["date"]) != pd.Timestamp(before["date"])
                    or row["category"] != before["category"]
                    or float(row["amount"]) != float(before["amount"])
                    or row["payment_method"] != before["payment_method"]
                    or (row["note"] or "") != before["note"]
                )
                if changed:
                    try:
                        db.update_expense(int(row["id"]), row["date"], row["category"],
                                          row["amount"], row["payment_method"], row["note"])
                        updated += 1
                    except ValueError as err:
                        errors.append(f"Row #{int(row['id'])}: {err}")

            deleted = db.delete_expenses(to_delete)
            if errors:
                for message in errors:
                    st.error(message)
            elif updated or deleted:
                st.session_state["editor_version"] += 1
                flash_and_rerun(f"Saved: {updated} updated, {deleted} deleted")
            else:
                st.info("No changes to save.")

# ----------------------------------------------------------------------
# Budgets
# ----------------------------------------------------------------------
with tab_budget:
    st.write("Set a monthly spending limit per category. Use **0** for no budget.")
    saved = db.get_budgets()
    with st.form("budgets"):
        cols = st.columns(3)
        new_limits = {}
        for i, cat in enumerate(categories):
            new_limits[cat] = cols[i % 3].number_input(
                cat, min_value=0.0, step=100.0, value=float(saved.get(cat, 0.0)), key=f"budget_{cat}"
            )
        save_budgets = st.form_submit_button("Save budgets", type="primary")

    if save_budgets:
        for cat, limit in new_limits.items():
            db.set_budget(cat, limit)
        flash_and_rerun("Budgets saved")
    if saved:
        st.metric("Total monthly budget", inr(sum(saved.values())))

# ----------------------------------------------------------------------
# Import / Export
# ----------------------------------------------------------------------
with tab_data:
    left, right = st.columns(2)
    with left:
        st.subheader("Export")
        st.write("Download every expense as a CSV file (opens in Excel).")
        st.download_button(
            "Download all expenses (CSV)",
            an.to_csv_bytes(all_df) if not all_df.empty else b"",
            file_name=f"expenses_{TODAY.isoformat()}.csv",
            mime="text/csv",
            disabled=all_df.empty,
        )
    with right:
        st.subheader("Import")
        st.write("CSV columns: `date`, `category`, `amount`, and optionally `payment_method`, `note`.")
        upload = st.file_uploader("Choose a CSV file", type="csv", label_visibility="collapsed")
        if upload is not None and st.button("Import file"):
            try:
                imported, skipped = db.import_dataframe(pd.read_csv(upload))
            except Exception as err:  # bad CSV, missing columns, etc.
                st.error(f"Could not import: {err}")
            else:
                flash_and_rerun(f"Imported {imported} rows ({skipped} skipped as invalid)")

    st.divider()
    st.subheader("Demo data & reset")
    d1, d2 = st.columns(2)
    with d1:
        st.write("Add 90 days of realistic sample expenses and budgets, handy for presenting.")
        if st.button("Load sample data"):
            added = db.add_sample_data()
            flash_and_rerun(f"Added {added} sample expenses")
    with d2:
        st.write("Delete **all** expenses and budgets. This cannot be undone.")
        sure = st.checkbox("I understand")
        if st.button("Delete all data", disabled=not sure):
            db.clear_all()
            flash_and_rerun("All data deleted")
