"""Render the Mermaid diagrams in docs/ARCHITECTURE.md to PNG (for Devpost and the video); the block diagram comes from docs/diagrams/architecture.html.

    python3 scripts/render_diagrams.py      # needs: pip install playwright && playwright install chromium

Writes docs/diagrams/architecture.png and docs/diagrams/agent_workflow.png.
"""

from __future__ import annotations

import asyncio
import html
import re
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "ARCHITECTURE.md"
OUT = ROOT / "docs" / "diagrams"
NAMES = ["architecture_auto", "agent_workflow"]

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<style>body{{margin:0;background:#fff;font-family:system-ui,sans-serif}} #d{{padding:24px;display:inline-block}}</style></head>
<body><div id="d" class="mermaid">{src}</div>
<script>mermaid.initialize({{startOnLoad:true, theme:'default', flowchart:{{htmlLabels:true, curve:'basis'}}}});</script></body></html>"""


async def main() -> None:
    blocks = re.findall(r"```mermaid\n(.*?)```", SRC.read_text(encoding="utf-8"), re.S)
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1800, "height": 1200}, device_scale_factor=2)
        for name, src in zip(NAMES, blocks):
            await pg.set_content(PAGE.format(src=html.escape(src)), wait_until="networkidle")
            await pg.wait_for_selector("#d svg", timeout=20000)
            el = await pg.query_selector("#d")
            await el.screenshot(path=str(OUT / f"{name}.png"))
            print("wrote", OUT / f"{name}.png")
        # Hand-laid block diagram (more legible than the auto-layout for the video).
        await pg.goto((ROOT / "docs" / "diagrams" / "architecture.html").as_uri(), wait_until="networkidle")
        el = await pg.query_selector(".wrap")
        await el.screenshot(path=str(OUT / "architecture_blocks.png"))
        print("wrote", OUT / "architecture_blocks.png")
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
