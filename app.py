import os
from datetime import datetime

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import (
    create_user,
    get_category_totals,
    get_db,
    get_expense_summary,
    get_expenses_by_user,
    get_top_category,
    get_user_by_email,
    get_user_by_id,
    init_db,
    seed_db,
)

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
# Profile helpers                                                     #
# ------------------------------------------------------------------ #

def _format_currency(amount):
    return f"₹{amount:,.2f}"


def _format_member_since(created_at):
    dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
    return dt.strftime("%B %Y")


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]
    user_row = get_user_by_id(user_id)
    user = {
        "name": user_row["name"],
        "email": user_row["email"],
        "member_since": _format_member_since(user_row["created_at"]),
        "initials": "".join(p[0] for p in user_row["name"].split()[:2]).upper(),
    }

    # ==== SUBAGENT 1: build `transactions` from get_expenses_by_user() ====
    expense_rows = get_expenses_by_user(user_id)
    transactions = [
        {
            "date": row["date"],
            "description": row["description"] or "",
            "category": row["category"],
            "amount": _format_currency(row["amount"]),
        }
        for row in expense_rows
    ]
    # ==== END SUBAGENT 1 ====

    # ==== SUBAGENT 2: build `stats` from get_expense_summary()/get_top_category() ====
    summary = get_expense_summary(user_id)
    top_category = get_top_category(user_id)
    stats = [
        {"label": "Total spent", "value": _format_currency(summary["total"])},
        {"label": "Transactions", "value": str(summary["count"])},
        {
            "label": "Top category",
            "value": top_category["category"] if top_category else "—",
        },
    ]
    # ==== END SUBAGENT 2 ====

    # ==== SUBAGENT 3: build `categories` from get_category_totals() ====
    category_rows = get_category_totals(user_id)
    categories = []
    if category_rows:
        max_total = category_rows[0]["total"]
        categories = [
            {
                "name": row["category"],
                "amount": _format_currency(row["total"]),
                "percent": round(row["total"] / max_total * 100),
            }
            for row in category_rows
        ]
    # ==== END SUBAGENT 3 ====

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
        display_name=user["name"],
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
