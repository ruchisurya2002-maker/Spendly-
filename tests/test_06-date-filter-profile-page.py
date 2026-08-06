"""
Tests for Step 6 — "Date Filter for Profile Page".

Spec: .claude/specs/06-date-filter-profile-page.md

These tests are written against the *spec*, not against app.py's internal
implementation. app.py and database/db.py were read only for structural
context (route names, form field names, get_db()/DB_PATH wiring, the shape
of seed_db()'s fixture data, and the class names profile.html uses) — never
to copy business-logic expectations out of the implementation.

Fixture design notes
---------------------
database/db.py's `get_db()` opens a *new* sqlite3 connection per call and
closes it immediately, keyed off a module-level `DB_PATH` constant (not
Flask's `app.config`). That means the common ":memory:" trick from the
project-wide fixture template does NOT work here — every call would get a
brand-new, empty in-memory database. Instead, each test gets its own
temp-file SQLite database by monkeypatching `database.db.DB_PATH` to a
unique path under pytest's `tmp_path`, then explicitly calling `init_db()`
and `seed_db()` against that path. This gives full test isolation while
staying faithful to how the app is actually wired.

`app.py` also runs `init_db()` / `seed_db()` once at *import* time using the
default `DB_PATH`. To avoid ever touching the real `spendly.db` file, `app`
is imported lazily inside the `app` fixture, after `DB_PATH` has already
been monkeypatched.

Demo user (seeded by database/db.py:seed_db()): demo@spendly.com / demo123,
with 8 expenses at fixed *offsets* (in days-ago) from "today". Because the
offsets shift with the current date, every expected total/count/category
below is computed dynamically from those offsets rather than hardcoded.
"""

import html
import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qsl, urlsplit

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
    # (which only actually runs Python code the first time it's imported in
    # the whole test session) targets the patched DB_PATH.
    import app as app_module

    flask_app = app_module.app
    flask_app.config.update({"TESTING": True})

    # Explicitly (re-)initialise / (re-)seed against *this* test's DB file,
    # since app_module may already have been imported (and its top-level
    # init/seed already executed against a different tmp path) by an
    # earlier test in this session. init_db() is idempotent
    # (CREATE TABLE IF NOT EXISTS) and seed_db() no-ops if already seeded,
    # so this is safe to call unconditionally.
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
def fresh_client(client):
    """Test client logged in as a brand-new user with zero expenses."""
    client.post(
        "/register",
        data={
            "name": "Fresh User",
            "email": "fresh.user@example.com",
            "password": "freshpass123",
            "confirm_password": "freshpass123",
        },
    )
    response = client.post(
        "/login",
        data={"email": "fresh.user@example.com", "password": "freshpass123"},
    )
    assert response.status_code == 302, "Fresh user login should redirect (to /profile)"
    return client


# --------------------------------------------------------------------- #
# Seed-data helpers                                                      #
# --------------------------------------------------------------------- #

# Mirrors the 8 demo expenses seed_db() inserts: (amount, category,
# days_ago, description). This is test *fixture* data (what the seed
# creates), not the feature's business logic, so it's fine to encode here —
# expected filter results are derived from it dynamically below rather than
# hardcoded, since the offsets are relative to "today".
SEED_EXPENSE_OFFSETS = [
    (450.00, "Food", 2, "Groceries"),
    (180.00, "Transport", 5, "Bus pass"),
    (1450.00, "Bills", 7, "Electricity bill"),
    (620.00, "Health", 11, "Pharmacy"),
    (349.00, "Entertainment", 14, "Streaming subscription"),
    (1899.00, "Shopping", 18, "New shoes"),
    (120.00, "Other", 23, "Miscellaneous"),
    (780.00, "Food", 29, "Restaurant"),
]


def seed_expenses(today=None):
    today = today or date.today()
    return [
        {"amount": amount, "category": category, "date": today - timedelta(days=days_ago)}
        for amount, category, days_ago, _description in SEED_EXPENSE_OFFSETS
    ]


def filter_by_range(expenses, date_from, date_to):
    if date_from is None or date_to is None:
        return list(expenses)
    return [e for e in expenses if date_from <= e["date"] <= date_to]


def expected_total(expenses):
    return sum(e["amount"] for e in expenses)


def expected_category_totals(expenses):
    totals = {}
    for e in expenses:
        totals[e["category"]] = totals.get(e["category"], 0.0) + e["amount"]
    return totals


