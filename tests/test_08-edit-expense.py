"""
Tests for Step 8 — "Edit Expense".

Spec: .claude/specs/08-edit-expense.md

These tests are written against the spec's behavior, not against app.py's
internal implementation of edit_expense(). app.py and database/db.py were
read only for structural context (route/endpoint names, the request.form
field names the route contracts to read, the get_db()/DB_PATH wiring, and
the shape of seed_db()'s fixture data) — never to copy business-logic
expectations (e.g. exact validation error wording) out of the implementation.

Fixture design notes
---------------------
Mirrors tests/test_07-add-expense.py: database/db.py's get_db() opens a
brand-new sqlite3 connection per call keyed off a module-level DB_PATH
constant (not Flask's app.config), so each test gets its own temp-file
SQLite database by monkeypatching database.db.DB_PATH to a unique path
under pytest's tmp_path, then explicitly calling init_db() and seed_db()
against that path. app.py is imported lazily inside the `app` fixture,
after DB_PATH has already been monkeypatched, to avoid ever touching the
real spendly.db file.

Demo user (seeded by database/db.py:seed_db()): demo@spendly.com / demo123,
with 8 pre-existing expenses — used as the expenses being edited. A second
registered user (`other_client`) is needed for ownership tests, since
seed_db() only ever seeds one account.
"""

import re

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
def other_client(app):
    """A second registered+logged-in user, for cross-ownership tests."""
    other = app.test_client()
    other.post(
        "/register",
        data={
            "name": "Other User",
            "email": "other.user@example.com",
            "password": "otherpass123",
            "confirm_password": "otherpass123",
        },
    )
    response = other.post(
        "/login",
        data={"email": "other.user@example.com", "password": "otherpass123"},
    )
    assert response.status_code == 302, "Other user login should redirect (to /profile)"
    return other


@pytest.fixture
def demo_expense_id(app):
    """Id of one of the seeded demo user's expenses — the target of most edit tests.

    Reads straight from the DB rather than depending on the `demo_client`
    fixture, since that fixture logs in on the shared `client` test client —
    pulling it in here would leak an authenticated session into tests that
    specifically need an unauthenticated `client`.
    """
    user_id = get_user_id("demo@spendly.com")
    return first_expense_id_for_user(user_id)


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


def get_expense_row(expense_id):
    conn = db_module.get_db()
    row = conn.execute(
        "SELECT * FROM expenses WHERE id = ?", (expense_id,)
    ).fetchone()
    conn.close()
    return row


def first_expense_id_for_user(user_id):
    rows = get_expenses_for_user(user_id)
    assert rows, f"Expected at least one seeded expense for user {user_id}"
    return rows[0]["id"]


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
# Unit tests — get_expense_by_id / update_expense                        #
# --------------------------------------------------------------------- #

class TestGetExpenseByIdUnit:
    def test_returns_row_for_owning_user(self, app, demo_expense_id):
        user_id = get_user_id("demo@spendly.com")
        row = db_module.get_expense_by_id(demo_expense_id, user_id)
        assert row is not None
        assert row["id"] == demo_expense_id
        assert row["user_id"] == user_id

    def test_returns_none_for_other_users_expense(self, app, demo_expense_id):
        user_id = get_user_id("demo@spendly.com")
        row = db_module.get_expense_by_id(demo_expense_id, user_id + 999)
        assert row is None

    def test_returns_none_for_nonexistent_id(self, app):
        user_id = get_user_id("demo@spendly.com")
        row = db_module.get_expense_by_id(999999, user_id)
        assert row is None


