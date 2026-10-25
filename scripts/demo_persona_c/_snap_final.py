"""Screenshot the dashboard in its current state to verify UI renders."""
import asyncio, os, sys
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width":1440,"height":900})
        p = await ctx.new_page()
        await p.goto("http://127.0.0.1:5173", wait_until="networkidle")
        await p.wait_for_timeout(3000)
        await p.screenshot(path="/tmp/dashboard_snap.png", full_page=True)
        await b.close()
        sz = os.path.getsize("/tmp/dashboard_snap.png")
        print(f"snap saved {sz/1024:.1f} KB")

asyncio.run(main())
