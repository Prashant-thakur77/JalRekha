"""docs/REPORT.md -> docs/REPORT.pdf, rendered by Chromium (Playwright) in the app's typography.

    python3 scripts/report_pdf.py
"""

import json
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
md = (root / "docs" / "REPORT.md").read_text()
html = f"""<!doctype html><html><head><meta charset="utf-8"><base href="file://{root}/docs/">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Host+Grotesk:wght@400;500;600&family=Fragment+Mono&family=Anek+Devanagari:wght@400;500&display=block">
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
<style>
@page {{ size: A4; margin: 16mm 15mm 18mm; }}
body {{ font-family: 'Host Grotesk','Anek Devanagari',sans-serif; color:#121211; font-size:10.5pt; line-height:1.5; }}
h1 {{ font-weight:500; font-size:26pt; letter-spacing:-0.03em; margin:0 0 6pt; }}
h2 {{ font-weight:500; font-size:15pt; letter-spacing:-0.01em; margin:18pt 0 6pt; padding-top:6pt; border-top:1px solid #D6D4CC; break-after:avoid; }}
h3 {{ font-weight:600; font-size:11.5pt; margin:12pt 0 4pt; break-after:avoid; }}
code, pre {{ font-family:'Fragment Mono',monospace; font-size:8.5pt; }}
pre {{ background:#F3F2EE; padding:8pt; border-radius:6pt; white-space:pre-wrap; }}
table {{ border-collapse:collapse; width:100%; font-size:8.8pt; margin:6pt 0 10pt; break-inside:auto; }}
th {{ font-family:'Fragment Mono',monospace; font-size:7.5pt; text-transform:uppercase; letter-spacing:.08em; color:#5F5E58; text-align:left; border-bottom:1px solid #121211; padding:4pt 5pt; }}
td {{ border-bottom:1px solid #E8E7E1; padding:4pt 5pt; vertical-align:top; }}
tr {{ break-inside:avoid; }}
img {{ max-width:100%; }}
a {{ color:#121211; }}
blockquote {{ border-left:3px solid #C6FF3D; margin:6pt 0; padding:2pt 10pt; background:#F3F2EE; }}
</style></head><body><main id="c"></main>
<script>document.getElementById('c').innerHTML = marked.parse({json.dumps(md)});</script></body></html>"""
tmp = Path(tempfile.mkdtemp()) / "report.html"
tmp.write_text(html)
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page()
    pg.goto(f"file://{tmp}", wait_until="networkidle"); pg.wait_for_timeout(1500)
    pg.pdf(path=str(root / "docs" / "REPORT.pdf"), format="A4", print_background=True, display_header_footer=True,
           header_template="<span></span>",
           footer_template="<div style='font-family:monospace;font-size:7pt;color:#5F5E58;width:100%;text-align:center'>NadiSaathi · technical report · <span class='pageNumber'></span>/<span class='totalPages'></span></div>",
           margin={"top": "16mm", "bottom": "18mm", "left": "15mm", "right": "15mm"})
    b.close()
