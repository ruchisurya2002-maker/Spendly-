# Spec: Registration

## Overview
Spendly currently renders a registration form (`GET /register`) but has no
way to actually create an account — submitting the form has nowhere to go.
This feature adds the `POST /register` handler that validates the submitted
data, hashes the password, inserts a new row into the existing `users`
table, and routes the user to sign in. It builds directly on the database
layer from Step 1 and does not introduce sessions or authentication state —
that remains out of scope until the login/logout steps.

## Depends on
Step 1 — Database setup (`users` table, `get_db()`, `init_db()`, `seed_db()`
already implemented in `database/db.py`).

## Routes
- `POST /register` — validate form input (including password confirmation),
   create the user, redirect to `/login` on success or re-render
  `register.html` with an error — public

## Database changes
No database changes. The existing `users` table (id, name, email,
password_hash, created_at) already supports this feature. New logic is
added as functions in `database/db.py`, not schema changes:
- `get_user_by_email(email)` — parameterized `SELECT` used to check for
  duplicate emails
- `create_user(name, email, password)` — hashes the password with
  `generate_password_hash` and inserts the row via a parameterized query

## Templates
- **Create:** none
- **Modify:** `templates/register.html`
  - Change the hardcoded `action="/register"` to
    `action="{{ url_for('register') }}"`
  - Add a **Confirm Password** input field below the Password field
  - Display an error if the passwords do not match

## Files to change
- `app.py` — change `register()` to accept `GET` and `POST`; on `POST`,
  validate name, email, password and confirm password, ensure the two
  password fields match, call the new `database/db.py` helpers, and
  either redirect to `/login` or re-render `register.html` with `error`set
## Files to create
None.

## New dependencies
No new dependencies. `werkzeug.security.generate_password_hash` is already
imported in `database/db.py`.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug (`generate_password_hash`, never store
  plaintext)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- No hardcoded URLs — use `url_for()` everywhere, including the form
  `action`
- Validate on the server as well as the client:
  Name, email, password and confirm password are required
  Password and confirm password must match before creating the user
  Reject duplicate emails with a clear error
  Never create a user if validation fails
  Don't crash on bad input
- Do not implement sessions, login state, or the `POST /login` handler —
  those are out of scope for this step
- Keep all DB logic in `database/db.py`; `register()` in `app.py` only
  collects form data, calls the helpers, and decides what to render

## Definition of done
- [ ] Submitting the register form with valid, unique data inserts a new
      row into `users` with a hashed (not plaintext) password
- [ ] Submitting with an email that already exists re-renders
      `register.html` with an error message and does not create a
      duplicate row
  - [ ] Registration fails with a clear error message if Password and
      Confirm Password do not match
- [ ] No user is inserted into the database when the passwords do not
      match
- [ ] Submitting with a missing required field does not crash the app
- [ ] On success, the browser is redirected to `/login`
- [ ] `templates/register.html` form action uses `url_for('register')`,
      not a hardcoded path
- [ ] No new packages were added to `requirements.txt`
- [ ] All SQL in `database/db.py` uses `?` placeholders, no f-strings
