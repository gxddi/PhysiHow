#!/usr/bin/env python3
"""
Dump Melbourne CHESM video library page structure for tuning selectors.
Run with venv active: python scraper/inspect_unimelb.py
"""

import sys
from pathlib import Path

_scraper_root = Path(__file__).resolve().parent
if str(_scraper_root) not in sys.path:
    sys.path.insert(0, str(_scraper_root))

from playwright.sync_api import sync_playwright

URL = "https://healthsciences.unimelb.edu.au/departments/physiotherapy/chesm/video-library/exercise"
OUT = Path(__file__).resolve().parent.parent / "data" / "unimelb_inspect.txt"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"Load error: {e}")
            browser.close()
            return 1

        info = page.evaluate(
            """
            () => {
                const out = [];
                out.push('=== HEADINGS (h1, h2, h3) ===');
                document.querySelectorAll('h1, h2, h3, h4').forEach(h => {
                    out.push(h.tagName + ': ' + (h.textContent || '').trim().slice(0, 120));
                });

                out.push('\\n=== LINKS (a[href]) - first 80 ===');
                const links = Array.from(document.querySelectorAll('a[href]'));
                links.slice(0, 80).forEach(a => {
                    const href = (a.getAttribute('href') || '').trim();
                    const text = (a.textContent || '').trim().slice(0, 80);
                    if (href && (href.startsWith('http') || href.startsWith('/')))
                        out.push(text + ' => ' + href.slice(0, 120));
                });

                out.push('\\n=== IFRAMES ===');
                document.querySelectorAll('iframe[src]').forEach(f => {
                    out.push((f.getAttribute('src') || '').slice(0, 200));
                });

                out.push('\\n=== VIDEO / SOURCE TAGS ===');
                document.querySelectorAll('video source, video').forEach(v => {
                    const src = v.getAttribute('src') || (v.querySelector('source') && v.querySelector('source').getAttribute('src'));
                    out.push('video: ' + (src || 'no src').slice(0, 200));
                });

                out.push('\\n=== ELEMENTS WITH "knee" or "hip" IN CLASS/ID/TEXT (sample) ===');
                const all = document.querySelectorAll('[class*="knee"], [class*="Knee"], [id*="knee"], [class*="hip"], [class*="Hip"], [id*="hip"]');
                all.forEach((el, i) => {
                    if (i >= 20) return;
                    out.push(el.tagName + (el.id ? '#' + el.id : '') + (el.className ? '.' + el.className : '') + ' ' + (el.textContent || '').trim().slice(0, 60));
                });

                return out.join('\\n');
            }
            """
        )

        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(info if isinstance(info, str) else str(info), encoding="utf-8")
        print(f"Wrote {OUT}")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
