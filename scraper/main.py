#!/usr/bin/env python3
"""
Extract Hip/Knee exercise metadata and videos from hep2go.com or Uni Melbourne CHESM video library.
Output: data/exercises/ and data/exercises.json + data/extraction-report.json
"""

import argparse
import json
import sys
from pathlib import Path

# Allow running as python scraper/main.py from repo root
_scraper_root = Path(__file__).resolve().parent
if str(_scraper_root) not in sys.path:
    sys.path.insert(0, str(_scraper_root))

from playwright.sync_api import sync_playwright

from models import Catalog, ExerciseRecord, ExtractionReport
from utils.download import download_file, download_vimeo
from utils.slug import slugify

# Base URL for listing; pagination uses query param page=0, 1, 2, ...
# (Clicking Next triggers Cloudflare; URL-based pagination in same session works for page 0.)
BASE_LISTING = "https://www.hep2go.com/exercises.php?ex_type=19&order=sent&group=all&position=-1&userRef=gciaake"

# Project paths (relative to repo root)
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
EXERCISES_DIR = DATA_DIR / "exercises"

# JS: extract only tiles that have a video (videoOverDiv). Name/desc from img onmouseover (exOver).
EXTRACT_TILES_SCRIPT = """
() => {
  const items = [];
  const baseUrl = window.location.origin;
  const tds = document.querySelectorAll('td[id^="exTd_"]');
  tds.forEach(td => {
    const idMatch = td.id.match(/exTd_(\\d+)/);
    const exId = idMatch ? idMatch[1] : '';
    const videoDiv = td.querySelector('.videoOverDiv, div[onclick*="goPlayVideo"]');
    if (!videoDiv) return;
    const onclick = videoDiv.getAttribute('onclick') || '';
    const vimeoMatch = onclick.match(/goPlayVideo[^(]*\\(['"]?(\\d+)['"]?/);
    const vimeoId = (vimeoMatch && vimeoMatch[1] !== '0') ? vimeoMatch[1] : '';
    if (!vimeoId) return;
    let name = '', desc = '';
    const img = td.querySelector('img[onmouseover*="exOver"]');
    if (img) {
      const raw = img.getAttribute('onmouseover') || '';
      const match = raw.match(/exOver\\([^,]+,\\s*['"]([^'"]+)['"]/);
      if (match) {
        try {
          let decoded = decodeURIComponent(match[1].replace(/\\+/g, ' '));
          decoded = decoded.replace(/\\\\n/g, String.fromCharCode(10));
          const parts = decoded.split(String.fromCharCode(10));
          name = (parts[0] || '').trim();
          desc = (parts.slice(1).join(String.fromCharCode(10)) || '').trim();
        } catch (e) {}
      }
    }
    if (!name) name = 'Exercise ' + exId;
    items.push({
      exId,
      exerciseName: name,
      description: desc,
      vimeoId,
      sourceExerciseUrl: baseUrl + '/exercise_editor.php?exId=' + exId + '&userRef=gciaake'
    });
  });
  return items;
}
"""


def classify_exercise(name: str, description: str) -> str:
    """Classify as hip, knee, or other from name and description text."""
    text = f"{name} {description}".lower()
    hip_keywords = ["hip", "hip flexor", "glute", "gluteal", "piriformis", "it band", "iliotibial"]
    knee_keywords = ["knee", "patella", "quad", "quadriceps", "hamstring", "acl", "mcl", "meniscus"]
    if any(k in text for k in hip_keywords) and not any(k in text for k in knee_keywords):
        return "hip"
    if any(k in text for k in knee_keywords):
        return "knee"
    return "other"


