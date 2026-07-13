"""FastAPI web app: User Dashboard + Admin Panel (server-rendered, Bootstrap)."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

# Dependency-free signed-cookie sessions (no itsdangerous / starlette sessions).
from src.web.session import SessionMiddleware

from src.config import Settings
from src.core.security import hash_password, verify_password
from src.db.base import create_tables, init_db
from src.db.crud import (
    create_user,
    delete_user,
    get_user_activity,
    get_user_by_id,
    get_user_by_username,
    get_user_by_telegram,
    list_users,
    log_activity,
    set_active,
    set_link_code,
    set_panel_credentials,
    set_subscription,
    set_telegram,
)

settings = Settings()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _render(name: str, context: dict) -> HTMLResponse:
    return HTMLResponse(templates.get_template(name).render(**context))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the DB is ready whenever the web app runs (standalone or via main).
    init_db(settings)
    await create_tables()
    if settings.admin_username:
        from src.db.base import SessionLocal

        async with SessionLocal() as s:
            if not await get_user_by_username(s, settings.admin_username):
                await create_user(
                    s, settings.admin_username, settings.admin_password, is_admin=True
                )
    yield


app = FastAPI(title="SMS Panel Dashboard", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.web_secret_key)


@app.get("/healthz", response_class=HTMLResponse)
async def healthz() -> HTMLResponse:
    return HTMLResponse("ok")


async def get_db():
    from src.db.base import SessionLocal

    async with SessionLocal() as session:
        yield session


async def get_current_user(request: Request, db=Depends(get_db)):
    uid = request.session.get("user_id")
    if not uid:
        return None
    return await get_user_by_id(db, uid)


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=302)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


# ----------------------------- Auth -----------------------------
@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request, db=Depends(get_db)):
    if await get_current_user(request, db):
        return _redirect("/")
    return _render("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    db=Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
):
    user = await get_user_by_username(db, username)
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return _render(
            "login.html", {"request": request, "error": "Invalid credentials."}
        )
    request.session["user_id"] = user.id
    await log_activity(db, user.id, "dashboard_login", ip=_client_ip(request))
    return _redirect("/admin" if user.is_admin else "/")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return _redirect("/login")


# ----------------------------- User dashboard -----------------------------
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db=Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return _redirect("/login")
    activity = await get_user_activity(db, user.id, limit=15)
    return _render(
        "home.html",
        {"request": request, "user": user, "activity": activity},
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_get(request: Request, db=Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return _redirect("/login")
    return _render("settings.html", {"request": request, "user": user})


@app.post("/settings")
async def settings_post(
    request: Request,
    db=Depends(get_db),
    panel_username: str = Form(""),
    panel_password: str = Form(""),
    old_password: str = Form(""),
    new_password: str = Form(""),
):
    user = await get_current_user(request, db)
    if not user:
        return _redirect("/login")
    # Update panel credentials if provided
    if panel_username and panel_password:
        await set_panel_credentials(db, user, panel_username, panel_password)
        await log_activity(db, user.id, "setpanel", "updated panel credentials (web)")
    # Change dashboard password if provided
    if new_password:
        if not verify_password(old_password or "", user.password_hash):
            return _render(
                "settings.html",
                {"request": request, "user": user, "error": "Current password is incorrect."},
            )
        user.password_hash = hash_password(new_password)
        db.add(user)
        await db.commit()
        await log_activity(db, user.id, "change_password")
    return _redirect("/settings")


@app.get("/link/telegram", response_class=HTMLResponse)
async def link_get(request: Request, db=Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return _redirect("/login")
    return _render("link.html", {"request": request, "user": user})


@app.post("/link/telegram/generate")
async def link_generate(request: Request, db=Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return _redirect("/login")
    code = await set_link_code(db, user)
    await log_activity(db, user.id, "link_code", "generated telegram link code")
    return _render(
        "link.html", {"request": request, "user": user, "code": code}
    )


# ----------------------------- Admin panel -----------------------------
@app.get("/admin", response_class=HTMLResponse)
async def admin_list(request: Request, db=Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return _redirect("/login")
    if not user.is_admin:
        return _redirect("/")
    users = await list_users(db)
    return _render("admin.html", {"request": request, "users": users})


@app.post("/admin/users/create")
async def admin_create(
    request: Request,
    db=Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
    email: str = Form(""),
    is_admin: str = Form("off"),
    is_active: str = Form("on"),
):
    user = await get_current_user(request, db)
    if not user or not user.is_admin:
        return _redirect("/login")
    if await get_user_by_username(db, username):
        return _render(
            "admin.html",
            {"request": request, "users": await list_users(db), "error": "Username already exists."},
        )
    await create_user(
        db,
        username,
        password,
        email=email or None,
        is_admin=(is_admin == "on"),
        is_active=(is_active == "on"),
    )
    await log_activity(db, user.id, "admin_create_user", f"username={username}")
    return _redirect("/admin")


@app.post("/admin/users/{uid}/toggle-active")
async def admin_toggle_active(request: Request, uid: int, db=Depends(get_db)):
    user = await get_current_user(request, db)
    if not user or not user.is_admin:
        return _redirect("/login")
    target = await get_user_by_id(db, uid)
    if target:
        await set_active(db, target, not target.is_active)
        await log_activity(db, user.id, "admin_toggle_active", f"uid={uid} active={not target.is_active}")
    return _redirect("/admin")


@app.post("/admin/users/{uid}/set-subscription")
async def admin_subscription(
    request: Request,
    uid: int,
    db=Depends(get_db),
    plan: str = Form("free"),
    expires_at: str = Form(""),
    is_subscribed: str = Form("off"),
):
    user = await get_current_user(request, db)
    if not user or not user.is_admin:
        return _redirect("/login")
    target = await get_user_by_id(db, uid)
    if target:
        exp = None
        if expires_at:
            try:
                exp = datetime.strptime(expires_at, "%Y-%m-%d")
            except ValueError:
                exp = None
        await set_subscription(db, target, plan, exp, is_subscribed == "on")
        await log_activity(db, user.id, "admin_subscription", f"uid={uid} plan={plan}")
    return _redirect("/admin")


@app.post("/admin/users/{uid}/unlink-telegram")
async def admin_unlink(request: Request, uid: int, db=Depends(get_db)):
    user = await get_current_user(request, db)
    if not user or not user.is_admin:
        return _redirect("/login")
    target = await get_user_by_id(db, uid)
    if target:
        await set_telegram(db, target, None)
        await log_activity(db, user.id, "admin_unlink_telegram", f"uid={uid}")
    return _redirect("/admin")


@app.post("/admin/users/{uid}/delete")
async def admin_delete(request: Request, uid: int, db=Depends(get_db)):
    user = await get_current_user(request, db)
    if not user or not user.is_admin:
        return _redirect("/login")
    if uid == user.id:
        return _render(
            "admin.html",
            {"request": request, "users": await list_users(db), "error": "You cannot delete your own account."},
        )
    target = await get_user_by_id(db, uid)
    if target:
        await delete_user(db, target)
        await log_activity(db, user.id, "admin_delete_user", f"uid={uid}")
    return _redirect("/admin")


@app.get("/admin/users/{uid}/activity", response_class=HTMLResponse)
async def admin_activity(request: Request, uid: int, db=Depends(get_db)):
    user = await get_current_user(request, db)
    if not user or not user.is_admin:
        return _redirect("/login")
    target = await get_user_by_id(db, uid)
    activity = await get_user_activity(db, uid, limit=100)
    return _render(
        "admin_user_activity.html",
        {"request": request, "target": target, "activity": activity},
    )
