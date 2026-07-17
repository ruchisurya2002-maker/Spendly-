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
