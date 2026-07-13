"""Per-user panel automation: login (with the user's own creds) + count + allocate.

Refactored from the shared-account version: this instance is created per
allocation using a specific user's panel username/password. A fresh page is
opened from the user's isolated browser context for each operation, then
closed; the context (cookies) persists so logins survive between calls.
"""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urljoin

import structlog

from src.config import Settings
from src.core.errors import InsufficientNumbers, PanelAuthError
from src.panel import selectors as S
from src.panel.browser import BrowserManager

log = structlog.get_logger(__name__)


class PanelService:
    def __init__(
        self,
        settings: Settings,
        browser: BrowserManager,
        panel_username: str,
        panel_password: str,
        storage_state: str | None = None,
        user_key: str | None = None,
        lock: asyncio.Lock | None = None,
    ) -> None:
        self.settings = settings
        self.browser = browser
        self.panel_username = panel_username
        self.panel_password = panel_password
        self.storage_state = storage_state
        self.user_key = user_key or panel_username
        self._lock = lock or asyncio.Lock()
        self._logged_in = False
        self._dashboard_base: str | None = None
        self._page_cache = None

    # ----------------------------- public -----------------------------
    async def allocate(self, client_name: str, count: int) -> list[str]:
        async with self._lock:
            await self.ensure_logged_in()
            if self.settings.panel_mode == "live":
                try:
                    return await self._allocate_live(client_name, count)
                except PanelAuthError:
                    # Session may have expired — re-login once and retry.
                    self._logged_in = False
                    await self.ensure_logged_in()
                    return await self._allocate_live(client_name, count)
            return self._allocate_mock(count)

    async def get_unallocated_count(self) -> int:
        async with self._lock:
            await self.ensure_logged_in()
            if self.settings.panel_mode == "live":
                try:
                    return await self._count_live()
                except PanelAuthError:
                    self._logged_in = False
                    await self.ensure_logged_in()
                    return await self._count_live()
            return self._count_mock()

    async def ensure_logged_in(self) -> None:
        if self._logged_in:
            return
        if self.settings.panel_mode == "live":
            # If we already have a saved session, try to reuse it before doing
            # a full (captcha) login. This avoids a redundant re-login on every
            # allocation and the flakiness that comes with it.
            if self.storage_state:
                try:
                    if await self._try_restore_session():
                        self._logged_in = True
                        return
                except Exception as exc:  # noqa: BLE001
                    log.warning("panel.restore.failed", user=self.user_key, error=str(exc))
                    self.storage_state = None
            await self._login_live()
        else:
            log.warning("panel.mock.login", user=self.user_key)
        self._logged_in = True

    async def _try_restore_session(self) -> bool:
        """Return True if the saved ``storage_state`` already yields a logged-in
        session on the MySMSNumbers page (no captcha login needed)."""
        ctx, page = await self._page()
        target = self.settings.panel_base_url.rstrip("/") + "/agent/MySMSNumbers"
        try:
            await page.goto(target, wait_until="networkidle")
        except Exception:
            return False
        # Landed back on the login form -> not authenticated.
        if await page.query_selector(S.LOGIN["username"]):
            return False
        try:
            await page.wait_for_selector(
                S.TABLE["id"], timeout=self.settings.browser_timeout_ms
            )
        except Exception:
            return False
        current = await page.evaluate("window.location.href")
        self._dashboard_base = (
            current.rsplit("/", 1)[0]
            if current.startswith("http")
            else self.settings.panel_base_url.rstrip("/")
        )
        self.storage_state = json.dumps(await ctx.storage_state())
        log.info("panel.session.restored", user=self.user_key)
        return True

    # ------------------------------ mock ------------------------------
    def _allocate_mock(self, count: int) -> list[str]:
        return [f"+1000000000{i:04d}" for i in range(count)]

    def _count_mock(self) -> int:
        return 500

    # ------------------------------ live ------------------------------
    async def _page(self):
        ctx = await self.browser.get_context(self.user_key, self.storage_state)
        # Reuse one parked page per service (mirrors a logged-in browser tab).
        if self._page_cache is None or self._page_cache.is_closed():
            self._page_cache = await ctx.new_page()
            self._page_cache.set_default_timeout(self.settings.browser_timeout_ms)
        return ctx, self._page_cache

    async def _login_live(self) -> None:
        ctx, page = await self._page()
        try:
            login_url = (
                self.settings.panel_base_url.rstrip("/") + self.settings.panel_login_path
            )
            await page.goto(login_url, wait_until="networkidle")
            await page.fill(S.LOGIN["username"], self.panel_username)
            await page.fill(S.LOGIN["password"], self.panel_password)
            await self._solve_captcha(page)
            await page.click(S.LOGIN["submit"])
            await page.wait_for_selector("#main", timeout=self.settings.browser_timeout_ms)
            current = await page.evaluate("window.location.href")
            self._dashboard_base = (
                current.rsplit("/", 1)[0]
                if current.startswith("http")
                else self.settings.panel_base_url.rstrip("/")
            )
            target = urljoin(current, "MySMSNumbers")
            log.info("panel.login.url", current=current, target=target)
            await page.goto(target, wait_until="networkidle")
            await page.wait_for_selector(S.TABLE["id"], timeout=self.settings.browser_timeout_ms)
            self.storage_state = json.dumps(await ctx.storage_state())
            log.info("panel.login.success", user=self.user_key)
        except Exception as exc:  # noqa: BLE001
            self._logged_in = False
            self.storage_state = None
            raise PanelAuthError(f"Login failed: {exc}") from exc

    async def _solve_captcha(self, page) -> None:
        input_el = await page.query_selector(S.LOGIN["captcha_input"])
        if input_el is None:
            raise PanelAuthError("Captcha input not found — check LOGIN selectors.")
        parent = await input_el.evaluate_handle("el => el.parentElement")
        expr = (await parent.inner_text()).strip()
        answer = self._solve_math(expr)
        await input_el.fill(str(answer))
        log.info("panel.captcha.solved", expr=expr, answer=answer)

    @staticmethod
    def _solve_math(expr: str) -> str:
        expr = expr.lower().replace("x", "*").replace("×", "*").replace("÷", "/")
        tokens = re.findall(r"\d+\.?\d*|[+\-*/]", expr)
        if not tokens:
            raise ValueError(f"Cannot parse captcha expression: {expr!r}")
        total = float(tokens[0])
        for i in range(1, len(tokens), 2):
            op, val = tokens[i], float(tokens[i + 1])
            if op == "+":
                total += val
            elif op == "-":
                total -= val
            elif op == "*":
                total *= val
            elif op == "/":
                total /= val
        return str(int(total)) if total == int(total) else str(total)

    async def _ensure_my_numbers(self, page) -> None:
        if await page.query_selector(S.TABLE["id"]):
            return
        base = self._dashboard_base or await page.evaluate("window.location.href")
        target = urljoin(base, "MySMSNumbers")
        await page.goto(target, wait_until="networkidle")
        await page.wait_for_selector(S.TABLE["id"])

    async def _col_index(self, page, text: str) -> int | None:
        headers = await page.query_selector_all(f'{S.TABLE["id"]} thead th')
        for i, h in enumerate(headers, start=1):
            t = (await h.inner_text()).strip()
            if text.lower() in t.lower():
                return i
        return None

    async def _set_show_records(self, page, value: str = "All") -> None:
        await page.select_option(S.TABLE["show_records"], label=value)
        await page.wait_for_timeout(S.TABLE_SETTLE_MS)
        await page.wait_for_selector(f'{S.TABLE["id"]} tbody tr')

    async def _unallocated_rows(self, page):
        await self._ensure_my_numbers(page)
        client_header = await page.query_selector(S.TABLE["client_header"])
        if client_header:
            await client_header.click()
            await page.wait_for_timeout(S.TABLE_SETTLE_MS)
        await self._set_show_records(page, "All")
        rows = await page.query_selector_all(f'{S.TABLE["id"]} tbody tr')
        client_idx = await self._col_index(page, "Client") or 2
        unallocated = []
        for row in rows:
            cell = await row.query_selector(f"td:nth-child({client_idx})")
            if cell is None:
                continue
            text = (await cell.inner_text()).strip()
            if text == "" or await cell.query_selector(S.TABLE["pencil_icon"]):
                unallocated.append(row)
        return unallocated, client_idx

    async def _count_live(self) -> int:
        ctx, page = await self._page()
        try:
            rows, _ = await self._unallocated_rows(page)
            return len(rows)
        finally:
            self.storage_state = json.dumps(await ctx.storage_state())

    async def _allocate_live(self, client_name: str, count: int) -> list[str]:
        ctx, page = await self._page()
        try:
            rows, _ = await self._unallocated_rows(page)
            if len(rows) < count:
                raise InsufficientNumbers(requested=count, available=len(rows))
            number_idx = (
                await self._col_index(page, "Number")
                or await self._col_index(page, "MSISDN")
                or 1
            )
            chosen = rows[:count]
            numbers: list[str] = []
            for row in chosen:
                cb = await row.query_selector("input[type=checkbox]")
                if cb:
                    await cb.check()
                num_cell = await row.query_selector(f"td:nth-child({number_idx})")
                num = (await num_cell.inner_text()).strip() if num_cell else ""
                numbers.append(num)
            await page.click(S.TABLE["assign_all_btn"])
            await page.wait_for_selector(
                S.POPUP["client_select"], timeout=self.settings.browser_timeout_ms
            )
            await self._select_option_by_text(page, S.POPUP["client_select"], client_name)
            await page.select_option(
                S.POPUP["payment_select"], S.POPUP["payment_weekly_value"]
            )
            await page.click(S.POPUP["allocate_submit"])
            await page.wait_for_timeout(S.TABLE_SETTLE_MS)
            log.info("panel.allocate.done", client=client_name, count=count, user=self.user_key)
            return numbers
        finally:
            self.storage_state = json.dumps(await ctx.storage_state())

    async def _select_option_by_text(self, page, selector: str, text: str) -> None:
        opts = await page.query_selector_all(f"{selector} option")
        for opt in opts:
            t = (await opt.inner_text()).strip()
            if t == text:
                val = await opt.get_attribute("value")
                await page.select_option(selector, value=val)
                return
        await page.select_option(selector, label=text)
