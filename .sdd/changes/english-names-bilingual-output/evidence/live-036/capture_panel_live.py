"""Live panel check against the INSTALLED daemon (:9393), with two browsers (es-ES and en-US).

Unlike `evidence/B4/capture_screens.py` (its own port and mocked `/api/*`), this one opens the
real daemon's panel with its real data. It authenticates with HTTP Basic using the token that the
daemon's launcher already uses (user variable `LOCAL_DELEGATE_WEB_TOKEN`, read as in
`scripts/measure_structured_summary.py`; never printed). For each locale and theme it records the
`<html lang>`, the selector value, the heading of "backend processes", and the processes listed;
then, in the Spanish context, it switches the selector to EN and checks that the choice survives a
reload. Screenshots and `panel-live.json` go next to this script.

    uv run python capture_panel_live.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

from measure_structured_summary import _token

URL = "http://127.0.0.1:9393/"
STATE = """() => ({
  lang: document.documentElement.lang,
  selector: document.getElementById('lang').value,
  processes_heading: document.querySelector('#procSection .subh').textContent.trim(),
  processes: [...document.querySelectorAll('#procTable tr')].map(r => r.innerText.replace(/\\s+/g, ' ').trim()),
  system_title: document.querySelector('[data-i18n="system.title"]').textContent.trim(),
  kpi_labels: [...document.querySelectorAll('#kpis .k, #kpis .lbl, #kpis .label')].slice(0, 6).map(e => e.textContent.trim()),
})"""


async def main() -> int:
    from playwright.async_api import async_playwright

    report: dict = {}
    creds = {"username": "panel", "password": _token()}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for locale in ("es-ES", "en-US"):
            for theme in ("light", "dark"):
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 1400},
                    locale=locale,
                    http_credentials=creds,
                )
                page = await context.new_page()
                await page.add_init_script(
                    f"try{{localStorage.setItem('ld-theme','{theme}')}}catch(e){{}}"
                )
                await page.goto(URL, wait_until="networkidle")
                await page.wait_for_timeout(6000)  # the backend and process polls
                state = await page.evaluate(STATE)
                report[f"{locale}-{theme}"] = state
                await page.screenshot(
                    path=str(HERE / f"panel-{locale}-{theme}.png"), full_page=True
                )
                if locale == "es-ES" and theme == "light":
                    await page.select_option("#lang", "en")
                    await page.wait_for_timeout(1500)
                    after = await page.evaluate(STATE)
                    await page.reload(wait_until="networkidle")
                    await page.wait_for_timeout(3000)
                    reloaded = await page.evaluate(STATE)
                    report["es-ES-switch-to-en"] = {
                        "after_select": {
                            k: after[k] for k in ("lang", "selector", "processes_heading")
                        },
                        "after_reload": {
                            k: reloaded[k] for k in ("lang", "selector", "processes_heading")
                        },
                        "stored": await page.evaluate("() => localStorage.getItem('ld-lang')"),
                    }
                await context.close()
        await browser.close()
    out = HERE / "panel-live.json"
    out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
