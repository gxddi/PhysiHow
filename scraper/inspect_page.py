#!/usr/bin/env python3
"""
One-off script to dump hep2go listing page structure so we can tune selectors.
Run with venv active: python scraper/inspect_page.py
"""

import sys
from pathlib import Path

_scraper_root = Path(__file__).resolve().parent
if str(_scraper_root) not in sys.path:
    sys.path.insert(0, str(_scraper_root))

from playwright.sync_api import sync_playwright

URL = "https://www.hep2go.com/exercises.php?ex_type=19&userRef=gciaake&order=sent&group=all&position=-1"
OUT = Path(__file__).resolve().parent.parent / "data" / "page_inspect.txt"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        try:
            page.goto(URL, wait_until="networkidle", timeout=25000)
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Load error: {e}")
            browser.close()
            return 1

        # Dump useful structure
        info = page.evaluate(
            """
            () => {
                const out = [];
                // All links with position or page
                const allLinks = document.querySelectorAll('a[href]');
                const posLinks = Array.from(allLinks).filter(a => (a.getAttribute('href') || '').includes('position') || (a.getAttribute('href') || '').includes('page'));
                out.push('=== PAGINATION (links with position/page) ===');
                posLinks.slice(0, 15).forEach(a => out.push(a.textContent?.trim() + ' => ' + (a.getAttribute('href') || '').slice(0, 100)));

                // videoOverDiv: count and parent + extract goPlayVideo ID
                const videoDivs = document.querySelectorAll('.videoOverDiv, div[onclick*="goPlayVideo"]');
                out.push('\\n=== VIDEO OVERLAY DIVS (count: ' + videoDivs.length + ') ===');
                const vimeoIds = [];
                videoDivs.forEach((el, i) => {
                    if (i >= 5) return;
                    const onclick = el.getAttribute('onclick') || '';
                    const match = onclick.match(/goPlayVideo[^(]*\\(['"]?(\\d+)['"]?/);
                    const id = match ? match[1] : '';
                    if (id) vimeoIds.push(id);
                    const parent = el.closest('div[class], td, tr');
                    out.push('id=' + id + ' parent=' + (parent?.className || parent?.tagName));
                });
                document.querySelectorAll('div[onclick*="goPlayVideo"]').forEach(el => {
                    const m = (el.getAttribute('onclick') || '').match(/['"]?(\\d+)['"]?/);
                    if (m) vimeoIds.push(m[1]);
                });
                out.push('Vimeo IDs (first 20): ' + [...new Set(vimeoIds)].slice(0, 20).join(', '));

                // Exercise tile: td with exTd_ and img with exEdit + name in onmouseover
                const firstTd = document.querySelector('td[id^="exTd_"]');
                if (firstTd) {
                    const img = firstTd.querySelector('img[onclick*="exEdit"]');
                    const mouseover = img?.getAttribute('onmouseover') || '';
                    out.push('\\n=== TILE: exTd + exEdit + name in onmouseover ===');
                    out.push('Sample onmouseover (first 300 chars): ' + mouseover.slice(0, 300));
                    const allTds = document.querySelectorAll('td[id^="exTd_"]');
                    out.push('Total tiles on page: ' + allTds.length);
                }

                // Pagination: any Next / numbered links / buttons
                const nextBtn = Array.from(document.querySelectorAll('a, button, input[type="button"]')).find(el => /next|\\d+/.test((el.textContent || '').trim().toLowerCase()));
                out.push('\\n=== PAGINATION ===');
                document.querySelectorAll('a').forEach(a => {
                    const t = (a.textContent || '').trim();
                    const h = a.getAttribute('href') || '';
                    if (/next|\\d+/.test(t) || h.includes('position') || h.includes('page')) out.push('Link: ' + t.slice(0, 20) + ' => ' + h.slice(0, 90));
                });
                return out.join('\\n');
            }
        """
        )

        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(info or "No data", encoding="utf-8")
        print(f"Wrote {OUT}")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
