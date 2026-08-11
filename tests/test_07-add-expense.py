"""
Tests for Step 7 — "Add Expense".

Spec: .claude/Specs/07-add-expense.md

These tests are written against the *spec*, not against app.py's internal
implementation of add_expense(). app.py and database/db.py were read only
for structural context (route/endpoint names, the request.form field names
the route contracts to read -- amount/category/date/description --, the
get_db()/DB_PATH wiring, and the shape of seed_db()'s fixture data) — never
to copy business-logic expectations (e.g. exact validation error wording)
out of the implementation.

Fixture design notes
---------------------
Mirrors tests/test_06-date-filter-profile-page.py: database/db.py's
get_db() opens a brand-new sqlite3 connection per call keyed off a
module-level DB_PATH constant (not Flask's app.config), so each test gets
its own temp-file SQLite database by monkeypatching database.db.DB_PATH to
a unique path under pytest's tmp_path, then explicitly calling init_db()
and seed_db() against that path. app.py is imported lazily inside the
`app` fixture, after DB_PATH has already been monkeypatched, to avoid ever
touching the real spendly.db file.

Demo user (seeded by database/db.py:seed_db()): demo@spendly.com / demo123,
with 8 pre-existing expenses. Tests that assert "the new expense shows up
on the profile page" compare the page before vs. after the POST rather
than hardcoding the seeded totals, so they stay valid regardless of the
seed data's exact contents.
"""

import re
from datetime import date

import pytest

import database.db as db_module


# --------------------------------------------------------------------- #
# Fixtures                                                               #
# --------------------------------------------------------------------- #

@pytest.fixture
def app(tmp_path, monkeypatch):
    db_file = tmp_path / "test_spendly.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(db_file))

    # Import lazily so the module-level init_db()/seed_db() call in app.py
    # targets the patched DB_PATH rather than the real spendly.db.
    import app as app_module

    flask_app = app_module.app
    flask_app.config.update({"TESTING": True})

    with flask_app.app_context():
        db_module.init_db()
        db_module.seed_db()

    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def demo_client(client):
    """Test client logged in as the seeded demo user (8 expenses)."""
    response = client.post(
        "/login",
        data={"email": "demo@spendly.com", "password": "demo123"},
    )
    assert response.status_code == 302, "Demo login should redirect (to /profile)"
    return client


@pytest.fixture
def fresh_client(app):
    """Test client logged in as a brand-new user with zero expenses.

    Uses its own test_client() instance (independent cookie jar/session)
    rather than depending on the shared `client` fixture, so it stays
    isolated from `demo_client` when a test requests both.
    """
    fresh = app.test_client()
    fresh.post(
        "/register",
        data={
            "name": "Fresh User",
            "email": "fresh.user@example.com",
            "password": "freshpass123",
            "confirm_password": "freshpass123",
        },
    )
    response = fresh.post(
        "/login",
        data={"email": "fresh.user@example.com", "password": "freshpass123"},
    )
    assert response.status_code == 302, "Fresh user login should redirect (to /profile)"
    return fresh


# --------------------------------------------------------------------- #
# DB helpers (parameterised queries only)                                #
# --------------------------------------------------------------------- #

def get_user_id(email):
    user = db_module.get_user_by_email(email)
    assert user is not None, f"Expected a seeded/registered user for {email}"
    return user["id"]


def count_all_expenses():
    conn = db_module.get_db()
    row = conn.execute("SELECT COUNT(*) AS c FROM expenses").fetchone()
    conn.close()
    return row["c"]


def get_expenses_for_user(user_id):
    conn = db_module.get_db()
    rows = conn.execute(
        "SELECT * FROM expenses WHERE user_id = ? ORDER BY id DESC", (user_id,)
    ).fetchall()
    conn.close()
    return rows


VALID_FORM = {
    "amount": "250.50",
    "category": "Food",
    "date": "2024-06-15",
    "description": "Lunch with team",
}


def valid_form(**overrides):
    data = dict(VALID_FORM)
    data.update(overrides)
    return data


# --------------------------------------------------------------------- #
# HTML-parsing helpers (no bs4 available — plain regex is enough here)   #
# --------------------------------------------------------------------- #

STAT_RE = re.compile(
    r'<span class="profile-stat-label">(?P<label>[^<]*)</span>\s*'
    r'<span class="profile-stat-value">(?P<value>[^<]*)</span>'
)

CATEGORY_ROW_RE = re.compile(
    r'<span class="profile-cat-name">(?P<name>[^<]*)</span>.*?'
    r'<span class="profile-cat-amount">(?P<amount>[^<]*)</span>',
    re.DOTALL,
)

TRANSACTION_DATE_CELL_RE = re.compile(r'<td data-label="Date">(?P<date>[^<]*)</td>')


