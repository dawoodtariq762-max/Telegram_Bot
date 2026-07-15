# Telegram SMS Number-Allocation Bot + Web Dashboard

A complete system that logs into a **third-party SMS panel** (no public API)
with **Playwright** browser automation, allocates numbers to a **client**, and
returns them on Telegram — plus a **web Admin Panel** and **User Dashboard**
where each user manages their own (encrypted) panel credentials.

> Built for 24/7 hosting on Railway. The bot pipeline is **validated live**
> against the real panel; the dashboard is a FastAPI app that runs in the same
> process as the bot.

---

## Features (mapped to requirements)

1. **Admin Panel** — create users, activate/deactivate, manage subscriptions,
   delete users, view activity logs, manage Telegram linkage. (`src/web/app.py`)
2. **User Dashboard** — login, save/update **encrypted** panel username &
   password, view activity, link Telegram. Admin **cannot** see panel passwords.
3. **Telegram auth via token** — the bot **never asks for panel credentials**.
   The user generates an **access token** on the dashboard (Settings → Generate
   Token) and pastes it once into the bot (`/start`). The token resolves to the
   user's encrypted panel credentials on the server.
   (`src/bot/handlers/start.py`, `allocate.py`, `src/db/crud.py` `create_token`)
4. **Commands** — `/start` (connect with token), `/allocate` (asks Client →
   Quantity → allocates), `/help`. (`src/bot/handlers/allocate.py`, `start.py`)
5. **Daily limit** — max **300 numbers per client per UK day**; exceeding returns
   *"Each client can only receive a maximum of 300 numbers per day."*
6. **Insufficient** — if fewer are available: *"Only X numbers are currently
   available."*
7. **Scalability** — every user has their own dashboard account, own **encrypted**
   credentials, own Telegram link, and own **isolated browser session**. No cross
   contamination.
8. **Language** — all dashboard text / Telegram messages / errors are in English.

---

## Architecture

```
                 ┌─────────────── Telegram user ───────────────┐
                 │  /start (paste token)  /allocate  /help       │
                 └──────────────────────┬───────────────────────┘
                                        │ token
                                        ▼
        ┌──────────────────────── Dispatcher + DepsMiddleware ───────────────────────┐
        │  resolves Token → DashboardUser → decrypts panel creds → PanelService        │
        └───────────────────────────────┬─────────────────────────────────────────────┘
                                          │ Playwright (per-token context)
                                          ▼
        ┌──────────────────────── BrowserManager (1 chromium, N isolated contexts) ─────┐
        │  context[key=token]  •  lock[key]  •  storage_state persisted per token in DB  │
        └───────────────────────────────────────────┬──────────────────────────────────┘
                                                     │ HTTPS
                                                     ▼
                                          Third-party SMS Panel
                                          (each token logs in as its OWN panel account)

        Web (FastAPI, same process):  /login  /  /  (dashboard)  /settings
                                       (Settings → Panel Password + Generate Token)
                                       /admin  (users, subs, delete, logs)
                                                     │
                                                     ▼
                  PostgreSQL / SQLite  (users, tokens, allocation_logs, activity_logs,
                                       encrypted panel creds)
```

**Key change from the earlier design:** there is **no shared owner account**
anymore. Each *dashboard user* logs into the panel with **their own** panel
username/password. The bot identifies them by Telegram → dashboard account.

---

## Where everything lives

| Concern | File |
|---|---|
| Config / env | `src/config.py` |
| Encryption (panel creds) + password hashing | `src/core/security.py` |
| Users, panel-cred storage, activity, daily-limit counting | `src/db/models.py`, `src/db/crud.py` |
| Per-user browser contexts + locks | `src/panel/browser.py` |
| Per-user login / count / allocate | `src/panel/service.py` |
| DOM selectors (edit here if panel HTML changes) | `src/panel/selectors.py` |
| Bot commands (FSM) | `src/bot/handlers/allocate.py`, `start.py` |
| Middleware / dispatcher | `src/bot/middlewares.py`, `src/bot/dispatcher.py` |
| **Web dashboard + admin** | `src/web/app.py` + `src/web/templates/*.html` |
| **Combined entrypoint (bot + web)** | `src/main.py` |
| Deploy config | `Dockerfile`, `railway.json` |

---

## Local setup

```bash
cd telegram-panel-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# Fill: BOT_TOKEN, ENCRYPTION_KEY (generate), WEB_SECRET_KEY, ADMIN_USERNAME/PASSWORD
python -m src.main        # runs BOTH the bot and the web dashboard
```

- Bot: talk to it on Telegram (`/start`, `/link`, `/setpanel`, `/allocate`).
- Dashboard: open `http://localhost:8000/` (login with the admin you set, or an
  admin created the first launch from `ADMIN_USERNAME`/`ADMIN_PASSWORD`).
