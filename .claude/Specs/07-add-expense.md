# Spec: Add Expense

## Overview
Spendly currently only lets users view expenses (via the profile page and
analytics dashboard) — there is no way to create one. This feature
implements the `/expenses/add` route so a logged-in user can submit a new
expense (amount, category, date, description) through a form, have it
persisted to the `expenses` table, and land back on their profile page
with the new entry reflected in their transaction history, stats, and
category breakdown.

## Depends on
- Step 1 — Database setup (`expenses` table, `get_db()`, `init_db()`).
- Step 3 — Login + Logout (`session["user_id"]` identifies the current
  user; the route must be auth-gated).
- Step 5 — Backend routes for profile page (`get_expenses_by_user()` and
  friends already read from `expenses`; this step is the write-side
  counterpart that populates real data instead of only the seeded rows).

## Routes
- `GET /expenses/add` — render the add-expense form, pre-filled with
  today's date — logged-in only (redirect to `/login` if no
  `session["user_id"]`, matching the pattern used by `/profile` and
  `/analytics`).
- `POST /expenses/add` — validate and insert the submitted expense for the
  current user, then redirect to `/profile` — logged-in only.

Both methods are handled by the same `add_expense()` view, replacing the
current stub that returns a raw string.

## Database changes
No schema changes. The existing `expenses` table already has every column
needed (`user_id`, `amount`, `category`, `date`, `description`). One new
write function is added to `database/db.py`:

- `create_expense(user_id, amount, category, date, description)` — inserts
  a row into `expenses` using a parameterized `INSERT` and returns the new
  row's id.

## Templates
- **Create:** `templates/expenses_add.html` — form with fields for amount,
  category (`<select>` populated from `db.CATEGORIES`), date (defaults to
  today), and an optional description. Extends `base.html`. On validation
  error, re-renders with the entered values preserved and an error message
  (reusing the `flash`/`flash-error` pattern already used by
  `register.html`/`login.html`, or an inline error passed to the
  template — pick whichever matches the existing register/login
  convention).
- **Modify:** `templates/profile.html` — add an "Add expense" link/button
  pointing to `url_for('add_expense')`, since no route currently links to
  this page.

## Files to change
- `app.py`:
  - Replace the `add_expense()` stub with a real `GET`/`POST` view:
    - Auth guard identical to `profile()`/`analytics()`.
    - `GET`: render `expenses_add.html` with today's date as the default.
    - `POST`: read `amount`, `category`, `date`, `description` from
      `request.form`; validate that `amount` is a positive number, `date`
      parses as `YYYY-MM-DD`, and `category` is one of `db.CATEGORIES`;
      on failure re-render the form with an error (`abort(400)` is not
      appropriate here since this is a user input error, not a routing
      error — follow the existing `register()`/`login()` pattern of
      re-rendering the template with an `error` message).
    - On success, call `create_expense()`, then `redirect(url_for("profile"))`.
  - Import `create_expense` and `CATEGORIES` from `database.db`.
- `database/db.py` — add `create_expense()`.
- `templates/profile.html` — add the add-expense link/button.

## Files to create
- `templates/expenses_add.html`
- `static/css/expenses_add.css` (page-specific styles; follow the
  `analytics.css`/`landing.css` precedent of one CSS file per page rather
  than inline `<style>` tags)

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Keep all DB logic in `database/db.py`; `add_expense()` in `app.py` only
  validates form input, calls `create_expense()`, and redirects/renders
- Category values must be validated against `db.CATEGORIES`, not accepted
  as free text
- Amount must be validated as a positive number server-side, not trusted
  from the client
- Do not implement `/expenses/<id>/edit` or `/expenses/<id>/delete` —
  those remain out of scope (Steps 8–9)
- Do not use raw string returns — the stub behavior must be fully replaced

## Definition of done
- [ ] Visiting `/expenses/add` without being logged in redirects to `/login`
- [ ] Visiting `/expenses/add` while logged in as the seeded demo user
      (`demo@spendly.com` / `demo123`) returns HTTP 200 with a form
- [ ] Submitting the form with valid data creates a new row in `expenses`
      for the current user and redirects to `/profile`
- [ ] The newly added expense appears in the profile page's transaction
      history, stats, and category breakdown immediately after redirect
- [ ] Submitting with a missing/negative/non-numeric amount re-renders the
      form with an error and does not insert a row
- [ ] Submitting with an invalid date re-renders the form with an error
      and does not insert a row
- [ ] Submitting with a category not in `db.CATEGORIES` re-renders the
      form with an error and does not insert a row
- [ ] The profile page has a visible link/button to `/expenses/add`
- [ ] All new SQL queries use `?` placeholders, no f-strings
- [ ] No DB queries appear inline in `app.py` — all live in
      `database/db.py`
- [ ] No new packages were added to `requirements.txt`