def get_stats_dict(html):
    return {m.group("label").strip(): m.group("value").strip() for m in STAT_RE.finditer(html)}


def get_categories_dict(html):
    return {m.group("name").strip(): m.group("amount").strip() for m in CATEGORY_ROW_RE.finditer(html)}


def get_transaction_dates(html):
    return [m.group("date").strip() for m in TRANSACTION_DATE_CELL_RE.finditer(html)]


def parse_currency(value):
    return float(value.replace("₹", "").replace(",", "").strip())


def extract_input_value(html, field_id):
    """Extract the value="" attribute of an <input id="field_id" ...> tag."""
    tag_match = re.search(rf'<input[^>]*\bid="{re.escape(field_id)}"[^>]*>', html)
    assert tag_match, f"Expected an <input id=\"{field_id}\"> in the rendered form"
    value_match = re.search(r'value="([^"]*)"', tag_match.group(0))
    return value_match.group(1) if value_match else ""


def extract_selected_category(html):
    """Return the value of whichever non-empty <option> is marked selected."""
    match = re.search(r'<option value="([^"]+)" selected>', html)
    return match.group(1) if match else None


def get_category_select_options(html):
    select_match = re.search(r'<select[^>]*\bid="category"[^>]*>(.*?)</select>', html, re.DOTALL)
    assert select_match, 'Expected a <select id="category"> in the rendered form'
    return re.findall(r'<option value="([^"]+)"', select_match.group(1))


# --------------------------------------------------------------------- #
# Auth guard                                                             #
# --------------------------------------------------------------------- #

class TestAddExpenseAuthGuard:
    def test_get_add_expense_without_login_redirects_to_login(self, client):
        response = client.get("/expenses/add")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_post_add_expense_without_login_redirects_to_login(self, client):
        before = count_all_expenses()
        response = client.post("/expenses/add", data=valid_form())
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]
        assert count_all_expenses() == before, "Unauthenticated POST must not insert a row"


# --------------------------------------------------------------------- #
# GET — form rendering                                                   #
# --------------------------------------------------------------------- #

class TestAddExpenseGetForm:
    def test_get_add_expense_logged_in_returns_200_with_form(self, demo_client):
        response = demo_client.get("/expenses/add")
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert "<form" in html, "Expected the add-expense page to render a form"

    def test_get_add_expense_form_has_required_fields(self, demo_client):
        html = demo_client.get("/expenses/add").get_data(as_text=True)

        assert 'name="amount"' in html
        assert 'name="category"' in html
        assert 'name="date"' in html
        assert 'name="description"' in html

    def test_get_add_expense_date_defaults_to_today(self, demo_client):
        html = demo_client.get("/expenses/add").get_data(as_text=True)
        assert extract_input_value(html, "date") == date.today().isoformat()

    def test_get_add_expense_category_select_lists_all_categories(self, demo_client):
        html = demo_client.get("/expenses/add").get_data(as_text=True)
        options = get_category_select_options(html)

        for category in db_module.CATEGORIES:
            assert category in options, f"Expected {category!r} in the category <select>"

    def test_get_add_expense_form_posts_to_add_expense_route(self, demo_client, app):
        html = demo_client.get("/expenses/add").get_data(as_text=True)
        with app.test_request_context():
            from flask import url_for
            expected_action = url_for("add_expense")
        assert f'action="{expected_action}"' in html


# --------------------------------------------------------------------- #
# POST — happy path                                                      #
# --------------------------------------------------------------------- #

