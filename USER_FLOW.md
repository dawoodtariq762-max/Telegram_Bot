# User Workflow & Token-Based Setup — Complete Reference

This document explains the **end-to-end workflow** for admins and users of the
Telegram SMS Number-Allocation system: login, credential management, **Telegram
token authentication**, access control, per-token isolation, and daily usage.

> All dashboard text, Telegram messages, and errors are in **English** (by design).
> **The bot never asks for — and never sees in plain text — the panel password.**
> Panel credentials are managed **only on the website**; the bot authenticates
> users with a single **access token**.

---

## 1. URLs (Public Endpoints)

| Purpose | URL | Notes |
|---|---|---|
| Login (admin **and** user) | `/login` | Single shared login page for everyone |
| Health check | `/healthz` | Returns `200 OK` (Railway healthcheck) |
| User dashboard | `/` | Redirects to `/login` if not authenticated |
| Settings (panel password + token) | `/settings` | Save panel creds, generate/revoke Telegram token |
| Generate token | `POST /settings/token/generate` | Revokes any prior token, returns a new one |
| Revoke token | `POST /settings/token/revoke` | Invalidates the active token immediately |
| Admin panel | `/admin` | Only visible to `is_admin` accounts |

- **Admin and users use the SAME public URL and the SAME login page.** After
  login the app redirects: admins → `/admin`, normal users → `/`.
- There is **no separate user vs admin login screen** — role is decided by the
  `is_admin` flag on the account.

---

## 2. Roles & Access

| Capability | Admin | User |
|---|---|---|
| Create / activate / deactivate users | ✅ | ❌ |
| Manage subscriptions | ✅ | ❌ |
| Delete users | ✅ | ❌ |
| View activity logs | ✅ (any user) | ✅ (own only) |
| Log into dashboard | ✅ | ✅ |
| Set own panel password (website) | ✅ (own) | ✅ (own) |
| See/edit **another** user's panel password | ❌ | ❌ |
| Use `/allocate` via Telegram | ✅ (if token connected) | ✅ (if token connected) |

---

## 3. Admin Workflow (step-by-step)

1. **Open** the dashboard URL → `/login` → log in with the initial admin
   (`ADMIN_USERNAME` / `ADMIN_PASSWORD` from env, or the admin you created).
