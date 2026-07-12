"""Read-only LIVE probe: logs in and reads the unallocated count.

Safe — it never allocates. Use it to verify selectors + whether reCAPTCHA
blocks automated login. Set PANEL_USERNAME/PASSWORD via env or edit below.
"""
import asyncio
import os

from cryptography.fernet import Fernet

os.environ.update(
    {
        "BOT_TOKEN": "x",
        "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "PANEL_USERNAME": os.environ.get("PANEL_USERNAME", "Anas777_FD"),
        "PANEL_PASSWORD": os.environ.get("PANEL_PASSWORD", "2255"),
        "PANEL_BASE_URL": "http://168.119.13.175/ints",
        "PANEL_MODE": "live",
        "HEADLESS": "true",
        "LOG_LEVEL": "DEBUG",
    }
)

from src.config import Settings  # noqa: E402
from src.core.logging import configure_logging  # noqa: E402
from src.core.security import CredentialStore  # noqa: E402
from src.panel.browser import BrowserManager  # noqa: E402
from src.panel.service import PanelService  # noqa: E402


async def main() -> None:
    configure_logging("DEBUG")
    settings = Settings()
    bm = BrowserManager(settings)
    await bm.start()
    svc = PanelService(settings, bm, CredentialStore(settings))
    try:
        n = await svc.get_unallocated_count()
        print("\n=== UNALLOCATED_COUNT =", n, "===\n")
        # Inspect the table so we can confirm column + unallocated detection.
        page = bm.page
        headers = await page.evaluate(
            "Array.from(document.querySelectorAll('#dt thead th')).map(th => th.innerText.trim())"
        )
        print("HEADERS:", headers)
        rows_info = await page.evaluate(
            """
            Array.from(document.querySelectorAll('#dt tbody tr')).slice(0,5).map(tr => {
                const cells = tr.querySelectorAll('td');
                return {
                    client: cells.length>1 ? cells[1].innerText.trim() : '',
                    number: cells.length>0 ? cells[0].innerText.trim() : ''
                };
            })
            """
        )
        print("FIRST ROWS:", rows_info)
    except Exception as exc:  # noqa: BLE001
        print("\n=== LIVE PROBE ERROR:", type(exc).__name__, exc, "===\n")
        # Dump where we ended up to help debug selectors.
        try:
            url = bm.page.url
            print("URL:", url)
            nav = await bm.page.evaluate(
                "document.querySelector('#main') ? document.querySelector('#main').outerHTML.slice(0,2500) : 'NO #main ELEMENT'"
            )
            print("NAV #main:\n", nav)
            links = await bm.page.evaluate(
                """
                Array.from(document.querySelectorAll('a'))
                  .filter(a => (a.innerText||'').includes('IPRN SMS Module'))
                  .map(a => ({html: a.outerHTML.slice(0,200), visible: a.offsetParent !== null}))
                """
            )
            print("IPRN LINKS:", links)
        except Exception as dump_err:  # noqa: BLE001
            print("could not dump page:", dump_err)
    finally:
        await bm.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