class TestAddExpenseValidPost:
    def test_post_valid_data_redirects_to_profile(self, demo_client, app):
        response = demo_client.post("/expenses/add", data=valid_form())
        assert response.status_code == 302
        with app.test_request_context():
            from flask import url_for
            expected_location = url_for("profile")
        assert response.headers["Location"].endswith(expected_location)

    def test_post_valid_data_inserts_exactly_one_row(self, demo_client):
        before = count_all_expenses()
        demo_client.post("/expenses/add", data=valid_form())
        assert count_all_expenses() == before + 1

    def test_post_valid_data_persists_correct_field_values_for_current_user(self, demo_client):
        user_id = get_user_id("demo@spendly.com")
        demo_client.post(
            "/expenses/add",
            data=valid_form(amount="333.75", category="Health", date="2024-05-01",
                             description="Doctor visit"),
        )
        rows = get_expenses_for_user(user_id)
        newest = rows[0]

        assert newest["user_id"] == user_id
        assert newest["amount"] == pytest.approx(333.75)
        assert newest["category"] == "Health"
        assert newest["date"] == "2024-05-01"
        assert newest["description"] == "Doctor visit"

    def test_post_valid_data_without_description_still_succeeds(self, demo_client):
        before = count_all_expenses()
        response = demo_client.post(
            "/expenses/add",
            data=valid_form(description=""),
        )
        assert response.status_code == 302
        assert count_all_expenses() == before + 1, "Description is optional per spec"

    def test_post_valid_data_scopes_row_to_current_user_only(self, demo_client, fresh_client):
        demo_id = get_user_id("demo@spendly.com")
        fresh_id = get_user_id("fresh.user@example.com")

        fresh_client.post(
            "/expenses/add",
            data=valid_form(amount="99.00", description="Fresh-only expense"),
        )

        assert len(get_expenses_for_user(fresh_id)) == 1
        demo_descriptions = [r["description"] for r in get_expenses_for_user(demo_id)]
        assert "Fresh-only expense" not in demo_descriptions, (
            "An expense created by one user must not appear under another user's id"
        )

    @pytest.mark.parametrize("category", db_module.CATEGORIES)
    def test_post_accepts_every_category_in_db_categories(self, demo_client, category):
        before = count_all_expenses()
        response = demo_client.post("/expenses/add", data=valid_form(category=category))
        assert response.status_code == 302, f"Category {category!r} from CATEGORIES should be accepted"
        assert count_all_expenses() == before + 1

    def test_post_description_with_html_is_escaped_on_profile_page(self, demo_client):
        demo_client.post(
            "/expenses/add",
            data=valid_form(description="<script>alert(1)</script>"),
        )
        html = demo_client.get("/profile").get_data(as_text=True)
        assert "<script>alert(1)</script>" not in html, "Description must be HTML-escaped, not raw"
        assert "&lt;script&gt;" in html

    def test_post_description_with_sql_special_characters_is_stored_safely(self, demo_client):
        payload = "Robert'); DROP TABLE expenses;--"
        before = count_all_expenses()
        response = demo_client.post("/expenses/add", data=valid_form(description=payload))
        assert response.status_code == 302
        assert count_all_expenses() == before + 1, "SQL-special-character input must not break the insert"

        user_id = get_user_id("demo@spendly.com")
        rows = get_expenses_for_user(user_id)
        assert rows[0]["description"] == payload, "Parameterised queries must store the literal string"


# --------------------------------------------------------------------- #
# POST — new expense reflected on the profile page                       #
# --------------------------------------------------------------------- #

class TestAddExpenseReflectedOnProfile:
    def test_new_expense_appears_in_transaction_history(self, demo_client):
        demo_client.post(
            "/expenses/add",
            data=valid_form(date="2024-06-15", description="Lunch with team"),
        )
        html = demo_client.get("/profile").get_data(as_text=True)

        assert "2024-06-15" in get_transaction_dates(html)
        assert "Lunch with team" in html

    def test_new_expense_increments_transaction_count_and_total(self, demo_client):
        before_html = demo_client.get("/profile").get_data(as_text=True)
        before_stats = get_stats_dict(before_html)
        before_count = int(before_stats["Transactions"])
        before_total = parse_currency(before_stats["Total spent"])

        demo_client.post("/expenses/add", data=valid_form(amount="500.00"))

        after_html = demo_client.get("/profile").get_data(as_text=True)
        after_stats = get_stats_dict(after_html)

        assert int(after_stats["Transactions"]) == before_count + 1
        assert parse_currency(after_stats["Total spent"]) == pytest.approx(before_total + 500.00, abs=0.01)

    def test_new_expense_updates_category_breakdown(self, fresh_client):
        # Fresh user starts with zero expenses, so the new category total is
        # unambiguous and doesn't need to be diffed against pre-existing data.
        fresh_client.post(
            "/expenses/add",
            data=valid_form(category="Entertainment", amount="150.00"),
        )
        html = fresh_client.get("/profile").get_data(as_text=True)
        categories = get_categories_dict(html)

        assert "Entertainment" in categories
        assert parse_currency(categories["Entertainment"]) == pytest.approx(150.00, abs=0.01)

    def test_new_expense_visible_immediately_after_redirect_is_followed(self, demo_client):
        response = demo_client.post(
            "/expenses/add", data=valid_form(description="Redirect-follow check"),
            follow_redirects=True,
        )
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert "Redirect-follow check" in html


# --------------------------------------------------------------------- #
# POST — invalid amount                                                  #
# --------------------------------------------------------------------- #

