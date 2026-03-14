# Hip/Knee Exercise Scraper

Extracts physiotherapy exercise metadata and videos from either:

- **[hep2go.com](https://www.hep2go.com)** – Hip and Knee exercises listing (Vimeo)
- **[Uni Melbourne CHESM](https://healthsciences.unimelb.edu.au/departments/physiotherapy/chesm/video-library/exercise)** – Knee Osteoarthritis and Hip Osteoarthritis exercise videos (YouTube)

Output: structured catalog and video files under `data/`.

## Requirements

- Python 3.10+
- pip

## Setup

From the **project root** (the `physitrack` directory), use a virtual environment for all scraper work:

**Windows (PowerShell):**

```powershell
# Create virtual environment
py -3.12 -m venv .venv

# Activate it (required before pip/playwright)
.\.venv\Scripts\Activate.ps1

# Install scraper dependencies
pip install -r scraper/requirements.txt

# Install Playwright Chromium (required once)
python -m playwright install chromium
```

**Windows (Command Prompt):** use `.\.venv\Scripts\activate.bat` instead of the PowerShell activate script.

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scraper/requirements.txt
python -m playwright install chromium
```

## How to run

From the **project root**, with the virtual environment **activated**:

**Choose source** with `--source`:

- `hep2go` (default) – hep2go.com listing
- `unimelb` – Melbourne CHESM video library (Knee OA + Hip OA; merges into existing catalog)
- `both` – run hep2go first, then unimelb; writes one combined catalog (recommended for a full dataset)

**Both sources in one run (combined catalog):**

```bash
# Scrape hep2go then unimelb; exercises.json and data/exercises/ contain both
python scraper/main.py --source both --mode full
```

**Uni Melbourne (Knee + Hip Osteoarthritis):**

```bash
# Scrape all Knee and Hip OA exercises and download YouTube videos
python scraper/main.py --source unimelb --mode full

# Dry run (metadata only, no downloads)
python scraper/main.py --source unimelb --mode dry
```

**hep2go:**

**Full run** (scrape listing pages, download Vimeo videos via yt-dlp):

```bash
python scraper/main.py --source hep2go --mode full
```

**Dry run** (scrape and write catalog/report only; no video downloads):

```bash
python scraper/main.py --mode dry
```

**Limit pages** (hep2go only) (e.g. test with one page):

```bash
python scraper/main.py --mode full --max-pages 1
python scraper/main.py --mode dry --max-pages 5
```

**Resume from a given page** (0-based):

```bash
python scraper/main.py --mode full --start-page 100 --max-pages 50
```

**Use your own list of page URLs** (e.g. links you copied from the browser):

```bash
# One URL per line in data/listing_urls.txt; empty lines and lines starting with # are ignored
python scraper/main.py --mode full --urls-file data/listing_urls.txt
```

**Run with a visible browser** (so you can solve Cloudflare manually; then page 2+ may work in that session):

```bash
python scraper/main.py --mode full --headed --urls-file data/listing_urls.txt
```

**Custom data directory** (default is `data` next to the project root):

```bash
python scraper/main.py --mode full --data-dir C:\path\to\data
```

## Behavior

**Uni Melbourne (`--source unimelb`):** Loads the main exercise page, discovers all category links under Knee and Hip Osteoarthritis, visits each category and extracts exercise titles plus the first YouTube embed per exercise. Videos downloaded with yt-dlp (video-only).

**hep2go:** The listing has **789 pages** (15 tiles per page). The scraper loads each page by URL (`page=0`, `1`, `2`, …). **Note:** Clicking the site’s “Next” button triggers a Cloudflare challenge in headless mode; requesting later pages by URL in the same session can also be blocked. So you may only get page 0 (15 exercises). **Why:** When you request `page=1` (or any URL with page≥1), the server/Cloudflare often returns a **challenge page** instead of the listing — 200 OK but body is the challenge, not the grid (0 tiles). It's not click vs. URL; the response for page=1 is different (anti-bot). Use `--headed` to solve the challenge once in a visible browser so page 2+ may work.
- Only **video** tiles are collected: tiles that have a video icon (`.videoOverDiv`) are included; image-only tiles are skipped.
- Each video is hosted on **Vimeo**. Downloads use **yt-dlp** with the embed URL and a hep2go referer. Some embeds may fail with “format not available”; those are recorded as failed in the report. Only the video stream is downloaded (no audio); format `bestvideo/best` is used, so ffmpeg is not required.

## Output

- **`data/exercises.json`** – Catalog with one entry per exercise: `id`, `exerciseName`, `description`, `videoUrlOriginal`, `videoPathLocal`, `sourceExerciseUrl`, `downloadStatus`, `contentType`, `fileSizeBytes`.
- **`data/extraction-report.json`** – Run summary: `totalScraped`, `successCount`, `failedCount`, `skippedCount`, `failedItems`, `errors`.
- **`data/exercises/`** – Downloaded video files named `ex_0001_slugified-name.mp4` (flat, no per-type folders).

Reruns are idempotent: existing video files are skipped and the catalog is overwritten with the latest run.
