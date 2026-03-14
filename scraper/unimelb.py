"""
Scrape Knee and Hip Osteoarthritis exercise videos from University of Melbourne
CHESM video library: healthsciences.unimelb.edu.au/.../video-library/exercise
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

from models import Catalog, ExerciseRecord, ExtractionReport
from utils.download import download_video_url
from utils.slug import slugify

BASE_URL = "https://healthsciences.unimelb.edu.au/departments/physiotherapy/chesm/video-library/exercise"

# JS: from main exercise page, get all category links (knee-oa and hip-oa subpages)
EXTRACT_CATEGORY_LINKS_SCRIPT = """
() => {
  const base = window.location.origin;
  const path = window.location.pathname || '';
  const links = [];
  document.querySelectorAll('a[href]').forEach(a => {
    const href = (a.getAttribute('href') || '').trim();
    if (!href) return;
    const full = href.startsWith('http') ? href : (base + (href.startsWith('/') ? href : (path.replace(/\\/[^/]*$/, '/') + href)));
    if (full.includes('/exercise/knee-oa/') || full.includes('/exercise/hip-oa/'))
      links.push({ url: full, text: (a.textContent || '').trim().slice(0, 150) });
  });
  return [...new Map(links.map(l => [l.url, l])).values()];
}
"""

# JS: extract each exercise from category page: H2 title (strip "Q10. " prefix), description = text between H2 and iframe, videoUrl from first YouTube iframe that follows
EXTRACT_EXERCISES_FROM_CATEGORY_SCRIPT = """
() => {
  const ytEmbedRe = /youtube\\.com\\/embed\\/([a-zA-Z0-9_-]+)/;
  const main = document.querySelector('main') || document.body;
  const h2s = Array.from(main.querySelectorAll('h2')).filter(h => (h.textContent || '').trim() !== 'Site footer');
  const iframes = Array.from(main.querySelectorAll('iframe[src*="youtube.com/embed"]'));
  const all = [];
  h2s.forEach(h => all.push({ el: h, type: 'h2', title: (h.textContent || '').trim() }));
  iframes.forEach(f => all.push({ el: f, type: 'iframe', src: f.getAttribute('src') || '' }));
  all.sort((a, b) => {
    const pos = a.el.compareDocumentPosition(b.el);
    if (pos & document.DOCUMENT_POSITION_FOLLOWING) return -1;
    if (pos & document.DOCUMENT_POSITION_PRECEDING) return 1;
    return 0;
  });
  const exercises = [];
  let i = 0;
  while (i < all.length) {
    if (all[i].type !== 'h2') { i++; continue; }
    const h2 = all[i].el;
    let title = (all[i].title || '').trim();
    let videoUrl = '';
    let description = '';
    let j = i + 1;
    while (j < all.length) {
      if (all[j].type === 'iframe') {
        const m = (all[j].src || '').match(ytEmbedRe);
        if (m) {
          videoUrl = 'https://www.youtube.com/watch?v=' + m[1];
          try {
            const range = document.createRange();
            range.setStartAfter(h2);
            range.setEndBefore(all[j].el);
            description = range.toString().replace(/\\r\\n/g, '\\n').replace(/\\r/g, '\\n').replace(/\\n{3,}/g, '\\n\\n').trim();
          } catch (e) {}
        }
        break;
      }
      j++;
    }
    if (title && videoUrl) {
      const name = title.replace(/^Q\\d+\\.\\s*/i, '').trim() || title;
      exercises.push({ exerciseName: name, description: description, videoUrl: videoUrl });
    }
    i++;
  }
  return exercises;
}
"""


def _extract_category_links(page) -> list[dict]:
    raw = page.evaluate(EXTRACT_CATEGORY_LINKS_SCRIPT)
    if not isinstance(raw, list):
        return []
    return [r for r in raw if isinstance(r, dict) and r.get("url")]


def _extract_exercises_from_category_page(page, category_url: str) -> list[dict]:
    raw = page.evaluate(EXTRACT_EXERCISES_FROM_CATEGORY_SCRIPT)
    if not isinstance(raw, list):
        return []
    for item in raw:
        if isinstance(item, dict):
            item["sourceExerciseUrl"] = category_url
    return raw


def run_unimelb_scraper(
    mode: str,
    data_dir: Path,
    exercises_dir: Path,
    *,
    headed: bool = False,
    start_index: int = 0,
    existing_video_urls: set[str] | None = None,  # skip if video URL already in catalog
) -> tuple[Catalog, ExtractionReport]:
    catalog = Catalog(sourcePage=BASE_URL)
    report = ExtractionReport(mode=mode)
    all_exercises: list[dict] = []
    seen_video_url: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            category_links = _extract_category_links(page)
            if not category_links:
                report.errors.append("No knee-oa/hip-oa category links found on main page.")
            for cat in category_links:
                url = cat.get("url", "")
                text = (cat.get("text") or "").strip().split("\n")[0].strip() or url.rstrip("/").split("/")[-1].replace("-", " ").title()
                print(f"  Category: {text[:60]}... -> {url[:70]}...")
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)
                items = _extract_exercises_from_category_page(page, url)
                for item in items:
                    video_url = (item.get("videoUrl") or "").strip()
                    if not video_url:
                        continue
                    if existing_video_urls is not None and video_url in existing_video_urls:
                        continue
                    if video_url in seen_video_url:
                        continue
                    seen_video_url.add(video_url)
                    all_exercises.append(item)
        except Exception as e:
            report.errors.append(f"Scraping error: {e}")
        finally:
            browser.close()

    report.totalScraped = len(all_exercises)
    exercises_dir.mkdir(parents=True, exist_ok=True)

    for idx, item in enumerate(all_exercises):
        name = (item.get("exerciseName") or "").strip() or f"Exercise {idx + 1}"
        description = (item.get("description") or "").strip()
        video_url = (item.get("videoUrl") or "").strip()
        source_url = (item.get("sourceExerciseUrl") or "").strip()

        exercise_id = f"ex_{start_index + idx + 1:04d}"
        slug = slugify(name)
        rel_path = f"exercises/{exercise_id}_{slug}.mp4"  # start_index ensures no clash with existing
        dest_path = data_dir / rel_path

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

        if mode == "full" and video_url:
            ok, content_type, size = download_video_url(video_url, dest_path, skip_existing=True)
            if ok:
                record.downloadStatus = "success"
                record.contentType = content_type or "video/mp4"
                record.fileSizeBytes = size
                report.successCount += 1
            else:
                record.downloadStatus = "failed"
                report.failedCount += 1
                report.failedItems.append({"id": exercise_id, "reason": "video download failed"})
        elif mode == "full" and not video_url:
            record.downloadStatus = "skipped"
            report.skippedCount += 1
            report.failedItems.append({"id": exercise_id, "reason": "no video URL"})
        else:
            if video_url:
                report.successCount += 1
            else:
                report.skippedCount += 1

        catalog.exercises.append(record)

    catalog.totalExercises = len(catalog.exercises)
    catalog.totalVideos = sum(1 for r in catalog.exercises if r.downloadStatus == "success")
    catalog.failedDownloads = report.failedCount + report.skippedCount
    return catalog, report
