# Personal Expense Tracker

A Python web app to record daily expenses, set budgets and see where your money goes.
Built with **SQLite, pandas, Plotly and Streamlit** for a skill lab activity.

## Features
- **Add expenses** with date, amount, category, payment method (UPI, cash, cards...) and a note
- **Dashboard** for any month or all time: total spent, average per day, projected month-end spend,
  comparison with last month, top category
- **Charts**: spending by category (donut), per day / per month bars, 12-month trend, payment methods
- **Budgets**: monthly limit per category with colour-coded progress (green / orange at 80% / red when over)
- **Manage**: search, filter, edit cells in place, tick *Delete* to remove rows
- **Import / Export** CSV (works with Excel), plus one-click **sample data** for demos
- Data is saved locally in `expenses.db` (SQLite), nothing is sent anywhere

## Setup
```bash
python -m venv venv
venv\Scripts\activate          # Windows  (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
streamlit run app.py
```
The app opens at http://localhost:8501. For a quick demo, open **Import / Export** and press
**Load sample data**.

## Project structure
```
app.py            # Streamlit user interface (5 tabs)
db.py             # SQLite database layer: tables, add/edit/delete, budgets, CSV import, demo data
analytics.py      # Pure pandas calculations: summaries, totals, budget status
test_core.py      # 17 unit tests for db.py and analytics.py
requirements.txt
README.md
```
The code is split into layers: `app.py` only draws the interface, `analytics.py` does the maths,
and `db.py` is the only file that touches SQL. This keeps each part easy to test and explain.

## Database design
```
expenses(id, date, category, amount, payment_method, note)   -- amount must be > 0
budgets(category PRIMARY KEY, monthly_limit)                 -- limit must be > 0
```
All queries use `?` placeholders (parameterised SQL), so user input can never alter a query
(no SQL injection). Every expense is validated before saving.

## CSV format
```
date,category,amount,payment_method,note
2026-10-05,Food & Dining,250,UPI,Lunch
```
Only `date`, `category` and `amount` are required. Invalid rows are skipped and counted.

## Running the tests
```bash
python -m unittest -v
```

## Possible extensions
- Recurring expenses (rent, subscriptions)
- Multiple users with login
- Income tracking and savings goals
- Export a monthly PDF report