2. **Go to Admin** (`/admin`).
3. **Create User** — fill the "Create User" form:
   - `Username`, `Password` (this becomes the user's dashboard login),
   - optional `Email`, `Admin` checkbox, `Active` checkbox (default on).
4. **Share the dashboard credentials** with the user out-of-band (the app does
   not email them). The user logs in with exactly these.
5. (Optional) Manage subscription, activate/deactivate, delete, or view
   activity from the same `/admin` table.
6. **You cannot see or edit the user's SMS-panel password** — the admin table
   only shows `Set` / `—` for the panel column.

> Files: `src/web/app.py` (`/admin`, `/admin/users/create`, …),
> template `src/web/templates/admin.html`.

---

## 4. User Workflow (step-by-step)

### First-time setup
1. **Login** at `/login` with the username/password the admin gave you.
2. **Set your SMS panel password** (website only — never in Telegram):
   - Dashboard → **Settings** (`/settings`) → "Panel Credentials" section →
     enter your **panel Username + Password** → *Save Panel Credentials*.
   - Credentials are **encrypted** before they are stored (see §6).
3. **Generate a Telegram token:**
   - Dashboard → **Settings** → **Generate Token**. Copy the token shown
     (it is displayed only once).
4. **Connect in Telegram:**
   - Send `/start` → the bot asks for your access token.
   - Paste the token → bot replies **✅ Connected successfully.**
5. **Test:** in Telegram send `/allocate` → bot asks **Client Username** →
   **Quantity** → allocates and returns the numbers.

### Daily use
- In Telegram: `/allocate` → Client → Quantity → done.
- Limit: **300 numbers per client per UK day**. Over limit →
  *"Each client can only receive a maximum of 300 numbers per day."*
- If the panel has fewer free numbers → *"Only X numbers are currently
  available."*
- **Concurrency:** if you send a second allocation while one is already
  running, it is **queued**: *"⏳ Another allocation is currently running. Your
  request has been queued. Estimated wait: ~20 seconds."* It starts
  automatically when the first finishes.

> Files: `src/web/app.py` (`/settings`, token routes),
> `src/bot/handlers/allocate.py` (`/allocate`), `src/bot/handlers/start.py`
> (`/start`, token validation), `src/bot/queue.py` (per-token queue).

---

## 5. Credential & Token Management

### Dashboard login password
- **Set at creation** by the admin.
- **Change anytime** (user or admin): `/settings` → "Change Dashboard Password"
  → needs the *current* password + new password. Stored as **bcrypt hash**
  (not reversible).

### SMS panel credentials (Username + Password)
- **Saved only via `/settings` (website).** The bot **never** asks for them.
- **Encrypted at rest** with **Fernet** (key = `ENCRYPTION_KEY`). The admin
  dashboard shows only `Set` / `—` — the value is **never visible** to admin.
- **Update:** re-submit the panel form with new values — it overwrites. After
  changing the panel password you should **Generate a new Token** (the old
  token's saved browser session is cleared automatically).

### Telegram access token
- **Generated on the website** (`/settings` → Generate Token). Format:
  `mufasa_<random>`.
- Stored in the `tokens` table: `token`, `user_id`, an **encrypted snapshot**
  of the panel username/password, `storage_state` (this token's browser
  session), `telegram_id`, `created_at`, optional `expires_at`, `is_active`.
- **One user may regenerate anytime; the previous token becomes invalid
  immediately** (`is_active = false`).
- The bot resolves `token → user → encrypted credentials` and decrypts
  server-side; it never stores or transmits the panel password.

---

## 6. Where things are saved

| Field | Per-user? | Where entered | Stored |
|---|---|---|---|
| **Panel URL** | ❌ Global | Env `PANEL_BASE_URL` | Config only |
| **Panel Username** | ✅ Per user | `/settings` (web) | `users.encrypted_panel_username` (Fernet) **and** copied into `tokens.panel_username` |
| **Panel Password** | ✅ Per user | `/settings` (web) | `users.encrypted_panel_password` (Fernet) **and** copied into `tokens.encrypted_panel_password` |
| **Telegram token** | ✅ Per user | `/settings` → Generate | `tokens` table |

**Isolation model:** every **token** gets its **own isolated browser context**
(keyed by the token string) and its **own persisted `storage_state`** in the
`tokens` table. Two different tokens — even for the same user with different
credentials, or for different users — **never share cookies or login state**.
The bot serializes allocations **per token** (see §7); different tokens run in
parallel.

At allocation time the bot:
1. Resolves the active `Token` from the connected `telegram_id`.
2. Decrypts **that token's** panel username/password.
3. Logs into `PANEL_BASE_URL` in **that token's** isolated browser context.
4. Allocates numbers to the requested client.

---

## 7. Concurrency & Queueing

- Each **token** may run **at most one** allocation at a time.
- Requests that arrive while a token's allocation is running are **queued** and
  executed in order once the current one finishes, with a user-facing notice.
- **Different tokens run in parallel** (separate browser contexts + separate
  worker tasks).
- Implementation: `src/bot/queue.py` (`AllocationQueue` → one `_TokenExecutor`
  FIFO worker per token). The `BrowserManager` adds a per-key lock as a safety
  net (`src/panel/browser.py`).

---

## 8. Access Control — "who can see what"

- **Each user only sees their own dashboard** (no list of other users). The bot
  only ever uses the calling user's own token's encrypted panel creds.
- **Admin cannot view or edit any user's panel password** — the admin table
  shows `Set` / `—` only.
- **Admin can** create/deactivate/delete users, manage subscriptions, and view
  activity logs.
- **A user can update their own panel credentials** (overwrite) and regenerate
  their token, but cannot delete their own account (admin only).

---

## 9. Screens (files)

| Screen | Template file | Route |
|---|---|---|
| Login (shared) | `src/web/templates/login.html` | `GET/POST /login` |
| User dashboard | `src/web/templates/home.html` | `GET /` |
| **Panel password + Token** | `src/web/templates/settings.html` | `GET/POST /settings`, `POST /settings/token/generate`, `POST /settings/token/revoke` |
| Admin → Create User / manage | `src/web/templates/admin.html` | `GET /admin`, `POST /admin/users/create`, … |
| Admin → user activity | `src/web/templates/admin_user_activity.html` | `GET /admin/users/{uid}/activity` |

### Database tables
`users` (`src/db/models.py`): `encrypted_panel_username`,
`encrypted_panel_password`, `panel_creds_set`, `telegram_id`, `telegram_linked`,
`password_hash` (bcrypt).

`tokens` (`src/db/models.py`): `token`, `user_id`, `panel_username`,
`encrypted_panel_password`, `storage_state`, `telegram_id`, `created_at`,
`expires_at`, `last_used_at`, `is_active`.

Allocation audit: `allocation_logs` (enforces the 300/day/client limit).
Activity audit: `activity_logs`.

---

## 10. Quick start checklist

- [ ] Admin logs in at `/login` → `/admin` → Create User (username + password).
- [ ] User logs in at `/login` with those creds.
- [ ] User opens `/settings` → saves **Panel Username + Password** (encrypted, website only).
- [ ] User opens `/settings` → **Generate Token** → copies it.
- [ ] User sends `/start` in Telegram → pastes the token → **Connected successfully.**
- [ ] User sends `/allocate` in Telegram → Client → Quantity → numbers returned.
- [ ] Daily: repeat `/allocate` (capped at 300/client/UK-day; concurrent requests queue per token).