class TestUpdateExpenseUnit:
    def test_persists_new_values_for_owning_user(self, app, demo_expense_id):
        user_id = get_user_id("demo@spendly.com")
        db_module.update_expense(
            demo_expense_id, user_id, 99.0, "Health", "2024-07-01", "Updated via unit test",
        )

        row = get_expense_row(demo_expense_id)
        assert row["amount"] == pytest.approx(99.0)
        assert row["category"] == "Health"
        assert row["date"] == "2024-07-01"
        assert row["description"] == "Updated via unit test"

    def test_wrong_user_id_leaves_row_unchanged(self, app, demo_expense_id):
        user_id = get_user_id("demo@spendly.com")
        original = get_expense_row(demo_expense_id)

        db_module.update_expense(
            demo_expense_id, user_id + 999, 1.0, "Other", "2024-01-01", "Should not apply",
        )

        row = get_expense_row(demo_expense_id)
        assert row["amount"] == pytest.approx(original["amount"])
        assert row["category"] == original["category"]
        assert row["date"] == original["date"]
        assert row["description"] == original["description"]


# --------------------------------------------------------------------- #
# Auth guard                                                             #
# --------------------------------------------------------------------- #

class TestEditExpenseAuthGuard:
    def test_get_edit_expense_without_login_redirects_to_login(self, client, demo_expense_id):
        response = client.get(f"/expenses/{demo_expense_id}/edit")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_post_edit_expense_without_login_redirects_to_login(self, client, demo_expense_id):
        original = get_expense_row(demo_expense_id)

        response = client.post(f"/expenses/{demo_expense_id}/edit", data=valid_form())
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

        unchanged = get_expense_row(demo_expense_id)
        assert unchanged["amount"] == original["amount"], "Unauthenticated POST must not update the row"


# --------------------------------------------------------------------- #
# GET — form rendering                                                   #
# --------------------------------------------------------------------- #

class TestEditExpenseGetForm:
    def test_get_own_expense_returns_200_with_prefilled_form(self, demo_client, demo_expense_id):
        expense = get_expense_row(demo_expense_id)

        response = demo_client.get(f"/expenses/{demo_expense_id}/edit")
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert "<form" in html
        assert extract_input_value(html, "amount") == str(expense["amount"])
        assert extract_input_value(html, "date") == expense["date"]
        assert extract_input_value(html, "description") == (expense["description"] or "")
        assert extract_selected_category(html) == expense["category"]

    def test_get_own_expense_category_select_lists_all_categories(self, demo_client, demo_expense_id):
        html = demo_client.get(f"/expenses/{demo_expense_id}/edit").get_data(as_text=True)
        options = get_category_select_options(html)

        for category in db_module.CATEGORIES:
            assert category in options, f"Expected {category!r} in the category <select>"

    def test_get_own_expense_form_posts_to_edit_expense_route(self, demo_client, app, demo_expense_id):
        html = demo_client.get(f"/expenses/{demo_expense_id}/edit").get_data(as_text=True)
        with app.test_request_context():
            from flask import url_for
            expected_action = url_for("edit_expense", id=demo_expense_id)
        assert f'action="{expected_action}"' in html

    def test_get_other_users_expense_returns_404(self, other_client, demo_expense_id):
        response = other_client.get(f"/expenses/{demo_expense_id}/edit")
        assert response.status_code == 404

    def test_get_nonexistent_id_returns_404(self, demo_client):
        response = demo_client.get("/expenses/999999/edit")
        assert response.status_code == 404


# --------------------------------------------------------------------- #
# POST — happy path                                                      #
# --------------------------------------------------------------------- #