def expected_top_category(expenses):
    totals = expected_category_totals(expenses)
    if not totals:
        return None
    return max(totals.items(), key=lambda kv: kv[1])[0]


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

PILL_RE = re.compile(
    r'<a href="(?P<href>[^"]*)"\s+class="filter-pill(?P<active>\s+active)?">(?P<label>[^<]*)</a>'
)

TRANSACTION_DATE_CELL_RE = re.compile(r'<td data-label="Date">')

FLASH_TEXT = "Start date must be before end date."


def get_stats_dict(html):
    return {m.group("label").strip(): m.group("value").strip() for m in STAT_RE.finditer(html)}


def get_categories_dict(html):
    return {m.group("name").strip(): m.group("amount").strip() for m in CATEGORY_ROW_RE.finditer(html)}


def get_pills(page_html):
    # Jinja auto-escapes "&" as "&amp;" inside href="..." attributes, so the
    # captured href must be HTML-unescaped before it's treated as a real URL
    # (used for query-string parsing and for following the link).
    return {
        m.group("label").strip(): {
            "href": html.unescape(m.group("href")),
            "active": bool(m.group("active")),
        }
        for m in PILL_RE.finditer(page_html)
    }


def count_transaction_rows(html):
    return len(TRANSACTION_DATE_CELL_RE.findall(html))


def is_custom_form_active(html):
    return 'class="profile-filter-custom active"' in html


def parse_currency(value):
    return float(value.replace("₹", "").replace(",", "").strip())


def assert_sections_match(html, expected_expenses):
    """Assert the summary stats, transaction list, and category breakdown
    in `html` are consistent with `expected_expenses`."""
    stats = get_stats_dict(html)

    assert "₹" in stats["Total spent"], "Total spent must display the rupee symbol"
    assert parse_currency(stats["Total spent"]) == pytest.approx(
        expected_total(expected_expenses), abs=0.01
    )
    assert stats["Transactions"] == str(len(expected_expenses))

    expected_top = expected_top_category(expected_expenses)
    if expected_top is not None:
        assert stats["Top category"] == expected_top

    assert count_transaction_rows(html) == len(expected_expenses)

    expected_cats = expected_category_totals(expected_expenses)
    actual_cats = get_categories_dict(html)
    assert set(actual_cats.keys()) == set(expected_cats.keys())
    for name, total in expected_cats.items():
        assert parse_currency(actual_cats[name]) == pytest.approx(total, abs=0.01)


# --------------------------------------------------------------------- #
# Auth guard                                                             #
# --------------------------------------------------------------------- #

class TestProfileFilterAuthGuard:
    def test_unauthenticated_get_profile_redirects_to_login(self, client):
        response = client.get("/profile")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_unauthenticated_get_profile_with_filter_params_redirects_to_login(self, client):
        response = client.get("/profile?date_from=2024-01-01&date_to=2024-01-31")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


# --------------------------------------------------------------------- #
# Happy paths                                                            #
# --------------------------------------------------------------------- #

