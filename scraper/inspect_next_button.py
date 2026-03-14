#!/usr/bin/env python3
"""Inspect the Next (page_turn_Rt) button and what happens when we click it."""

import sys
from pathlib import Path

_scraper_root = Path(__file__).resolve().parent
if str(_scraper_root) not in sys.path:
    sys.path.insert(0, str(_scraper_root))

from playwright.sync_api import sync_playwright

URL = "https://www.hep2go.com/exercises.php?ex_type=19&userRef=gciaake&order=sent&group=all&position=-1"
OUT = Path(__file__).resolve().parent.parent / "data" / "inspect_next.txt"


def main():
    lines = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()
        try:
            page.goto(URL, wait_until="networkidle", timeout=25000)
            page.wait_for_timeout(2000)

            # Find Next button and its container
            info = page.evaluate("""
                () => {
                    const img = document.querySelector('img[src*="page_turn_Rt"]');
                    if (!img) return { found: false, reason: 'img not found' };
                    const parent = img.parentElement;
                    const grand = parent ? parent.parentElement : null;
                    return {
                        found: true,
                        imgSrc: img.src,
                        imgOuter: img.outerHTML.slice(0, 300),
                        parentTag: parent ? parent.tagName : null,
                        parentOuter: parent ? parent.outerHTML.slice(0, 500) : null,
                        parentOnclick: parent ? parent.getAttribute('onclick') : null,
                        parentHref: parent ? parent.getAttribute('href') : null,
                        grandTag: grand ? grand.tagName : null,
                        grandOuter: grand ? grand.outerHTML.slice(0, 400) : null,
                        firstPageTileIds: Array.from(document.querySelectorAll('td[id^="exTd_"]')).slice(0, 5).map(t => t.id)
                    };
                }
            """)
            lines.append("=== Next button (page_turn_Rt) and container ===")
            for k, v in (info or {}).items():
                lines.append(f"{k}: {v}")

            # Call goToPage(1) via JS (might do AJAX in-place, no full navigation)
            lines.append("\n=== Call goToPage(1) via evaluate ===")
            try:
                page.evaluate("goToPage(1)")
                page.wait_for_timeout(5000)
                structure = page.evaluate("""
                    () => ({
                        url: window.location.href,
                        tileCount: document.querySelectorAll('td[id^="exTd_"]').length,
                        firstIds: Array.from(document.querySelectorAll('td[id^="exTd_"]')).slice(0, 5).map(t => t.id),
                        hasCfChl: !!document.querySelector('[id*="cf-chl"]')
                    })
                """)
                for k, v in (structure or {}).items():
                    lines.append(f"  {k}: {v}")
            except Exception as e:
                lines.append(f"  error: {e}")
        except Exception as e:
            lines.append(f"Error: {e}")
        finally:
            browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