- In `mock` mode the allocation returns dummy numbers (no real panel calls).

---

## User onboarding flow

1. Admin creates the user in the **Admin Panel** (`/admin` → Create User).
2. User opens the dashboard → **Settings** → saves their **Panel Password**
   (encrypted, stored only on the website; the admin never sees it).
3. User clicks **Generate Token** on the Settings page and copies it.
4. In Telegram: `/start` → paste the token → bot replies **Connected successfully.**
5. User runs `/allocate` → bot asks **Client Username** → **Quantity** → allocates
   using the token's credentials, returns the numbers. The bot never asks for the
   panel password.

---

## Going live

- Set `PANEL_MODE=live` and `PANEL_BASE_URL` in env.
- `src/panel/selectors.py` is already validated against the live panel.
- The math captcha is solved automatically; the Google reCAPTCHA on the login
  page is **not** enforced server-side.

---

## Daily limit & messages

- `DAILY_CLIENT_LIMIT` (default **300**) and `DAILY_LIMIT_TIMEZONE`
  (`Europe/London`) in env.
- Enforced in `src/bot/handlers/allocate.py` using the `allocation_logs` table.
- Exact messages (do not change wording):
  - Over limit → `"Each client can only receive a maximum of 300 numbers per day."`
  - Not enough available → `"Only X numbers are currently available."`

---

## Security & privacy

- Each user's **panel password is Fernet-encrypted** before DB storage; the admin
  dashboard only shows "Set / Not set" — never the value.
- Dashboard passwords are **bcrypt-hashed** (not reversible).
- Each user has an **isolated browser context**; one user's session/cookies can
  never leak to another.
- `storage_state` (panel login cookies) is persisted per user in the DB so logins
  survive restarts.

---

## Deploying on Railway (detailed)

Railway runs **one service** that starts `python -m src.main`, which launches
both the Telegram bot AND the FastAPI web dashboard in the same process.

1. Push this repo to GitHub.
2. Railway → **New Project → Deploy from GitHub repo**.
   - The `Dockerfile` auto-installs Python deps + Chromium and runs
     `python -m src.main`.
3. Add a **PostgreSQL** plugin; copy its `DATABASE_URL` into the service
   environment variables (it overrides the SQLite default).
4. Set these **environment variables** in Railway (Variables tab):
   - `BOT_TOKEN` — from @BotFather (format `<id>:<hash>`). The web dashboard
     and `/healthz` start **even if this is temporarily invalid**; the bot
     simply won't run until a valid token is set (watch the logs for
     `bot.startup.failed`).
   - `ENCRYPTION_KEY` — `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   - `WEB_SECRET_KEY` — any long random string
   - `ADMIN_USERNAME` / `ADMIN_PASSWORD` — the initial admin login
   - `PANEL_BASE_URL`, `PANEL_LOGIN_PATH`, `PANEL_MODE=live`
   - `DAILY_CLIENT_LIMIT`, `DAILY_LIMIT_TIMEZONE`
   - `HEADLESS=true`
5. **Expose the dashboard**: the web server listens on `WEB_PORT` (default 8000).
   On Railway the app also auto-reads the platform-injected `PORT` env var, so
   you usually do **not** need to change anything — the health check hits
   `GET /healthz` (always returns `200 OK`, no auth), defined in `railway.json`.
   If you prefer a fixed port, set `WEB_PORT` in the Variables tab.
6. The **bot** (polling) needs no public port — it just runs alongside.
7. After deploy, open the dashboard URL, log in as the admin, and create users.

### Changing credentials later
- **Panel username/password** are per *user* and live only in the DB (encrypted).
  Users change them via the dashboard **Settings** page (Panel Credentials card).
  They must then **Generate a new Token** (the old one is revoked immediately).
  No code change needed.
- **Telegram bot token** → update `BOT_TOKEN` env + redeploy.
- **Dashboard admin password** → change it from the admin's own Settings page
  (or recreate the admin in the DB).
- If the panel's **base URL** ever changes → update `PANEL_BASE_URL`. If its HTML
  changes → edit only `src/panel/selectors.py`.

---

## Testing

```bash
python -m tests.test_core     # crypto, settings, per-user mock allocate, CRUD, daily limit
```

For a live end-to-end check, set `PANEL_MODE=live` and talk to the bot; or reuse
`tests/live_allocate.py` (allocates 1 real number to a client).

> **Safe live check (no allocation):** `python -m tests.live_readonly_count`
> logs in with the panel credentials you set, solves the captcha, navigates to
> `MySMSNumbers`, and prints the number of **unallocated** rows — proving the
> live integration works without touching any real numbers.

> **Test data to clean up:** during development two numbers
> (`393780712189`, `393780715226`) were allocated to client `R1ZARA`. Please
> unallocate them from the panel so they return to the free pool.