class TestProfileFilterHappyPaths:
    def test_no_query_params_shows_unfiltered_data(self, demo_client):
        response = demo_client.get("/profile")
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert_sections_match(html, seed_expenses())

    def test_no_query_params_marks_all_time_as_active(self, demo_client):
        html = demo_client.get("/profile").get_data(as_text=True)
        pills = get_pills(html)

        assert pills["All Time"]["active"] is True
        for label, pill in pills.items():
            if label != "All Time":
                assert pill["active"] is False, f"{label} should not be active by default"
        assert not is_custom_form_active(html)

    def test_this_month_preset_filters_all_three_sections(self, demo_client):
        today = date.today()
        first_of_month = date(today.year, today.month, 1)
        expected = filter_by_range(seed_expenses(today), first_of_month, today)

        response = demo_client.get(
            f"/profile?date_from={first_of_month.isoformat()}&date_to={today.isoformat()}"
        )
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert_sections_match(html, expected)

        pills = get_pills(html)
        assert pills["This Month"]["active"] is True
        assert pills["All Time"]["active"] is False

    def test_last_3_months_preset_link_filters_all_three_sections(self, demo_client):
        # Follow the app's own rendered "Last 3 Months" link rather than
        # re-deriving its exact month-shift arithmetic (an implementation
        # detail the spec doesn't pin down beyond "3-month window ending
        # today"). Every seed expense is at most 29 days old, which is
        # comfortably inside any reasonable 3-month window ending today, so
        # the filtered result must equal the full unfiltered seed set.
        baseline_html = demo_client.get("/profile").get_data(as_text=True)
        href = get_pills(baseline_html)["Last 3 Months"]["href"]

        query = dict(parse_qsl(urlsplit(href).query))
        assert query.get("date_to") == date.today().isoformat(), "Last 3 Months must end today"
        datetime.strptime(query["date_from"], "%Y-%m-%d")  # must be a well-formed ISO date

        response = demo_client.get(href)
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert_sections_match(html, seed_expenses())
        assert get_pills(html)["Last 3 Months"]["active"] is True

    def test_last_6_months_preset_link_filters_all_three_sections(self, demo_client):
        baseline_html = demo_client.get("/profile").get_data(as_text=True)
        href = get_pills(baseline_html)["Last 6 Months"]["href"]

        query = dict(parse_qsl(urlsplit(href).query))
        assert query.get("date_to") == date.today().isoformat(), "Last 6 Months must end today"
        datetime.strptime(query["date_from"], "%Y-%m-%d")  # must be a well-formed ISO date

        response = demo_client.get(href)
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert_sections_match(html, seed_expenses())
        assert get_pills(html)["Last 6 Months"]["active"] is True

    def test_all_time_preset_uses_a_clean_url_with_no_query_params(self, demo_client):
        # Start from an already-filtered view so "All Time" is a meaningful
        # transition, not just the default state.
        filtered_html = demo_client.get(
            "/profile?date_from=2000-01-01&date_to=2000-01-02"
        ).get_data(as_text=True)
        href = get_pills(filtered_html)["All Time"]["href"]

        assert "?" not in href, "All Time preset link must be a clean /profile URL"

        response = demo_client.get(href)
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert_sections_match(html, seed_expenses())
        assert get_pills(html)["All Time"]["active"] is True

    def test_custom_date_range_filters_all_three_sections(self, demo_client):
        today = date.today()
        # date_to is deliberately != today so this range can never coincide
        # with This Month / Last 3 Months / Last 6 Months (all of which end
        # today), keeping the "no preset should be active" assertion valid
        # regardless of what day the suite runs on.
        date_from = today - timedelta(days=7)
        date_to = today - timedelta(days=5)
        expected = filter_by_range(seed_expenses(today), date_from, date_to)

        response = demo_client.get(
            f"/profile?date_from={date_from.isoformat()}&date_to={date_to.isoformat()}"
        )
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert len(expected) > 0, "Test setup sanity check: expected a non-empty custom range"
        assert_sections_match(html, expected)

        assert is_custom_form_active(html)
        pills = get_pills(html)
        assert all(not pill["active"] for pill in pills.values()), (
            "No quick-select preset should be marked active for an arbitrary custom range"
        )

    def test_custom_date_range_reflects_values_in_input_fields(self, demo_client):
        today = date.today()
        date_from = today - timedelta(days=7)
        date_to = today - timedelta(days=5)

        html = demo_client.get(
            f"/profile?date_from={date_from.isoformat()}&date_to={date_to.isoformat()}"
        ).get_data(as_text=True)

        assert f'id="date_from" name="date_from" value="{date_from.isoformat()}"' in html
        assert f'id="date_to" name="date_to" value="{date_to.isoformat()}"' in html


# --------------------------------------------------------------------- #
# Validation errors / fallback behaviour                                 #
# --------------------------------------------------------------------- #

