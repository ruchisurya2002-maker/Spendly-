# Spec: Backend Routes For Profile Page

## Overview
The `/profile` route currently renders `profile.html` using hardcoded Python
dicts (`PROFILE_USER`, `PROFILE_STATS`, `PROFILE_TRANSACTIONS`,
`PROFILE_CATEGORIES`) defined directly in `app.py`, as called out in the
Step 4 spec ("real DB wiring in Step 5"). This feature replaces that
hardcoded data with real queries against the `users` and `expenses` tables,
so the profile page reflects the actual logged-in user's data: their name,
email, join date, total spent, transaction count, top category, full
transaction history, and per-category spending breakdown.

## Depends on
- Step 1 — Database setup (`users` and `expenses` tables, `get_db()`, `init_db()`).
- Step 2 — Registration (`create_user()` populates real user rows to query).
- Step 3 — Login + Logout (`session["user_id"]` identifies the current user).
- Step 4 — Profile page design (`templates/profile.html` and
  `static/css/profile.css` already expect this exact shape of data — this
  step supplies real values for the same template, no template redesign).

## Routes
No new routes.
- `GET /profile` — existing route, behavior unchanged (redirect to `/login`
  if not authenticated) — logged-in only. Only the data source changes,
  from hardcoded dicts to real DB queries.

## Database changes
No schema changes. The existing `users` and `expenses` tables are
sufficient. New read-only query functions are added to `database/db.py`:

- `get_user_by_id(user_id)` — fetch a single user row by primary key.
- `get_expenses_by_user(user_id)` — fetch all expenses for a user, ordered
  by `date DESC, id DESC` (most recent first).
- `get_expense_summary(user_id)` — return total amount spent and total
  transaction count for a user via `SUM(amount)` and `COUNT(*)`.
- `get_top_category(user_id)` — return the single category with the
  highest total spend for a user via `GROUP BY category ORDER BY
  SUM(amount) DESC LIMIT 1`.
- `get_category_totals(user_id)` — return per-category totals for a user,
  `GROUP BY category ORDER BY SUM(amount) DESC`.

All new functions use parameterized queries (`?` placeholders) and live
only in `database/db.py`, never inline in `app.py`.

## Templates
- **Create:** none.
- **Modify:** none. `templates/profile.html` already expects `user`,
  `stats`, `transactions`, `categories`, and `display_name` in the exact
  shapes described below — this step only changes where those values come
  from in `app.py`.

## Files to change
- `database/db.py` — add the five query functions listed above.
- `app.py`:
  - Remove the hardcoded `PROFILE_USER`, `PROFILE_STATS`,
    `PROFILE_TRANSACTIONS`, `PROFILE_CATEGORIES` module-level dicts.
  - Rewrite the `profile()` view to:
    - Keep the existing auth guard (`redirect` to `/login` if no
      `session["user_id"]`).
    - Call `get_user_by_id()`, `get_expenses_by_user()`,
      `get_expense_summary()`, `get_top_category()`, and
      `get_category_totals()`.
    - Build a `user` dict for the template with `name`, `email`,
      `member_since` (formatted from `created_at`, e.g. `"March 2025"`),
      and `initials` (derived from `name`, e.g. `"Demo User"` → `"DU"`).
    - Build a `stats` list (`Total spent`, `Transactions`, `Top category`)
      formatted as currency strings (e.g. `"₹5,848.00"`) to match the
      existing template markup.
    - Build a `transactions` list from `get_expenses_by_user()`, formatting
      each `amount` as a currency string.
    - Build a `categories` list from `get_category_totals()`, with each
      row's `percent` computed relative to the highest category total (the
      top category is 100%, matching the existing progress-bar markup).
    - Pass `display_name=user["name"]` as before.
    - Handle the case of a user with zero expenses without crashing
      (empty transaction list, empty category list, stats showing zero
      values).

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Keep all DB logic in `database/db.py`; `profile()` in `app.py` only
  calls those functions, formats the results for display, and renders the
  template
- Do not modify `templates/profile.html`, `templates/base.html`, or
  `static/css/profile.css` — the template contract from Step 4 already
  matches the data shapes this step produces
- Do not implement `/expenses/add`, `/expenses/<id>/edit`, or
  `/expenses/<id>/delete` — those remain out of scope (Steps 7–9)
- Currency formatting must use the `₹` symbol with two decimal places and
  thousands separators, consistent with the Step 4 hardcoded values

## Definition of done
- [ ] Visiting `/profile` without being logged in redirects to `/login`
- [ ] Visiting `/profile` while logged in as the seeded demo user
      (`demo@spendly.com` / `demo123`) returns HTTP 200
- [ ] The user info card shows the real logged-in user's name, email, and
      a member-since date derived from `created_at`
- [ ] The summary stats show the real total spent, real transaction count,
      and real top category for the logged-in user
- [ ] The transaction history table lists every expense belonging to the
      logged-in user, most recent first
- [ ] The category breakdown lists every category the user has spent in,
      with amounts and proportional bar widths
- [ ] A newly registered user with no expenses can visit `/profile`
      without the app crashing, showing zero/empty states
- [ ] All new SQL queries use `?` placeholders, no f-strings
- [ ] No DB queries appear inline in `app.py` — all live in
      `database/db.py`
- [ ] No new packages were added to `requirements.txt`
