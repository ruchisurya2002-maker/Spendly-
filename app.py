import os

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import create_user, get_db, get_user_by_email, init_db, seed_db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("profile"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name or not email or not password or not confirm_password:
            return render_template("register.html", error="All fields are required.")

        if password != confirm_password:
            return render_template("register.html", error="Passwords do not match.")

        if get_user_by_email(email):
            return render_template("register.html", error="An account with that email already exists.")

        create_user(name, email, password)
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("profile"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user = get_user_by_email(email) if email and password else None

        if not user or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="Invalid email or password.")

        session["user_id"] = user["id"]
        return redirect(url_for("profile"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Hardcoded demo data for /profile (Step 4 — real DB wiring in Step 5) #
# ------------------------------------------------------------------ #

PROFILE_USER = {
    "name": "Demo User",
    "email": "demo@spendly.com",
    "member_since": "March 2025",
    "initials": "DU",
    "display_name": "Demo User",
}

PROFILE_STATS = [
    {"label": "Total spent", "value": "₹5,848.00"},
    {"label": "Transactions", "value": "8"},
    {"label": "Top category", "value": "Shopping"},
]

PROFILE_TRANSACTIONS = [
    {"date": "2026-07-26", "description": "Groceries", "category": "Food", "amount": "₹450.00"},
    {"date": "2026-07-23", "description": "Bus pass", "category": "Transport", "amount": "₹180.00"},
    {"date": "2026-07-21", "description": "Electricity bill", "category": "Bills", "amount": "₹1,450.00"},
    {"date": "2026-07-17", "description": "Pharmacy", "category": "Health", "amount": "₹620.00"},
    {"date": "2026-07-14", "description": "Streaming subscription", "category": "Entertainment", "amount": "₹349.00"},
    {"date": "2026-07-10", "description": "New shoes", "category": "Shopping", "amount": "₹1,899.00"},
    {"date": "2026-07-05", "description": "Miscellaneous", "category": "Other", "amount": "₹120.00"},
    {"date": "2026-06-29", "description": "Restaurant", "category": "Food", "amount": "₹780.00"},
]

PROFILE_CATEGORIES = [
    {"name": "Shopping", "amount": "₹1,899.00", "percent": 100},
    {"name": "Bills", "amount": "₹1,450.00", "percent": 76},
    {"name": "Food", "amount": "₹1,230.00", "percent": 65},
    {"name": "Health", "amount": "₹620.00", "percent": 33},
    {"name": "Entertainment", "amount": "₹349.00", "percent": 18},
    {"name": "Transport", "amount": "₹180.00", "percent": 9},
    {"name": "Other", "amount": "₹120.00", "percent": 6},
]


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    return render_template(
        "profile.html",
        user=PROFILE_USER,
        stats=PROFILE_STATS,
        transactions=PROFILE_TRANSACTIONS,
        categories=PROFILE_CATEGORIES,
        display_name=PROFILE_USER["display_name"],
    )


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
