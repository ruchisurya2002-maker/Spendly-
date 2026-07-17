# Spec: Login and Logout

## Overview
Spendly currently renders a sign-in form (`GET /login`) but has no way to
actually authenticate — submitting the form has nowhere to go, and there is
no way to end a session once started. This feature adds the `POST /login`
handler that verifies credentials against the `users` table and starts a
signed Flask session, plus the `GET /logout` handler that ends it. It builds
directly on the database layer from Step 1 and the account creation flow
from Step 2, and it introduces the session state that later steps (`/profile`
in Step 4, and the expense routes) will depend on to identify the current
user.

## Depends on
- Step 1 — Database setup (`users` table, `get_db()`, `init_db()`).
- Step 2 — Registration (`create_user()`, `get_user_by_email()` already
  implemented in `database/db.py`).

## Routes
- `POST /login` — validate email + password against the stored hash, start
  a session on success and redirect to `/profile`, or re-render
  `login.html` with an error — public
- `GET /logout` — clear the session and redirect to `/` — logged-in

## Database changes
No database changes. The existing `users` table and `get_user_by_email()`
helper already support this feature. No new functions are required in
`database/db.py` — password verification uses
`werkzeug.security.check_password_hash` directly against the row already
returned by `get_user_by_email()`.

## Templates
- **Create:** none
- **Modify:**
  - `templates/login.html` — change the hardcoded `action="/login"` to
    `action="{{ url_for('login') }}"`
  - `templates/base.html` — nav currently always shows "Sign in" /
    "Get started" regardless of auth state; update it to show a
    "Sign out" link (`url_for('logout')`) when `session` contains a
    logged-in user, and the existing "Sign in" / "Get started" links
    otherwise

## Files to change
- `app.py`:
  - Set `app.secret_key` (required for Flask's signed session cookie —
    read from an environment variable with a hardcoded local-dev fallback,
    since no new config system exists yet)
  - Import `check_password_hash` from `werkzeug.security`
  - Change `login()` to accept `GET` and `POST`; on `POST`, look up the
    user by email, verify the password with `check_password_hash`, store
    `user_id` in `session` on success and redirect to `/profile`, or
    re-render `login.html` with an `error` on failure (missing fields,
    unknown email, or wrong password all produce the same generic error
    message so login does not leak which part was wrong)
  - Implement `logout()` to call `session.clear()` and redirect to `/`
- `templates/login.html` — form action fix described above
- `templates/base.html` — conditional nav described above

## Files to create
None.

## New dependencies
No new dependencies. `werkzeug.security.check_password_hash` ships with
the `werkzeug` package already in `requirements.txt`; Flask's `session` is
part of Flask itself.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug (verify with `check_password_hash`,
  never compare plaintext)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- No hardcoded URLs — use `url_for()` everywhere, including the `login.html`
  form `action` and the new nav links
- Use one generic error message ("Invalid email or password.") for every
  login failure case — do not reveal whether the email exists
- Keep all DB logic in `database/db.py`; `login()` in `app.py` only
  collects form data, calls `get_user_by_email()`, verifies the hash, and
  decides what to render or where to redirect
- Do not implement `/profile` beyond its existing stub — Step 4 owns that
- Do not add "remember me," password reset, or rate limiting — out of
  scope for this step
- Validate on the server:
   Email and password are required
   Missing fields should re-render `login.html`
   with the generic error message
   Never crash on malformed input

## Definition of done
- [ ] Submitting `/login` with any valid existing account
      (for example `demo@spendly.com` / `demo123`
      or another registered account)
      redirects to `/profile`
- [ ] Submitting `/login` with a wrong password re-renders `login.html`
      with "Invalid email or password." and does not start a session
- [ ] Submitting `/login` with an email that doesn't exist re-renders
      `login.html` with the same "Invalid email or password." message
- [ ] Submitting `/login` with a missing field does not crash the app
- [ ] After a successful login, visiting `/logout` clears the session and
      redirects to `/`
- [ ] After `/logout`, the nav shows "Sign in" / "Get started" again
      instead of "Sign out"
- [ ] While logged in, the nav shows a "Sign out" link instead of
      "Sign in" / "Get started"
- [ ] `templates/login.html` form action uses `url_for('login')`, not a
      hardcoded path
- [ ] No new packages were added to `requirements.txt`
- [ ] All SQL used by this feature uses `?` placeholders, no f-strings
