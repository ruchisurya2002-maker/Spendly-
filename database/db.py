import sqlite3
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

DB_PATH = "spendly.db"

CATEGORIES = [
    "Food", "Transport", "Bills", "Health",
    "Entertainment", "Shopping", "Other",
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            date TEXT NOT NULL,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()


def seed_db():
    conn = get_db()
    already_seeded = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
    if already_seeded:
        conn.close()
        return

    password_hash = generate_password_hash("demo123")
    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Demo User", "demo@spendly.com", password_hash),
    )
    user_id = cursor.lastrowid

    today = datetime.now()
    sample_expenses = [
        (user_id, 450.00,  "Food",          (today - timedelta(days=2)).strftime("%Y-%m-%d"), "Groceries"),
        (user_id, 180.00,  "Transport",     (today - timedelta(days=5)).strftime("%Y-%m-%d"), "Bus pass"),
        (user_id, 1450.00, "Bills",         (today - timedelta(days=7)).strftime("%Y-%m-%d"), "Electricity bill"),
        (user_id, 620.00,  "Health",        (today - timedelta(days=11)).strftime("%Y-%m-%d"), "Pharmacy"),
        (user_id, 349.00,  "Entertainment", (today - timedelta(days=14)).strftime("%Y-%m-%d"), "Streaming subscription"),
        (user_id, 1899.00, "Shopping",      (today - timedelta(days=18)).strftime("%Y-%m-%d"), "New shoes"),
        (user_id, 120.00,  "Other",         (today - timedelta(days=23)).strftime("%Y-%m-%d"), "Miscellaneous"),
        (user_id, 780.00,  "Food",          (today - timedelta(days=29)).strftime("%Y-%m-%d"), "Restaurant"),
    ]
    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        sample_expenses,
    )
    conn.commit()
    conn.close()


def get_user_by_email(email):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    return user


def create_user(name, email, password):
    password_hash = generate_password_hash(password)
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, password_hash),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    return user_id


def create_expense(user_id, amount, category, expense_date, description):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, category, expense_date, description),
    )
    conn.commit()
    expense_id = cursor.lastrowid
    conn.close()
    return expense_id


def get_expense_by_id(expense_id, user_id):
    conn = get_db()
    expense = conn.execute(
        "SELECT * FROM expenses WHERE id = ? AND user_id = ?",
        (expense_id, user_id),
    ).fetchone()
    conn.close()
    return expense


def update_expense(expense_id, user_id, amount, category, expense_date, description):
    conn = get_db()
    conn.execute(
        "UPDATE expenses SET amount = ?, category = ?, date = ?, description = ? "
        "WHERE id = ? AND user_id = ?",
        (amount, category, expense_date, description, expense_id, user_id),
    )
    conn.commit()
    conn.close()


def get_user_by_id(user_id):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return user


def _date_range_clause(date_from, date_to):
    if date_from is not None and date_to is not None:
        return " AND date BETWEEN ? AND ?", (date_from, date_to)
    return "", ()


# ==== SUBAGENT 1: transaction history query ====
def get_expenses_by_user(user_id, date_from=None, date_to=None):
    clause, params = _date_range_clause(date_from, date_to)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM expenses WHERE user_id = ?" + clause + " ORDER BY date DESC, id DESC",
        (user_id, *params),
    ).fetchall()
    conn.close()
    return rows
# ==== END SUBAGENT 1 ====


# ==== SUBAGENT 2: summary stats queries ====
def get_expense_summary(user_id, date_from=None, date_to=None):
    clause, params = _date_range_clause(date_from, date_to)
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS count "
        "FROM expenses WHERE user_id = ?" + clause,
        (user_id, *params),
    ).fetchone()
    conn.close()
    return row


def get_top_category(user_id, date_from=None, date_to=None):
    clause, params = _date_range_clause(date_from, date_to)
    conn = get_db()
    row = conn.execute(
        "SELECT category, SUM(amount) AS total FROM expenses "
        "WHERE user_id = ?" + clause + " GROUP BY category ORDER BY total DESC LIMIT 1",
        (user_id, *params),
    ).fetchone()
    conn.close()
    return row
# ==== END SUBAGENT 2 ====


# ==== SUBAGENT 3: category breakdown query ====
def get_category_totals(user_id, date_from=None, date_to=None):
    clause, params = _date_range_clause(date_from, date_to)
    conn = get_db()
    rows = conn.execute(
        "SELECT category, SUM(amount) AS total FROM expenses "
        "WHERE user_id = ?" + clause + " GROUP BY category ORDER BY total DESC",
        (user_id, *params),
    ).fetchall()
    conn.close()
    return rows
# ==== END SUBAGENT 3 ====