class TestEditExpenseValidPost:
    def test_valid_data_redirects_to_profile(self, demo_client, app, demo_expense_id):
        response = demo_client.post(f"/expenses/{demo_expense_id}/edit", data=valid_form())
        assert response.status_code == 302
        with app.test_request_context():
            from flask import url_for
            expected_location = url_for("profile")
        assert response.headers["Location"].endswith(expected_location)

    def test_valid_data_updates_row_in_place_without_changing_row_count(self, demo_client, demo_expense_id):
        before = count_all_expenses()
        demo_client.post(
            f"/expenses/{demo_expense_id}/edit",
            data=valid_form(amount="333.75", category="Health", date="2024-05-01",
                             description="Doctor visit"),
        )
        assert count_all_expenses() == before, "Editing must not insert or delete rows"

        row = get_expense_row(demo_expense_id)
        assert row["amount"] == pytest.approx(333.75)
        assert row["category"] == "Health"
        assert row["date"] == "2024-05-01"
        assert row["description"] == "Doctor visit"

    def test_valid_data_without_description_saves_as_null(self, demo_client, demo_expense_id):
        response = demo_client.post(
            f"/expenses/{demo_expense_id}/edit", data=valid_form(description=""),
        )
        assert response.status_code == 302

        row = get_expense_row(demo_expense_id)
        assert row["description"] is None

    def test_valid_data_visible_on_profile_after_redirect(self, demo_client, demo_expense_id):
        response = demo_client.post(
            f"/expenses/{demo_expense_id}/edit",
            data=valid_form(description="Edited via redirect-follow check"),
            follow_redirects=True,
        )
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert "Edited via redirect-follow check" in html


# --------------------------------------------------------------------- #
# POST — cross-ownership                                                 #
# --------------------------------------------------------------------- #

class TestEditExpenseCrossOwnershipPost:
    def test_editing_other_users_expense_returns_404_and_does_not_update(self, other_client, demo_expense_id):
        original = get_expense_row(demo_expense_id)

        response = other_client.post(
            f"/expenses/{demo_expense_id}/edit",
            data=valid_form(amount="1.00", description="Should not apply"),
        )
        assert response.status_code == 404

        unchanged = get_expense_row(demo_expense_id)
        assert unchanged["amount"] == original["amount"]
        assert unchanged["description"] == original["description"]


# --------------------------------------------------------------------- #
# POST — invalid amount                                                  #
# --------------------------------------------------------------------- #

class TestEditExpenseInvalidAmount:
    @pytest.mark.parametrize(
        "bad_amount",
        ["", "   ", "-50", "-0.01", "0", "0.00", "abc", "nan", "inf", "-inf"],
        ids=["empty", "whitespace", "negative", "negative_decimal", "zero",
             "zero_decimal", "non_numeric", "nan", "inf", "neg_inf"],
    )
    def test_invalid_amount_rerenders_form_without_updating(self, demo_client, demo_expense_id, bad_amount):
        original = get_expense_row(demo_expense_id)

        response = demo_client.post(
            f"/expenses/{demo_expense_id}/edit", data=valid_form(amount=bad_amount),
        )
        html = response.get_data(as_text=True)

        assert response.status_code == 200, f"Amount {bad_amount!r} should re-render the form, not redirect"
        assert "<form" in html

        unchanged = get_expense_row(demo_expense_id)
        assert unchanged["amount"] == original["amount"], f"Amount {bad_amount!r} must not update the row"

    def test_invalid_amount_shows_an_error_message(self, demo_client, demo_expense_id):
        html = demo_client.post(
            f"/expenses/{demo_expense_id}/edit", data=valid_form(amount="-50"),
        ).get_data(as_text=True)
        assert 'class="auth-error"' in html

    def test_invalid_amount_preserves_entered_date_and_description(self, demo_client, demo_expense_id):
        html = demo_client.post(
            f"/expenses/{demo_expense_id}/edit",
            data=valid_form(amount="-50", date="2024-03-03", description="Kept on error"),
        ).get_data(as_text=True)

        assert extract_input_value(html, "date") == "2024-03-03"
        assert extract_input_value(html, "description") == "Kept on error"

    def test_invalid_amount_preserves_selected_category(self, demo_client, demo_expense_id):
        html = demo_client.post(
            f"/expenses/{demo_expense_id}/edit", data=valid_form(amount="abc", category="Shopping"),
        ).get_data(as_text=True)
        assert extract_selected_category(html) == "Shopping"


# --------------------------------------------------------------------- #
# POST — invalid date                                                    #
# --------------------------------------------------------------------- #