def extract_tiles_from_page(page) -> list[dict]:
    """Extract exercise tiles that have a video (videoOverDiv) from current page."""
    try:
        page.wait_for_selector("td[id^='exTd_']", timeout=15000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    raw = page.evaluate(EXTRACT_TILES_SCRIPT)
    return raw if isinstance(raw, list) else []


def _listing_url(page_index: int) -> str:
    """Build listing URL for a given page (0-based). Page 0 has no param; page 1+ uses page=N."""
    if page_index <= 0:
        return BASE_LISTING
    sep = "&" if "?" in BASE_LISTING else "?"
    return f"{BASE_LISTING}{sep}page={page_index}"


def run_scraper(
    mode: str,
    start_page: int = 0,
    max_pages: int | None = None,
    urls: list[str] | None = None,
    headed: bool = False,
) -> tuple[Catalog, ExtractionReport]:
    """Run extraction: load each listing page by URL, collect video tiles, optionally download via yt-dlp.
    If urls is non-empty, use that list; otherwise build URLs from start_page/max_pages."""
    catalog = Catalog(sourcePage=BASE_LISTING)
    report = ExtractionReport(mode=mode)
    unique_items: list[dict] = []
    seen_ex_ids: set[str] = set()

    if urls:
        url_list = [u.strip() for u in urls if u.strip() and not u.strip().startswith("#")]
    else:
        total_pages = max_pages if max_pages is not None else 789
        url_list = [_listing_url(i) for i in range(start_page, min(start_page + total_pages, 789))]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        try:
            prev_url = None
            for i, url in enumerate(url_list):
                # Send Referer from previous listing page so the server sees in-site navigation
                if prev_url:
                    context.set_extra_http_headers({"Referer": prev_url})
                    page.wait_for_timeout(2000)
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                prev_url = url
                items = extract_tiles_from_page(page)
                # If we got 0 tiles, check whether we hit a Cloudflare challenge (explains why only page 0 works)
                hint = ""
                if not items and i > 0:
                    try:
                        cf = page.evaluate("""() => {
                            const hasCf = document.querySelector('[id*="cf"], [class*="cf-chl"], [class*="challenge"]') || (document.title && document.title.indexOf('Just a moment') >= 0);
                            return hasCf ? ' (Cloudflare challenge)' : '';
                        }""")
                        hint = cf or ""
                    except Exception:
                        pass
                print(f"  page {i}: {len(items)} tiles{hint}")
                if not items:
                    if i == 0:
                        report.errors.append("No video tiles on first page.")
                    continue
                for item in items:
                    ex_id = (item.get("exId") or "").strip()
                    if not ex_id or ex_id in seen_ex_ids:
                        continue
                    seen_ex_ids.add(ex_id)
                    unique_items.append(item)
                if i < len(url_list) - 1:
                    page.wait_for_timeout(1500)
        except Exception as e:
            report.errors.append(f"Scraping error: {e}")
        finally:
            browser.close()

    report.totalScraped = len(unique_items)

    # Single flat exercises directory; no per-type subfolders
    EXERCISES_DIR.mkdir(parents=True, exist_ok=True)

    for idx, item in enumerate(unique_items):
        name = (item.get("exerciseName") or "").strip() or f"Exercise {item.get('exId', idx + 1)}"
        description = (item.get("description") or "").strip()
        vimeo_id = (item.get("vimeoId") or "").strip()
        source_url = (item.get("sourceExerciseUrl") or "").strip()
        video_url = f"https://vimeo.com/{vimeo_id}" if vimeo_id else ""

        exercise_id = f"ex_{idx + 1:04d}"
        slug = slugify(name)
        rel_path = f"exercises/{exercise_id}_{slug}.mp4"
        dest_path = DATA_DIR / rel_path

        record = ExerciseRecord(
            id=exercise_id,
            exerciseName=name,
            description=description,
            videoUrlOriginal=video_url,
            videoPathLocal=rel_path,
            sourceExerciseUrl=source_url,
            downloadStatus="failed",
            contentType="",
            fileSizeBytes=None,
        )

        if mode == "full" and vimeo_id:
            ok, content_type, size = download_vimeo(vimeo_id, dest_path, skip_existing=True)
            if ok:
                record.downloadStatus = "success"
                record.contentType = content_type or "video/mp4"
                record.fileSizeBytes = size
                report.successCount += 1
            else:
                record.downloadStatus = "failed"
                report.failedCount += 1
                report.failedItems.append({"id": exercise_id, "reason": "vimeo download failed"})
        elif mode == "full" and not vimeo_id:
            record.downloadStatus = "skipped"
            report.skippedCount += 1
            report.failedItems.append({"id": exercise_id, "reason": "no vimeo ID"})
        else:
            if vimeo_id:
                report.successCount += 1
            else:
                report.skippedCount += 1

        catalog.exercises.append(record)

    catalog.totalExercises = len(catalog.exercises)
    catalog.totalVideos = sum(1 for r in catalog.exercises if r.downloadStatus == "success")
    catalog.failedDownloads = report.failedCount + report.skippedCount
    return catalog, report


def main() -> int:
    global DATA_DIR, EXERCISES_DIR
    parser = argparse.ArgumentParser(description="Scrape physiotherapy exercise videos (hep2go or Uni Melbourne)")
    parser.add_argument(
        "--source",
        choices=["hep2go", "unimelb", "both"],
        default="hep2go",
        help="Source: hep2go, unimelb, or both (hep2go first, then unimelb merged in)",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "dry"],
        default="full",
        help="full: scrape and download videos; dry: metadata only",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Max number of listing pages to scrape (default: all 789)",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=0,
        help="First page index (0-based) to scrape",
    )
    parser.add_argument(
        "--urls-file",
        type=Path,
        default=None,
        metavar="FILE",
        help="Text file with one listing URL per line (skips empty and # lines). Use this to scrape specific pages.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser visible (non-headless). Use to solve Cloudflare challenge manually so page 2+ may work.",
    )
    default_data = DATA_DIR  # capture before we reassign
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data,
        help="Base data directory (default: repo/data)",
    )
    args = parser.parse_args()
    DATA_DIR = Path(args.data_dir).resolve()
    EXERCISES_DIR = DATA_DIR / "exercises"

    urls_from_file = None
    if args.urls_file and args.urls_file.is_file():
        urls_from_file = args.urls_file.read_text(encoding="utf-8").strip().splitlines()

    catalog_path = DATA_DIR / "exercises.json"
    report_path = DATA_DIR / "extraction-report.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if args.source == "both":
        # 1) Run hep2go (writes initial catalog)
        print("=== Source: hep2go ===")
        catalog, hep2go_report = run_scraper(
            args.mode,
            start_page=args.start_page,
            max_pages=args.max_pages,
            urls=urls_from_file,
            headed=args.headed,
        )
        with open(catalog_path, "w", encoding="utf-8") as f:
            json.dump(catalog.model_dump(), f, indent=2, ensure_ascii=False)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(hep2go_report.model_dump(), f, indent=2, ensure_ascii=False)
        print(f"Catalog: {catalog_path} ({catalog.totalExercises} exercises, {catalog.totalVideos} videos)")

        # 2) Run unimelb and merge into existing catalog
        print("=== Source: unimelb (merge) ===")
        from unimelb import run_unimelb_scraper
        existing_catalog = catalog
        start_index = len(existing_catalog.exercises)
        existing_video_urls = {r.videoUrlOriginal for r in existing_catalog.exercises if r.videoUrlOriginal}
        unimelb_catalog, unimelb_report = run_unimelb_scraper(
            args.mode,
            DATA_DIR,
            EXERCISES_DIR,
            headed=args.headed,
            start_index=start_index,
            existing_video_urls=existing_video_urls,
        )
        merged_exercises = list(existing_catalog.exercises) + list(unimelb_catalog.exercises)
        catalog = Catalog(
            sourcePage=existing_catalog.sourcePage + "; " + unimelb_catalog.sourcePage,
            exercises=merged_exercises,
            totalExercises=len(merged_exercises),
            totalVideos=sum(1 for r in merged_exercises if r.downloadStatus == "success"),
            failedDownloads=sum(1 for r in merged_exercises if r.downloadStatus != "success"),
        )
        report = unimelb_report
        report.errors = [f"[hep2go] {e}" for e in hep2go_report.errors] + [f"[unimelb] {e}" for e in unimelb_report.errors]
        with open(catalog_path, "w", encoding="utf-8") as f:
            json.dump(catalog.model_dump(), f, indent=2, ensure_ascii=False)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report.model_dump(), f, indent=2, ensure_ascii=False)
        print(f"Catalog: {catalog_path} ({catalog.totalExercises} exercises, {catalog.totalVideos} videos) [combined]")
    elif args.source == "unimelb":
        from unimelb import run_unimelb_scraper
        existing_catalog = None
        if catalog_path.exists():
            try:
                data = json.loads(catalog_path.read_text(encoding="utf-8"))
                existing_catalog = Catalog.model_validate(data)
            except Exception:
                existing_catalog = None
        start_index = len(existing_catalog.exercises) if existing_catalog else 0
        existing_video_urls = {r.videoUrlOriginal for r in (existing_catalog.exercises if existing_catalog else []) if r.videoUrlOriginal}
        catalog, report = run_unimelb_scraper(
            args.mode,
            DATA_DIR,
            EXERCISES_DIR,
            headed=args.headed,
            start_index=start_index,
            existing_video_urls=existing_video_urls,
        )
        if existing_catalog and existing_catalog.exercises:
            merged_exercises = list(existing_catalog.exercises) + list(catalog.exercises)
            catalog = Catalog(
                sourcePage=existing_catalog.sourcePage + "; " + catalog.sourcePage,
                exercises=merged_exercises,
                totalExercises=len(merged_exercises),
                totalVideos=sum(1 for r in merged_exercises if r.downloadStatus == "success"),
                failedDownloads=sum(1 for r in merged_exercises if r.downloadStatus != "success"),
            )
        with open(catalog_path, "w", encoding="utf-8") as f:
            json.dump(catalog.model_dump(), f, indent=2, ensure_ascii=False)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report.model_dump(), f, indent=2, ensure_ascii=False)
        print(f"Catalog: {catalog_path} ({catalog.totalExercises} exercises, {catalog.totalVideos} videos)")
    else:
        catalog, report = run_scraper(
            args.mode,
            start_page=args.start_page,
            max_pages=args.max_pages,
            urls=urls_from_file,
            headed=args.headed,
        )
        with open(catalog_path, "w", encoding="utf-8") as f:
            json.dump(catalog.model_dump(), f, indent=2, ensure_ascii=False)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report.model_dump(), f, indent=2, ensure_ascii=False)
        print(f"Catalog: {catalog_path} ({catalog.totalExercises} exercises, {catalog.totalVideos} videos)")

    print(f"Report:  {report_path} (success={report.successCount}, failed={report.failedCount}, skipped={report.skippedCount})")
    if report.errors:
        for e in report.errors:
            print(f"Error: {e}", file=sys.stderr)
    return 0 if not report.errors else 1


if __name__ == "__main__":
    sys.exit(main())