class TestAddExpenseInvalidAmount:
    @pytest.mark.parametrize(
        "bad_amount",
        ["", "   ", "-50", "-0.01", "0", "0.00", "abc", "nan", "inf", "-inf"],
        ids=["empty", "whitespace", "negative", "negative_decimal", "zero",
             "zero_decimal", "non_numeric", "nan", "inf", "neg_inf"],
    )
    def test_invalid_amount_rerenders_form_without_inserting(self, demo_client, bad_amount):
        before = count_all_expenses()
        response = demo_client.post("/expenses/add", data=valid_form(amount=bad_amount))
        html = response.get_data(as_text=True)

        assert response.status_code == 200, f"Amount {bad_amount!r} should re-render the form, not redirect"
        assert "<form" in html
        assert count_all_expenses() == before, f"Amount {bad_amount!r} must not create a row"

    def test_invalid_amount_shows_an_error_message(self, demo_client):
        html = demo_client.post("/expenses/add", data=valid_form(amount="-50")).get_data(as_text=True)
        assert 'class="auth-error"' in html, (
            "Spec requires re-using the flash/flash-error pattern already used by "
            "register.html/login.html for validation errors"
        )

    def test_invalid_amount_preserves_entered_date_and_description(self, demo_client):
        html = demo_client.post(
            "/expenses/add",
            data=valid_form(amount="-50", date="2024-03-03", description="Kept on error"),
        ).get_data(as_text=True)

        assert extract_input_value(html, "date") == "2024-03-03"
        assert extract_input_value(html, "description") == "Kept on error"

    def test_invalid_amount_preserves_selected_category(self, demo_client):
        html = demo_client.post(
            "/expenses/add", data=valid_form(amount="abc", category="Shopping"),
        ).get_data(as_text=True)
        assert extract_selected_category(html) == "Shopping"


# --------------------------------------------------------------------- #
# POST — invalid date                                                    #
# --------------------------------------------------------------------- #

class TestAddExpenseInvalidDate:
    @pytest.mark.parametrize(
        "bad_date",
        ["", "not-a-date", "2024-13-45", "2024-02-30", "01/01/2024", "2024/06/15"],
        ids=["empty", "garbage", "bad_month_day", "invalid_feb_30", "slash_us_format", "slash_iso_order"],
    )
    def test_invalid_date_rerenders_form_without_inserting(self, demo_client, bad_date):
        before = count_all_expenses()
        response = demo_client.post("/expenses/add", data=valid_form(date=bad_date))
        html = response.get_data(as_text=True)

        assert response.status_code == 200, f"Date {bad_date!r} should re-render the form, not redirect"
        assert "<form" in html
        assert count_all_expenses() == before, f"Date {bad_date!r} must not create a row"

    def test_invalid_date_shows_an_error_message(self, demo_client):
        html = demo_client.post(
            "/expenses/add", data=valid_form(date="not-a-date"),
        ).get_data(as_text=True)
        assert 'class="auth-error"' in html

    def test_invalid_date_preserves_entered_amount_and_description(self, demo_client):
        html = demo_client.post(
            "/expenses/add",
            data=valid_form(date="not-a-date", amount="42.50", description="Kept on date error"),
        ).get_data(as_text=True)

        assert extract_input_value(html, "amount") == "42.50"
        assert extract_input_value(html, "description") == "Kept on date error"


# --------------------------------------------------------------------- #
# POST — invalid category                                                #
# --------------------------------------------------------------------- #

class TestAddExpenseInvalidCategory:
    @pytest.mark.parametrize(
        "bad_category",
        ["", "Bogus", "food", "FOOD", "Groceries"],
        ids=["empty", "not_in_list", "lowercase", "uppercase", "similar_but_absent"],
    )
    def test_invalid_category_rerenders_form_without_inserting(self, demo_client, bad_category):
        before = count_all_expenses()
        response = demo_client.post("/expenses/add", data=valid_form(category=bad_category))
        html = response.get_data(as_text=True)

        assert response.status_code == 200, f"Category {bad_category!r} should re-render the form, not redirect"
        assert "<form" in html
        assert count_all_expenses() == before, f"Category {bad_category!r} must not create a row"

    def test_invalid_category_shows_an_error_message(self, demo_client):
        html = demo_client.post(
            "/expenses/add", data=valid_form(category="Bogus"),
        ).get_data(as_text=True)
        assert 'class="auth-error"' in html

    def test_invalid_category_preserves_entered_amount_and_date(self, demo_client):
        html = demo_client.post(
            "/expenses/add",
            data=valid_form(category="Bogus", amount="77.00", date="2024-01-20"),
        ).get_data(as_text=True)

        assert extract_input_value(html, "amount") == "77.00"
        assert extract_input_value(html, "date") == "2024-01-20"


# --------------------------------------------------------------------- #
# Profile page — link to /expenses/add                                   #
# --------------------------------------------------------------------- #

class TestProfileHasAddExpenseLink:
    def test_profile_page_links_to_add_expense_route(self, demo_client, app):
        html = demo_client.get("/profile").get_data(as_text=True)
        with app.test_request_context():
            from flask import url_for
            expected_href = url_for("add_expense")

        assert f'href="{expected_href}"' in html, (
            "Profile page must contain a visible link/button to /expenses/add"
        )

    def test_profile_add_expense_link_is_reachable(self, demo_client):
        response = demo_client.get("/expenses/add")
        assert response.status_code == 200