class TestEditExpenseInvalidDate:
    @pytest.mark.parametrize(
        "bad_date",
        ["", "not-a-date", "2024-13-45", "2024-02-30", "01/01/2024", "2024/06/15"],
        ids=["empty", "garbage", "bad_month_day", "invalid_feb_30", "slash_us_format", "slash_iso_order"],
    )
    def test_invalid_date_rerenders_form_without_updating(self, demo_client, demo_expense_id, bad_date):
        original = get_expense_row(demo_expense_id)

        response = demo_client.post(
            f"/expenses/{demo_expense_id}/edit", data=valid_form(date=bad_date),
        )
        html = response.get_data(as_text=True)

        assert response.status_code == 200, f"Date {bad_date!r} should re-render the form, not redirect"
        assert "<form" in html

        unchanged = get_expense_row(demo_expense_id)
        assert unchanged["date"] == original["date"], f"Date {bad_date!r} must not update the row"

    def test_invalid_date_shows_an_error_message(self, demo_client, demo_expense_id):
        html = demo_client.post(
            f"/expenses/{demo_expense_id}/edit", data=valid_form(date="not-a-date"),
        ).get_data(as_text=True)
        assert 'class="auth-error"' in html

    def test_invalid_date_preserves_entered_amount_and_description(self, demo_client, demo_expense_id):
        html = demo_client.post(
            f"/expenses/{demo_expense_id}/edit",
            data=valid_form(date="not-a-date", amount="42.50", description="Kept on date error"),
        ).get_data(as_text=True)

        assert extract_input_value(html, "amount") == "42.50"
        assert extract_input_value(html, "description") == "Kept on date error"


# --------------------------------------------------------------------- #
# POST — invalid category                                                #
# --------------------------------------------------------------------- #

class TestEditExpenseInvalidCategory:
    @pytest.mark.parametrize(
        "bad_category",
        ["", "Bogus", "food", "FOOD", "Groceries"],
        ids=["empty", "not_in_list", "lowercase", "uppercase", "similar_but_absent"],
    )
    def test_invalid_category_rerenders_form_without_updating(self, demo_client, demo_expense_id, bad_category):
        original = get_expense_row(demo_expense_id)

        response = demo_client.post(
            f"/expenses/{demo_expense_id}/edit", data=valid_form(category=bad_category),
        )
        html = response.get_data(as_text=True)

        assert response.status_code == 200, f"Category {bad_category!r} should re-render the form, not redirect"
        assert "<form" in html

        unchanged = get_expense_row(demo_expense_id)
        assert unchanged["category"] == original["category"], f"Category {bad_category!r} must not update the row"

    def test_invalid_category_shows_an_error_message(self, demo_client, demo_expense_id):
        html = demo_client.post(
            f"/expenses/{demo_expense_id}/edit", data=valid_form(category="Bogus"),
        ).get_data(as_text=True)
        assert 'class="auth-error"' in html

    def test_invalid_category_preserves_entered_amount_and_date(self, demo_client, demo_expense_id):
        html = demo_client.post(
            f"/expenses/{demo_expense_id}/edit",
            data=valid_form(category="Bogus", amount="77.00", date="2024-01-20"),
        ).get_data(as_text=True)

        assert extract_input_value(html, "amount") == "77.00"
        assert extract_input_value(html, "date") == "2024-01-20"


# --------------------------------------------------------------------- #
# Profile page — link to /expenses/<id>/edit                             #
# --------------------------------------------------------------------- #

class TestProfileHasEditExpenseLinks:
    def test_profile_page_links_to_edit_expense_for_each_transaction(self, demo_client, app, demo_expense_id):
        html = demo_client.get("/profile").get_data(as_text=True)
        with app.test_request_context():
            from flask import url_for
            expected_href = url_for("edit_expense", id=demo_expense_id)

        assert f'href="{expected_href}"' in html, (
            "Profile page must contain a visible edit link for each transaction"
        )

    def test_profile_edit_expense_link_is_reachable(self, demo_client, demo_expense_id):
        response = demo_client.get(f"/expenses/{demo_expense_id}/edit")
        assert response.status_code == 200
