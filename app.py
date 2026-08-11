import calendar
import math
import os
from datetime import date, datetime

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import (
    CATEGORIES,
    create_expense,
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


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _shift_months(d, n):
    month_index = d.month - 1 + n
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _date_presets(today):
    return [
        ("This Month", date(today.year, today.month, 1), today),
        ("Last 3 Months", _shift_months(today, -3), today),
        ("Last 6 Months", _shift_months(today, -6), today),
        ("All Time", None, None),
    ]


def _resolve_date_filter(args, today):
    """Resolve date_from/date_to from query args, matching them against presets.

    Returns (date_from_str, date_to_str, filters, is_custom_active).
    """
    parsed_from = _parse_date(args.get("date_from"))
    parsed_to = _parse_date(args.get("date_to"))

    if parsed_from is None or parsed_to is None:
        date_from, date_to = None, None
    elif parsed_from > parsed_to:
        flash("Start date must be before end date.")
        date_from, date_to = None, None
    else:
        date_from, date_to = parsed_from, parsed_to

    date_from_str = date_from.isoformat() if date_from else None
    date_to_str = date_to.isoformat() if date_to else None

    filters = []
    for label, preset_from, preset_to in _date_presets(today):
        preset_from_str = preset_from.isoformat() if preset_from else None
        preset_to_str = preset_to.isoformat() if preset_to else None
        active = date_from_str == preset_from_str and date_to_str == preset_to_str
        filters.append({
            "label": label,
            "date_from": preset_from_str,
            "date_to": preset_to_str,
            "active": active,
        })

    is_custom_active = bool(date_from_str and date_to_str) and not any(
        f["active"] for f in filters
    )

    return date_from_str, date_to_str, filters, is_custom_active


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

    date_from_str, date_to_str, filters, is_custom_active = _resolve_date_filter(
        request.args, date.today()
    )

    # ==== SUBAGENT 1: build `transactions` from get_expenses_by_user() ====
    expense_rows = get_expenses_by_user(user_id, date_from_str, date_to_str)
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
    summary = get_expense_summary(user_id, date_from_str, date_to_str)
    top_category = get_top_category(user_id, date_from_str, date_to_str)
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
    category_rows = get_category_totals(user_id, date_from_str, date_to_str)
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
        filters=filters,
        custom_date_from=date_from_str or "",
        custom_date_to=date_to_str or "",
        is_custom_active=is_custom_active,
    )


@app.route("/analytics")
def analytics():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    return render_template("analytics.html")


# ------------------------------------------------------------------ #
# Add-expense helpers                                                 #
# ------------------------------------------------------------------ #

MAX_DESCRIPTION_LENGTH = 255


def _validate_expense_form(amount_raw, date_raw, category_raw, description_raw):
    """Validate submitted add-expense fields.

    Returns (amount, error) — amount is a float and error is None on
    success; amount is None and error is a user-facing message otherwise.
    """
    try:
        amount = float(amount_raw)
    except ValueError:
        amount = None

    if amount is None or not math.isfinite(amount) or amount <= 0:
        return None, "Enter a valid amount greater than zero."

    if _parse_date(date_raw) is None:
        return None, "Enter a valid date."

    if category_raw not in CATEGORIES:
        return None, "Select a valid category."

    if len(description_raw) > MAX_DESCRIPTION_LENGTH:
        return None, f"Description must be {MAX_DESCRIPTION_LENGTH} characters or fewer."

    return amount, None


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    if request.method == "POST":
        amount_raw = request.form.get("amount", "").strip()
        date_raw = request.form.get("date", "").strip()
        category_raw = request.form.get("category", "").strip()
        description_raw = request.form.get("description", "").strip()

        form_values = {
            "amount": amount_raw,
            "date": date_raw,
            "category": category_raw,
            "description": description_raw,
        }

        amount, error = _validate_expense_form(
            amount_raw, date_raw, category_raw, description_raw
        )
        if error:
            return render_template(
                "expenses_add.html", categories=CATEGORIES,
                error=error, **form_values,
            )

        create_expense(
            session["user_id"], amount, category_raw, date_raw,
            description_raw or None,
        )
        return redirect(url_for("profile"))

    return render_template(
        "expenses_add.html", categories=CATEGORIES,
        amount="", date=date.today().isoformat(), category="", description="",
    )


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
