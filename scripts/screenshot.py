"""Screenshot every view of site/index.html at desktop and phone widths and report console errors.
Run: python scripts/screenshot.py [--views ranked,company,...]"""
import asyncio, sys, json, pathlib
from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screens"

async def main():
    url = (ROOT / "site" / "index.html").as_uri()
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        errors = []
        for label, w, h in (("desktop", 1440, 900), ("phone", 390, 844)):
            page = await browser.new_page(viewport={"width": w, "height": h})
            page.on("pageerror", lambda e: errors.append(f"{label}: {e}"))
            page.on("console", lambda m: errors.append(f"{label} console.{m.type}: {m.text}") if m.type in ("error",) else None)
            await page.goto(url, wait_until="load", timeout=120000)
            await page.wait_for_timeout(1500)
            views = await page.evaluate("Array.from(document.querySelectorAll('[data-view],nav a,nav button,.nav a,.nav button')).map(e=>e.getAttribute('data-view')||e.textContent.trim()).filter(Boolean)")
            print(label, "nav:", views[:16])
            await page.screenshot(path=str(OUT / f"{label}_home.png"), full_page=False)
            seen = set()
            for v in views:
                key = v.lower().replace(" ", "_")[:20]
                if key in seen: continue
                seen.add(key)
                try:
                    el = page.locator(f"[data-view='{v}']").first
                    if await el.count() == 0:
                        el = page.get_by_role("button", name=v, exact=True).first
                    if await el.count() == 0:
                        el = page.get_by_text(v, exact=True).first
                    await el.click(timeout=3000)
                    await page.wait_for_timeout(900)
                    await page.screenshot(path=str(OUT / f"{label}_{key}.png"), full_page=False)
                except Exception as e:
                    print(label, v, "click failed:", str(e)[:120])
            await page.close()
        await browser.close()
        print("errors:", len(errors))
        for e in errors[:20]: print("  ", e)

asyncio.run(main())