class TestProfileFilterValidation:
    def test_date_from_after_date_to_flashes_error_and_falls_back_to_unfiltered(self, demo_client):
        today = date.today()
        date_from = today
        date_to = today - timedelta(days=10)

        response = demo_client.get(
            f"/profile?date_from={date_from.isoformat()}&date_to={date_to.isoformat()}"
        )
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert FLASH_TEXT in html
        assert_sections_match(html, seed_expenses())
        assert get_pills(html)["All Time"]["active"] is True

    def test_malformed_date_from_falls_back_silently_without_crashing(self, demo_client):
        response = demo_client.get("/profile?date_from=not-a-date&date_to=2024-01-01")
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert FLASH_TEXT not in html, "Malformed input must fall back silently, no flash message"
        assert_sections_match(html, seed_expenses())
        assert get_pills(html)["All Time"]["active"] is True

    def test_malformed_date_to_falls_back_silently_without_crashing(self, demo_client):
        response = demo_client.get("/profile?date_from=2024-01-01&date_to=also-not-a-date")
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert FLASH_TEXT not in html
        assert_sections_match(html, seed_expenses())

    @pytest.mark.parametrize(
        "query_string",
        [
            "date_from=2024-01-01",  # date_to absent
            "date_to=2024-01-01",  # date_from absent
            "",  # both absent
        ],
        ids=["date_to_missing", "date_from_missing", "both_missing"],
    )
    def test_single_or_no_param_falls_back_to_unfiltered(self, demo_client, query_string):
        url = "/profile" + (f"?{query_string}" if query_string else "")
        response = demo_client.get(url)
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert_sections_match(html, seed_expenses())

    def test_empty_string_date_params_fall_back_to_unfiltered(self, demo_client):
        response = demo_client.get("/profile?date_from=&date_to=")
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert_sections_match(html, seed_expenses())


# --------------------------------------------------------------------- #
# Edge cases                                                             #
# --------------------------------------------------------------------- #

class TestProfileFilterEdgeCases:
    def test_fresh_user_with_no_expenses_sees_zero_state(self, fresh_client):
        response = fresh_client.get("/profile")
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert_sections_match(html, [])
        assert "₹0.00" in html, "Zero total must still display with the rupee symbol"

    def test_fresh_user_with_no_expenses_sees_zero_state_with_a_filter_applied(self, fresh_client):
        today = date.today()
        first_of_month = date(today.year, today.month, 1)

        response = fresh_client.get(
            f"/profile?date_from={first_of_month.isoformat()}&date_to={today.isoformat()}"
        )
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert_sections_match(html, [])
        assert "₹0.00" in html

    def test_demo_user_range_with_no_matching_expenses_sees_zero_state(self, demo_client):
        # Demo user *does* have expenses overall, just none in this range —
        # exercises the "no results within the selected range" edge case
        # distinctly from "user has no expenses at all".
        response = demo_client.get("/profile?date_from=2000-01-01&date_to=2000-01-02")
        html = response.get_data(as_text=True)

        assert response.status_code == 200
        assert_sections_match(html, [])
        assert "₹0.00" in html
        assert is_custom_form_active(html)


# --------------------------------------------------------------------- #
# UI active-state indicator                                              #
# --------------------------------------------------------------------- #

class TestProfileFilterUIState:
    def test_default_view_marks_only_all_time_pill_active(self, demo_client):
        html = demo_client.get("/profile").get_data(as_text=True)
        pills = get_pills(html)

        assert pills["All Time"]["active"] is True
        assert pills["This Month"]["active"] is False
        assert pills["Last 3 Months"]["active"] is False
        assert pills["Last 6 Months"]["active"] is False
        assert not is_custom_form_active(html)

    def test_this_month_view_marks_only_this_month_pill_active(self, demo_client):
        today = date.today()
        first_of_month = date(today.year, today.month, 1)

        html = demo_client.get(
            f"/profile?date_from={first_of_month.isoformat()}&date_to={today.isoformat()}"
        ).get_data(as_text=True)
        pills = get_pills(html)

        assert pills["This Month"]["active"] is True
        assert pills["All Time"]["active"] is False
        assert pills["Last 3 Months"]["active"] is False
        assert pills["Last 6 Months"]["active"] is False
        assert not is_custom_form_active(html)

    def test_custom_range_view_marks_custom_form_active_and_no_preset(self, demo_client):
        today = date.today()
        date_from = today - timedelta(days=7)
        date_to = today - timedelta(days=5)

        html = demo_client.get(
            f"/profile?date_from={date_from.isoformat()}&date_to={date_to.isoformat()}"
        ).get_data(as_text=True)
        pills = get_pills(html)

        assert is_custom_form_active(html)
        assert all(not pill["active"] for pill in pills.values())

    def test_fallback_view_after_invalid_range_marks_all_time_active(self, demo_client):
        today = date.today()
        html = demo_client.get(
            f"/profile?date_from={today.isoformat()}&date_to={(today - timedelta(days=1)).isoformat()}"
        ).get_data(as_text=True)

        assert get_pills(html)["All Time"]["active"] is True
        assert not is_custom_form_active(html)
